from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.app.platform_store import platform_store


SCENARIOS = {
    "text_collaboration": "scripts/verify-real-openclaw-e2e.py",
    "engineering_collaboration": "scripts/verify-real-engineering-team-e2e.py",
}


def redact_text(value: str, token: str) -> str:
    return value.replace(token, "[REDACTED]") if token else value


def run_scenario(runtime_name: str, scenario_name: str, script: str, token: str) -> dict[str, Any]:
    env = dict(os.environ)
    env["JIANGHU_G5_TEST_RUNTIME"] = runtime_name
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [sys.executable, script],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
            check=False,
        )
        duration = time.perf_counter() - started
        stdout = redact_text(completed.stdout, token)
        stderr = redact_text(completed.stderr, token)
        return {
            "runtime": runtime_name,
            "scenario": scenario_name,
            "status": "passed" if completed.returncode == 0 else "failed",
            "exit_code": completed.returncode,
            "duration_seconds": round(duration, 3),
            "stdout_tail": stdout[-16000:],
            "stderr_tail": stderr[-8000:],
        }
    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - started
        return {
            "runtime": runtime_name,
            "scenario": scenario_name,
            "status": "failed",
            "exit_code": None,
            "duration_seconds": round(duration, 3),
            "error": "scenario_timeout",
            "stdout_tail": redact_text(str(exc.stdout or "")[-16000:], token),
            "stderr_tail": redact_text(str(exc.stderr or "")[-8000:], token),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="")
    parser.add_argument("--runtime", choices=("all", "openclaw", "claude_code"), default="all")
    parser.add_argument("--scenario", choices=("all", *SCENARIOS), default="all")
    args = parser.parse_args()
    model_config = platform_store.get_active_model_config(include_secret=True)
    if not model_config or not model_config.get("token"):
        raise RuntimeError("active_model_config_missing")
    token = str(model_config["token"])
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_root = Path(
        args.output_root or f"experiments/runtime-g5/results/platform-{timestamp}"
    ).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    runtimes = ("openclaw", "claude_code") if args.runtime == "all" else (args.runtime,)
    scenarios = tuple(SCENARIOS) if args.scenario == "all" else (args.scenario,)
    results: list[dict[str, Any]] = []
    for scenario_name in scenarios:
        for runtime_name in runtimes:
            print(
                json.dumps(
                    {"phase": "started", "runtime": runtime_name, "scenario": scenario_name},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            result = run_scenario(runtime_name, scenario_name, SCENARIOS[scenario_name], token)
            results.append(result)
            print(
                json.dumps(
                    {
                        "phase": "completed",
                        "runtime": runtime_name,
                        "scenario": scenario_name,
                        "status": result["status"],
                        "duration_seconds": result["duration_seconds"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    pair_checks = {
        scenario_name: all(
            item["status"] == "passed"
            for item in results
            if item["scenario"] == scenario_name
        )
        and len([item for item in results if item["scenario"] == scenario_name]) == len(runtimes)
        for scenario_name in scenarios
    }
    report = {
        "schema_version": "jianghu.runtime-g5-platform-comparison.v1",
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
        "status": "passed" if all(item["status"] == "passed" for item in results) else "failed",
        "pair_checks": pair_checks,
        "results": results,
    }
    result_path = output_root / "result.json"
    result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps({"status": report["status"], "result_path": str(result_path)}, ensure_ascii=False),
        flush=True,
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
