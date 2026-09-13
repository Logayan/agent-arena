#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from runtime_probe.delivery import build, check_manifest, verify, write_manifest
from runtime_probe.gate import evaluate, remediate
from runtime_probe.platform import EvidenceError, capture


def main() -> int:
    parser = argparse.ArgumentParser(description="Jianghu Claude Agent SDK runtime evidence and fault probe")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build")
    sub.add_parser("capture")
    sub.add_parser("verify")
    sub.add_parser("write-manifest")
    sub.add_parser("check-manifest")
    gate = sub.add_parser("gate")
    gate.add_argument("candidate")
    repair = sub.add_parser("remediate")
    repair.add_argument("candidate")
    repair.add_argument("output")
    args = parser.parse_args()
    root = Path.cwd()
    try:
        if args.command == "build":
            result = build(root)
            idx = result["index"]
            print(f"BUILD PASS events={idx['snapshot']['projection']['event_count']} sequence_last={idx['snapshot']['projection']['sequence_last']} artifacts={idx['analysis']['artifacts']['registry_count']} local_faults={result['faults']['status']} supplemental_probes={result['supplemental']['status']} candidate_v1_gate={result['gate']['verdict']}:{result['gate']['exit_code']} migration=NO_GO")
        elif args.command == "capture":
            result = capture(root)
            print(f"CAPTURE PASS events={result['snapshot']['projection']['event_count']} sequence_last={result['snapshot']['projection']['sequence_last']} artifacts={result['analysis']['artifacts']['registry_count']}")
        elif args.command == "verify":
            print(json.dumps(verify(root), ensure_ascii=False, indent=2))
        elif args.command == "write-manifest":
            result = write_manifest(root)
            print(f"MANIFEST WRITTEN files={result['file_count']}")
        elif args.command == "check-manifest":
            print(json.dumps(check_manifest(root), ensure_ascii=False, indent=2))
        elif args.command == "gate":
            receipt = evaluate(root / args.candidate, root / "config" / "predeclared-blocker.json")
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
            return int(receipt["exit_code"])
        else:
            output = root / args.output
            result = remediate(
                root / args.candidate,
                output,
                root / "evidence" / "runtime_probe" / "platform_snapshot" / "events.ndjson",
                root / "evidence" / "runtime_probe" / "platform_snapshot" / "artifact-byte-receipts.json",
            )
            print(f"REMEDIATION CANDIDATE WRITTEN path={output.as_posix()} version={result['candidate_version']} platform_rejudge=PENDING_NOT_FABRICATED")
        return 0
    except (EvidenceError, OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"FAIL: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
