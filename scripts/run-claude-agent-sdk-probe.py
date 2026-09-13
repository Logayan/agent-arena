from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
PROBE_ROOT = ROOT / "experiments" / "claude-agent-sdk-probe"
RESULTS_ROOT = PROBE_ROOT / "results"


def redact_text(value: str, token: str) -> str:
    text = str(value or "")
    if token:
        text = text.replace(token, "<redacted-token>")
    return text[:600]


def endpoint_url(base_url: str, suffix: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    return f"{normalized}/v1/{suffix.lstrip('/')}"


def protocol_probe(config: dict[str, Any]) -> dict[str, Any]:
    token = str(config["token"])
    body = {
        "model": str(config["model"]),
        "max_tokens": 8,
        "messages": [{"role": "user", "content": "Reply OK"}],
    }
    try:
        response = httpx.post(
            endpoint_url(str(config["base_url"]), "messages"),
            headers={
                "x-api-key": token,
                "Authorization": f"Bearer {token}",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
            timeout=30,
        )
        content_type = response.headers.get("content-type", "")
        provider_type = None
        provider_error_type = None
        if "json" in content_type:
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    provider_type = payload.get("type")
                    error = payload.get("error")
                    if isinstance(error, dict):
                        provider_error_type = error.get("type") or error.get("code")
            except ValueError:
                pass
        return {
            "status": "passed" if response.is_success else "failed",
            "http_status": response.status_code,
            "content_type": content_type.split(";", 1)[0],
            "provider_type": provider_type,
            "provider_error_type": provider_error_type,
            "body_sha256_present": bool(response.content),
        }
    except Exception as exc:  # noqa: BLE001 - probe must classify environment failures
        return {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": redact_text(str(exc), token),
        }


def run_node(script: str, env: dict[str, str] | None = None, timeout: int = 90) -> dict[str, Any]:
    completed = subprocess.run(
        ["node", script],
        cwd=PROBE_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "status": "failed",
            "exit_code": completed.returncode,
            "stderr": completed.stderr[:600],
        }
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "status": "failed",
            "exit_code": completed.returncode,
            "error": "node_probe_non_json_output",
            "stdout_length": len(completed.stdout),
            "stderr_length": len(completed.stderr),
        }


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from server.app.platform_store import platform_store

    config = platform_store.get_active_model_config(include_secret=True)
    if not config:
        raise RuntimeError("active_model_config_missing")

    token = str(config["token"])
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with tempfile.TemporaryDirectory(prefix="jianghu-claude-sdk-g3-", ignore_cleanup_errors=True) as temporary:
        temp_root = Path(temporary)
        base_child_env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}
        }
        base_child_env.update(
            {
                "PROBE_BASE_URL": str(config["base_url"]),
                "PROBE_MODEL": str(config["model"]),
                "PROBE_TOKEN": token,
                "PROBE_TIMEOUT_MS": "45000",
            }
        )

        def scenario_env(name: str) -> dict[str, str]:
            result = dict(base_child_env)
            result["PROBE_WORKSPACE"] = str(temp_root / f"{name}-workspace")
            result["PROBE_CONFIG_DIR"] = str(temp_root / f"{name}-claude-config")
            return result

        static_result = run_node("./src/static-probe.mjs")
        protocol_result = (
            {"status": "not_rerun", "reason": "reuse_prior_protocol_evidence"}
            if "--skip-protocol" in sys.argv[1:]
            else protocol_probe(config)
        )
        live_result = (
            {"status": "not_rerun", "reason": "reuse_prior_minimal_sdk_evidence"}
            if "--skip-minimal" in sys.argv[1:]
            else run_node("./src/live-probe.mjs", scenario_env("minimal"))
        )
        feature_result = (
            run_node("./src/feature-probe.mjs", scenario_env("feature"), timeout=180)
            if "--full" in sys.argv[1:] and "--skip-features" not in sys.argv[1:]
            else {"status": "not_run", "reason": "full_probe_not_requested"}
        )
        cancel_result = (
            run_node("./src/cancel-probe.mjs", scenario_env("cancel"), timeout=60)
            if "--full" in sys.argv[1:] and "--skip-cancel" not in sys.argv[1:]
            else {"status": "not_run", "reason": "full_probe_not_requested"}
        )
        security_result = (
            run_node("./src/security-probe.mjs", scenario_env("security"), timeout=90)
            if "--full" in sys.argv[1:] and "--skip-security" not in sys.argv[1:]
            else {"status": "not_run", "reason": "full_probe_not_requested"}
        )
        extensions_result = (
            run_node("./src/extensions-probe.mjs", scenario_env("extensions"), timeout=120)
            if "--full" in sys.argv[1:] and "--skip-extensions" not in sys.argv[1:]
            else {"status": "not_run", "reason": "full_probe_not_requested"}
        )

    serialized_live = json.dumps(live_result, ensure_ascii=False)
    if token and token in serialized_live:
        raise RuntimeError("probe_output_contains_token")

    report = {
        "schema_version": 1,
        "probe_id": timestamp,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "production_runtime_changed": False,
        "model_config": {
            "provider": str(config.get("provider") or ""),
            "base_url_scheme": str(config.get("base_url") or "").split(":", 1)[0],
            "model": str(config.get("model") or ""),
            "token_present": bool(token),
            "token_persisted_in_result": False,
        },
        "static": static_result,
        "anthropic_messages_protocol": protocol_result,
        "sdk_live_minimal": live_result,
        "sdk_features_and_resume": feature_result,
        "sdk_cancel_and_cleanup": cancel_result,
        "sdk_workspace_permission_boundary": security_result,
        "sdk_mcp_and_controlled_subagent": extensions_result,
    }
    if token and token in json.dumps(report, ensure_ascii=False):
        raise RuntimeError("probe_report_contains_token")
    output_path = RESULTS_ROOT / f"g3-probe-{timestamp}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"probe_id": timestamp, "result": str(output_path.relative_to(ROOT)), "statuses": {
        "static": static_result.get("status"),
        "anthropic_messages_protocol": protocol_result.get("status"),
        "sdk_live_minimal": live_result.get("status"),
        "sdk_features_and_resume": feature_result.get("status"),
        "sdk_cancel_and_cleanup": cancel_result.get("status"),
        "sdk_workspace_permission_boundary": security_result.get("status"),
        "sdk_mcp_and_controlled_subagent": extensions_result.get("status"),
    }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
