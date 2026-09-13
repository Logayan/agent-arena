from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from server.app.agent_runtime import (
    AgentRuntimeError,
    AgentRuntimePort,
    FakeAgentRuntime,
    classify_runtime_error,
    public_runtime_error,
)
from server.app.agent_runtime_registry import AgentRuntimeRegistry, agent_runtime
from experiments.openclaw_baseline import OpenClawRuntime, OpenClawRuntimeError, openclaw_runtime


def test_openclaw_adapter_satisfies_runtime_port(tmp_path) -> None:
    runtime = OpenClawRuntime(tmp_path / "state", tmp_path / "workspaces")

    assert isinstance(runtime, AgentRuntimePort)
    assert runtime.runtime_name == "openclaw"
    assert runtime.health()["runtime"] == "openclaw"
    assert isinstance(OpenClawRuntimeError("openclaw_timeout:10s"), AgentRuntimeError)


def test_runtime_errors_have_framework_neutral_categories() -> None:
    assert classify_runtime_error("HTTP 401 unauthorized") == ("provider_auth", False)
    assert classify_runtime_error("HTTP 403 forbidden") == ("provider_auth", False)
    assert classify_runtime_error("HTTP 429 rate limit") == ("provider_rate_limit", True)
    assert classify_runtime_error("openclaw_timeout:10s") == ("timeout", True)
    assert classify_runtime_error("openclaw_workspace_path_escape") == ("security", False)
    assert classify_runtime_error("openclaw_non_json_output") == ("invalid_output", True)

    error = AgentRuntimeError("HTTP 401 unauthorized", runtime="openclaw")
    assert error.as_dict() == {
        "message": "HTTP 401 unauthorized",
        "category": "provider_auth",
        "retryable": False,
        "runtime": "openclaw",
        "details": {},
    }


def test_runtime_errors_have_safe_public_copy_and_trace_fingerprint() -> None:
    raw = (
        "claude_agent_failed:[trace:embedded-run] sessionId=secret-session "
        "url=http://43.106.8.32:3000/v1/responses tool policy removed 24 tools "
        "causeCode=EACCES message=fetch failed rawError=Connection error"
    )

    public = public_runtime_error(AgentRuntimeError(raw, runtime="claude_code"))

    assert public["error_code"] == "model_service_unreachable"
    assert public["error_category"] == "provider_failure"
    assert public["retryable"] is True
    assert public["runtime"] == "claude_code"
    assert public["diagnostic_id"].startswith("diag-")
    assert "模型服务暂时无法连接" in public["error_detail"]
    assert "43.106.8.32" not in public["error_detail"]
    assert "secret-session" not in public["error_detail"]
    assert "tool policy" not in public["error_detail"]


def test_run_time_budget_error_keeps_safe_retry_semantics() -> None:
    public = public_runtime_error(RuntimeError("budget_exhausted:run_time_limit"))

    assert public["error_code"] == "run_time_budget_exhausted"
    assert public["retryable"] is True
    assert "增加运行时间后可从未完成节点继续" in public["error_detail"]
    assert "budget_exhausted" not in public["error_detail"]


@pytest.mark.anyio
async def test_fake_runtime_streams_normalized_actions_and_records_calls(tmp_path) -> None:
    actions = [
        {"kind": "tool_call", "tool_call_id": "call-1", "tool_name": "exec", "arguments": {"command": "pytest -q"}},
        {"kind": "tool_result", "tool_call_id": "call-1", "tool_name": "exec", "status": "completed", "is_error": False, "exit_code": 0, "output": "3 passed"},
    ]
    runtime = FakeAgentRuntime(
        tmp_path,
        scripted_results=[
            {
                "id": "fake-result",
                "session_id": "session-1",
                "model": "test-model",
                "content": [{"type": "text", "text": "完成"}],
                "usage": {"input_tokens": 10, "output_tokens": 2},
                "actions": actions,
                "file_changes": [],
            }
        ],
    )
    streamed = []

    async def on_action(action) -> None:
        streamed.append(action)

    response = await runtime.message(
        agent={"id": "agent-1"},
        prompt="运行测试",
        session_key="session-1",
        model_config={"model": "test-model"},
        on_action=on_action,
    )

    assert response["id"] == "fake-result"
    assert streamed == actions
    assert runtime.messages == [{"agent_id": "agent-1", "prompt": "运行测试", "session_key": "session-1", "model": "test-model"}]


def test_registry_uses_claude_as_product_default_and_supports_legacy_adapters(tmp_path) -> None:
    assert agent_runtime.runtime_name == "claude_code"

    fake = FakeAgentRuntime(tmp_path)
    registry = AgentRuntimeRegistry(openclaw_runtime)
    registry.register(fake)
    assert registry.get("openclaw") is openclaw_runtime
    assert registry.get("fake") is fake
    assert registry.default is openclaw_runtime

    with pytest.raises(AgentRuntimeError) as captured:
        registry.get("missing")
    assert captured.value.category == "configuration"
    assert captured.value.retryable is False


def test_registry_preserves_legacy_one_argument_for_run_contract() -> None:
    class LegacyRuntime:
        runtime_name = "legacy"
        supports_live_actions = False

        def for_run(self, run_id):
            return f"legacy:{run_id}"

    registry = AgentRuntimeRegistry(LegacyRuntime())

    assert registry.for_run("run-1") == "legacy:run-1"


def test_platform_modules_do_not_import_openclaw_adapter_directly() -> None:
    project_root = Path(__file__).resolve().parents[3]
    assert not (project_root / "server/app/openclaw_runtime.py").exists()
    assert (project_root / "experiments/openclaw_baseline/openclaw_runtime.py").is_file()
    for relative in ("server/app/main.py", "server/app/platform_executor.py", "server/app/agent_runtime_registry.py"):
        source = (project_root / relative).read_text(encoding="utf-8")
        assert "from .openclaw_runtime import" not in source


def test_product_runtime_registry_rejects_openclaw_configuration() -> None:
    project_root = Path(__file__).resolve().parents[3]
    registry_source = (project_root / "server/app/agent_runtime_registry.py").read_text(encoding="utf-8")
    assert 'configured_runtime != "claude_code"' in registry_source
    assert "JIANGHU_ENABLE_LEGACY_OPENCLAW" not in registry_source
    environment = os.environ.copy()
    environment["JIANGHU_AGENT_RUNTIME"] = "openclaw"
    completed = subprocess.run(
        [sys.executable, "-c", "import server.app.agent_runtime_registry"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert completed.returncode != 0
    assert "agent_runtime_fixed_to_claude_code" in completed.stderr


def test_generic_runtime_status_route_keeps_openclaw_compatibility_alias() -> None:
    from server.app.main import app

    paths = {route.path for route in app.routes}
    assert "/api/platform/runtime/status" in paths
    assert "/api/platform/openclaw/status" in paths
