from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.app.claude_code_runtime import ClaudeCodeRuntime
from server.app.openclaw_runtime import OpenClawRuntime
from server.app.platform_store import platform_store


AGENT = {
    "id": "g5_parity_engineer",
    "name": "沈青岚",
    "role": "后端工程师",
    "version": "1.0.0",
    "persona": "只按可公开复验的文件和命令证据交付。",
    "skills": [
        {
            "key": "g5-parity-delivery",
            "name": "G5 同题交付",
            "description": "创建确定性文件并执行普通命令复验。",
            "instructions": "必须实际使用文件和命令工具，不以文字声明代替执行。",
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


def action_summary(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for action in actions:
        item = {
            "kind": str(action.get("kind") or ""),
            "tool_name": str(action.get("tool_name") or ""),
            "status": str(action.get("status") or ""),
            "is_error": bool(action.get("is_error")) if "is_error" in action else None,
            "exit_code": action.get("exit_code"),
        }
        if action.get("kind") == "tool_result":
            item["output"] = str(action.get("output") or "")[:2000]
        summary.append(item)
    return summary


def has_successful_command(runtime_name: str, actions: list[dict[str, Any]]) -> bool:
    accepted_names = {"exec"} if runtime_name == "openclaw" else {"Bash"}
    return any(
        action.get("kind") == "tool_result"
        and str(action.get("tool_name") or "") in accepted_names
        and action.get("is_error") is False
        and action.get("status") == "completed"
        and action.get("exit_code") == 0
        and "RUNTIME_PARITY_OK" in str(action.get("output") or "")
        for action in actions
    )


async def run_runtime(runtime_name: str, output_root: Path, model_config: dict[str, Any]) -> dict[str, Any]:
    runtime = (
        OpenClawRuntime(output_root / "state", output_root / "workspaces")
        if runtime_name == "openclaw"
        else ClaudeCodeRuntime(output_root / "state", output_root / "workspaces")
    )
    sync = runtime.sync(
        [AGENT],
        {AGENT["id"]: [{"title": "同题规则", "content": "交付标记必须是 RUNTIME_PARITY_OK。"}]},
        model_config,
        tool_enabled_agent_ids={str(AGENT["id"])},
    )
    streamed: list[dict[str, Any]] = []

    async def on_action(action: dict[str, Any]) -> None:
        streamed.append(action)

    if runtime_name == "openclaw":
        prompt = (
            "执行 Runtime G5 同题真实验证。只在 delivery 目录行动。"
            "使用文件工具创建 delivery/runtime-parity.txt，内容必须恰好是 RUNTIME_PARITY_OK 加一个换行；"
            "然后把工作目录设为 delivery，执行普通 PowerShell 命令 "
            "Get-Content -Raw -LiteralPath .\\runtime-parity.txt。"
            "不要使用 python -c、node -e 或 PowerShell -Command。"
            "最终回答包含 G5_SINGLE_AGENT_OK。不得读取环境变量或任何密钥。"
        )
    else:
        prompt = "\n".join(
            [
                "执行 Runtime G5 同题真实验证。按顺序使用 Workspace 工具：",
                "1. Write 写入 delivery/runtime-parity.txt，内容恰好是 RUNTIME_PARITY_OK 加一个换行。",
                "2. Bash 执行：Get-Content -Raw -LiteralPath .\\runtime-parity.txt",
                "3. Read 读取 delivery/runtime-parity.txt。",
                "最终回答包含 G5_SINGLE_AGENT_OK。不得读取环境变量或任何密钥。",
            ]
        )

    started = time.perf_counter()
    response = await runtime.message(
        agent=AGENT,
        prompt=prompt,
        session_key="g5-single-agent-resume",
        model_config=model_config,
        timeout_seconds=180,
        capture_workspace=True,
        on_action=on_action,
    )
    elapsed = time.perf_counter() - started
    resume_marker = f"G5_RESUME_{runtime_name.upper()}"
    resumed_started = time.perf_counter()
    resumed = await runtime.message(
        agent=AGENT,
        prompt=f"只回复这个标记，不要添加其他内容：{resume_marker}",
        session_key="g5-single-agent-resume",
        model_config=model_config,
        timeout_seconds=120,
    )
    resumed_elapsed = time.perf_counter() - resumed_started
    delivery_file = runtime.workspace_path(AGENT) / "delivery" / "runtime-parity.txt"
    file_bytes = delivery_file.read_bytes() if delivery_file.is_file() else b""
    actions = list(response.get("actions") or [])
    streamed_serialized = json.dumps(streamed, ensure_ascii=False)
    response_text = str(response.get("content", [{}])[0].get("text") or "")
    resume_text = str(resumed.get("content", [{}])[0].get("text") or "").strip()
    checks = {
        "health_available": bool(runtime.health().get("available")),
        "file_exact": file_bytes == b"RUNTIME_PARITY_OK\n",
        "file_change_reported": any(
            item.get("path") == "runtime-parity.txt" and item.get("action") in {"created", "modified"}
            for item in response.get("file_changes", [])
        ),
        "tool_action_streamed_before_return": any(
            item.get("kind") in {"tool_call", "tool_result"} for item in streamed
        ),
        "tool_call_observed": any(item.get("kind") == "tool_call" for item in actions),
        "tool_result_observed": any(item.get("kind") == "tool_result" for item in actions),
        "command_succeeded": has_successful_command(runtime_name, actions),
        "final_marker": "G5_SINGLE_AGENT_OK" in response_text,
        "session_id_present": bool(response.get("session_id")),
        "resume_exact": resume_text == resume_marker,
        "usage_present": int(response.get("usage", {}).get("input_tokens", 0) or 0) > 0
        and int(response.get("usage", {}).get("output_tokens", 0) or 0) > 0,
        "token_not_public": str(model_config["token"]) not in streamed_serialized
        and str(model_config["token"]) not in response_text,
    }
    blocking_checks = {
        key: value
        for key, value in checks.items()
        if key != "tool_action_streamed_before_return"
    }
    return {
        "runtime": runtime_name,
        "status": "passed" if all(blocking_checks.values()) else "failed",
        "checks": checks,
        "blocking_checks": blocking_checks,
        "sync": {
            "runtime": sync.get("runtime"),
            "agent_count": sync.get("agent_count"),
            "models": sync.get("models"),
        },
        "health": runtime.health(),
        "result": {
            "session_id_present": bool(response.get("session_id")),
            "model": response.get("model"),
            "usage": response.get("usage", {}),
            "duration_seconds": round(elapsed, 3),
            "resume_duration_seconds": round(resumed_elapsed, 3),
            "file_sha256": hashlib.sha256(file_bytes).hexdigest() if file_bytes else "",
            "file_size_bytes": len(file_bytes),
            "file_changes": response.get("file_changes", []),
            "actions": action_summary(actions),
            "streamed_action_kinds": [str(item.get("kind") or "") for item in streamed],
        },
    }


async def run_comparison(output_root: Path) -> dict[str, Any]:
    model_config = platform_store.get_active_model_config(include_secret=True)
    if not model_config or not model_config.get("token"):
        raise RuntimeError("active_model_config_missing")
    token = str(model_config["token"])
    results: dict[str, Any] = {}
    for runtime_name in ("openclaw", "claude_code"):
        try:
            results[runtime_name] = await run_runtime(runtime_name, output_root / runtime_name, model_config)
        except Exception as exc:
            results[runtime_name] = {
                "runtime": runtime_name,
                "status": "failed",
                "error": {"name": type(exc).__name__, "message": str(exc)[:2000]},
            }
    openclaw = results["openclaw"]
    claude = results["claude_code"]
    parity_checks = {
        "both_passed": openclaw.get("status") == "passed" and claude.get("status") == "passed",
        "same_file_sha256": openclaw.get("result", {}).get("file_sha256")
        == claude.get("result", {}).get("file_sha256"),
        "same_file_size": openclaw.get("result", {}).get("file_size_bytes")
        == claude.get("result", {}).get("file_size_bytes"),
        "both_report_usage": all(
            int(results[name].get("result", {}).get("usage", {}).get("input_tokens", 0) or 0) > 0
            for name in results
        ),
    }
    report = {
        "schema_version": "jianghu.runtime-g5-single-agent-comparison.v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "environment": {"platform": sys.platform, "os_name": os.name},
        "model_config": {
            "source": "active_encrypted_platform_config",
            "provider": str(model_config.get("provider") or ""),
            "base_url_scheme": str(model_config.get("base_url") or "").split(":", 1)[0],
            "model": str(model_config.get("model") or ""),
            "token_present": True,
            "token_persisted_in_result": False,
        },
        "status": "passed" if all(parity_checks.values()) else "failed",
        "parity_checks": parity_checks,
        "runtimes": results,
    }
    return redact(report, token)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="")
    args = parser.parse_args()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_root = Path(
        args.output_root or f"experiments/runtime-g5/results/single-agent-{timestamp}"
    ).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    result_path = output_root / "result.json"
    try:
        report = asyncio.run(run_comparison(output_root))
    except Exception as exc:
        report = {
            "schema_version": "jianghu.runtime-g5-single-agent-comparison.v1",
            "captured_at": datetime.now(UTC).isoformat(),
            "status": "failed",
            "error": {"name": type(exc).__name__, "message": str(exc)[:2000]},
        }
    result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report.get("status"), "result_path": str(result_path)}, ensure_ascii=False))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
