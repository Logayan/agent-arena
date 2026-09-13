from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.app.claude_code_runtime import ClaudeCodeRuntime
from server.app.platform_store import platform_store


AGENT = {
    "id": "g4_adapter_engineer",
    "name": "沈青岚",
    "role": "后端工程师",
    "version": "1.0.0",
    "persona": "先验证、后交付；所有结论必须留下可复验的文件与命令证据。",
    "skills": [
        {
            "key": "g4-verified-delivery",
            "name": "G4 证据化交付",
            "description": "在 delivery 目录生成正式成果并执行真实验证命令。",
            "instructions": "使用获准的 Workspace 工具；最终回答只报告可公开验证的结果。",
            "enabled": True,
        }
    ],
}


def redact(value: Any, token: str) -> Any:
    if isinstance(value, dict):
        return {str(key): redact(item, token) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, token) for item in value]
    if isinstance(value, str):
        return value.replace(token, "[REDACTED]") if token else value
    return value


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist.exe", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return f'"{pid}"' in completed.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def wait_for_file(path: Path, timeout_seconds: float) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if path.is_file():
            return True
        await asyncio.sleep(0.1)
    return path.is_file()


async def run_probe(output_root: Path) -> dict[str, Any]:
    model_config = platform_store.get_active_model_config(include_secret=True)
    if not model_config:
        raise RuntimeError("active_model_config_missing")
    token = str(model_config.get("token") or "")
    if not token:
        raise RuntimeError("active_model_token_missing")
    runtime = ClaudeCodeRuntime(output_root / "state", output_root / "workspaces")
    runtime.sync([AGENT], {}, model_config, tool_enabled_agent_ids={str(AGENT["id"])})
    health = runtime.health()
    streamed: list[dict[str, Any]] = []

    async def on_action(action: dict[str, Any]) -> None:
        streamed.append(action)

    normal_prompt = "\n".join(
        [
            "执行 G4 Claude Runtime Adapter 真实验证。必须按顺序使用 Workspace 工具：",
            "1. 调用 Write，写入 delivery/g4-adapter.txt，内容必须恰好为 G4_ADAPTER_FILE_OK 加一个换行。",
            "2. 调用 Bash 执行下面这条 PowerShell 命令，不得改写：",
            "$matches = Get-ChildItem Env: | Where-Object { $_.Name -match 'ANTHROPIC|OPENAI|API.?KEY|TOKEN|SECRET|PASSWORD|AUTH|CREDENTIAL' }; Write-Output 'G4_POWERSHELL_OK'; if ($matches) { Write-Output 'G4_PROVIDER_ENV_LEAK'; $matches.Name } else { Write-Output 'G4_PROVIDER_ENV_HIDDEN' }",
            "3. 调用 Read 读取 delivery/g4-adapter.txt。",
            "最后回答必须包含 G4_ADAPTER_NORMAL_OK。",
        ]
    )
    first = await runtime.message(
        agent=AGENT,
        prompt=normal_prompt,
        session_key="g4-normal-resume",
        model_config=model_config,
        timeout_seconds=180,
        capture_workspace=True,
        on_action=on_action,
    )
    resume_nonce = "G4_RESUME_7F29"
    resumed = await runtime.message(
        agent=AGENT,
        prompt=f"记住并只回复这个标记：{resume_nonce}",
        session_key="g4-normal-resume",
        model_config=model_config,
        timeout_seconds=120,
    )

    workspace = runtime.workspace_path(AGENT)
    delivery = workspace / "delivery"
    started_path = delivery / "child-started.txt"
    pid_path = delivery / "child.pid"
    survived_path = delivery / "child-survived.txt"
    for path in (started_path, pid_path, survived_path):
        path.unlink(missing_ok=True)
    cancellation_actions: list[dict[str, Any]] = []

    async def on_cancel_action(action: dict[str, Any]) -> None:
        cancellation_actions.append(action)

    cancel_command = (
        "powershell.exe -NoProfile -NonInteractive -Command \"`$PID | Set-Content -LiteralPath 'child.pid'; "
        "'STARTED' | Set-Content -LiteralPath 'child-started.txt'; Start-Sleep -Seconds 60; "
        "'SURVIVED' | Set-Content -LiteralPath 'child-survived.txt'\""
    )
    cancel_prompt = "\n".join(
        [
            "立即调用 Bash 一次，不调用其他工具。命令必须原样使用：",
            cancel_command,
            "命令完成后回答 G4_CANCEL_COMMAND_FINISHED。",
        ]
    )
    cancel_task = asyncio.create_task(
        runtime.message(
            agent=AGENT,
            prompt=cancel_prompt,
            session_key="g4-cancel",
            model_config=model_config,
            timeout_seconds=120,
            on_action=on_cancel_action,
        )
    )
    child_started = await wait_for_file(started_path, 45)
    child_pid = 0
    if child_started and pid_path.is_file():
        try:
            child_pid = int(pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            child_pid = 0
    cancel_task.cancel()
    cancelled = False
    try:
        await cancel_task
    except asyncio.CancelledError:
        cancelled = True
    await asyncio.sleep(1.5)
    child_alive_after_cancel = process_exists(child_pid)
    survived_after_cancel = survived_path.is_file()

    serialized_actions = json.dumps(streamed, ensure_ascii=False)
    action_kinds = [str(item.get("kind") or "") for item in streamed]
    tool_names = [str(item.get("tool_name") or "") for item in streamed if item.get("kind") == "tool_call"]
    output_text = "\n".join(str(item.get("output") or "") for item in streamed if item.get("kind") == "tool_result")
    file_path = delivery / "g4-adapter.txt"
    checks = {
        "health_available": bool(health.get("available")),
        "sdk_version_pinned": health.get("version") == "0.3.268",
        "claude_code_version_pinned": health.get("claude_code_version") == "2.1.268",
        "normal_final_marker": "G4_ADAPTER_NORMAL_OK" in str(first.get("content", [{}])[0].get("text") or ""),
        "delivery_file_exact": file_path.is_file() and file_path.read_text(encoding="utf-8") == "G4_ADAPTER_FILE_OK\n",
        "streamed_tool_call_and_result": "tool_call" in action_kinds and "tool_result" in action_kinds,
        "read_write_bash_observed": all(name in tool_names for name in ("Read", "Write", "Bash")),
        "powershell_command_succeeded": "G4_POWERSHELL_OK" in output_text,
        "provider_environment_hidden": "G4_PROVIDER_ENV_HIDDEN" in output_text and "G4_PROVIDER_ENV_LEAK" not in output_text,
        "provider_token_not_in_actions": token not in serialized_actions,
        "session_resume_exact": str(resumed.get("content", [{}])[0].get("text") or "").strip() == resume_nonce,
        "cancel_task_cancelled": cancelled,
        "cancel_child_started": child_started and child_pid > 0,
        "cancel_child_terminated": child_pid > 0 and not child_alive_after_cancel,
        "cancel_no_surviving_output": not survived_after_cancel,
    }
    result = {
        "schema_version": "jianghu.claude-code-runtime-g4-evidence.v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "status": "passed" if all(checks.values()) else "failed",
        "environment": {"os_name": os.name, "platform": sys.platform},
        "model_config": {
            "source": "active_encrypted_platform_config",
            "provider": str(model_config.get("provider") or ""),
            "base_url_scheme": str(model_config.get("base_url") or "").split(":", 1)[0],
            "model": str(model_config.get("model") or ""),
            "token_present": True,
            "token_persisted_in_result": False,
        },
        "health": health,
        "checks": checks,
        "normal": {
            "session_id_present": bool(first.get("session_id")),
            "action_kinds": action_kinds,
            "tool_names": tool_names,
            "file_changes": first.get("file_changes", []),
            "usage": first.get("usage", {}),
        },
        "cancellation": {
            "action_kinds": [str(item.get("kind") or "") for item in cancellation_actions],
            "child_pid_recorded": child_pid > 0,
            "child_alive_after_cancel": child_alive_after_cancel,
            "survived_file_present": survived_after_cancel,
        },
    }
    return redact(result, token)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="")
    args = parser.parse_args()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_root = Path(args.output_root or f"experiments/claude-agent-sdk-probe/results/g4-adapter-{timestamp}").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    result_path = output_root / "result.json"
    try:
        result = asyncio.run(run_probe(output_root))
    except Exception as exc:
        result = {
            "schema_version": "jianghu.claude-code-runtime-g4-evidence.v1",
            "captured_at": datetime.now(UTC).isoformat(),
            "status": "failed",
            "error": {"name": type(exc).__name__, "message": str(exc)[:2000]},
        }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result.get("status"), "result_path": str(result_path)}, ensure_ascii=False))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
