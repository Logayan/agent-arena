#!/usr/bin/env python3
"""Single dependency-free CLI for evidence verification and package integrity."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from runtime_acceptance.verifier import (
    EvidenceError,
    check_manifest,
    verify_all,
    write_manifest,
    write_receipts,
)


def summary(result: dict) -> str:
    return (
        "VERIFICATION PASS "
        f"events={result['snapshot']['count']} "
        f"sdk_bindings={result['runtime']['session_binding_count']} "
        f"node_sdk_bindings={result['runtime']['node_session_binding_count']} "
        f"run_tool_calls={result['tools']['run_wide_tool_call_group_count']} "
        f"node_tool_calls={result['tools']['tool_call_group_count']} "
        f"public_messages={len(result['collaboration']['messages'])} "
        f"artifacts={result['artifacts']['registry_count']} "
        f"open_p0={result['gaps']['open_p0_count']} "
        f"overall={result['migration_acceptance']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("verify", "write-receipts", "write-manifest", "check-manifest", "print-verdict"),
    )
    args = parser.parse_args()
    root = Path.cwd()
    try:
        if args.command == "verify":
            print(summary(verify_all(root)))
        elif args.command == "write-receipts":
            print(summary(write_receipts(root)))
        elif args.command == "write-manifest":
            payload = write_manifest(root)
            print(f"MANIFEST WRITTEN files={payload['file_count']}")
        elif args.command == "check-manifest":
            payload = check_manifest(root)
            print(f"MANIFEST PASS files={payload['file_count']}")
        else:
            result = verify_all(root)
            print(
                json.dumps(
                    {
                        "run_id": result["run_id"],
                        "node_key": result["node_key"],
                        "node_delivery_status": result["node_delivery_status"],
                        "current_runtime_route": result["runtime"]["status"],
                        "backend_interruption_recovery": result["absent_lifecycles"]["interruption_recovery_status"],
                        "migration_acceptance": result["migration_acceptance"],
                        "openclaw_retirement": result["openclaw_retirement"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0
    except (EvidenceError, OSError, ValueError, KeyError) as exc:
        print(f"VERIFICATION FAIL: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
