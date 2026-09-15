from __future__ import annotations

import hashlib
import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


class GitDeliveryError(RuntimeError):
    pass


def _git_binary() -> str:
    binary = shutil.which("git")
    if not binary:
        raise GitDeliveryError("git_not_available")
    resolved = Path(binary).resolve()
    # Git for Windows exposes a small cmd/git.exe launcher which starts the
    # real mingw64/bin/git.exe process. If subprocess.run times out, killing
    # only the launcher leaves the real Git process alive with stdout/stderr
    # pipes open, so communicate() can wait forever. Invoke the real binary
    # directly when this standard layout is available.
    if resolved.parent.name.lower() == "cmd":
        direct = resolved.parent.parent / "mingw64" / "bin" / "git.exe"
        if direct.is_file():
            return str(direct)
    return str(resolved)


def _git_command_timeout_seconds() -> int:
    try:
        configured = int(os.getenv("JIANGHU_GIT_COMMAND_TIMEOUT_SECONDS", "600"))
    except ValueError:
        configured = 600
    return max(30, configured)


def _run_git(
    repository: Path,
    *arguments: str,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            [_git_binary(), "-C", str(repository), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_git_command_timeout_seconds(),
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        operation = str(arguments[0] if arguments else "unknown")
        raise GitDeliveryError(f"git_command_timeout:{operation}") from exc
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "git_command_failed").strip()
        raise GitDeliveryError(detail[:2000])
    return completed


def _identity(agent: dict[str, Any]) -> tuple[str, str]:
    name = str(agent.get("name") or "Jianghu Agent").strip()[:120] or "Jianghu Agent"
    safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(agent.get("id") or "agent")).strip("-.")
    return name, f"{safe_id or 'agent'}@agents.jianghu.local"


def ensure_run_repository(code_root: str | Path, run_id: str) -> dict[str, Any]:
    repository = Path(code_root).resolve()
    repository.mkdir(parents=True, exist_ok=True)
    created = not (repository / ".git").is_dir()
    if created:
        _run_git(repository, "init", "--quiet")
        _run_git(repository, "config", "user.name", "Jianghu Platform")
        _run_git(repository, "config", "user.email", "platform@jianghu.local")
        _run_git(
            repository,
            "commit",
            "--quiet",
            "--allow-empty",
            "--no-gpg-sign",
            "-m",
            f"chore: initialize run workspace {run_id}",
        )
    exclude_path = repository / ".git" / "info" / "exclude"
    managed_excludes = (
        "\n# Jianghu platform-generated runtime projections\n"
        ".jianghu-platform-evidence/\n"
        "evidence/platform_snapshot/\n"
        "evidence/**/platform_snapshot/\n"
        "**/__pycache__/\n"
        "**/.pytest_cache/\n"
        "**/*.pyc\n"
    )
    current_excludes = exclude_path.read_text(encoding="utf-8", errors="replace") if exclude_path.is_file() else ""
    if "# Jianghu platform-generated runtime projections" not in current_excludes:
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        exclude_path.write_text(current_excludes.rstrip() + managed_excludes, encoding="utf-8", newline="\n")
    head = _run_git(repository, "rev-parse", "HEAD").stdout.strip()
    return {"created": created, "repository": str(repository), "baseline_commit": head}


def ensure_run_source_checkout(
    source_root: str | Path,
    run_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Create a Run-local checkout of the configured product repository.

    The historical ``code/`` directory is a Run delivery ledger and may have
    been initialized before a remote repository was bound.  Reusing it as if
    it were the product checkout leaves later remediation nodes with reports
    and harness files but no real ``client/`` or ``server/`` tree.  A separate
    checkout keeps that immutable history intact while giving engineering and
    Judge turns the actual target-branch source and a Git history that can be
    delivered back to the configured remote.

    Existing dirty checkouts are never reset or overwritten.  A clean checkout
    is fast-forwarded when possible; an ahead/diverged checkout is preserved so
    an interrupted Run cannot lose Agent changes.
    """
    repository_url = str(config.get("repository_url") or "").strip()
    if not repository_url:
        raise GitDeliveryError("git_repository_url_required")
    target_branch = str(config.get("default_branch") or config.get("target_branch") or "main").strip() or "main"
    repository = Path(source_root).resolve()
    created = not (repository / ".git").is_dir()
    if created:
        if repository.exists() and any(repository.iterdir()):
            raise GitDeliveryError("run_source_checkout_not_empty")
        repository.mkdir(parents=True, exist_ok=True)
        _run_git(repository, "init", "--quiet")
        _run_git(repository, "config", "user.name", "Jianghu Platform")
        _run_git(repository, "config", "user.email", "platform@jianghu.local")
        _run_git(repository, "remote", "add", "origin", repository_url)
    else:
        existing = _run_git(repository, "remote", "get-url", "origin", check=False)
        _run_git(
            repository,
            "remote",
            "set-url" if existing.returncode == 0 else "add",
            "origin",
            repository_url,
        )

    auth_environment = _remote_auth_environment(config)
    _run_git(
        repository,
        "fetch",
        "--no-tags",
        "origin",
        f"refs/heads/{target_branch}:refs/remotes/origin/{target_branch}",
        env=auth_environment,
    )
    target_commit = _run_git(repository, "rev-parse", f"refs/remotes/origin/{target_branch}").stdout.strip()
    run_branch = f"jianghu-run-{re.sub(r'[^a-zA-Z0-9_-]+', '-', run_id).strip('-')[:48] or 'run'}"
    update_status = "created"
    if created:
        _run_git(
            repository,
            "checkout",
            "--quiet",
            "-b",
            run_branch,
            f"refs/remotes/origin/{target_branch}",
        )
    else:
        dirty = bool(_run_git(repository, "status", "--porcelain").stdout.strip())
        current_branch = _run_git(repository, "branch", "--show-current").stdout.strip()
        if dirty:
            update_status = "preserved_dirty"
        elif current_branch != run_branch:
            update_status = "preserved_branch"
        else:
            fast_forward = _run_git(
                repository,
                "merge",
                "--ff-only",
                f"refs/remotes/origin/{target_branch}",
                check=False,
            )
            update_status = "fast_forwarded" if fast_forward.returncode == 0 else "preserved_diverged"

    head = _run_git(repository, "rev-parse", "HEAD").stdout.strip()
    return {
        "created": created,
        "repository": str(repository),
        "baseline_commit": head,
        "target_commit": target_commit,
        "target_branch": target_branch,
        "run_branch": run_branch,
        "update_status": update_status,
        "authoritative_source": True,
    }


def _remote_auth_environment(config: dict[str, Any]) -> dict[str, str]:
    environment = os.environ.copy()
    token = str(config.get("token") or "")
    repository_url = str(config.get("repository_url") or "")
    if token and repository_url.startswith(("http://", "https://")):
        username = str(config.get("username") or "oauth2")
        encoded = base64.b64encode(f"{username}:{token}".encode("utf-8")).decode("ascii")
        environment.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.extraHeader",
                "GIT_CONFIG_VALUE_0": f"Authorization: Basic {encoded}",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
    return environment


def test_remote_repository(config: dict[str, Any]) -> dict[str, Any]:
    repository_url = str(config.get("repository_url") or "").strip()
    if not repository_url:
        raise GitDeliveryError("git_repository_url_required")
    completed = subprocess.run(
        [_git_binary(), "ls-remote", "--heads", repository_url],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        env=_remote_auth_environment(config),
    )
    if completed.returncode != 0:
        raise GitDeliveryError((completed.stderr or completed.stdout or "git_remote_connection_failed").strip()[:2000])
    heads = [line.split("\t", 1)[1].removeprefix("refs/heads/") for line in completed.stdout.splitlines() if "\trefs/heads/" in line]
    return {"ok": True, "repository_url": repository_url, "branches": heads[:20], "branch_count": len(heads)}


def _repository_slug(repository_url: str) -> str:
    if re.match(r"^[^/@\s]+@[^:]+:.+", repository_url):
        path = repository_url.split(":", 1)[1]
    else:
        path = urlparse(repository_url).path
    return path.strip("/").removesuffix(".git")


def _create_merge_request(config: dict[str, Any], *, source_branch: str, target_branch: str, title: str, description: str) -> dict[str, Any]:
    provider = str(config.get("provider") or "generic")
    repository_url = str(config.get("repository_url") or "")
    api_base_url = str(config.get("api_base_url") or "").rstrip("/")
    token = str(config.get("token") or "")
    slug = _repository_slug(repository_url)
    if not token:
        raise GitDeliveryError("git_token_required_for_merge_request")
    if provider == "github":
        api_root = api_base_url or "https://api.github.com"
        endpoint = f"{api_root}/repos/{slug}/pulls"
        lookup_endpoint = f"{endpoint}?{urlencode({'state': 'open', 'head': f'{slug.split('/', 1)[0]}:{source_branch}', 'base': target_branch})}"
        payload = {"title": title, "head": source_branch, "base": target_branch, "body": description}
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    elif provider == "gitlab":
        origin = urlparse(repository_url)
        api_root = api_base_url or f"{origin.scheme}://{origin.netloc}/api/v4"
        endpoint = f"{api_root}/projects/{quote(slug, safe='')}/merge_requests"
        lookup_endpoint = f"{endpoint}?{urlencode({'state': 'opened', 'source_branch': source_branch, 'target_branch': target_branch})}"
        payload = {"title": title, "source_branch": source_branch, "target_branch": target_branch, "description": description}
        headers = {"PRIVATE-TOKEN": token}
    elif provider == "gitee":
        api_root = api_base_url or "https://gitee.com/api/v5"
        endpoint = f"{api_root}/repos/{slug}/pulls"
        lookup_endpoint = f"{endpoint}?{urlencode({'access_token': token, 'state': 'open', 'head': source_branch, 'base': target_branch})}"
        payload = {"access_token": token, "title": title, "head": source_branch, "base": target_branch, "body": description}
        headers = {}
    else:
        raise GitDeliveryError("git_provider_does_not_support_merge_request_api")
    lookup_request = Request(lookup_endpoint, headers={"User-Agent": "Jianghu-Online", **headers}, method="GET")
    try:
        with urlopen(lookup_request, timeout=30) as response:
            existing = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise GitDeliveryError(f"git_merge_request_lookup_http_{exc.code}:{detail}") from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise GitDeliveryError(f"git_merge_request_lookup_failed:{exc}") from exc
    if isinstance(existing, list) and existing:
        result = existing[0]
        return {
            "provider": provider,
            "number": result.get("iid") or result.get("number"),
            "title": result.get("title") or title,
            "state": result.get("state") or "opened",
            "url": result.get("web_url") or result.get("html_url") or result.get("url"),
            "source_branch": source_branch,
            "target_branch": target_branch,
            "reused_existing": True,
        }
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Jianghu-Online", **headers},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise GitDeliveryError(f"git_merge_request_http_{exc.code}:{detail}") from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise GitDeliveryError(f"git_merge_request_failed:{exc}") from exc
    return {
        "provider": provider,
        "number": result.get("iid") or result.get("number"),
        "title": result.get("title") or title,
        "state": result.get("state") or "opened",
        "url": result.get("web_url") or result.get("html_url") or result.get("url"),
        "source_branch": source_branch,
        "target_branch": target_branch,
    }


def _overlay_source_tree(repository: Path, *, base_commit_sha: str, source_commit_sha: str) -> str:
    """Overlay an isolated Run tree on a real repository base without deleting unrelated files."""
    index_path = repository / ".git" / f"jianghu-delivery-{hashlib.sha256(source_commit_sha.encode()).hexdigest()[:16]}.index"
    index_environment = os.environ.copy()
    index_environment["GIT_INDEX_FILE"] = str(index_path)
    try:
        _run_git(repository, "read-tree", base_commit_sha, env=index_environment)
        listing = _run_git(repository, "ls-tree", "-r", "-z", source_commit_sha).stdout
        for entry in listing.split("\0"):
            if not entry or "\t" not in entry:
                continue
            metadata, path = entry.split("\t", 1)
            parts = metadata.split()
            if len(parts) != 3 or parts[1] not in {"blob", "commit"}:
                continue
            mode, _, object_sha = parts
            _run_git(
                repository, "update-index", "--add", "--cacheinfo", mode, object_sha, path,
                env=index_environment,
            )
        return _run_git(repository, "write-tree", env=index_environment).stdout.strip()
    finally:
        index_path.unlink(missing_ok=True)


def deliver_commit_to_remote(
    code_root: str | Path,
    *,
    commit: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    repository = Path(code_root).resolve()
    mode = str(config.get("delivery_mode") or "local_commit")
    if mode == "local_commit":
        return {"mode": mode, "push": None, "merge_request": None}
    repository_url = str(config.get("repository_url") or "").strip()
    if not repository_url:
        raise GitDeliveryError("git_repository_url_required")
    run_scope = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(commit.get("run_id") or "run")).strip("-")[:48]
    node_scope = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(commit.get("node_key") or "delivery")).strip("-")[:48]
    branch = f"jianghu/{run_scope}/{node_scope}"
    existing = _run_git(repository, "remote", "get-url", "origin", check=False)
    _run_git(repository, "remote", "set-url" if existing.returncode == 0 else "add", "origin", repository_url)
    target_branch = str(config.get("default_branch") or config.get("target_branch") or "main")
    auth_environment = _remote_auth_environment(config)
    _run_git(
        repository,
        "fetch",
        "--no-tags",
        "origin",
        f"refs/heads/{target_branch}:refs/remotes/origin/{target_branch}",
        env=auth_environment,
    )
    remote_branch_fetch = _run_git(
        repository,
        "fetch",
        "--no-tags",
        "origin",
        f"refs/heads/{branch}:refs/remotes/origin/{branch}",
        check=False,
        env=auth_environment,
    )
    source_commit_sha = str(commit["commit_sha"])
    delivery_commit_sha = source_commit_sha
    target_commit_sha = _run_git(repository, "rev-parse", f"refs/remotes/origin/{target_branch}").stdout.strip()
    remote_branch_sha = ""
    remote_tree_sha = ""
    if remote_branch_fetch.returncode == 0:
        remote_branch_sha = _run_git(repository, "rev-parse", f"refs/remotes/origin/{branch}").stdout.strip()
        remote_tree_sha = _run_git(repository, "rev-parse", f"{remote_branch_sha}^{{tree}}").stdout.strip()
    related = _run_git(
        repository,
        "merge-base",
        "--is-ancestor",
        target_commit_sha,
        source_commit_sha,
        check=False,
    ).returncode == 0
    delivery_tree_sha = (
        _run_git(repository, "rev-parse", f"{source_commit_sha}^{{tree}}").stdout.strip()
        if related else
        _overlay_source_tree(repository, base_commit_sha=target_commit_sha, source_commit_sha=source_commit_sha)
    )
    if remote_branch_sha and remote_tree_sha == delivery_tree_sha:
        delivery_commit_sha = remote_branch_sha
    elif not related or (remote_branch_sha and _run_git(
        repository, "merge-base", "--is-ancestor", remote_branch_sha, source_commit_sha, check=False,
    ).returncode != 0):
        parent_shas = [remote_branch_sha or target_commit_sha]
        if remote_branch_sha and _run_git(
            repository, "merge-base", "--is-ancestor", target_commit_sha, remote_branch_sha, check=False,
        ).returncode != 0:
            parent_shas.append(target_commit_sha)
        author = _run_git(repository, "show", "-s", "--format=%an%n%ae%n%aI", source_commit_sha).stdout.splitlines()
        commit_environment = os.environ.copy()
        commit_environment.update(
            {
                "GIT_AUTHOR_NAME": author[0] if author else "Jianghu Agent",
                "GIT_AUTHOR_EMAIL": author[1] if len(author) > 1 else "agent@agents.jianghu.local",
                "GIT_AUTHOR_DATE": author[2] if len(author) > 2 else "",
                "GIT_COMMITTER_NAME": "Jianghu Platform",
                "GIT_COMMITTER_EMAIL": "platform@jianghu.local",
            }
        )
        arguments = ["commit-tree", delivery_tree_sha]
        for parent_sha in parent_shas:
            arguments.extend(["-p", parent_sha])
        arguments.extend(["-m", str(commit.get("subject") or "Jianghu Run delivery")])
        delivery_commit_sha = _run_git(repository, *arguments, env=commit_environment).stdout.strip()
    _run_git(repository, "branch", "-f", branch, delivery_commit_sha)
    pushed = _run_git(
        repository,
        "push",
        "--porcelain",
        "origin",
        f"{delivery_commit_sha}:refs/heads/{branch}",
        env=auth_environment,
    )
    push_receipt = {
        "repository_url": repository_url,
        "branch": branch,
        "commit_sha": delivery_commit_sha,
        "source_commit_sha": source_commit_sha,
        "target_commit_sha": target_commit_sha,
        "previous_remote_commit_sha": remote_branch_sha or None,
        "history_anchored": not related,
        "status": "pushed",
        "detail": (pushed.stdout or pushed.stderr).strip()[:2000],
    }
    merge_request = None
    if mode == "create_merge_request":
        merge_request = _create_merge_request(
            config,
            source_branch=branch,
            target_branch=target_branch,
            title=str(commit.get("subject") or "Jianghu Run delivery"),
            description=(
                f"Run `{commit.get('run_id')}` · Node `{commit.get('node_key')}`\n\n"
                f"Delivery commit: `{delivery_commit_sha}`\n"
                f"Run-isolated source commit: `{source_commit_sha}`"
            ),
        )
    return {"mode": mode, "push": push_receipt, "merge_request": merge_request}


def commit_run_changes(
    code_root: str | Path,
    *,
    run_id: str,
    node_key: str,
    node_name: str,
    agent: dict[str, Any],
    paths: list[str] | None = None,
) -> dict[str, Any] | None:
    repository = Path(code_root).resolve()
    ensure_run_repository(repository, run_id)
    scoped_paths: list[str] | None = None
    if paths is not None:
        scoped_paths = []
        for raw_path in paths:
            normalized = str(raw_path or "").replace("\\", "/").strip("/")
            parts = Path(normalized).parts
            if not normalized or any(part in {"", ".", ".."} for part in parts):
                continue
            scoped_paths.append(normalized)
        scoped_paths = sorted(set(scoped_paths))
        if not scoped_paths:
            return None
        for offset in range(0, len(scoped_paths), 100):
            _run_git(repository, "add", "--all", "--", *scoped_paths[offset : offset + 100])
    else:
        status = _run_git(repository, "status", "--porcelain=v1", "--untracked-files=all").stdout
        if not status.strip():
            return None
        _run_git(repository, "add", "--all")
    if _run_git(repository, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return None

    author_name, author_email = _identity(agent)
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": "Jianghu Platform",
            "GIT_COMMITTER_EMAIL": "platform@jianghu.local",
        }
    )
    scope = re.sub(r"[^a-zA-Z0-9_-]+", "-", node_key).strip("-_")[:48] or "delivery"
    subject = f"feat({scope}): {node_name}"[:240]
    _run_git(repository, "commit", "--quiet", "--no-gpg-sign", "-m", subject, env=environment)

    commit_sha = _run_git(repository, "rev-parse", "HEAD").stdout.strip()
    tree_sha = _run_git(repository, "rev-parse", "HEAD^{tree}").stdout.strip()
    parents = _run_git(repository, "show", "-s", "--format=%P", "HEAD").stdout.strip().split()
    branch = _run_git(repository, "branch", "--show-current").stdout.strip() or "HEAD"
    committed_at = _run_git(repository, "show", "-s", "--format=%cI", "HEAD").stdout.strip()
    name_status = _run_git(
        repository,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-status",
        "-r",
        "-M",
        "HEAD",
    ).stdout
    files: list[dict[str, str]] = []
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            files.append({"status": parts[0], "path": parts[-1]})
    shortstat = _run_git(repository, "show", "--shortstat", "--format=", "HEAD").stdout.strip()
    patch = export_commit_patch(repository, commit_sha)
    return {
        "schema_version": "jianghu.git-commit.v1",
        "run_id": run_id,
        "node_key": node_key,
        "commit_sha": commit_sha,
        "short_sha": commit_sha[:12],
        "tree_sha": tree_sha,
        "parent_shas": parents,
        "branch": branch,
        "subject": subject,
        "author_name": author_name,
        "author_agent_id": str(agent.get("id") or ""),
        "committed_at": committed_at,
        "files": files,
        "file_count": len(files),
        "shortstat": shortstat,
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
        "repository": str(repository),
    }


def export_commit_patch(code_root: str | Path, commit_sha: str) -> bytes:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
        raise GitDeliveryError("invalid_commit_sha")
    repository = Path(code_root).resolve()
    verified = _run_git(repository, "rev-parse", "--verify", f"{commit_sha}^{{commit}}", check=False)
    if verified.returncode != 0:
        raise GitDeliveryError("commit_not_found")
    completed = subprocess.run(
        [_git_binary(), "-C", str(repository), "format-patch", "-1", "--stdout", commit_sha],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        raise GitDeliveryError((completed.stderr or b"git_patch_failed").decode("utf-8", errors="replace")[:2000])
    return completed.stdout


__all__ = [
    "GitDeliveryError", "commit_run_changes", "deliver_commit_to_remote", "ensure_run_repository",
    "export_commit_patch", "test_remote_repository",
]
