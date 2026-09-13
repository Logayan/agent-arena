from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from server.app.agent_runtime import AgentRuntimeError, AgentRuntimePort
from server.app.claude_code_runtime import ClaudeCodeRuntime
from server.app.openclaw_runtime import OpenClawRuntime
from server.app.platform_executor import _is_command_tool


MODEL_CONFIG = {
    "provider": "openai-responses",
    "base_url": "https://model.example.test",
    "model": "gpt-parity-medium",
    "tier": "medium",
    "token": "g5-parity-secret",
}


def _agent(agent_id: str, *, engineering: bool = False) -> dict[str, Any]:
    return {
        "id": agent_id,
        "name": "沈青岚" if engineering else "叶知秋",
        "role": "后端工程师" if engineering else "需求分析师",
        "version": "2.0.0",
        "persona": "先验证再交付。" if engineering else "区分事实、推断和风险。",
        "skills": [
            {
                "key": "evidence-delivery",
                "name": "证据化交付",
                "description": "用公开证据支持结论",
                "instructions": "只报告可公开复验的事实。",
                "enabled": True,
            }
        ],
    }


@pytest.fixture(params=("openclaw", "claude_code"))
def runtime(request, tmp_path) -> AgentRuntimePort:
    if request.param == "openclaw":
        return OpenClawRuntime(tmp_path / "openclaw-state", tmp_path / "openclaw-workspaces")
    return ClaudeCodeRuntime(tmp_path / "claude-state", tmp_path / "claude-workspaces")


def _runtime_roots(runtime: AgentRuntimePort) -> list[Path]:
    return [
        Path(getattr(runtime, "state_root")).resolve(),
        Path(getattr(runtime, "workspace_root")).resolve(),
    ]


def _persisted_text(runtime: AgentRuntimePort) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for root in _runtime_roots(runtime)
        for path in root.rglob("*")
        if path.is_file()
    )


def _normalized_models(result: dict[str, Any]) -> list[str]:
    return [str(item).split("/", 1)[-1] for item in result.get("models", [])]


def _tool_profile(runtime: AgentRuntimePort, agent_id: str) -> str:
    if runtime.runtime_name == "openclaw":
        config = json.loads(Path(getattr(runtime, "config_path")).read_text(encoding="utf-8"))
        agent = next(item for item in config["agents"]["list"] if item["id"] == agent_id)
        return str(agent["tools"]["profile"])
    policy = json.loads(Path(getattr(runtime, "policy_path")).read_text(encoding="utf-8"))
    return "coding" if policy[agent_id]["engineering"] else "minimal"


def test_rtc_001_health_and_port_are_available_for_both_adapters(runtime) -> None:
    health = runtime.health()

    assert isinstance(runtime, AgentRuntimePort)
    assert health["runtime"] == runtime.runtime_name
    assert isinstance(health.get("available"), bool)
    assert health.get("mode")
    assert health.get("version")


def test_rtc_002_005_009_011_projection_models_secrets_and_tool_policy_match(runtime) -> None:
    engineer = _agent("agent_engineer_v2", engineering=True)
    analyst = _agent("agent_analyst_v2")
    alternate = {**MODEL_CONFIG, "model": "gpt-parity-high", "tier": "high"}

    result = runtime.sync(
        [engineer, analyst],
        {engineer["id"]: [{"title": "历史交付", "content": "曾完成一次可复验修复。"}]},
        MODEL_CONFIG,
        tool_enabled_agent_ids={engineer["id"]},
        model_configs=[alternate],
    )

    engineer_workspace = runtime.workspace_path(engineer)
    analyst_workspace = runtime.workspace_path(analyst)
    engineer_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in engineer_workspace.rglob("*.md")
    )
    assert "沈青岚" in engineer_text
    assert "先验证再交付" in engineer_text
    assert "曾完成一次可复验修复" in engineer_text
    assert "证据化交付" in engineer_text
    assert engineer_workspace != analyst_workspace
    assert _tool_profile(runtime, engineer["id"]) == "coding"
    assert _tool_profile(runtime, analyst["id"]) == "minimal"
    assert _normalized_models(result) == ["gpt-parity-medium", "gpt-parity-high"]
    assert MODEL_CONFIG["token"] not in _persisted_text(runtime)


def test_rtc_003_004_run_agent_and_session_state_roots_are_isolated(runtime) -> None:
    first_agent = _agent("agent_family_v1")
    second_agent = _agent("agent_family_v2")
    run_one = runtime.for_run("run-one", Path(getattr(runtime, "state_root")) / "execution-one")
    run_two = runtime.for_run("run-two", Path(getattr(runtime, "state_root")) / "execution-two")

    assert runtime.workspace_path(first_agent) != runtime.workspace_path(second_agent)
    assert Path(getattr(run_one, "state_root")) != Path(getattr(run_two, "state_root"))
    assert Path(getattr(run_one, "workspace_root")) != Path(getattr(run_two, "workspace_root"))
    assert Path(getattr(run_one, "state_root")).is_relative_to(Path(getattr(runtime, "state_root")))
    assert Path(getattr(run_two, "state_root")).is_relative_to(Path(getattr(runtime, "state_root")))


def test_rtc_012_file_change_schema_matches(runtime) -> None:
    agent = _agent("agent_changes", engineering=True)
    delivery = runtime.workspace_path(agent) / "delivery"
    delivery.mkdir(parents=True)
    before = runtime._workspace_snapshot(delivery)  # type: ignore[attr-defined]
    (delivery / "created.txt").write_text("v1\n", encoding="utf-8")
    created_size = (delivery / "created.txt").stat().st_size
    created = runtime._workspace_changes(before, runtime._workspace_snapshot(delivery))  # type: ignore[attr-defined]
    before_modified = runtime._workspace_snapshot(delivery)  # type: ignore[attr-defined]
    (delivery / "created.txt").write_text("v2\n", encoding="utf-8")
    modified = runtime._workspace_changes(before_modified, runtime._workspace_snapshot(delivery))  # type: ignore[attr-defined]
    before_deleted = runtime._workspace_snapshot(delivery)  # type: ignore[attr-defined]
    (delivery / "created.txt").unlink()
    deleted = runtime._workspace_changes(before_deleted, runtime._workspace_snapshot(delivery))  # type: ignore[attr-defined]

    assert created[0]["action"] == "created"
    assert created[0]["path"] == "created.txt"
    assert created[0]["sha256"]
    assert created[0]["size_bytes"] == created_size
    assert modified[0]["action"] == "modified"
    assert modified[0]["previous_sha256"] == created[0]["sha256"]
    assert deleted[0]["action"] == "deleted"
    assert deleted[0]["size_bytes"] == 0


def test_rtc_013_014_015_submission_promotion_and_seed_semantics_match(runtime, tmp_path) -> None:
    contributor = _agent("agent_contributor", engineering=True)
    lead = _agent("agent_lead", engineering=True)
    contributor_delivery = runtime.workspace_path(contributor) / "delivery"
    (contributor_delivery / "src").mkdir(parents=True)
    (contributor_delivery / "src" / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    (runtime.workspace_path(contributor) / "private-memory.txt").write_text("PRIVATE\n", encoding="utf-8")
    changes = runtime._workspace_changes({}, runtime._workspace_snapshot(contributor_delivery))  # type: ignore[attr-defined]

    submission = runtime.publish_workspace_submission(
        agent=contributor,
        changes=changes,
        destination=runtime.workspace_path(lead) / "collaboration" / contributor["id"],
    )
    assert submission["file_count"] == 1
    assert (Path(submission["files_root"]) / "src" / "feature.py").is_file()
    assert not (Path(submission["files_root"]) / "private-memory.txt").exists()

    seed = tmp_path / "seed"
    (seed / "pkg").mkdir(parents=True)
    (seed / "pkg" / "base.py").write_text("BASE = True\n", encoding="utf-8")
    runtime._copy_tree(seed, runtime.workspace_path(lead) / "delivery")  # type: ignore[attr-defined]
    assert (runtime.workspace_path(lead) / "delivery" / "pkg" / "base.py").is_file()
    assert (seed / "pkg" / "base.py").read_text(encoding="utf-8") == "BASE = True\n"

    final_root = tmp_path / "final"
    final_root.mkdir()
    (final_root / "stale.txt").write_text("stale", encoding="utf-8")
    promoted = runtime.promote_workspace_tree(agent=lead, destination=final_root)
    assert (final_root / "pkg" / "base.py").is_file()
    assert not (final_root / "stale.txt").exists()
    assert {(item["action"], item["path"]) for item in promoted} == {
        ("created", "pkg/base.py"),
        ("deleted", "stale.txt"),
    }


def test_rtc_009_path_escape_is_rejected_by_both_adapters(runtime, tmp_path) -> None:
    with pytest.raises(AgentRuntimeError) as captured:
        runtime.promote_workspace_changes(  # type: ignore[attr-defined]
            agent=_agent("agent_escape", engineering=True),
            changes=[{"path": str(Path(tmp_path.anchor) / "escape.txt"), "action": "created"}],
            destination=tmp_path / "final",
        )
    assert captured.value.category == "security"


def test_rtc_007_010_platform_command_semantics_accept_both_runtime_names() -> None:
    assert _is_command_tool("exec")
    assert _is_command_tool("process")
    assert _is_command_tool("Bash")
    assert not _is_command_tool("Read")
