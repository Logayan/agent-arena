from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path

import pytest

from server.app.agent_runtime import AgentRuntimePort
from server.app.agent_runtime_registry import agent_runtime
from server.app.claude_code_runtime import ClaudeCodeRuntime, ClaudeCodeRuntimeError, claude_code_runtime


MODEL_CONFIG = {
    "provider": "anthropic-compatible",
    "base_url": "https://model.example.test",
    "model": "gpt-test-model",
    "token": "g4-contract-secret",
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _agent() -> dict[str, object]:
    return {
        "id": "agent_engineer_v1",
        "name": "沈青岚",
        "role": "后端工程师",
        "version": "1.0.0",
        "persona": "先验证再交付。",
        "skills": [
            {
                "key": "verified-delivery",
                "name": "证据化交付",
                "description": "运行测试并记录证据",
                "instructions": "所有工程结论必须有真实命令和退出码。",
                "enabled": True,
            }
        ],
    }


def _fake_bridge(tmp_path: Path) -> Path:
    path = tmp_path / "fake_bridge.py"
    path.write_text(
        textwrap.dedent(
            """
            import json
            import sys
            from pathlib import Path

            payload = json.load(sys.stdin)
            delivery = Path(payload["workspace"]) / "delivery"
            delivery.mkdir(parents=True, exist_ok=True)
            (delivery / "artifact.txt").write_text("G4_ADAPTER_OK\\n", encoding="utf-8")
            resume = str(payload.get("resume_session_id") or "")
            secret = str(payload.get("token") or "")
            events = [
                {"type": "meta", "session_id": "sdk-session-1", "model": payload["model"]},
                {"type": "action", "action": {"kind": "tool_call", "tool_call_id": "call-1", "tool_name": "Bash", "arguments": {"command": "echo ok", "token_probe": secret}}},
                {"type": "action", "action": {"kind": "tool_result", "tool_call_id": "call-1", "status": "completed", "is_error": False, "exit_code": 0, "output": "G4_COMMAND_OK"}},
                {"type": "result", "result": {"session_id": "sdk-session-1", "model": payload["model"], "is_error": False, "text": "RESUMED:" + resume if resume else "G4_ADAPTER_OK", "usage": {"input_tokens": 12, "output_tokens": 3}}},
            ]
            for event in events:
                print(json.dumps(event, ensure_ascii=False), flush=True)
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def _blocking_bridge(tmp_path: Path) -> Path:
    path = tmp_path / "blocking_bridge.py"
    path.write_text(
        "import json, sys, time\njson.load(sys.stdin)\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    return path


def test_claude_adapter_is_registered_and_is_product_default(tmp_path) -> None:
    runtime = ClaudeCodeRuntime(tmp_path / "state", tmp_path / "workspaces")

    assert isinstance(runtime, AgentRuntimePort)
    assert runtime.runtime_name == "claude_code"
    assert isinstance(ClaudeCodeRuntimeError("claude_timeout:1s"), RuntimeError)
    assert agent_runtime.get("claude_code") is claude_code_runtime
    assert agent_runtime.default is claude_code_runtime
    assert agent_runtime.runtime_name == "claude_code"


def test_claude_sync_projects_context_memory_skills_and_policy_without_token(tmp_path) -> None:
    runtime = ClaudeCodeRuntime(tmp_path / "state", tmp_path / "workspaces")
    agent = _agent()

    result = runtime.sync(
        [agent],
        {str(agent["id"]): [{"title": "历史交付", "content": "曾完成一次可复验修复。"}]},
        MODEL_CONFIG,
        tool_enabled_agent_ids={str(agent["id"])},
        model_configs=[{**MODEL_CONFIG, "model": "alternate-model"}],
    )

    workspace = runtime.workspace_path(agent)
    context = (workspace / "CLAUDE.md").read_text(encoding="utf-8")
    skill = workspace / ".claude" / "skills" / "verified-delivery" / "SKILL.md"
    policy = json.loads(runtime.policy_path.read_text(encoding="utf-8"))
    assert "沈青岚" in context
    assert "曾完成一次可复验修复" in context
    assert skill.is_file()
    assert "所有工程结论必须有真实命令" in skill.read_text(encoding="utf-8")
    assert policy[str(agent["id"])] == {
        "engineering": True,
        "skill_ids": ["verified-delivery"],
        "model": "gpt-test-model",
    }
    assert result["models"] == ["gpt-test-model", "alternate-model"]
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for root in (runtime.state_root, runtime.workspace_root)
        for path in root.rglob("*")
        if path.is_file()
    )
    assert MODEL_CONFIG["token"] not in persisted

    runtime.sync([{**agent, "skills": []}], {}, MODEL_CONFIG)
    assert not skill.exists()


@pytest.mark.anyio
async def test_claude_message_normalizes_stream_resume_and_file_changes(monkeypatch, tmp_path) -> None:
    runtime = ClaudeCodeRuntime(tmp_path / "state", tmp_path / "workspaces")
    agent = _agent()
    runtime.sync([agent], {}, MODEL_CONFIG, tool_enabled_agent_ids={str(agent["id"])})
    bridge = _fake_bridge(tmp_path)
    monkeypatch.setattr(runtime, "_base_command", lambda: [sys.executable, str(bridge)])
    streamed: list[dict[str, object]] = []

    async def on_action(action: dict[str, object]) -> None:
        streamed.append(action)

    first = await runtime.message(
        agent=agent,
        prompt="创建交付并执行命令",
        session_key="workflow:node-1",
        model_config=MODEL_CONFIG,
        timeout_seconds=5,
        capture_workspace=True,
        on_action=on_action,
    )

    assert first["content"][0]["text"] == "G4_ADAPTER_OK"
    assert [item["kind"] for item in streamed] == ["tool_call", "tool_result"]
    assert streamed[0]["arguments"]["token_probe"] == "[REDACTED]"
    assert streamed[1]["exit_code"] == 0
    assert first["file_changes"][0]["path"] == "artifact.txt"
    assert first["usage"] == {"input_tokens": 12, "output_tokens": 3}
    assert json.loads(runtime.sessions_path.read_text(encoding="utf-8"))[f'{agent["id"]}:workflow:node-1'] == "sdk-session-1"

    resumed = await runtime.message(
        agent=agent,
        prompt="继续",
        session_key="workflow:node-1",
        model_config=MODEL_CONFIG,
        timeout_seconds=5,
    )
    assert resumed["content"][0]["text"] == "RESUMED:sdk-session-1"


@pytest.mark.anyio
async def test_claude_message_cancellation_terminates_bridge_tree(monkeypatch, tmp_path) -> None:
    runtime = ClaudeCodeRuntime(tmp_path / "state", tmp_path / "workspaces")
    agent = _agent()
    runtime.sync([agent], {}, MODEL_CONFIG)
    bridge = _blocking_bridge(tmp_path)
    monkeypatch.setattr(runtime, "_base_command", lambda: [sys.executable, str(bridge)])
    terminated = asyncio.Event()
    original = runtime._terminate_process_tree

    async def tracked_terminate(process) -> None:
        terminated.set()
        await original(process)

    monkeypatch.setattr(runtime, "_terminate_process_tree", tracked_terminate)
    task = asyncio.create_task(
        runtime.message(
            agent=agent,
            prompt="等待取消",
            session_key="cancel-test",
            model_config=MODEL_CONFIG,
            timeout_seconds=30,
        )
    )
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert terminated.is_set()


def test_claude_submission_and_promotion_are_limited_to_delivery(tmp_path) -> None:
    runtime = ClaudeCodeRuntime(tmp_path / "state", tmp_path / "workspaces")
    agent = _agent()
    delivery = runtime.workspace_path(agent) / "delivery"
    (delivery / "src").mkdir(parents=True)
    (delivery / "src" / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    (runtime.workspace_path(agent) / "private.txt").write_text("PRIVATE\n", encoding="utf-8")
    changes = runtime._workspace_changes({}, runtime._workspace_snapshot(delivery))

    submission = runtime.publish_workspace_submission(
        agent=agent,
        changes=changes,
        destination=tmp_path / "submission",
    )
    assert (Path(submission["files_root"]) / "src" / "feature.py").is_file()
    assert not (Path(submission["files_root"]) / "private.txt").exists()

    final_root = tmp_path / "final"
    final_root.mkdir()
    (final_root / "stale.txt").write_text("stale", encoding="utf-8")
    promoted = runtime.promote_workspace_tree(agent=agent, destination=final_root)
    assert (final_root / "src" / "feature.py").is_file()
    assert not (final_root / "stale.txt").exists()
    assert {(item["action"], item["path"]) for item in promoted} == {
        ("created", "src/feature.py"),
        ("deleted", "stale.txt"),
    }


def test_claude_submission_records_file_that_vanishes_during_copy_as_deleted(monkeypatch, tmp_path) -> None:
    runtime = ClaudeCodeRuntime(tmp_path / "state", tmp_path / "workspaces")
    agent = _agent()
    delivery = runtime.workspace_path(agent) / "delivery"
    delivery.mkdir(parents=True)
    transient = delivery / "transient.json"
    transient.write_text('{"state":"temporary"}\n', encoding="utf-8")
    changes = runtime._workspace_changes({}, runtime._workspace_snapshot(delivery))

    def vanish_then_fail(source, target):
        Path(source).unlink(missing_ok=True)
        raise FileNotFoundError(source)

    monkeypatch.setattr("server.app.claude_code_runtime.shutil.copy2", vanish_then_fail)
    submission = runtime.publish_workspace_submission(
        agent=agent,
        changes=changes,
        destination=tmp_path / "submission",
    )

    assert submission["file_count"] == 0
    assert submission["changes"] == [
        {"path": "transient.json", "action": "deleted", "sha256": "", "size_bytes": 0}
    ]
    assert not (Path(submission["files_root"]) / "transient.json").exists()


def test_claude_submission_supports_windows_max_path_boundary(tmp_path) -> None:
    runtime = ClaudeCodeRuntime(tmp_path / "state", tmp_path / "workspaces")
    agent = _agent()
    delivery = runtime.workspace_path(agent) / "delivery"
    source = delivery / "evidence" / "runtime_acceptance" / "local_final_state.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"state":"final"}\n', encoding="utf-8")
    changes = runtime._workspace_changes({}, runtime._workspace_snapshot(delivery))

    destination = tmp_path / "collaboration" / ("long-segment-" * 5) / ("attempt-segment-" * 2)
    submission = runtime.publish_workspace_submission(
        agent=agent,
        changes=changes,
        destination=destination,
    )

    copied = Path(submission["files_root"]) / "evidence" / "runtime_acceptance" / "local_final_state.json"
    assert len(str(copied.resolve())) >= 260
    assert Path(runtime._copy_path(copied)).read_text(encoding="utf-8") == '{"state":"final"}\n'


def test_claude_submission_creates_parent_directory_beyond_windows_max_path(tmp_path) -> None:
    runtime = ClaudeCodeRuntime(tmp_path / "state", tmp_path / "workspaces")
    agent = _agent()
    delivery = runtime.workspace_path(agent) / "delivery"
    relative = Path("evidence") / ("nested-segment-" * 7) / "message.json"
    source = delivery / relative
    source.parent.mkdir(parents=True)
    source.write_text('{"message":"published"}\n', encoding="utf-8")
    changes = runtime._workspace_changes({}, runtime._workspace_snapshot(delivery))

    destination = tmp_path / "collaboration" / ("attempt-segment-" * 4)
    target = destination / "files" / relative
    assert len(str(target.parent.resolve())) >= 260

    submission = runtime.publish_workspace_submission(
        agent=agent,
        changes=changes,
        destination=destination,
    )

    copied = Path(submission["files_root"]) / relative
    assert Path(runtime._copy_path(copied)).read_text(encoding="utf-8") == '{"message":"published"}\n'


def test_claude_promotion_rejects_path_escape(tmp_path) -> None:
    runtime = ClaudeCodeRuntime(tmp_path / "state", tmp_path / "workspaces")
    with pytest.raises(ClaudeCodeRuntimeError) as captured:
        runtime.promote_workspace_changes(
            agent=_agent(),
            changes=[{"path": str(Path(tmp_path.anchor) / "escape.txt"), "action": "created"}],
            destination=tmp_path / "final",
        )
    assert captured.value.category == "security"
