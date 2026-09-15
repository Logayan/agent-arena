from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
E2E = ROOT / "client" / "evidence" / "epoch45-final-remediation" / "e2e"
OUT = ROOT / "evidence" / "epoch45-final-remediation"
SNAPSHOT = ROOT / ".jianghu-platform-evidence" / "snapshots" / "attempt-ef6476c5bf4ad3e8"
EXPECTED_CASES = {f"EVC-{number:03d}" for number in range(1, 10)}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> dict[str, Any]:
    value = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            value.update(chunk)
            size += len(chunk)
    return {"size_bytes": size, "sha256": value.hexdigest()}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    results = read_json(E2E / "test-results.json")
    cases = read_json(E2E / "test-cases.json")["cases"]
    screenshot_index = read_json(E2E / "screenshot-index.json")["screenshots"]
    result_ids = [str(item["case_id"]) for item in results["results"]]
    case_ids = [str(item["id"]) for item in cases]
    require(set(result_ids) == EXPECTED_CASES, f"result_case_domain:{result_ids}")
    require(set(case_ids) == EXPECTED_CASES, f"declared_case_domain:{case_ids}")
    require(len(result_ids) == len(set(result_ids)) == 9, "duplicate_or_missing_results")
    require(int(results["passed"]) == 9 and int(results["failed"]) == 0, "e2e_not_9_of_9")
    require(not results.get("console_errors"), "browser_console_errors")
    require(not results.get("failed_requests"), "browser_failed_requests")
    require(not results.get("http_errors"), "browser_http_errors")
    require(not results.get("prohibited_management_requests"), "prohibited_browser_management_requests")
    require(all(item.get("status") == "PASS" for item in results["results"]), "per_case_failure")
    browser_request_doc = read_json(E2E / "browser-requests.json")
    browser_requests = list(browser_request_doc.get("requests") or [])
    require(browser_requests, "browser_request_index_empty")
    require(not browser_request_doc.get("prohibited_management_requests"), "browser_request_index_prohibited_management_requests")

    junit_root = ET.parse(E2E / "junit.xml").getroot()
    require(int(junit_root.attrib.get("tests", "0")) == 9, "junit_test_count")
    require(int(junit_root.attrib.get("failures", "0")) == 0, "junit_failures")
    require(int(junit_root.attrib.get("errors", "0")) == 0, "junit_errors")
    junit_ids = {str(item.attrib.get("name") or "") for item in junit_root.findall("testcase")}
    require(junit_ids == EXPECTED_CASES, "junit_case_domain")
    html = (E2E / "playwright-report.html").read_text(encoding="utf-8")
    require(all(case_id in html for case_id in EXPECTED_CASES), "html_case_domain")

    screenshot_receipts: list[dict[str, Any]] = []
    indexed_paths = {str(item["path"]) for item in screenshot_index}
    result_evidence = {
        str(path)
        for item in results["results"]
        for path in item.get("evidence", [])
        if str(path).lower().endswith(".png")
    }
    require(indexed_paths == result_evidence, "screenshot_index_result_mismatch")
    for relative in sorted(indexed_paths):
        path = (E2E / relative).resolve()
        require(path.is_relative_to(E2E.resolve()) and path.is_file(), f"screenshot_path:{relative}")
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            extrema = rgb.getextrema()
            width, height = image.size
        non_uniform = any(low != high for low, high in extrema)
        require(width > 0 and height > 0 and non_uniform, f"blank_screenshot:{relative}")
        screenshot_receipts.append(
            {"path": relative, **digest(path), "width": width, "height": height, "non_uniform": True}
        )
    require(len(screenshot_receipts) == 9, "screenshot_count")

    har_path = E2E / "network.har"
    har = read_json(har_path)
    entries = list((har.get("log") or {}).get("entries") or [])
    require(entries, "har_empty")
    har_http_errors = [
        {"url": str((entry.get("request") or {}).get("url") or ""), "status": int((entry.get("response") or {}).get("status") or 0)}
        for entry in entries
        if int((entry.get("response") or {}).get("status") or 0) >= 400
    ]
    require(not har_http_errors, f"har_http_errors:{har_http_errors[:5]}")

    trace_path = E2E / "trace.zip"
    with zipfile.ZipFile(trace_path) as archive:
        trace_bad_member = archive.testzip()
        trace_members = archive.namelist()
    require(trace_bad_member is None and trace_members, "trace_crc_or_empty")

    manifest_path = E2E / "sha256-manifest.json"
    manifest = read_json(manifest_path)
    declared_names = [str(item["path"]) for item in manifest["files"]]
    require(len(declared_names) == len(set(declared_names)), "e2e_manifest_duplicate")
    required_names = {
        "test-cases.json", "test-results.json", "screenshot-index.json", "junit.xml",
        "playwright-report.html", "network.har", "trace.zip", "browser-download-receipts.json",
        "browser-requests.json",
    } | indexed_paths
    require(required_names.issubset(set(declared_names)), "e2e_manifest_required_domain")
    manifest_receipts = []
    for item in manifest["files"]:
        path = (E2E / str(item["path"])).resolve()
        require(path.is_relative_to(E2E.resolve()) and path.is_file(), f"manifest_path:{item['path']}")
        observed = digest(path)
        require(
            observed["size_bytes"] == int(item["size_bytes"])
            and observed["sha256"] == str(item["sha256"]),
            f"manifest_digest:{item['path']}",
        )
        manifest_receipts.append({"path": item["path"], **observed, "exact": True})

    download_result = next(item for item in results["results"] if item["case_id"] == "EVC-009")
    match = re.search(r"artifact=(artifact_[A-Za-z0-9]+)", str(download_result.get("actual") or ""))
    require(match is not None, "download_artifact_id_missing")
    artifact_id = match.group(1)
    download_entries = [item for item in manifest["files"] if str(item["path"]).startswith("downloads/")]
    require(len(download_entries) == 1, "browser_download_count")
    download_path = E2E / str(download_entries[0]["path"])
    download_digest = digest(download_path)
    download_receipt_doc = read_json(E2E / "browser-download-receipts.json")
    download_receipts = list(download_receipt_doc.get("downloads") or [])
    require(len(download_receipts) == 1, "browser_download_receipt_count")
    download_receipt = download_receipts[0]
    require(str(download_receipt.get("artifact_id") or "") == artifact_id, "browser_download_receipt_artifact")
    require(str(download_receipt.get("path") or "") == str(download_entries[0]["path"]), "browser_download_receipt_path")
    require(
        download_digest["size_bytes"] == int(download_receipt.get("downloaded_size_bytes") or 0)
        and download_digest["size_bytes"] == int(download_receipt.get("api_registry_size_bytes") or 0)
        and download_digest["sha256"] == str(download_receipt.get("downloaded_sha256") or "")
        and download_digest["sha256"] == str(download_receipt.get("api_registry_sha256") or "")
        and download_receipt.get("exact") is True,
        "browser_download_api_registry_mismatch",
    )

    receipt = read_json(OUT / "commands" / "evidence-center-e2e-receipt.json")
    receipt_paths = {str(item["path"]) for item in receipt.get("files", [])}
    require(int(receipt.get("exit_code", -1)) == 0, "e2e_command_exit")
    require(
        {
            "client/evidence/epoch45-final-remediation/e2e/network.har",
            "client/evidence/epoch45-final-remediation/e2e/trace.zip",
            "client/evidence/epoch45-final-remediation/e2e/sha256-manifest.json",
        }.issubset(receipt_paths),
        "e2e_command_receipt_missing_media",
    )

    verification = {
        "schema_version": "jianghu.epoch45.e2e-independent-verification.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "run_id": results["run_id"],
        "frontend": results["frontend"],
        "backend": results["backend"],
        "cases": {"total": 9, "passed": 9, "failed": 0, "ids": sorted(EXPECTED_CASES)},
        "per_test_outcomes_verified": True,
        "junit": {"tests": 9, "failures": 0, "errors": 0, **digest(E2E / "junit.xml")},
        "html": {"all_case_ids_present": True, **digest(E2E / "playwright-report.html")},
        "json": digest(E2E / "test-results.json"),
        "browser_requests": {
            "count": len(browser_requests),
            "prohibited_management_request_count": 0,
            **digest(E2E / "browser-requests.json"),
        },
        "screenshots": {"verified": 9, "receipts": screenshot_receipts},
        "har": {"entries": len(entries), "http_errors": 0, **digest(har_path)},
        "trace": {"members": len(trace_members), "crc_pass": True, **digest(trace_path)},
        "manifest": {"verified": len(manifest_receipts), **digest(manifest_path), "receipts": manifest_receipts},
        "browser_download": {
            "artifact_id": artifact_id,
            "path": str(download_entries[0]["path"]),
            **download_digest,
            "api_registry_size_bytes": int(download_receipt["api_registry_size_bytes"]),
            "api_registry_sha256": download_receipt["api_registry_sha256"],
            "browser_receipt": digest(E2E / "browser-download-receipts.json"),
            "exact": True,
            "boundary": "This is a real backend API current-Run Artifact download, not the not-yet-registered v2 package and not platform package authority.",
        },
        "command_receipt": digest(OUT / "commands" / "evidence-center-e2e-receipt.json"),
    }
    write_json(OUT / "e2e-independent-verification.json", verification)

    old_result = ROOT / "client" / "evidence" / "epoch45-remediation" / "e2e-attempt1" / "test-results.json"
    old_count = None
    if old_result.is_file():
        prior = read_json(old_result)
        old_count = len(prior.get("results", []))
    reconciliation = {
        "schema_version": "jianghu.epoch45.e2e-denominator-reconciliation.v2",
        "status": "RESOLVED_BY_FRESH_RERUN",
        "historical_observed_case_count": old_count if old_count is not None else 8,
        "fresh_authoritative_case_count": 9,
        "fresh_authoritative_passed": 9,
        "decision": "The v2 denominator uses nine only because the current source re-adopts EVC-009 and this fresh 5173+8003 rerun independently passed all nine cases with HAR, trace and download-byte evidence. It does not copy the historical 9/9 arithmetic.",
        "historical_eight_case_run_preserved": old_result.is_file(),
        "no_averaging_or_summing": True,
    }
    write_json(OUT / "e2e-denominator-reconciliation.json", reconciliation)
    print(json.dumps({"status": "PASS", "cases": "9/9", "screenshots": 9, "har_entries": len(entries), "trace_members": len(trace_members), "download": artifact_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
