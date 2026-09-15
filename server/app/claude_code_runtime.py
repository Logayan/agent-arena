from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from .agent_runtime import AgentRuntimeError, RuntimeErrorCategory


def _safe_name(value: object, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "")).strip("-_").lower()
    return normalized[:64] or fallback


def _configured_max_turns(_engineering: bool) -> int | None:
    """Return an explicitly configured SDK turn limit.

    Claude Agent SDK ``maxTurns`` is a hard terminal limit, not an inactivity
    or cost guard.  Mature audit and E2E roles routinely need more than one
    hundred tool turns, so imposing a default silently truncates healthy work.
    Token/cost budgets and the heartbeat inactivity watchdog remain the
    platform safety controls.  A deployment may still opt in to a positive
    hard turn limit when it deliberately wants one.
    """

    raw = os.getenv("JIANGHU_CLAUDE_MAX_TURNS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _bridge_stream_limit_bytes() -> int:
    default = 8 * 1024 * 1024
    try:
        value = int(os.getenv("JIANGHU_CLAUDE_STREAM_LIMIT_BYTES", str(default)))
    except ValueError:
        value = default
    return max(1024 * 1024, min(value, 16 * 1024 * 1024))


class ClaudeCodeRuntimeError(AgentRuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: RuntimeErrorCategory | None = None,
        retryable: bool | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            category=category,
            retryable=retryable,
            runtime="claude_code",
            details=details,
        )


class ClaudeCodeRuntime:
    """Claude Agent SDK implementation of the framework-neutral Runtime Port.

    Provider credentials are sent to the private Node bridge over stdin and
    never persisted. Engineering
    tools run through the bridge's MCP workspace gateway with a scrubbed
    environment instead of inheriting the model credential environment.
    """

    runtime_name = "claude_code"
    supports_live_actions = True

    def __init__(
        self,
        state_root: str | Path | None = None,
        workspace_root: str | Path | None = None,
        bridge_path: str | Path | None = None,
        node_path: str | Path | None = None,
    ) -> None:
        self.state_root = Path(state_root or os.getenv("JIANGHU_CLAUDE_STATE_ROOT", ".data/claude-code")).resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else self.state_root / "workspaces"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        default_bridge = Path(__file__).resolve().parents[1] / "claude_agent_runtime" / "bridge.mjs"
        self.bridge_path = Path(bridge_path or os.getenv("JIANGHU_CLAUDE_BRIDGE_PATH", str(default_bridge))).resolve()
        self._configured_node_path = Path(node_path).resolve() if node_path else None
        self.sessions_path = self.state_root / "sessions.json"
        self.policy_path = self.state_root / "agent-policies.json"
        self._state_lock = threading.Lock()

    def for_run(self, run_id: str, execution_root: str | Path | None = None) -> "ClaudeCodeRuntime":
        safe_run_id = _safe_name(run_id, "run")
        run_state = (self.state_root / "runs" / safe_run_id).resolve()
        if not run_state.is_relative_to(self.state_root):
            raise ClaudeCodeRuntimeError("claude_run_state_escape", category="security", retryable=False)
        run_workspace_root = (
            Path(execution_root).resolve() / "tmp" / "claude-agents"
            if execution_root
            else self.workspace_root
        )
        return ClaudeCodeRuntime(
            run_state,
            workspace_root=run_workspace_root,
            bridge_path=self.bridge_path,
            node_path=self._configured_node_path,
        )

    def _node_path(self) -> Path | None:
        configured = os.getenv("JIANGHU_CLAUDE_NODE_PATH")
        candidates = [
            self._configured_node_path,
            Path(configured).resolve() if configured else None,
            Path(".data/runtime/node-v24.15.0-win-x64/node.exe").resolve(),
            Path("C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"),
        ]
        for candidate in candidates:
            if candidate and candidate.is_file():
                return candidate
        discovered = shutil.which("node")
        return Path(discovered).resolve() if discovered else None

    def _base_command(self) -> list[str]:
        node = self._node_path()
        if not node:
            raise ClaudeCodeRuntimeError("claude_node_runtime_not_found", category="configuration", retryable=False)
        if not self.bridge_path.is_file():
            raise ClaudeCodeRuntimeError("claude_bridge_not_found", category="configuration", retryable=False)
        return [str(node), str(self.bridge_path)]

    @staticmethod
    def _redact_text(value: object, secrets: list[str] | None = None, limit: int = 8_000) -> str:
        text = str(value or "")
        for secret in secrets or []:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        text = re.sub(
            r"(?i)(api[_-]?key|token|secret|password|authorization)(\s*[=:]\s*)[^\s\"']+",
            r"\1\2[REDACTED]",
            text,
        )
        return text if len(text) <= limit else f"{text[:limit]}…"

    @classmethod
    def _redact_value(cls, value: Any, secrets: list[str] | None = None) -> Any:
        if isinstance(value, dict):
            output: dict[str, Any] = {}
            for key, item in value.items():
                public_key = str(key)
                sensitive_key = re.search(r"(?i)(key|token|secret|password|auth|credential)", public_key)
                if sensitive_key and isinstance(item, str):
                    output[public_key] = "[REDACTED]"
                else:
                    output[public_key] = cls._redact_value(item, secrets)
            return output
        if isinstance(value, list):
            return [cls._redact_value(item, secrets) for item in value]
        if isinstance(value, str):
            return cls._redact_text(value, secrets, 100_000)
        return value

    def health(self) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                [*self._base_command(), "--health"],
                cwd=str(self.bridge_path.parent),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
            raw = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
            payload = json.loads(raw) if raw else {}
            available = completed.returncode == 0 and bool(payload.get("available"))
            return {
                "available": available,
                "runtime": self.runtime_name,
                "mode": "agent-sdk-bridge",
                "version": str(payload.get("version") or ""),
                "claude_code_version": str(payload.get("claude_code_version") or ""),
                "error": "" if available else self._redact_text(completed.stderr or raw or "claude_health_failed"),
                "node_path": str(self._node_path() or ""),
                "entry_path": str(self.bridge_path),
                "state_root": str(self.state_root),
                "config_ready": self.policy_path.is_file(),
            }
        except Exception as exc:  # pragma: no cover - deployment diagnostics
            return {
                "available": False,
                "runtime": self.runtime_name,
                "mode": "agent-sdk-bridge",
                "version": "",
                "error": self._redact_text(exc),
                "node_path": str(self._node_path() or ""),
                "entry_path": str(self.bridge_path),
                "state_root": str(self.state_root),
                "config_ready": self.policy_path.is_file(),
            }

    def _workspace(self, agent: dict[str, Any]) -> Path:
        path = (self.workspace_root / _safe_name(agent.get("id"), "agent")).resolve()
        if not path.is_relative_to(self.workspace_root):
            raise ClaudeCodeRuntimeError("claude_workspace_escape", category="security", retryable=False)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def workspace_path(self, agent: dict[str, Any]) -> Path:
        return self._workspace(agent)

    @staticmethod
    def _write_if_changed(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.read_text(encoding="utf-8", errors="replace") == content:
            return
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _load_json(path: Path, default: Any) -> Any:
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def sync(
        self,
        agents: list[dict[str, Any]],
        memories_by_agent: dict[str, list[dict[str, Any]]],
        model_config: dict[str, Any],
        tool_enabled_agent_ids: set[str] | None = None,
        model_configs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not model_config.get("token"):
            raise ClaudeCodeRuntimeError("claude_model_token_missing", category="configuration", retryable=False)
        base_url = str(model_config.get("base_url") or "").rstrip("/")
        model_id = str(model_config.get("model") or "")
        if not base_url or not model_id:
            raise ClaudeCodeRuntimeError("claude_model_config_incomplete", category="configuration", retryable=False)
        engineering_agents = set(tool_enabled_agent_ids or set())
        policies: dict[str, Any] = {}
        for agent in agents:
            agent_id = str(agent.get("id") or "")
            workspace = self._workspace(agent)
            skills_root = workspace / ".claude" / "skills"
            skills_root.mkdir(parents=True, exist_ok=True)
            skill_ids: list[str] = []
            for index, skill in enumerate(agent.get("skills") or []):
                if not isinstance(skill, dict) or not skill.get("enabled", True):
                    continue
                skill_id = _safe_name(skill.get("key") or skill.get("name"), f"skill-{index + 1}")
                skill_ids.append(skill_id)
                description = str(skill.get("description") or skill.get("name") or "江湖人物专属技能").replace("\n", " ")
                skill_md = "\n".join(
                    [
                        "---",
                        f"name: {skill_id}",
                        f"description: {description}",
                        "---",
                        "",
                        f"# {skill.get('name') or skill_id}",
                        "",
                        str(skill.get("instructions") or skill.get("description") or "按人物职责谨慎完成任务，并留下可核验产物。"),
                        "",
                    ]
                )
                self._write_if_changed(skills_root / skill_id / "SKILL.md", skill_md)
            for stale_skill in skills_root.iterdir():
                if stale_skill.is_dir() and stale_skill.name not in skill_ids:
                    shutil.rmtree(stale_skill)
            memory_items = memories_by_agent.get(agent_id, [])
            memory_text = "\n\n".join(
                f"## {item.get('title') or item.get('kind') or '经历'}\n{item.get('content', '')}"
                for item in memory_items[:30]
            ) or "尚无长期经历；只依据本次获准的知识和任务行动。"
            claude_md = "\n".join(
                [
                    "# 江湖 Online 人物运行上下文",
                    "",
                    f"姓名：{agent.get('name', '')}",
                    f"职业身份：{agent.get('role', '')}",
                    f"版本：{agent.get('version', '1.0.0')}",
                    "",
                    "## 人物底色与立场",
                    str(agent.get("persona") or agent.get("description") or ""),
                    "",
                    "## 行动规范",
                    "你是长期存在、可复用且相对独立的拟人化 Agent。只处理平台交给你的当前节点。",
                    "必须保持独立判断，不迎合其他人物；公开表达结论、证据、假设和风险，但绝不暴露私有思维链。",
                    "正式成果必须可交付、可核验、可追溯；知识不足时明确说明，不得虚构。",
                    "不得读取其他 Agent 的私有会话、私有记忆或未授权知识。",
                    "工程交付必须写入 delivery/，平台只从该目录采集正式候选文件。",
                    "",
                    "## 长期记忆",
                    memory_text,
                    "",
                ]
            )
            self._write_if_changed(workspace / "CLAUDE.md", claude_md)
            policies[agent_id] = {
                "engineering": agent_id in engineering_agents,
                "skill_ids": skill_ids,
                "model": model_id,
            }
        self._write_if_changed(self.policy_path, json.dumps(policies, ensure_ascii=False, indent=2))
        configured_models = []
        for candidate in [model_config, *(model_configs or [])]:
            candidate_model = str(candidate.get("model") or "")
            if candidate_model and candidate_model not in configured_models:
                configured_models.append(candidate_model)
        return {
            "runtime": self.runtime_name,
            "agent_count": len(policies),
            "config_path": str(self.policy_path),
            "model": model_id,
            "models": configured_models,
            "tool_enabled_agent_ids": sorted(engineering_agents),
        }

    def _policy(self, agent_id: str) -> dict[str, Any]:
        policies = self._load_json(self.policy_path, {})
        return dict(policies.get(agent_id) or {}) if isinstance(policies, dict) else {}

    def _session_id(self, agent_id: str, session_key: str) -> str:
        sessions = self._load_json(self.sessions_path, {})
        if not isinstance(sessions, dict):
            return ""
        return str(sessions.get(f"{agent_id}:{session_key}") or "")

    def _save_session_id(self, agent_id: str, session_key: str, session_id: str) -> None:
        if not session_id:
            return
        with self._state_lock:
            sessions = self._load_json(self.sessions_path, {})
            if not isinstance(sessions, dict):
                sessions = {}
            sessions[f"{agent_id}:{session_key}"] = session_id
            self._write_if_changed(self.sessions_path, json.dumps(sessions, ensure_ascii=False, indent=2))

    @staticmethod
    def _workspace_snapshot(root: Path) -> dict[str, dict[str, Any]]:
        ignored = {
            ".git", "node_modules", "dist", "build", "coverage", "__pycache__",
            ".pytest_cache", ".venv", "venv", ".jianghu-platform-evidence",
        }
        snapshot: dict[str, dict[str, Any]] = {}
        if not root.is_dir():
            return snapshot
        def handle_walk_error(error: OSError) -> None:
            if not isinstance(error, (FileNotFoundError, NotADirectoryError)):
                raise error

        # Browser/test runners create and remove trace directories while their
        # process tree is shutting down. Path.rglob can fail the whole Agent
        # turn when one of those directories disappears between scandir calls.
        # os.walk's onerror hook keeps the snapshot best-effort while stable
        # files are still hashed and reported normally.
        for directory, directory_names, file_names in os.walk(
            root,
            topdown=True,
            onerror=handle_walk_error,
            followlinks=False,
        ):
            directory_names[:] = [name for name in directory_names if name not in ignored]
            directory_path = Path(directory)
            for file_name in file_names:
                path = directory_path / file_name
                try:
                    relative_path = path.relative_to(root)
                    data = path.read_bytes()
                except OSError:
                    continue
                snapshot[relative_path.as_posix()] = {
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                }
        return snapshot

    @staticmethod
    def _workspace_changes(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        for relative_path in sorted(set(before) | set(after)):
            old = before.get(relative_path)
            new = after.get(relative_path)
            if old == new:
                continue
            changes.append(
                {
                    "path": relative_path,
                    "action": "created" if old is None else ("deleted" if new is None else "modified"),
                    "sha256": str((new or {}).get("sha256") or ""),
                    "size_bytes": int((new or {}).get("size_bytes") or 0),
                    "previous_sha256": str((old or {}).get("sha256") or ""),
                }
            )
        return changes

    @staticmethod
    def _copy_tree(source: Path, destination: Path) -> None:
        if not source.is_dir():
            return
        ignored = {
            ".git", "node_modules", "dist", "build", "coverage", "__pycache__", ".pytest_cache", ".venv", "venv",
            # The platform evidence bundle is a read-only seed measured by its
            # own immutable Registry. Hashing several gigabytes of it once per
            # Agent before and after every turn cannot reveal deliverable changes.
            ".jianghu-platform-evidence",
        }
        destination.mkdir(parents=True, exist_ok=True)
        def handle_walk_error(error: OSError) -> None:
            if not isinstance(error, (FileNotFoundError, NotADirectoryError)):
                raise error

        for directory, directory_names, file_names in os.walk(
            source,
            topdown=True,
            onerror=handle_walk_error,
            followlinks=False,
        ):
            directory_names[:] = [name for name in directory_names if name not in ignored]
            directory_path = Path(directory)
            try:
                relative_directory = directory_path.relative_to(source)
                target_directory = destination / relative_directory
                target_directory.mkdir(parents=True, exist_ok=True)
            except (FileNotFoundError, NotADirectoryError):
                continue
            for file_name in file_names:
                path = directory_path / file_name
                target = target_directory / file_name
                try:
                    source_stat = path.stat()
                    if target.is_file():
                        target_stat = target.stat()
                        if (
                            source_stat.st_size == target_stat.st_size
                            and source_stat.st_mtime_ns == target_stat.st_mtime_ns
                        ):
                            continue
                    shutil.copy2(path, target)
                except (FileNotFoundError, NotADirectoryError):
                    # A transient browser trace may disappear after os.walk
                    # enumerates it. It is not a durable Agent deliverable and
                    # must not fail recovery or a completed model response.
                    continue

    @staticmethod
    def _mirror_evidence_bundle(bundle_root: Path, visible_root: Path) -> Path:
        """Expose one immutable Attempt evidence bundle inside an Agent workspace.

        The normal seed copy deliberately excludes ``.jianghu-platform-evidence``
        because copying and hashing several gigabytes for every Agent turn is
        prohibitively expensive.  Tool-enabled Agents still need the exact
        bundle named in their prompt, though.  Mirror only that snapshot and
        its content-addressed Artifact files with hard links where possible;
        the MCP write boundary remains limited to ``delivery/``.
        """
        source_bundle = bundle_root.resolve()
        if not source_bundle.is_dir() or source_bundle.parent.name != "snapshots":
            raise ClaudeCodeRuntimeError(
                "claude_evidence_bundle_invalid",
                category="configuration",
                retryable=False,
            )
        source_evidence_root = source_bundle.parent.parent.resolve()
        # Claude Code executes with delivery/ as cwd and the executor prompt
        # names the bundle relative to that project root.  Mirror into delivery
        # so the documented path is actually readable.  Workspace snapshots
        # already exclude this directory, so evidence cannot be promoted as a
        # user-authored deliverable.
        destination_evidence_root = (visible_root.resolve() / ".jianghu-platform-evidence").resolve()
        destination_bundle = destination_evidence_root / "snapshots" / source_bundle.name

        def mirror_file(source: Path, destination: Path) -> None:
            source = source.resolve()
            destination = destination.resolve()
            if not source.is_relative_to(source_evidence_root):
                raise ClaudeCodeRuntimeError(
                    "claude_evidence_source_escape",
                    category="configuration",
                    retryable=False,
                )
            if not destination.is_relative_to(destination_evidence_root):
                raise ClaudeCodeRuntimeError(
                    "claude_evidence_destination_escape",
                    category="configuration",
                    retryable=False,
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_file() and destination.stat().st_size == source.stat().st_size:
                return
            temporary = destination.with_name(
                f".{destination.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            temporary.unlink(missing_ok=True)
            try:
                try:
                    os.link(source, temporary)
                except OSError:
                    shutil.copy2(source, temporary)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)

        for source in source_bundle.rglob("*"):
            if source.is_file():
                mirror_file(source, destination_bundle / source.relative_to(source_bundle))

        registry_path = source_bundle / "artifact-registry.json"
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ClaudeCodeRuntimeError(
                "claude_evidence_registry_invalid",
                category="configuration",
                retryable=False,
            ) from exc
        if not isinstance(registry, list):
            raise ClaudeCodeRuntimeError(
                "claude_evidence_registry_invalid",
                category="configuration",
                retryable=False,
            )
        for item in registry:
            if not isinstance(item, dict) or not item.get("materialized"):
                continue
            relative_path = str(item.get("materialized_path") or "")
            if not relative_path:
                continue
            source = (source_bundle / relative_path).resolve()
            if not source.is_relative_to(source_evidence_root) or not source.is_file():
                raise ClaudeCodeRuntimeError(
                    "claude_evidence_artifact_missing",
                    category="configuration",
                    retryable=False,
                )
            destination = (destination_bundle / relative_path).resolve()
            mirror_file(source, destination)
        return destination_bundle

    @staticmethod
    async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        pid = process.pid
        if os.name == "nt":
            await asyncio.to_thread(
                subprocess.run,
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:  # pragma: no cover - exercised in Linux deployment profile
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            pass

    async def message(
        self,
        *,
        agent: dict[str, Any],
        prompt: str,
        session_key: str,
        model_config: dict[str, Any],
        timeout_seconds: int = 600,
        seed_directory: str | Path | None = None,
        evidence_directory: str | Path | None = None,
        capture_workspace: bool = False,
        on_action: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        token = str(model_config.get("token") or "")
        base_url = str(model_config.get("base_url") or "").rstrip("/")
        model = str(model_config.get("model") or "")
        if not token or not base_url or not model:
            raise ClaudeCodeRuntimeError("claude_model_config_incomplete", category="configuration", retryable=False)
        agent_id = str(agent.get("id") or "")
        workspace = self._workspace(agent)
        delivery = workspace / "delivery"
        if seed_directory:
            # Mature Runs seed hundreds of evidence files. Copying them on the
            # event-loop thread made /api/health and browser polling time out
            # even though the Claude bridge itself was healthy.
            await asyncio.to_thread(
                self._copy_tree,
                Path(seed_directory).resolve(),
                delivery,
            )
        if evidence_directory:
            await asyncio.to_thread(
                self._mirror_evidence_bundle,
                Path(evidence_directory),
                delivery,
            )
        await asyncio.to_thread(delivery.mkdir, parents=True, exist_ok=True)
        before = (
            await asyncio.to_thread(self._workspace_snapshot, delivery)
            if capture_workspace
            else {}
        )
        policy = await asyncio.to_thread(self._policy, agent_id)
        sdk_invocation_id = f"sdk-invocation-{uuid.uuid4().hex}"
        payload = {
            "agent_id": agent_id,
            "prompt": prompt,
            "workspace": str(workspace),
            "config_dir": str(self.state_root / "claude-config"),
            "base_url": base_url,
            "model": model,
            "token": token,
            "engineering": bool(policy.get("engineering")),
            "skill_ids": list(policy.get("skill_ids") or []),
            "sdk_invocation_id": sdk_invocation_id,
            "resume_session_id": self._session_id(agent_id, session_key),
            "command_timeout_seconds": max(1, min(int(timeout_seconds), 600)),
            # This is an internal liveness signal, not a wall-clock execution
            # limit. Long-running Agent turns may continue for days as long as
            # the bridge remains responsive.
            "heartbeat_interval_seconds": min(15, max(1, int(timeout_seconds) // 4)),
        }
        max_turns = _configured_max_turns(bool(policy.get("engineering")))
        if max_turns is not None:
            payload["max_turns"] = max_turns
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        process = await asyncio.create_subprocess_exec(
            *self._base_command(),
            cwd=str(workspace),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
            limit=_bridge_stream_limit_bytes(),
        )
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()
        actions: list[dict[str, Any]] = []
        final: dict[str, Any] | None = None
        bridge_error: dict[str, Any] | None = None
        bridge_session_id = ""
        request_digests: dict[str, str] = {}
        last_public_heartbeat_at = 0.0

        async def read_stderr() -> str:
            raw = await process.stderr.read()
            return self._redact_text(raw.decode("utf-8", errors="replace"), [token], 4_000)

        stderr_task = asyncio.create_task(read_stderr())
        try:
            while True:
                try:
                    # timeout_seconds is an inactivity watchdog. Every bridge
                    # heartbeat, model message, and Tool event renews it, so a
                    # healthy turn has no total wall-clock deadline.
                    raw_line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=max(1, int(timeout_seconds)),
                    )
                except TimeoutError as exc:
                    await self._terminate_process_tree(process)
                    raise ClaudeCodeRuntimeError(
                        f"claude_stalled:{timeout_seconds}s",
                        category="timeout",
                        retryable=True,
                    ) from exc
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ClaudeCodeRuntimeError("claude_bridge_non_json_output", category="invalid_output") from exc
                if event.get("type") == "heartbeat":
                    now = time.monotonic()
                    heartbeat_publish_interval = min(60.0, max(1.0, float(timeout_seconds)))
                    if on_action and now - last_public_heartbeat_at >= heartbeat_publish_interval:
                        heartbeat_action = {
                            "kind": "heartbeat",
                            "sdk_invocation_id": sdk_invocation_id,
                            "claude_sdk_session_id": bridge_session_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        last_public_heartbeat_at = now
                        try:
                            await on_action(heartbeat_action)
                        except Exception:
                            # Liveness telemetry must never terminate an otherwise
                            # healthy SDK turn; the inactivity watchdog remains authoritative.
                            pass
                    continue
                if event.get("type") == "meta":
                    bridge_session_id = str(event.get("session_id") or bridge_session_id)
                elif event.get("type") == "action" and isinstance(event.get("action"), dict):
                    action = self._redact_value(event["action"], [token])
                    tool_call_id = str(action.get("tool_call_id") or action.get("tool_use_id") or "")
                    action.setdefault("tool_call_id", tool_call_id)
                    action.setdefault("tool_use_id", tool_call_id)
                    action.setdefault("sdk_invocation_id", sdk_invocation_id)
                    action.setdefault("claude_sdk_session_id", bridge_session_id)
                    if action.get("kind") == "tool_call":
                        canonical_arguments = json.dumps(
                            action.get("arguments") if isinstance(action.get("arguments"), dict) else {},
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                            default=str,
                        )
                        request_sha256 = str(action.get("request_sha256") or hashlib.sha256(
                            canonical_arguments.encode("utf-8")
                        ).hexdigest())
                        action["request_sha256"] = request_sha256
                        if tool_call_id:
                            request_digests[tool_call_id] = request_sha256
                    elif action.get("kind") == "tool_result":
                        action.setdefault("request_sha256", request_digests.get(tool_call_id, ""))
                        action.setdefault(
                            "result_sha256",
                            hashlib.sha256(str(action.get("output") or "").encode("utf-8")).hexdigest(),
                        )
                    if (
                        action.get("kind") == "tool_result"
                        and action.get("tool_name") == "Bash"
                        and str(action.get("cwd") or "") in {"", "."}
                    ):
                        action["cwd"] = str(delivery)
                    actions.append(action)
                    if on_action:
                        try:
                            await on_action(action)
                            action["live_emitted"] = True
                        except Exception:
                            action["live_emitted"] = False
                elif event.get("type") == "result" and isinstance(event.get("result"), dict):
                    final = self._redact_value(event["result"], [token])
                elif event.get("type") == "error" and isinstance(event.get("error"), dict):
                    bridge_error = self._redact_value(event["error"], [token])
            return_code = await process.wait()
        except asyncio.CancelledError:
            await self._terminate_process_tree(process)
            raise
        finally:
            if process.returncode is None:
                await self._terminate_process_tree(process)
            stderr = await stderr_task
        if final is None:
            detail = str((bridge_error or {}).get("message") or stderr or f"bridge_exit_{return_code}")
            raise ClaudeCodeRuntimeError(f"claude_agent_failed:{detail}")
        if final.get("is_error"):
            status = final.get("api_error_status")
            category: RuntimeErrorCategory | None = None
            retryable: bool | None = None
            if status in {401, 403}:
                category, retryable = "provider_auth", False
            elif status == 429:
                category, retryable = "provider_rate_limit", True
            elif isinstance(status, int) and status >= 500:
                category, retryable = "provider_failure", True
            raise ClaudeCodeRuntimeError(
                f"claude_result_error:{final.get('terminal_reason') or final.get('subtype') or 'unknown'}",
                category=category,
                retryable=retryable,
                details={"api_error_status": status},
            )
        response_text = str(final.get("text") or "").strip()
        if not response_text:
            progress = [str(item.get("content") or "") for item in actions if item.get("kind") == "progress"]
            response_text = next((item for item in reversed(progress) if item.strip()), "")
        if not response_text:
            raise ClaudeCodeRuntimeError("claude_empty_output", category="invalid_output", retryable=True)
        session_id = str(final.get("session_id") or "")
        await asyncio.to_thread(self._save_session_id, agent_id, session_key, session_id)
        after = (
            await asyncio.to_thread(self._workspace_snapshot, delivery)
            if capture_workspace
            else {}
        )
        file_changes = (
            await asyncio.to_thread(self._workspace_changes, before, after)
            if capture_workspace
            else []
        )
        return {
            "id": session_id,
            "session_id": session_id,
            "model": model,
            "content": [{"type": "text", "text": response_text}],
            "usage": dict(final.get("usage") or {}),
            "actions": actions,
            "file_changes": file_changes,
            "claude_code": {
                "runtime": "agent-sdk-bridge",
                "sdk_invocation_id": str(final.get("sdk_invocation_id") or sdk_invocation_id),
                "agent_id": agent_id,
                "session_key": session_key,
                "session_id": session_id,
                "workspace": str(workspace),
                "model": model,
                "model_tier": str(model_config.get("tier") or "medium"),
            },
        }

    def promote_workspace_changes(
        self,
        *,
        agent: dict[str, Any],
        changes: list[dict[str, Any]],
        destination: str | Path,
    ) -> list[dict[str, Any]]:
        source_root = (self._workspace(agent) / "delivery").resolve()
        destination_root = Path(destination).resolve()
        destination_root.mkdir(parents=True, exist_ok=True)
        promoted: list[dict[str, Any]] = []
        for change in changes:
            relative_path = Path(str(change.get("path") or ""))
            if not relative_path.parts or any(part in {"..", "."} for part in relative_path.parts):
                continue
            source = (source_root / relative_path).resolve()
            target = (destination_root / relative_path).resolve()
            if not source.is_relative_to(source_root) or not target.is_relative_to(destination_root):
                raise ClaudeCodeRuntimeError("claude_promotion_path_escape", category="security", retryable=False)
            if change.get("action") == "deleted":
                if target.is_file():
                    target.unlink()
                promoted.append({**change, "path": relative_path.as_posix(), "promoted": True})
                continue
            if not source.is_file():
                continue
            self._copy_workspace_file(source, target, relative_path, operation="promotion")
            promoted.append({**change, "path": relative_path.as_posix(), "promoted": True})
        return promoted

    @staticmethod
    def _copy_path(path: Path) -> str:
        value = str(path.resolve())
        if os.name != "nt" or value.startswith("\\\\?\\"):
            return value
        if value.startswith("\\\\"):
            return f"\\\\?\\UNC\\{value[2:]}"
        return f"\\\\?\\{value}"

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        os.makedirs(ClaudeCodeRuntime._copy_path(path), exist_ok=True)

    @staticmethod
    def _is_file_path(path: Path) -> bool:
        return os.path.isfile(ClaudeCodeRuntime._copy_path(path))

    @staticmethod
    def _unlink_path(path: Path) -> None:
        os.unlink(ClaudeCodeRuntime._copy_path(path))

    @staticmethod
    def _copy_workspace_file(source: Path, target: Path, relative_path: Path, *, operation: str) -> None:
        for copy_attempt in range(2):
            try:
                ClaudeCodeRuntime._ensure_directory(target.parent)
                shutil.copy2(ClaudeCodeRuntime._copy_path(source), ClaudeCodeRuntime._copy_path(target))
                return
            except FileNotFoundError as exc:
                if copy_attempt == 0 and source.is_file():
                    continue
                raise ClaudeCodeRuntimeError(
                    f"claude_{operation}_file_missing",
                    category="runtime_failure",
                    retryable=True,
                    details={
                        "path": relative_path.as_posix(),
                        "copy_attempts": copy_attempt + 1,
                        "source_length": len(str(source)),
                        "target_length": len(str(target)),
                        "missing_filename": str(exc.filename or ""),
                        "missing_filename2": str(exc.filename2 or ""),
                    },
                ) from exc
        raise ClaudeCodeRuntimeError(
            f"claude_{operation}_copy_incomplete",
            category="runtime_failure",
            retryable=True,
            details={"path": relative_path.as_posix()},
        )

    def promote_workspace_tree(self, *, agent: dict[str, Any], destination: str | Path) -> list[dict[str, Any]]:
        source_root = (self._workspace(agent) / "delivery").resolve()
        destination_root = Path(destination).resolve()
        destination_root.mkdir(parents=True, exist_ok=True)
        changes = self._workspace_changes(self._workspace_snapshot(destination_root), self._workspace_snapshot(source_root))
        return self.promote_workspace_changes(agent=agent, changes=changes, destination=destination_root)

    def publish_workspace_submission(
        self,
        *,
        agent: dict[str, Any],
        changes: list[dict[str, Any]],
        destination: str | Path,
    ) -> dict[str, Any]:
        source_root = (self._workspace(agent) / "delivery").resolve()
        destination_root = Path(destination).resolve()
        files_root = destination_root / "files"
        files_root.mkdir(parents=True, exist_ok=True)
        public_changes: list[dict[str, Any]] = []
        for change in changes:
            relative_path = Path(str(change.get("path") or ""))
            if not relative_path.parts or any(part in {"..", "."} for part in relative_path.parts):
                continue
            source = (source_root / relative_path).resolve()
            target = (files_root / relative_path).resolve()
            if not source.is_relative_to(source_root) or not target.is_relative_to(files_root.resolve()):
                raise ClaudeCodeRuntimeError("claude_submission_path_escape", category="security", retryable=False)
            public_change = {
                "path": relative_path.as_posix(),
                "action": str(change.get("action") or "modified"),
                "sha256": str(change.get("sha256") or ""),
                "size_bytes": int(change.get("size_bytes") or 0),
            }
            public_changes.append(public_change)
            if public_change["action"] == "deleted" or not source.is_file():
                if public_change["action"] != "deleted":
                    public_change.update({"action": "deleted", "sha256": "", "size_bytes": 0})
                continue
            try:
                self._copy_workspace_file(source, target, relative_path, operation="submission")
            except ClaudeCodeRuntimeError as exc:
                if str(exc) != "claude_submission_file_missing" or source.is_file():
                    raise
                # A completed Agent may leave short-lived evidence files that
                # are removed by a supervised cleanup/fault-injection child
                # between the final workspace snapshot and publication.  The
                # public submission must reflect the final observable tree,
                # not fail the whole node or claim that the vanished file was
                # published.
                if self._is_file_path(target):
                    self._unlink_path(target)
                public_change.update({"action": "deleted", "sha256": "", "size_bytes": 0})
        manifest = {
            "schema_version": "jianghu.engineering-submission.v1",
            "agent_id": str(agent.get("id") or ""),
            "agent_name": str(agent.get("name") or ""),
            "files_root": str(files_root),
            "changes": public_changes,
        }
        self._write_if_changed(destination_root / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return {
            "agent_id": manifest["agent_id"],
            "agent_name": manifest["agent_name"],
            "root": str(destination_root),
            "manifest": str(destination_root / "manifest.json"),
            "files_root": str(files_root),
            "file_count": len([item for item in public_changes if item["action"] != "deleted"]),
            "changes": public_changes,
        }


claude_code_runtime = ClaudeCodeRuntime()


__all__ = ["ClaudeCodeRuntime", "ClaudeCodeRuntimeError", "claude_code_runtime"]
