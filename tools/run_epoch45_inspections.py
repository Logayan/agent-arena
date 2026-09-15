from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "epoch45-final-remediation"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def digest(path: Path) -> dict[str, Any]:
    value = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
            size += len(chunk)
    return {"size_bytes": size, "sha256": value.hexdigest()}


def production_files() -> list[Path]:
    roots = [ROOT / "server" / "app", ROOT / "server" / "claude_agent_runtime", ROOT / "client" / "src"]
    files = [
        ROOT / "Dockerfile",
        ROOT / "compose.yaml",
        ROOT / "compose.postgres.yaml",
        ROOT / "package.json",
        ROOT / "package-lock.json",
        ROOT / "client" / "package.json",
        ROOT / "client" / "package-lock.json",
        ROOT / "server" / "claude_agent_runtime" / "package.json",
        ROOT / "server" / "claude_agent_runtime" / "package-lock.json",
        ROOT / "pyproject.toml",
    ]
    for base in roots:
        if base.is_dir():
            files.extend(
                path
                for path in base.rglob("*")
                if path.is_file() and "node_modules" not in path.parts and "__pycache__" not in path.parts
            )
    return sorted({path for path in files if path.is_file()})


def scan_openclaw() -> dict[str, Any]:
    files = production_files()
    references: list[dict[str, Any]] = []
    prohibited: list[dict[str, Any]] = []
    import_pattern = re.compile(
        r"(?:^|\s)(?:from\s+openclaw|import\s+openclaw|require\s*\(\s*['\"]openclaw|import\s*\(\s*['\"]openclaw)",
        re.I,
    )
    dependency_names = {"package.json", "package-lock.json", "requirements.txt", "pyproject.toml"}
    deployment_names = {"compose.yaml", "compose.postgres.yaml", "Dockerfile"}
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(ROOT).as_posix()
        for line_number, line in enumerate(lines, 1):
            if "openclaw" not in line.lower():
                continue
            category = "static_migration_label_or_fail_closed_guard"
            rule_id = "OPENCLAW_STATIC_REFERENCE_ALLOWED"
            if import_pattern.search(line):
                category = "production_runtime_import"
                rule_id = "OPENCLAW_RUNTIME_IMPORT_PROHIBITED"
            elif path.name in dependency_names and re.search(
                r"(?:['\"]?openclaw['\"]?\s*[:=@<>]|(?:^|[/@])openclaw(?:$|[/@]))",
                line,
                re.I,
            ):
                category = "production_dependency"
                rule_id = "OPENCLAW_DEPENDENCY_PROHIBITED"
            elif path.name in deployment_names and re.search(
                r"(?:image|command|entrypoint|service|runtime|adapter|depends_on).*openclaw|openclaw.*(?:image|command|entrypoint|service|runtime|adapter|depends_on)",
                line,
                re.I,
            ):
                category = "production_deployment_or_adapter"
                rule_id = "OPENCLAW_DEPLOYMENT_PROHIBITED"
            record = {"path": relative, "line": line_number, "rule_id": rule_id, "category": category}
            references.append(record)
            if rule_id.endswith("_PROHIBITED"):
                prohibited.append(record)
    result = {
        "schema_version": "jianghu.openclaw-production-residual-scan.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "roots": ["server/app", "server/claude_agent_runtime", "client/src"],
            "deployment_and_dependency_files": [
                path.relative_to(ROOT).as_posix()
                for path in files
                if path.parent == ROOT or path.name in dependency_names or path.name in deployment_names
            ],
            "files_scanned": len(files),
        },
        "case_insensitive_references": len(references),
        "prohibited_adapter_dependency_config_findings": len(prohibited),
        "status": "PASS" if files and not prohibited else "FAIL",
        "references": references,
        "prohibited_findings": prohibited,
        "boundary": "This is a static production source/dependency/deployment residual scan. Allowed migration labels and fail-closed denial guards are not traffic evidence; OpenClaw retirement still requires separate approval.",
    }
    write_json(OUT / "openclaw-production-scan.json", result)
    return result


def credential_source_files() -> Iterable[Path]:
    excluded = {
        ".git", ".data", ".jianghu-platform-evidence", ".playwright-browsers", ".pytest_cache",
        "__pycache__", "node_modules", "dist", "artifacts", "deliverables", "evidence", "t", "x",
    }
    suffixes = {
        "", ".cfg", ".conf", ".css", ".env", ".example", ".html", ".ini", ".js", ".json",
        ".md", ".mjs", ".ps1", ".py", ".sh", ".toml", ".ts", ".tsx", ".txt", ".vue",
        ".yaml", ".yml",
    }
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in excluded for part in relative.parts):
            continue
        if path.suffix.lower() not in suffixes and path.name != "Dockerfile":
            continue
        yield path


def scan_credentials() -> dict[str, Any]:
    rules = {
        "CRED_PRIVATE_KEY_HEADER": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "CRED_PROVIDER_KEY_LITERAL": re.compile(r"\b(?:sk-ant-|sk-proj-|ghp_|github_pat_)[A-Za-z0-9_-]{12,}"),
        "CRED_BEARER_LITERAL": re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{24,}"),
        "CRED_SECRET_ASSIGNMENT_LITERAL": re.compile(
            r"(?i)\b(?:api[_-]?key|auth[_-]?token|access[_-]?token|client[_-]?secret|password)\b\s*[:=]\s*[\"'][^\"']{8,}[\"']"
        ),
    }
    findings: list[dict[str, Any]] = []
    scanned = 0
    for path in credential_source_files():
        scanned += 1
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, 1):
            for rule_id, pattern in rules.items():
                if pattern.search(line):
                    findings.append(
                        {"path": path.relative_to(ROOT).as_posix(), "line": line_number, "rule_id": rule_id}
                    )
    result = {
        "schema_version": "jianghu.credential-scan.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "delivery source/config/docs excluding generated evidence, packages, dependencies, caches and private platform evidence",
        "files_scanned": scanned,
        "finding_count": len(findings),
        "status": "PASS" if scanned and not findings else "FAIL",
        "findings": findings,
        "redaction_policy": "Findings contain only path, line and rule_id; matched source text and values are never emitted.",
    }
    write_json(OUT / "credential-scan.json", result)
    return result


def main() -> int:
    openclaw = scan_openclaw()
    credentials = scan_credentials()
    summary = {
        "schema_version": "jianghu.epoch45.inspection-summary.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if openclaw["status"] == credentials["status"] == "PASS" else "FAIL",
        "openclaw": {
            "status": openclaw["status"],
            "files_scanned": openclaw["scope"]["files_scanned"],
            "references": openclaw["case_insensitive_references"],
            "prohibited_findings": openclaw["prohibited_adapter_dependency_config_findings"],
        },
        "credentials": {
            "status": credentials["status"],
            "files_scanned": credentials["files_scanned"],
            "findings": credentials["finding_count"],
        },
    }
    write_json(OUT / "inspection-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
