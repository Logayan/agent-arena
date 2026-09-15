from __future__ import annotations

import subprocess
import json
from pathlib import Path

import pytest

from server.app.git_delivery import (
    GitDeliveryError,
    _create_merge_request,
    commit_run_changes,
    deliver_commit_to_remote,
    ensure_run_repository,
    ensure_run_source_checkout,
    export_commit_patch,
)


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout.strip()


def test_run_repository_creates_an_empty_baseline_without_swallowing_delivery_files(tmp_path: Path) -> None:
    code_root = tmp_path / "code"
    code_root.mkdir()
    (code_root / "README.md").write_text("baseline\n", encoding="utf-8")

    result = ensure_run_repository(code_root, "run_git_test")

    assert result["created"] is True
    assert len(result["baseline_commit"]) == 40
    assert _git(code_root, "show", "--format=", "--name-only", "HEAD") == ""
    assert _git(code_root, "status", "--short") == "?? README.md"
    repeated = ensure_run_repository(code_root, "run_git_test")
    assert repeated["created"] is False
    assert repeated["baseline_commit"] == result["baseline_commit"]

    commit = commit_run_changes(
        code_root,
        run_id="run_git_test",
        node_key="first_delivery",
        node_name="首个工程交付",
        agent={"id": "agent_engineer", "name": "工程实现者"},
    )
    assert commit is not None
    assert commit["files"] == [{"status": "A", "path": "README.md"}]


def test_run_source_checkout_exposes_authoritative_product_tree_without_reusing_delivery_ledger(tmp_path: Path) -> None:
    remote = tmp_path / "product.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    seed = tmp_path / "product-seed"
    seed.mkdir()
    subprocess.run(["git", "init"], cwd=seed, check=True, capture_output=True)
    _git(seed, "config", "user.name", "Seed")
    _git(seed, "config", "user.email", "seed@example.com")
    (seed / "client").mkdir()
    (seed / "server").mkdir()
    (seed / "client" / "package.json").write_text('{"scripts":{"build":"vite build"}}\n', encoding="utf-8")
    (seed / "server" / "main.py").write_text("RUNTIME = 'claude_code'\n", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "product baseline")
    _git(seed, "branch", "-M", "master")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "origin", "master")
    target_commit = _git(seed, "rev-parse", "HEAD")

    source_root = tmp_path / "run" / "product-source"
    result = ensure_run_source_checkout(
        source_root,
        "run_source_test",
        {
            "repository_url": str(remote),
            "target_branch": "master",
            "delivery_mode": "push_branch",
            "username": "",
            "token": "",
        },
    )

    assert result["created"] is True
    assert result["authoritative_source"] is True
    assert result["target_commit"] == target_commit
    assert result["baseline_commit"] == target_commit
    assert result["run_branch"] == "jianghu-run-run_source_test"
    assert (source_root / "client" / "package.json").is_file()
    assert (source_root / "server" / "main.py").is_file()
    assert _git(source_root, "remote", "get-url", "origin") == str(remote)

    repeated = ensure_run_source_checkout(
        source_root,
        "run_source_test",
        {"repository_url": str(remote), "target_branch": "master", "token": ""},
    )
    assert repeated["created"] is False
    assert repeated["update_status"] == "fast_forwarded"

    (source_root / "local-change.txt").write_text("preserve me\n", encoding="utf-8")
    preserved = ensure_run_source_checkout(
        source_root,
        "run_source_test",
        {"repository_url": str(remote), "target_branch": "master", "token": ""},
    )
    assert preserved["update_status"] == "preserved_dirty"
    assert (source_root / "local-change.txt").read_text(encoding="utf-8") == "preserve me\n"


def test_engineering_changes_create_a_traceable_commit_and_patch(tmp_path: Path) -> None:
    code_root = tmp_path / "code"
    ensure_run_repository(code_root, "run_git_test")
    (code_root / "app.py").write_text("print('jianghu')\n", encoding="utf-8")

    commit = commit_run_changes(
        code_root,
        run_id="run_git_test",
        node_key="claude_runtime_migration",
        node_name="Claude Code SDK Runtime 迁移",
        agent={"id": "agent_engineer", "name": "工程实现者"},
    )

    assert commit is not None
    assert len(commit["commit_sha"]) == 40
    assert commit["commit_sha"] == _git(code_root, "rev-parse", "HEAD")
    assert commit["parent_shas"]
    assert commit["author_agent_id"] == "agent_engineer"
    assert commit["author_name"] == "工程实现者"
    assert commit["subject"].startswith("feat(claude_runtime_migration):")
    assert commit["files"] == [{"status": "A", "path": "app.py"}]
    assert commit["patch_sha256"]
    patch = export_commit_patch(code_root, commit["commit_sha"])
    assert b"Subject: [PATCH]" in patch
    assert b"app.py" in patch


def test_clean_workspace_does_not_fabricate_a_commit(tmp_path: Path) -> None:
    code_root = tmp_path / "code"
    ensure_run_repository(code_root, "run_git_test")

    assert commit_run_changes(
        code_root,
        run_id="run_git_test",
        node_key="verification",
        node_name="只读复验",
        agent={"id": "agent_auditor", "name": "审计者"},
    ) is None


def test_patch_export_rejects_untrusted_or_missing_commit_ids(tmp_path: Path) -> None:
    code_root = tmp_path / "code"
    ensure_run_repository(code_root, "run_git_test")

    with pytest.raises(GitDeliveryError, match="invalid_commit_sha"):
        export_commit_patch(code_root, "HEAD; rm -rf .")
    with pytest.raises(GitDeliveryError, match="commit_not_found"):
        export_commit_patch(code_root, "0" * 40)


def test_merge_request_creation_reuses_existing_remote_request(monkeypatch) -> None:
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps([
                {"number": 42, "title": "Existing delivery", "state": "open", "html_url": "https://github.example/pr/42"}
            ]).encode("utf-8")

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr("server.app.git_delivery.urlopen", fake_urlopen)
    result = _create_merge_request(
        {
            "provider": "github", "repository_url": "https://github.com/acme/jianghu.git",
            "token": "secret", "api_base_url": "",
        },
        source_branch="jianghu/run-1/build", target_branch="main",
        title="Delivery", description="Run delivery",
    )

    assert result["number"] == 42
    assert result["reused_existing"] is True
    assert len(requests) == 1
    assert requests[0][0].method == "GET"


def test_remote_delivery_anchors_run_commit_to_target_history(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    seed = tmp_path / "seed"
    seed.mkdir()
    subprocess.run(["git", "init"], cwd=seed, check=True, capture_output=True)
    _git(seed, "config", "user.name", "Seed")
    _git(seed, "config", "user.email", "seed@example.com")
    (seed / "README.md").write_text("remote baseline\n", encoding="utf-8")
    (seed / "remote-only.txt").write_text("must be preserved\n", encoding="utf-8")
    _git(seed, "add", "README.md", "remote-only.txt")
    _git(seed, "commit", "-m", "initial baseline")
    _git(seed, "branch", "-M", "master")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "origin", "master")
    target_sha = _git(seed, "rev-parse", "HEAD")

    code_root = tmp_path / "run-code"
    ensure_run_repository(code_root, "run_delivery_anchor")
    (code_root / "README.md").write_text("remote baseline\n", encoding="utf-8")
    (code_root / "runtime.py").write_text("RUNTIME = 'claude_code'\n", encoding="utf-8")
    commit = commit_run_changes(
        code_root, run_id="run_delivery_anchor", node_key="runtime_migration",
        node_name="Claude Code SDK migration", agent={"id": "agent_engineer", "name": "Engineer"},
    )
    assert commit is not None

    result = deliver_commit_to_remote(
        code_root,
        commit=commit,
        config={
            "provider": "generic", "repository_url": str(remote), "default_branch": "master",
            "delivery_mode": "push_branch", "username": "", "token": "",
        },
    )
    pushed = result["push"]
    assert pushed["history_anchored"] is True
    assert pushed["source_commit_sha"] == commit["commit_sha"]
    assert pushed["target_commit_sha"] == target_sha
    assert _git(code_root, "merge-base", "--is-ancestor", target_sha, pushed["commit_sha"]) == ""
    assert _git(code_root, "show", f"{pushed['commit_sha']}:remote-only.txt") == "must be preserved"

    (code_root / "runtime.py").write_text("RUNTIME = 'claude_code'\nGIT_DELIVERY = 'event_scoped'\n", encoding="utf-8")
    updated_commit = commit_run_changes(
        code_root, run_id="run_delivery_anchor", node_key="runtime_migration",
        node_name="Claude Code SDK migration", agent={"id": "agent_engineer", "name": "Engineer"},
    )
    assert updated_commit is not None
    updated = deliver_commit_to_remote(
        code_root,
        commit=updated_commit,
        config={
            "provider": "generic", "repository_url": str(remote), "default_branch": "master",
            "delivery_mode": "push_branch", "username": "", "token": "",
        },
    )["push"]
    assert updated["previous_remote_commit_sha"] == pushed["commit_sha"]
    assert _git(code_root, "merge-base", "--is-ancestor", pushed["commit_sha"], updated["commit_sha"]) == ""
    assert _git(code_root, "show", f"{updated['commit_sha']}:remote-only.txt") == "must be preserved"
