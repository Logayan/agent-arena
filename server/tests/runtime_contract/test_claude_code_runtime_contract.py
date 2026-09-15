from __future__ import annotations

import asyncio
import json
import shutil
import sys
import textwrap
import time
from pathlib import Path

import pytest

from server.app.agent_runtime import AgentRuntimePort
from server.app.agent_runtime_registry import agent_runtime
from server.app.claude_code_runtime import (
    ClaudeCodeRuntime,
    ClaudeCodeRuntimeError,
    _run_workspace_root,
    claude_code_runtime,
)


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
        textwrap.dedent(
            """
            import json
            import sys
            import time
            from pathlib import Path

            payload = json.load(sys.stdin)
            marker = Path(payload["workspace"]) / ".blocking-bridge-started"
            marker.write_text("started\\n", encoding="utf-8")
            time.sleep(60)
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def _heartbeat_bridge(tmp_path: Path) -> Path:
    path = tmp_path / "heartbeat_bridge.py"
    path.write_text(
        textwrap.dedent(
            """
            import json
            import sys
            import time

            payload = json.load(sys.stdin)
            for _ in range(7):
                print(json.dumps({"type": "heartbeat"}), flush=True)
                time.sleep(0.2)
            print(json.dumps({
                "type": "result",
                "result": {
                    "session_id": "sdk-session-long",
                    "model": payload["model"],
                    "is_error": False,
                    "text": "LONG_RUNNING_OK",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            }), flush=True)
            """
        ).strip()
        + "\n",
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


def test_run_workspace_root_uses_short_temp_root_only_for_deep_windows_path(tmp_path) -> None:
    execution_root = tmp_path / ("deep-segment-" * 12)
    windows_root = _run_workspace_root(
        execution_root,
        "run-long-path",
        platform_name="nt",
        temporary_root=tmp_path / "short",
    )
    posix_root = _run_workspace_root(
        execution_root,
        "run-long-path",
        platform_name="posix",
        temporary_root=tmp_path / "short",
    )

    assert windows_root.parent == (tmp_path / "short" / "jianghu-claude-agents").resolve()
    assert windows_root.name.startswith("run-long-path-")
    assert posix_root == execution_root.resolve() / "tmp" / "claude-agents"


def test_run_workspace_root_preserves_short_windows_execution_root(tmp_path) -> None:
    execution_root = Path("C:/jh")

    assert _run_workspace_root(
        execution_root,
        "run-short",
        platform_name="nt",
        temporary_root=tmp_path / "short",
    ) == execution_root.resolve() / "tmp" / "claude-agents"


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


def test_workspace_seed_copy_skips_unchanged_large_files(monkeypatch, tmp_path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    payload = source / "large-evidence.bin"
    payload.write_bytes(b"evidence" * 1024)

    ClaudeCodeRuntime._copy_tree(source, destination)
    copied: list[tuple[Path, Path]] = []
    real_copy2 = shutil.copy2

    def track_copy(source_path, destination_path, *args, **kwargs):
        copied.append((Path(source_path), Path(destination_path)))
        return real_copy2(source_path, destination_path, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", track_copy)
    ClaudeCodeRuntime._copy_tree(source, destination)
    assert copied == []

    time.sleep(0.01)
    payload.write_bytes(b"changed-evidence" * 1024)
    ClaudeCodeRuntime._copy_tree(source, destination)
    assert copied == [(payload, destination / payload.name)]
    assert (destination / payload.name).read_bytes() == payload.read_bytes()


def test_workspace_change_snapshot_excludes_platform_evidence_cache(tmp_path) -> None:
    delivery = tmp_path / "delivery"
    evidence = delivery / ".jianghu-platform-evidence" / "artifacts"
    evidence.mkdir(parents=True)
    (evidence / "large-immutable-evidence.bin").write_bytes(b"immutable" * 1024)
    (delivery / "actual-delivery.txt").write_text("changed", encoding="utf-8")

    snapshot = ClaudeCodeRuntime._workspace_snapshot(delivery)

    assert set(snapshot) == {"actual-delivery.txt"}


def test_workspace_change_snapshot_excludes_playwright_browser_runtime(tmp_path) -> None:
    delivery = tmp_path / "delivery"
    browser_runtime = delivery / ".playwright-browsers" / "chromium" / "chrome-win64"
    browser_runtime.mkdir(parents=True)
    (browser_runtime / "chrome.exe").write_bytes(b"browser-runtime" * 1024)
    (delivery / "evidence" / "screenshot.png").parent.mkdir(parents=True)
    (delivery / "evidence" / "screenshot.png").write_bytes(b"real-e2e-evidence")

    snapshot = ClaudeCodeRuntime._workspace_snapshot(delivery)

    assert set(snapshot) == {"evidence/screenshot.png"}


def test_workspace_promotion_excludes_playwright_browser_runtime(tmp_path) -> None:
    runtime = ClaudeCodeRuntime(tmp_path / "state", tmp_path / "workspaces")
    agent = _agent()
    delivery = runtime.workspace_path(agent) / "delivery"
    browser_runtime = delivery / ".playwright-browsers" / "chromium"
    browser_runtime.mkdir(parents=True)
    (browser_runtime / "chrome.exe").write_bytes(b"browser-runtime")
    (delivery / "evidence.json").write_text('{"status":"passed"}\n', encoding="utf-8")

    destination = tmp_path / "product-source"
    promoted = runtime.promote_workspace_tree(agent=agent, destination=destination)

    assert (destination / "evidence.json").is_file()
    assert not (destination / ".playwright-browsers").exists()
    assert [item["path"] for item in promoted] == ["evidence.json"]


def test_current_attempt_evidence_bundle_is_mirrored_with_artifact_bytes(tmp_path) -> None:
    runtime = ClaudeCodeRuntime(tmp_path / "state", tmp_path / "workspaces")
    agent = _agent()
    runtime.sync([agent], {}, MODEL_CONFIG, tool_enabled_agent_ids={str(agent["id"])})
    source_evidence = tmp_path / "run-code" / ".jianghu-platform-evidence"
    bundle = source_evidence / "snapshots" / "attempt-current"
    artifacts = source_evidence / "artifacts"
    bundle.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    artifact_bytes = b"exact production source bytes\n"
    artifact_file = artifacts / "artifact-source-deadbeef.py"
    artifact_file.write_bytes(artifact_bytes)
    (bundle / "events.ndjson").write_text('{"sequence":1}\n', encoding="utf-8")
    (bundle / "artifact-registry.json").write_text(
        json.dumps(
            [
                {
                    "id": "artifact_source",
                    "title": "server/app/main.py",
                    "materialized": True,
                    "materialized_path": "../../artifacts/artifact-source-deadbeef.py",
                    "expected_sha256": "deadbeef",
                }
            ]
        ),
        encoding="utf-8",
    )

    delivery = runtime.workspace_path(agent) / "delivery"
    delivery.mkdir(parents=True, exist_ok=True)
    mirrored = runtime._mirror_evidence_bundle(bundle, delivery)

    assert mirrored == delivery / ".jianghu-platform-evidence" / "snapshots" / "attempt-current"
    assert (mirrored / "events.ndjson").read_text(encoding="utf-8") == '{"sequence":1}\n'
    assert (mirrored / "artifact-registry.json").is_file()
    assert (mirrored / "../../artifacts/artifact-source-deadbeef.py").resolve().read_bytes() == artifact_bytes
    assert runtime._workspace_snapshot(delivery) == {}


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
    assert str(streamed[0]["sdk_invocation_id"]).startswith("sdk-invocation-")
    assert streamed[0]["claude_sdk_session_id"] == "sdk-session-1"
    assert streamed[0]["tool_use_id"] == "call-1"
    assert len(str(streamed[0]["request_sha256"])) == 64
    assert streamed[1]["request_sha256"] == streamed[0]["request_sha256"]
    assert len(str(streamed[1]["result_sha256"])) == 64
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
async def test_claude_message_keeps_event_loop_responsive_during_large_seed_copy(
    monkeypatch, tmp_path
) -> None:
    runtime = ClaudeCodeRuntime(tmp_path / "state", tmp_path / "workspaces")
    agent = _agent()
    runtime.sync([agent], {}, MODEL_CONFIG, tool_enabled_agent_ids={str(agent["id"])})
    bridge = _fake_bridge(tmp_path)
    monkeypatch.setattr(runtime, "_base_command", lambda: [sys.executable, str(bridge)])
    seed = tmp_path / "large-seed"
    seed.mkdir()
    original_copy = runtime._copy_tree

    def slow_copy(source: Path, destination: Path) -> None:
        time.sleep(0.25)
        original_copy(source, destination)

    monkeypatch.setattr(runtime, "_copy_tree", slow_copy)
    started = time.monotonic()
    message = asyncio.create_task(
        runtime.message(
            agent=agent,
            prompt="验证复制期间事件循环仍响应",
            session_key="responsive-seed-copy",
            model_config=MODEL_CONFIG,
            timeout_seconds=5,
            seed_directory=seed,
            capture_workspace=True,
        )
    )

    await asyncio.sleep(0.03)
    heartbeat_elapsed = time.monotonic() - started
    result = await message

    assert heartbeat_elapsed < 0.15
    assert result["content"][0]["text"] == "G4_ADAPTER_OK"


@pytest.mark.anyio
async def test_claude_message_has_no_total_deadline_while_bridge_is_alive(
    monkeypatch, tmp_path
) -> None:
    runtime = ClaudeCodeRuntime(tmp_path / "state", tmp_path / "workspaces")
    agent = _agent()
    runtime.sync([agent], {}, MODEL_CONFIG)
    bridge = _heartbeat_bridge(tmp_path)
    monkeypatch.setattr(runtime, "_base_command", lambda: [sys.executable, str(bridge)])
    heartbeats: list[dict[str, object]] = []

    async def on_action(action: dict[str, object]) -> None:
        if action.get("kind") == "heartbeat":
            heartbeats.append(action)

    started = time.monotonic()
    result = await runtime.message(
        agent=agent,
        prompt="执行超过单个健康窗口的长任务",
        session_key="long-running-heartbeat",
        model_config=MODEL_CONFIG,
        timeout_seconds=1,
        on_action=on_action,
    )

    assert time.monotonic() - started >= 1.2
    assert result["content"][0]["text"] == "LONG_RUNNING_OK"
    assert heartbeats
    assert str(heartbeats[0]["sdk_invocation_id"]).startswith("sdk-invocation-")


@pytest.mark.anyio
async def test_claude_message_terminates_only_after_bridge_inactivity(
    monkeypatch, tmp_path
) -> None:
    runtime = ClaudeCodeRuntime(tmp_path / "state", tmp_path / "workspaces")
    agent = _agent()
    runtime.sync([agent], {}, MODEL_CONFIG)
    bridge = _blocking_bridge(tmp_path)
    monkeypatch.setattr(runtime, "_base_command", lambda: [sys.executable, str(bridge)])

    started = time.monotonic()
    with pytest.raises(ClaudeCodeRuntimeError, match="claude_stalled:1s"):
        await runtime.message(
            agent=agent,
            prompt="模拟底座停止心跳",
            session_key="stalled-heartbeat",
            model_config=MODEL_CONFIG,
            timeout_seconds=1,
        )

    assert time.monotonic() - started < 5


def test_workspace_snapshot_tolerates_disappearing_browser_trace_directory(
    monkeypatch, tmp_path
) -> None:
    root = tmp_path / "delivery"
    root.mkdir()
    stable = root / "report.json"
    stable.write_text('{"status":"passed"}', encoding="utf-8")

    def unstable_rglob(_self: Path, _pattern: str):
        yield stable
        raise FileNotFoundError("playwright trace directory disappeared")

    monkeypatch.setattr(Path, "rglob", unstable_rglob)

    snapshot = ClaudeCodeRuntime._workspace_snapshot(root)

    assert list(snapshot) == ["report.json"]
    assert snapshot["report.json"]["size_bytes"] == stable.stat().st_size


def test_seed_copy_tolerates_disappearing_browser_trace_file(
    monkeypatch, tmp_path
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "report.json").write_text('{"status":"passed"}', encoding="utf-8")
    (source / "trace.tmp").write_text("transient", encoding="utf-8")
    original_copy = shutil.copy2

    def copy_with_transient_removal(path: Path, target: Path):
        if path.name == "trace.tmp":
            path.unlink(missing_ok=True)
            raise FileNotFoundError(path)
        return original_copy(path, target)

    monkeypatch.setattr("server.app.claude_code_runtime.shutil.copy2", copy_with_transient_removal)

    ClaudeCodeRuntime._copy_tree(source, destination)

    assert (destination / "report.json").read_text(encoding="utf-8") == '{"status":"passed"}'
    assert not (destination / "trace.tmp").exists()


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
    marker = runtime.workspace_path(agent) / ".blocking-bridge-started"
    for _ in range(300):
        if marker.is_file():
            break
        await asyncio.sleep(0.01)
    assert marker.is_file(), "blocking bridge did not reach its running state"
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
