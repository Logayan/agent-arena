from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

from server.app.openclaw_runtime import OpenClawRuntime


@pytest.fixture
def capability_cases() -> dict[str, object]:
    path = Path(__file__).with_name("capability_cases.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_capability_manifest_is_complete_and_unique(capability_cases) -> None:
    cases = capability_cases["cases"]
    ids = [item["id"] for item in cases]
    assert capability_cases["schema_version"] == "jianghu.agent-runtime-capabilities.v1"
    assert ids == [f"RTC-{index:03d}" for index in range(1, 33)]
    assert len(ids) == len(set(ids))
    assert all(item["priority"] in {"P0", "P1"} for item in cases)


def test_openclaw_sync_projects_identity_memory_skills_models_and_tool_policy(tmp_path) -> None:
    runtime = OpenClawRuntime(tmp_path / "state", tmp_path / "workspaces")
    engineer = {
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
    analyst = {
        "id": "agent_analyst_v1",
        "name": "叶知秋",
        "role": "需求分析",
        "version": "1.0.0",
        "persona": "区分事实和假设。",
        "skills": [],
    }
    model = {
        "provider": "anthropic-compatible",
        "base_url": "https://model.example.test",
        "model": "claude-sonnet-baseline",
        "token": "baseline-secret",
    }
    alternate = {**model, "model": "claude-opus-baseline"}
    result = runtime.sync(
        [engineer, analyst],
        {engineer["id"]: [{"title": "历史交付", "content": "曾完成一次可复验修复。"}]},
        model,
        tool_enabled_agent_ids={engineer["id"]},
        model_configs=[alternate],
    )

    engineer_workspace = runtime.workspace_path(engineer)
    analyst_workspace = runtime.workspace_path(analyst)
    assert "沈青岚" in (engineer_workspace / "IDENTITY.md").read_text(encoding="utf-8")
    assert "先验证再交付" in (engineer_workspace / "SOUL.md").read_text(encoding="utf-8")
    assert "曾完成一次可复验修复" in (engineer_workspace / "MEMORY.md").read_text(encoding="utf-8")
    assert (engineer_workspace / "skills" / "verified-delivery" / "SKILL.md").is_file()
    assert analyst_workspace != engineer_workspace
    config = json.loads(runtime.config_path.read_text(encoding="utf-8"))
    agents = {item["id"]: item for item in config["agents"]["list"]}
    assert agents[engineer["id"]]["tools"]["profile"] == "coding"
    assert agents[analyst["id"]]["tools"]["profile"] == "minimal"
    assert result["models"] == ["jianghu/claude-sonnet-baseline", "jianghu/claude-opus-baseline"]
    assert "baseline-secret" not in runtime.config_path.read_text(encoding="utf-8")


def test_openclaw_run_and_agent_workspaces_are_isolated(tmp_path) -> None:
    runtime = OpenClawRuntime(tmp_path / "state", tmp_path / "workspaces")
    first = {"id": "agent_family_v1"}
    second = {"id": "agent_family_v2"}
    assert runtime.workspace_path(first) != runtime.workspace_path(second)
    run_one = runtime.for_run("run-one", tmp_path / "runs" / "run-one")
    run_two = runtime.for_run("run-two", tmp_path / "runs" / "run-two")
    assert run_one.state_root != run_two.state_root
    assert run_one.workspace_root != run_two.workspace_root
    assert run_one.state_root.is_relative_to(runtime.state_root)
    assert run_two.state_root.is_relative_to(runtime.state_root)


def test_openclaw_public_actions_hide_thinking_and_redact_secrets(tmp_path) -> None:
    session_file = tmp_path / "session.jsonl"
    secret = "baseline-top-secret"
    records = [
        {
            "type": "message",
            "timestamp": "2026-09-11T10:00:00Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "private chain must stay hidden"},
                    {"type": "text", "text": "正在运行验证命令。"},
                    {"type": "toolCall", "id": "call-1", "name": "exec", "arguments": {"command": f"pytest -q --token={secret}"}},
                ],
            },
        },
        {
            "type": "message",
            "timestamp": "2026-09-11T10:00:01Z",
            "message": {
                "role": "toolResult",
                "toolCallId": "call-1",
                "toolName": "exec",
                "content": [{"type": "text", "text": "12 passed"}],
                "details": {"status": "completed", "exitCode": 0, "durationMs": 812, "cwd": str(tmp_path)},
                "isError": False,
            },
        },
    ]
    session_file.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records), encoding="utf-8")
    actions = OpenClawRuntime._extract_public_actions(session_file, [secret])
    serialized = json.dumps(actions, ensure_ascii=False)
    assert [item["kind"] for item in actions] == ["progress", "tool_call", "tool_result"]
    assert "private chain" not in serialized
    assert secret not in serialized
    assert "[REDACTED]" in serialized
    assert actions[-1]["exit_code"] == 0
    assert actions[-1]["output"] == "12 passed"


def test_openclaw_submission_and_promotion_preserve_public_delivery_tree(tmp_path) -> None:
    runtime = OpenClawRuntime(tmp_path / "state", tmp_path / "workspaces")
    contributor = {"id": "agent_contributor", "name": "林砚", "role": "工程师"}
    lead = {"id": "agent_lead", "name": "顾行舟", "role": "技术负责人"}
    contributor_delivery = runtime.workspace_path(contributor) / "delivery"
    (contributor_delivery / "src").mkdir(parents=True)
    (contributor_delivery / "src" / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    changes = runtime._workspace_changes({}, runtime._workspace_snapshot(contributor_delivery))
    submission = runtime.publish_workspace_submission(
        agent=contributor,
        changes=changes,
        destination=runtime.workspace_path(lead) / "collaboration" / "node-build" / contributor["id"],
    )
    assert submission["file_count"] == 1
    assert (Path(submission["files_root"]) / "src" / "feature.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (Path(submission["root"]) / "MEMORY.md").exists()

    lead_delivery = runtime.workspace_path(lead) / "delivery"
    lead_delivery.mkdir(parents=True)
    (lead_delivery / "app.py").write_text("print('ready')\n", encoding="utf-8")
    final_root = tmp_path / "run" / "code"
    final_root.mkdir(parents=True)
    (final_root / "stale.txt").write_text("remove", encoding="utf-8")
    promoted = runtime.promote_workspace_tree(agent=lead, destination=final_root)
    assert (final_root / "app.py").read_text(encoding="utf-8") == "print('ready')\n"
    assert not (final_root / "stale.txt").exists()
    assert {(item["action"], item["path"]) for item in promoted} == {
        ("created", "app.py"),
        ("deleted", "stale.txt"),
    }


@pytest.mark.anyio
async def test_openclaw_message_emits_tools_before_return_and_captures_files(monkeypatch, tmp_path) -> None:
    runtime = OpenClawRuntime(tmp_path / "state", tmp_path / "workspaces")
    agent = {"id": "agent_stream", "name": "林砚", "role": "后端工程师"}
    session_key = "agent:agent_stream:baseline-delivery"
    sessions_dir = tmp_path / "state" / "agents" / "agent_stream" / "sessions"
    session_file = sessions_dir / "session-live.jsonl"
    callback_seen = threading.Event()
    callback_before_return = {"value": False}

    def fake_run(*args, **kwargs):
        command = args[0]
        assert command[command.index("--model") + 1] == "jianghu/test-model"
        workspace = runtime.workspace_path(agent)
        (workspace / "delivery").mkdir(parents=True, exist_ok=True)
        (workspace / "delivery" / "baseline.py").write_text("print('ok')\n", encoding="utf-8")
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (sessions_dir / "sessions.json").write_text(
            json.dumps({session_key: {"sessionId": "session-live", "sessionFile": str(session_file)}}),
            encoding="utf-8",
        )
        first = {
            "type": "message",
            "timestamp": "2026-09-11T10:00:00Z",
            "message": {"role": "assistant", "content": [{"type": "toolCall", "id": "call-live", "name": "exec", "arguments": {"command": "pytest -q"}}]},
        }
        session_file.write_text(json.dumps(first, ensure_ascii=False) + "\n", encoding="utf-8")
        callback_before_return["value"] = callback_seen.wait(timeout=2)
        records = [
            {
                "type": "message",
                "timestamp": "2026-09-11T10:00:01Z",
                "message": {"role": "toolResult", "toolCallId": "call-live", "toolName": "exec", "content": [{"type": "text", "text": "3 passed"}], "details": {"status": "completed", "exitCode": 0}, "isError": False},
            },
            {
                "type": "message",
                "timestamp": "2026-09-11T10:00:02Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "基线工程交付完成。"}]},
            },
        ]
        with session_file.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        payload = {"sessionId": "session-live", "payloads": [{"text": "基线工程交付完成。"}], "usage": {"inputTokens": 100, "outputTokens": 20}}
        return subprocess.CompletedProcess(args[0], 0, stdout=json.dumps(payload, ensure_ascii=False), stderr="")

    monkeypatch.setattr(runtime, "_base_command", lambda: ["openclaw-test"])
    monkeypatch.setattr("server.app.openclaw_runtime.subprocess.run", fake_run)
    streamed = []

    async def on_action(action):
        streamed.append(action)
        if action.get("kind") == "tool_call":
            callback_seen.set()

    response = await runtime.message(
        agent=agent,
        prompt="创建文件并运行测试",
        session_key=session_key,
        model_config={"model": "test-model", "token": "secret"},
        timeout_seconds=10,
        on_action=on_action,
        capture_workspace=True,
    )
    assert callback_before_return["value"] is True
    assert [item["kind"] for item in streamed] == ["tool_call", "tool_result", "progress"]
    assert response["usage"] == {"input_tokens": 100, "output_tokens": 20}
    assert response["session_id"] == "session-live"
    assert [item["path"] for item in response["file_changes"]] == ["baseline.py"]
    assert response["content"][0]["text"] == "基线工程交付完成。"
