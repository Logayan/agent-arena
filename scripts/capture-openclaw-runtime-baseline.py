from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.app.openclaw_runtime import OpenClawRuntime
from server.app.secret_store import unprotect_secret


def run(command: list[str], *, env: dict[str, str] | None = None) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-12000:],
        "stderr": completed.stderr[-12000:],
    }


def redact(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, dict):
        return {str(key): redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    return value


def classify_real_probe_error(error: str) -> str:
    normalized_error = error.lower()
    if "billing" in normalized_error or "insufficient balance" in normalized_error:
        return "provider_billing"
    if "http 401" in normalized_error or "status=401" in normalized_error or "reason=auth" in normalized_error:
        return "provider_auth"
    return "runtime_failure"


def has_successful_baseline_exec(actions: list[dict[str, Any]]) -> bool:
    return any(
        action.get("kind") == "tool_result"
        and action.get("tool_name") == "exec"
        and action.get("is_error") is False
        and action.get("status") == "completed"
        and action.get("exit_code") == 0
        and "OPENCLAW_BASELINE_OK" in str(action.get("output") or "")
        for action in actions
    )


def load_real_model_config(source: str, database_path: str) -> dict[str, Any]:
    if source == "environment":
        required = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_DEFAULT_SONNET_MODEL")
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise RuntimeError(f"missing_environment:{','.join(missing)}")
        return {
            "source": "environment",
            "provider": "anthropic-compatible",
            "base_url": str(os.environ["ANTHROPIC_BASE_URL"]),
            "model": str(os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"]),
            "token": str(os.environ["ANTHROPIC_AUTH_TOKEN"]),
            "tier": "medium",
        }

    db_path = (PROJECT_ROOT / database_path).resolve()
    if not db_path.is_file():
        raise RuntimeError("active_model_database_missing")
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """SELECT id,name,provider,base_url,model,tier,encrypted_token
               FROM model_configs
               WHERE active=1
               ORDER BY CASE tier WHEN 'medium' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,
                        updated_at DESC LIMIT 1"""
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise RuntimeError("active_model_config_missing")
    key_path = Path(os.getenv("JIANGHU_SECRET_KEY_FILE", str(db_path.parent / ".jianghu-secret.key"))).resolve()
    return {
        "source": "active-database",
        "config_id": str(row["id"]),
        "config_name": str(row["name"]),
        "provider": str(row["provider"]),
        "base_url": str(row["base_url"]),
        "model": str(row["model"]),
        "token": unprotect_secret(str(row["encrypted_token"]), key_path=key_path),
        "tier": str(row["tier"] or "medium"),
    }


async def real_probe(output_root: Path, model_config: dict[str, Any]) -> dict[str, Any]:
    token = str(model_config["token"])
    runtime = OpenClawRuntime(output_root / "real-state", output_root / "real-workspaces")
    agent = {
        "id": "agent_openclaw_baseline_v1",
        "name": "基线工程师",
        "role": "软件工程师",
        "version": "1.0.0",
        "persona": "严格按照可验证命令完成任务。",
        "skills": [
            {
                "key": "baseline-verification",
                "name": "基线验证",
                "description": "创建确定性文件并运行校验命令",
                "instructions": "必须创建要求的文件并真实执行读取校验命令。",
                "enabled": True,
            }
        ],
    }
    sync = runtime.sync(
        [agent],
        {agent["id"]: [{"title": "基线规则", "content": "交付必须包含 OPENCLAW_BASELINE_OK。"}]},
        model_config,
        tool_enabled_agent_ids={agent["id"]},
    )
    streamed_actions: list[dict[str, Any]] = []

    async def on_action(action: dict[str, Any]) -> None:
        streamed_actions.append(action)

    try:
        response = await runtime.message(
            agent=agent,
            prompt=(
                "这是 OpenClaw Runtime 迁移前的受控能力基线。请使用文件与命令工具，只在 delivery 目录内行动："
                "创建 delivery/openclaw-baseline.txt，内容必须恰好为 OPENCLAW_BASELINE_OK 加换行；"
                "然后将工作目录设为 delivery，并执行普通 PowerShell 命令 "
                "Get-Content -Raw -LiteralPath .\\openclaw-baseline.txt 读取并验证内容。"
                "不要使用 python -c、node -e、PowerShell -Command 或其他内联解释器执行形式。"
                "最终公开回答列出文件、实际命令、退出码和标记 OPENCLAW_BASELINE_OK。"
                "不得读取或输出任何环境变量、Token 或密钥。"
            ),
            session_key="agent:agent_openclaw_baseline_v1:runtime-baseline-real-probe",
            model_config=model_config,
            timeout_seconds=180,
            capture_workspace=True,
            on_action=on_action,
        )
    except Exception as exc:
        error = OpenClawRuntime._redact_public_text(str(exc), [token], 8000)
        category = classify_real_probe_error(error)
        return {
            "status": "blocked" if category in {"provider_billing", "provider_auth"} else "failed",
            "category": category,
            "model_source": model_config.get("source"),
            "provider": model_config["provider"],
            "model": model_config["model"],
            "error": error,
            "streamed_action_count": len(streamed_actions),
            "streamed_actions": redact(streamed_actions, [token]),
        }
    delivery_file = runtime.workspace_path(agent) / "delivery" / "openclaw-baseline.txt"
    file_content = delivery_file.read_text(encoding="utf-8") if delivery_file.is_file() else ""
    actions = list(response.get("actions") or [])
    tool_calls = [item for item in actions if item.get("kind") == "tool_call"]
    tool_results = [item for item in actions if item.get("kind") == "tool_result"]
    command_execution_ok = has_successful_baseline_exec(actions)
    result = {
        "status": "passed" if file_content == "OPENCLAW_BASELINE_OK\n" and tool_calls and tool_results and command_execution_ok else "failed",
        "sync": sync,
        "model_source": model_config.get("source"),
        "provider": model_config["provider"],
        "model": model_config["model"],
        "response_id": response.get("id"),
        "response_text": response.get("content", [{}])[0].get("text", ""),
        "usage": response.get("usage", {}),
        "file_content_ok": file_content == "OPENCLAW_BASELINE_OK\n",
        "command_execution_ok": command_execution_ok,
        "file_changes": response.get("file_changes", []),
        "actions": actions,
        "streamed_action_count": len(streamed_actions),
    }
    return redact(result, [token])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="Run one real model/tool probe.")
    parser.add_argument(
        "--real-model-source",
        choices=("environment", "active-database"),
        default="environment",
        help="Load the real probe model from Anthropic environment variables or the active platform database config.",
    )
    parser.add_argument("--model-database", default=".data/jianghu.db")
    parser.add_argument("--output-root", default=".data/verification/runtime-baselines/openclaw")
    args = parser.parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    commit = run(["git", "rev-parse", "HEAD"])["stdout"].strip()
    baseline_id = f"{timestamp}-{commit[:12] or 'unknown'}"
    output_root = (PROJECT_ROOT / args.output_root / baseline_id).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    runtime = OpenClawRuntime(output_root / "health-state", output_root / "health-workspaces")
    health = runtime.health()
    python = sys.executable
    isolated_env = dict(os.environ)
    isolated_env.update(
        {
            "JIANGHU_DATA_ROOT": str(output_root / "test-data"),
            "JIANGHU_DB_PATH": str(output_root / "test-data" / "test.db"),
            "JIANGHU_WORKSPACE_ROOT": str(output_root / "test-data" / "workspaces"),
            "JIANGHU_KNOWLEDGE_ROOT": str(output_root / "test-data" / "knowledge"),
            "JIANGHU_OPENCLAW_STATE_ROOT": str(output_root / "test-data" / "openclaw"),
        }
    )
    contract = run([python, "-m", "pytest", "server/tests/runtime_contract", "-q"], env=isolated_env)
    existing = run(
        [
            python,
            "-m",
            "pytest",
            "server/tests/test_api.py::test_agent_revision_preserves_frozen_workflow_and_continues_memory_and_knowledge",
            "server/tests/test_api.py::test_openclaw_sync_registers_all_same_endpoint_models_for_per_turn_override",
            "server/tests/test_api.py::test_openclaw_public_action_parser_hides_thinking_and_keeps_tool_evidence",
            "server/tests/test_api.py::test_openclaw_publishes_isolated_engineering_submission_and_promotes_complete_tree",
            "server/tests/test_api.py::test_openclaw_message_streams_public_tool_actions_before_turn_finishes",
            "-q",
        ],
        env=isolated_env,
    )
    real_model_config: dict[str, Any] | None = None
    real_model_error: str | None = None
    if args.real:
        try:
            real_model_config = load_real_model_config(args.real_model_source, args.model_database)
        except Exception as exc:
            real_model_error = str(exc)

    report: dict[str, Any] = {
        "schema_version": "jianghu.openclaw-runtime-baseline.v1",
        "baseline_id": baseline_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "commit": commit,
            "branch": run(["git", "branch", "--show-current"])["stdout"].strip(),
            "worktree_status": run(["git", "status", "--short"])["stdout"].splitlines(),
        },
        "environment": {
            "python": run([python, "--version"]),
            "node": run([str(runtime._node_path()), "--version"]) if runtime._node_path() else None,
            "openclaw_health": health,
            "model_environment_present": {
                name: bool(os.getenv(name))
                for name in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_DEFAULT_SONNET_MODEL")
            },
            "real_model_source": args.real_model_source if args.real else None,
        },
        "tests": {"runtime_contract": contract, "existing_openclaw_regression": existing},
        "real_probe": (
            asyncio.run(real_probe(output_root, real_model_config))
            if real_model_config is not None
            else ({"status": "failed", "category": "model_config", "error": real_model_error} if args.real else {"status": "not_requested"})
        ),
    }
    real_status = report["real_probe"].get("status")
    report["status"] = (
        "passed"
        if contract["exit_code"] == 0 and existing["exit_code"] == 0 and real_status in {"passed", "not_requested"}
        else ("blocked" if contract["exit_code"] == 0 and existing["exit_code"] == 0 and real_status == "blocked" else "failed")
    )
    (output_root / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"baseline_id": baseline_id, "output_root": str(output_root), "status": report["status"], "real_probe": report["real_probe"].get("status")}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else (2 if report["status"] == "blocked" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
