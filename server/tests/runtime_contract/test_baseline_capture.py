from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

from server.app.secret_store import protect_secret


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "capture-openclaw-runtime-baseline.py"
SPEC = importlib.util.spec_from_file_location("capture_openclaw_runtime_baseline", SCRIPT_PATH)
assert SPEC and SPEC.loader
baseline_capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline_capture)


def test_active_database_model_config_is_loaded_without_mutating_database(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("JIANGHU_SECRET_KEY_FILE", raising=False)
    database = tmp_path / "models.db"
    key_path = tmp_path / ".jianghu-secret.key"
    encrypted = protect_secret("test-secret-token", key_path=key_path)
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE model_configs (
               id TEXT, name TEXT, provider TEXT, base_url TEXT, model TEXT,
               tier TEXT, encrypted_token TEXT, active INTEGER, updated_at TEXT
           )"""
    )
    connection.execute(
        "INSERT INTO model_configs VALUES (?,?,?,?,?,?,?,?,?)",
        ("model-test", "Test GPT", "openai-responses", "https://model.test", "gpt-test", "medium", encrypted, 1, "2026-09-11"),
    )
    connection.commit()
    connection.close()
    before = database.read_bytes()

    config = baseline_capture.load_real_model_config("active-database", str(database))

    assert config == {
        "source": "active-database",
        "config_id": "model-test",
        "config_name": "Test GPT",
        "provider": "openai-responses",
        "base_url": "https://model.test",
        "model": "gpt-test",
        "token": "test-secret-token",
        "tier": "medium",
    }
    assert database.read_bytes() == before


def test_real_probe_provider_errors_are_classified() -> None:
    assert baseline_capture.classify_real_probe_error("HTTP 401: openai_error") == "provider_auth"
    assert baseline_capture.classify_real_probe_error("status=401 reason=auth") == "provider_auth"
    assert baseline_capture.classify_real_probe_error("Insufficient balance or no resource package") == "provider_billing"
    assert baseline_capture.classify_real_probe_error("subprocess timed out") == "runtime_failure"


def test_real_probe_requires_a_successful_exec_result_with_marker() -> None:
    failed = [{"kind": "tool_result", "tool_name": "exec", "is_error": True, "status": "error", "exit_code": None, "output": "gateway closed"}]
    passed = [{"kind": "tool_result", "tool_name": "exec", "is_error": False, "status": "completed", "exit_code": 0, "output": "OPENCLAW_BASELINE_OK\n"}]

    assert baseline_capture.has_successful_baseline_exec(failed) is False
    assert baseline_capture.has_successful_baseline_exec(passed) is True
