from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from server.app.agent_runtime import AgentRuntimeError


class OpenClawRuntimeError(AgentRuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message, runtime="openclaw")


def _safe_name(value: object, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "")).strip("-_").lower()
    return normalized[:64] or fallback


class OpenClawRuntime:
    """Frozen pre-cutover OpenClaw runtime used only by migration baselines.

    This module intentionally lives outside ``server.app`` and must never be
    imported by a product entrypoint.  It remains executable solely so the
    frozen capability corpus and direct parity tests can reproduce the legacy
    behavior after the production runtime has switched to Claude Code SDK.
    """

    runtime_name = "openclaw"
    supports_live_actions = True

    def __init__(
        self,
        state_root: str | Path | None = None,
        workspace_root: str | Path | None = None,
    ) -> None:
        self.state_root = Path(state_root or os.getenv("JIANGHU_OPENCLAW_STATE_ROOT", ".data/openclaw")).resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.state_root / "openclaw.json"
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else self.state_root / "workspaces"
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def for_run(self, run_id: str, execution_root: str | Path | None = None) -> "OpenClawRuntime":
        """Create an isolated OpenClaw state/config/session boundary for one Run.

        Agent workspaces remain shared by concrete Agent version so durable
        identity, Memory and Skills survive across Runs. OpenClaw's own session
        database and generated config are isolated per Run, preventing a model
        configuration change or concurrent Run from contaminating another Run.
        """

        safe_run_id = _safe_name(run_id, "run")
        run_state = (self.state_root / "runs" / safe_run_id).resolve()
        if not run_state.is_relative_to(self.state_root):
            raise OpenClawRuntimeError("openclaw_run_state_escape")
        run_workspace_root = (
            (Path(execution_root).resolve() / "tmp" / "openclaw-agents")
            if execution_root
            else self.workspace_root
        )
        return OpenClawRuntime(run_state, workspace_root=run_workspace_root)

    def _node_path(self) -> Path | None:
        configured = os.getenv("JIANGHU_OPENCLAW_NODE_PATH")
        candidates = [
            Path(configured) if configured else None,
            Path(".data/runtime/node-v24.15.0-win-x64/node.exe").resolve(),
            Path("C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"),
        ]
        for candidate in candidates:
            if candidate and candidate.is_file():
                return candidate
        discovered = shutil.which("node")
        return Path(discovered).resolve() if discovered else None

    def _entry_path(self) -> Path | None:
        configured = os.getenv("JIANGHU_OPENCLAW_ENTRY_PATH")
        candidates = [
            Path(configured) if configured else None,
            Path(os.getenv("APPDATA", "")) / "npm" / "node_modules" / "openclaw" / "openclaw.mjs",
        ]
        for candidate in candidates:
            if candidate and candidate.is_file():
                return candidate.resolve()
        return None

    def _base_command(self) -> list[str]:
        node = self._node_path()
        entry = self._entry_path()
        if not node:
            raise OpenClawRuntimeError("openclaw_node_runtime_not_found")
        if not entry:
            raise OpenClawRuntimeError("openclaw_package_not_found")
        return [str(node), str(entry)]

    def _environment(self, token: str | None = None) -> dict[str, str]:
        env = dict(os.environ)
        env["OPENCLAW_STATE_DIR"] = str(self.state_root)
        env["OPENCLAW_CONFIG_PATH"] = str(self.config_path)
        if token:
            env["JIANGHU_OPENCLAW_API_KEY"] = token
        return env

    def health(self) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                [*self._base_command(), "--version"],
                cwd=str(Path.cwd()),
                env=self._environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
            output = (completed.stdout or completed.stderr).strip()
            return {
                "available": completed.returncode == 0,
                "runtime": self.runtime_name,
                "mode": "embedded-local",
                "version": output if completed.returncode == 0 else "",
                "error": "" if completed.returncode == 0 else output[:1200],
                "node_path": str(self._node_path() or ""),
                "entry_path": str(self._entry_path() or ""),
                "state_root": str(self.state_root),
                "config_ready": self.config_path.is_file(),
            }
        except Exception as exc:
            return {
                "available": False,
                "runtime": self.runtime_name,
                "mode": "embedded-local",
                "version": "",
                "error": str(exc),
                "node_path": str(self._node_path() or ""),
                "entry_path": str(self._entry_path() or ""),
                "state_root": str(self.state_root),
                "config_ready": self.config_path.is_file(),
            }

    def _workspace(self, agent: dict[str, Any]) -> Path:
        # A WorkflowVersion binds a concrete AgentBlueprintVersion. Giving each
        # version its own workspace preserves that frozen identity even when a
        # living team has already moved to a newer version of the same person.
        agent_id = str(agent.get("id") or "agent")
        path = (self.workspace_root / _safe_name(agent_id, "agent")).resolve()
        if not path.is_relative_to(self.workspace_root):
            raise OpenClawRuntimeError("openclaw_workspace_escape")
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

    def sync(
        self,
        agents: list[dict[str, Any]],
        memories_by_agent: dict[str, list[dict[str, Any]]],
        model_config: dict[str, Any],
        tool_enabled_agent_ids: set[str] | None = None,
        model_configs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not model_config.get("token"):
            raise OpenClawRuntimeError("openclaw_model_token_missing")
        base_url = str(model_config.get("base_url") or "").rstrip("/")
        provider_protocol = str(model_config.get("provider") or "")
        if provider_protocol == "openai-responses" and not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        api = "openai-responses" if provider_protocol == "openai-responses" else "anthropic-messages"
        provider_id = "jianghu"
        model_id = str(model_config.get("model") or "")
        if not base_url or not model_id:
            raise OpenClawRuntimeError("openclaw_model_config_incomplete")

        configured_models: list[dict[str, Any]] = []
        seen_models: set[str] = set()
        for candidate in [model_config, *(model_configs or [])]:
            candidate_id = str(candidate.get("model") or "")
            candidate_url = str(candidate.get("base_url") or "").rstrip("/")
            if not candidate_id or not candidate_url or candidate_id in seen_models:
                continue
            if provider_protocol == "openai-responses" and not candidate_url.endswith("/v1"):
                candidate_url = f"{candidate_url}/v1"
            if candidate_url != base_url:
                # OpenClaw providers are shared by URL; do not silently attach
                # a model from another endpoint to the current provider.
                continue
            seen_models.add(candidate_id)
            configured_models.append({"id": candidate_id, "name": candidate_id})
        if model_id not in seen_models:
            configured_models.insert(0, {"id": model_id, "name": model_id})

        config_agents: list[dict[str, Any]] = []
        engineering_agents = tool_enabled_agent_ids or set()
        for index, agent in enumerate(agents):
            workspace = self._workspace(agent)
            skills = list(agent.get("skills") or [])
            skill_ids: list[str] = []
            for skill_index, skill in enumerate(skills):
                if not isinstance(skill, dict) or not skill.get("enabled", True):
                    continue
                skill_id = _safe_name(skill.get("key") or skill.get("name"), f"skill-{skill_index + 1}")
                skill_ids.append(skill_id)
                skill_md = "\n".join(
                    [
                        "---",
                        f"name: {skill_id}",
                        f"description: {str(skill.get('description') or skill.get('name') or '江湖人物专属技能')}",
                        "---",
                        "",
                        f"# {str(skill.get('name') or skill_id)}",
                        "",
                        str(skill.get("instructions") or skill.get("description") or "按人物职责谨慎完成任务，并留下可核验产物。"),
                        "",
                    ]
                )
                self._write_if_changed(workspace / "skills" / skill_id / "SKILL.md", skill_md)

            memory_items = memories_by_agent.get(str(agent.get("id")), [])
            memory_text = "\n\n".join(
                f"## {item.get('title') or item.get('kind') or '经历'}\n{item.get('content', '')}"
                for item in memory_items[:30]
            ) or "尚无长期经历；只依据本次获准的知识和任务行动。"
            self._write_if_changed(
                workspace / "IDENTITY.md",
                f"# 人物身份\n\n姓名：{agent.get('name', '')}\n\n职业身份：{agent.get('role', '')}\n\n版本：{agent.get('version', '1.0.0')}\n",
            )
            self._write_if_changed(
                workspace / "SOUL.md",
                f"# 人物底色与立场\n\n{agent.get('persona') or agent.get('description') or ''}\n\n"
                "你必须保持独立判断，不迎合其他人物；公开表达结论、证据、假设和风险，但绝不暴露私有思维链。\n",
            )
            self._write_if_changed(
                workspace / "AGENTS.md",
                "# 江湖 Online 行动规范\n\n"
                "你是一个长期存在、可复用且相对独立的拟人化 Agent。只处理平台交给你的当前节点。\n"
                "正式成果必须可交付、可核验、可追溯；知识不足时明确说明，不得虚构。\n"
                "同节点协作先独立形成意见，再通过平台提供的公开消息交流。\n"
                "不得读取其他 Agent 的私有会话、私有记忆或未授权知识。\n",
            )
            self._write_if_changed(workspace / "MEMORY.md", f"# 长期记忆\n\n{memory_text}\n")
            agent_config: dict[str, Any] = {
                    "id": str(agent["id"]),
                    "name": str(agent.get("name") or agent["id"]),
                    "default": index == 0,
                    "workspace": str(workspace),
                    "model": f"{provider_id}/{model_id}",
                    "skills": skill_ids,
                    "identity": {
                        "name": str(agent.get("name") or agent["id"]),
                        "theme": str(agent.get("role") or "江湖人物"),
                        "emoji": "🧑",
                    },
                }
            if str(agent["id"]) in engineering_agents:
                agent_config["tools"] = {
                    "profile": "coding",
                    "allow": ["read", "write", "edit", "apply_patch", "exec", "process"],
                    "exec": {
                        "mode": "full",
                        "host": "gateway",
                        "strictInlineEval": True,
                        "timeoutSec": 600,
                    },
                }
            else:
                agent_config["tools"] = {"profile": "minimal"}
            config_agents.append(agent_config)

        config = {
            "gateway": {"mode": "local", "bind": "loopback"},
            "models": {
                "mode": "merge",
                "providers": {
                    provider_id: {
                        "baseUrl": base_url,
                        "apiKey": "${JIANGHU_OPENCLAW_API_KEY}",
                        "api": api,
                        "authHeader": True,
                        "models": [
                            {
                                **candidate,
                                "api": api,
                                "reasoning": True,
                                "input": ["text"],
                                "contextWindow": 200000,
                                "maxTokens": 32000,
                                # Custom Responses gateways frequently reject the
                                # legacy `system` role while accepting the modern
                                # `developer` role. OpenClaw otherwise disables it
                                # automatically for non-OpenAI base URLs.
                                "compat": {"supportsDeveloperRole": True},
                                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                            }
                            for candidate in configured_models
                        ],
                    }
                },
            },
            "agents": {
                "defaults": {
                    "workspace": str(self.workspace_root / "main"),
                    "model": {"primary": f"{provider_id}/{model_id}"},
                },
                "list": config_agents,
            },
            "tools": {
                "profile": "minimal",
                "exec": {
                    "mode": "full",
                    "host": "gateway",
                    "strictInlineEval": True,
                    "timeoutSec": 600,
                },
            },
        }
        self._write_if_changed(self.config_path, json.dumps(config, ensure_ascii=False, indent=2))
        return {
            "runtime": self.runtime_name,
            "agent_count": len(config_agents),
            "config_path": str(self.config_path),
            "model": f"{provider_id}/{model_id}",
            "models": [f"{provider_id}/{item['id']}" for item in configured_models],
            "tool_enabled_agent_ids": sorted(engineering_agents),
        }

    @staticmethod
    def _workspace_snapshot(root: Path) -> dict[str, dict[str, Any]]:
        ignored_names = {
            ".git", "node_modules", "dist", "build", "coverage", "__pycache__", ".pytest_cache",
            ".mypy_cache", ".ruff_cache", ".venv", "venv", "skills",
        }
        control_files = {"IDENTITY.md", "SOUL.md", "AGENTS.md", "MEMORY.md"}
        snapshot: dict[str, dict[str, Any]] = {}
        if not root.is_dir():
            return snapshot
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if any(part in ignored_names for part in relative.parts) or relative.as_posix() in control_files:
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            snapshot[relative.as_posix()] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        return snapshot

    @staticmethod
    def _workspace_changes(
        before: dict[str, dict[str, Any]],
        after: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        for relative_path in sorted(set(before) | set(after)):
            old = before.get(relative_path)
            new = after.get(relative_path)
            if old == new:
                continue
            action = "created" if old is None else ("deleted" if new is None else "modified")
            changes.append(
                {
                    "path": relative_path,
                    "action": action,
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
        destination.mkdir(parents=True, exist_ok=True)
        ignored = {".git", "node_modules", "dist", "build", "coverage", "__pycache__", ".pytest_cache", ".venv", "venv"}
        for path in source.rglob("*"):
            relative = path.relative_to(source)
            if any(part in ignored for part in relative.parts):
                continue
            target = destination / relative
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif path.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)

    @staticmethod
    def _redact_public_text(value: object, secrets: list[str] | None = None, limit: int = 8_000) -> str:
        text = str(value or "")
        for secret in secrets or []:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        text = re.sub(
            r"(?i)(api[_-]?key|token|secret|password)(\s*[=:]\s*)[^\s\"']+",
            r"\1\2[REDACTED]",
            text,
        )
        return text if len(text) <= limit else f"{text[:limit]}…"

    @classmethod
    def _redact_public_value(cls, value: Any, secrets: list[str] | None = None) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._redact_public_value(item, secrets) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._redact_public_value(item, secrets) for item in value]
        if isinstance(value, str):
            return cls._redact_public_text(value, secrets, 100_000)
        return value

    @classmethod
    def _extract_public_actions(cls, session_file: Path, secrets: list[str] | None = None) -> list[dict[str, Any]]:
        if not session_file.is_file():
            return []
        actions: list[dict[str, Any]] = []
        tool_calls: dict[str, dict[str, Any]] = {}
        for line in session_file.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = item.get("message") if isinstance(item, dict) else None
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "")
            content = message.get("content") if isinstance(message.get("content"), list) else []
            if role == "assistant":
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and block.get("text"):
                        actions.append(
                            {
                                "kind": "progress",
                                "content": cls._redact_public_text(block.get("text"), secrets, 4_000),
                                "timestamp": item.get("timestamp"),
                            }
                        )
                    elif block.get("type") == "toolCall":
                        tool_id = str(block.get("id") or "")
                        arguments = block.get("arguments") if isinstance(block.get("arguments"), dict) else {}
                        public_arguments = cls._redact_public_value(arguments, secrets)
                        action = {
                            "kind": "tool_call",
                            "tool_call_id": tool_id,
                            "tool_name": str(block.get("name") or "unknown"),
                            "arguments": public_arguments,
                            "timestamp": item.get("timestamp"),
                        }
                        action["arguments_preview"] = cls._redact_public_text(
                            json.dumps(public_arguments, ensure_ascii=False), secrets, 4_000
                        )
                        tool_calls[tool_id] = action
                        actions.append(action)
            elif role == "toolResult":
                tool_id = str(message.get("toolCallId") or "")
                result_text = "\n".join(
                    str(block.get("text") or "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
                details = message.get("details") if isinstance(message.get("details"), dict) else {}
                actions.append(
                    {
                        "kind": "tool_result",
                        "tool_call_id": tool_id,
                        "tool_name": str(message.get("toolName") or tool_calls.get(tool_id, {}).get("tool_name") or "unknown"),
                        "is_error": bool(message.get("isError")),
                        "status": details.get("status") or ("failed" if message.get("isError") else "completed"),
                        "exit_code": details.get("exitCode"),
                        "duration_ms": details.get("durationMs"),
                        "cwd": cls._redact_public_text(details.get("cwd"), secrets, 1_000),
                        "output": cls._redact_public_text(result_text or details.get("aggregated"), secrets, 8_000),
                        "timestamp": item.get("timestamp"),
                    }
                )
        return actions

    def _session_file_for_key(self, agent_id: str, session_key: str) -> Path | None:
        index_path = self.state_root / "agents" / _safe_name(agent_id, "agent") / "sessions" / "sessions.json"
        if not index_path.is_file():
            return None
        try:
            sessions = json.loads(index_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            return None
        record = sessions.get(session_key) if isinstance(sessions, dict) else None
        if not isinstance(record, dict):
            return None
        raw_path = str(record.get("sessionFile") or "")
        if raw_path:
            path = Path(raw_path).resolve()
        else:
            session_id = str(record.get("sessionId") or "")
            if not session_id:
                return None
            path = (index_path.parent / f"{session_id}.jsonl").resolve()
        return path if path.is_relative_to(self.state_root) else None

    @staticmethod
    def _action_fingerprint(action: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(action, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

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
            raw_path = Path(str(change.get("path") or ""))
            relative = raw_path
            if not relative.parts or any(part in {"..", "."} for part in relative.parts):
                continue
            source = (source_root / raw_path).resolve()
            target = (destination_root / relative).resolve()
            if not source.is_relative_to(source_root) or not target.is_relative_to(destination_root):
                raise OpenClawRuntimeError("openclaw_promotion_path_escape")
            if change.get("action") == "deleted":
                if target.is_file():
                    target.unlink()
                promoted.append({**change, "path": relative.as_posix(), "promoted": True})
                continue
            if not source.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            promoted.append({**change, "path": relative.as_posix(), "promoted": True})
        return promoted

    def promote_workspace_tree(
        self,
        *,
        agent: dict[str, Any],
        destination: str | Path,
    ) -> list[dict[str, Any]]:
        """Synchronize the Agent's complete public delivery tree into the Run.

        A multi-person engineering node lets every participant work in an
        isolated workspace first.  The lead may already have created files in
        that independent turn before the final synthesis turn starts, so a
        simple "changes since synthesis started" snapshot would miss those
        files.  Comparing the complete delivery tree with the Run delivery
        directory makes the final promoted package match what the lead tested.
        """

        source_root = (self._workspace(agent) / "delivery").resolve()
        destination_root = Path(destination).resolve()
        destination_root.mkdir(parents=True, exist_ok=True)
        changes = self._workspace_changes(
            self._workspace_snapshot(destination_root),
            self._workspace_snapshot(source_root),
        )
        return self.promote_workspace_changes(
            agent=agent,
            changes=changes,
            destination=destination_root,
        )

    def publish_workspace_submission(
        self,
        *,
        agent: dict[str, Any],
        changes: list[dict[str, Any]],
        destination: str | Path,
    ) -> dict[str, Any]:
        """Publish only an Agent's declared file contribution for integration.

        The destination sits inside the lead Agent's workspace but outside its
        final ``delivery`` directory.  This gives the integrator real files to
        inspect without exposing another Agent's private session or Memory and
        without leaking collaboration scaffolding into the downloadable build.
        """

        source_root = (self._workspace(agent) / "delivery").resolve()
        destination_root = Path(destination).resolve()
        files_root = destination_root / "files"
        files_root.mkdir(parents=True, exist_ok=True)
        public_changes: list[dict[str, Any]] = []
        for change in changes:
            raw_path = Path(str(change.get("path") or ""))
            if not raw_path.parts or any(part in {"..", "."} for part in raw_path.parts):
                continue
            source = (source_root / raw_path).resolve()
            target = (files_root / raw_path).resolve()
            if not source.is_relative_to(source_root) or not target.is_relative_to(files_root.resolve()):
                raise OpenClawRuntimeError("openclaw_submission_path_escape")
            public_change = {
                "path": raw_path.as_posix(),
                "action": str(change.get("action") or "modified"),
                "sha256": str(change.get("sha256") or ""),
                "size_bytes": int(change.get("size_bytes") or 0),
            }
            public_changes.append(public_change)
            if public_change["action"] == "deleted" or not source.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        manifest = {
            "schema_version": "jianghu.engineering-submission.v1",
            "agent_id": str(agent.get("id") or ""),
            "agent_name": str(agent.get("name") or ""),
            "files_root": str(files_root),
            "changes": public_changes,
        }
        self._write_if_changed(
            destination_root / "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        return {
            "agent_id": manifest["agent_id"],
            "agent_name": manifest["agent_name"],
            "root": str(destination_root),
            "manifest": str(destination_root / "manifest.json"),
            "files_root": str(files_root),
            "file_count": len([item for item in public_changes if item["action"] != "deleted"]),
            "changes": public_changes,
        }

    async def message(
        self,
        *,
        agent: dict[str, Any],
        prompt: str,
        session_key: str,
        model_config: dict[str, Any],
        timeout_seconds: int = 600,
        seed_directory: str | Path | None = None,
        capture_workspace: bool = False,
        on_action: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        workspace = self._workspace(agent)
        delivery_workspace = workspace / "delivery"
        if seed_directory:
            self._copy_tree(Path(seed_directory).resolve(), delivery_workspace)
        delivery_workspace.mkdir(parents=True, exist_ok=True)
        before_snapshot = self._workspace_snapshot(delivery_workspace) if capture_workspace else {}
        command = [
            *self._base_command(),
            "agent",
            "--local",
            "--json",
            "--agent",
            str(agent["id"]),
            "--session-key",
            session_key,
            "--model",
            f"jianghu/{str(model_config.get('model') or '')}",
            "--timeout",
            str(max(30, min(timeout_seconds, 600))),
        ]

        def run() -> subprocess.CompletedProcess[str]:
            message_file: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    suffix=".md",
                    prefix="jianghu-openclaw-",
                    dir=str(self.state_root),
                    delete=False,
                ) as handle:
                    handle.write(prompt)
                    message_file = handle.name
                return subprocess.run(
                    [*command, "--message-file", message_file],
                    cwd=str(workspace),
                    env=self._environment(str(model_config.get("token") or "")),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_seconds + 30,
                    check=False,
                )
            finally:
                if message_file:
                    Path(message_file).unlink(missing_ok=True)

        streamed_fingerprints: set[str] = set()

        async def emit_available_actions() -> None:
            if on_action is None:
                return
            session_file = self._session_file_for_key(str(agent["id"]), session_key)
            if not session_file:
                return
            for action in self._extract_public_actions(session_file, [str(model_config.get("token") or "")]):
                fingerprint = self._action_fingerprint(action)
                if fingerprint in streamed_fingerprints:
                    continue
                try:
                    await on_action(action)
                except Exception:
                    # Observability must not terminate the real production turn.
                    continue
                streamed_fingerprints.add(fingerprint)

        process_task = asyncio.create_task(asyncio.to_thread(run))
        try:
            while not process_task.done():
                await emit_available_actions()
                await asyncio.sleep(0.35)
            completed = await process_task
            await emit_available_actions()
        except subprocess.TimeoutExpired as exc:
            raise OpenClawRuntimeError(f"openclaw_timeout:{timeout_seconds}s") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "openclaw_unknown_failure").strip()
            raise OpenClawRuntimeError(f"openclaw_agent_failed:{detail[:4000]}")
        raw = completed.stdout.strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OpenClawRuntimeError(f"openclaw_non_json_output:{raw[:2000]}") from exc
        agent_meta = payload.get("meta", {}).get("agentMeta", {}) if isinstance(payload.get("meta"), dict) else {}
        session_id = str(payload.get("sessionId") or agent_meta.get("sessionId") or "")
        session_file = self._session_file_for_key(str(agent["id"]), session_key)
        if session_file is None and session_id:
            session_file = self.state_root / "agents" / _safe_name(agent["id"], "agent") / "sessions" / f"{session_id}.jsonl"
        actions = self._extract_public_actions(session_file, [str(model_config.get("token") or "")]) if session_file else []
        for action in actions:
            action["live_emitted"] = self._action_fingerprint({key: value for key, value in action.items() if key != "live_emitted"}) in streamed_fingerprints
        response_text = self._extract_text(payload)
        if not response_text:
            visible_texts = [str(action.get("content") or "") for action in actions if action.get("kind") == "progress"]
            response_text = next((text for text in reversed(visible_texts) if text.strip()), "")
        if not response_text:
            raise OpenClawRuntimeError(f"openclaw_empty_output:{raw[:2000]}")
        usage = self._extract_usage(payload)
        after_snapshot = self._workspace_snapshot(delivery_workspace) if capture_workspace else {}
        file_changes = self._workspace_changes(before_snapshot, after_snapshot) if capture_workspace else []
        return {
            "id": payload.get("runId") or payload.get("id") or payload.get("sessionId") or agent_meta.get("sessionId"),
            "session_id": session_id,
            "model": str(model_config.get("model") or ""),
            "content": [{"type": "text", "text": response_text}],
            "usage": usage,
            "openclaw": {
                "runtime": "embedded-local",
                "agent_id": agent["id"],
                "session_key": session_key,
                "raw_status": payload.get("status") or "completed",
                "model": str(model_config.get("model") or ""),
                "model_tier": str(model_config.get("tier") or "medium"),
                "session_id": session_id,
                "session_file": str(session_file) if session_file else "",
                "workspace": str(workspace),
            },
            "actions": actions,
            "file_changes": file_changes,
        }

    @classmethod
    def _extract_text(cls, value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            parts = [cls._extract_text(item) for item in value]
            return "\n".join(item for item in parts if item).strip()
        if not isinstance(value, dict):
            return ""
        for key in ("text", "output_text", "reply", "response", "message", "content", "result", "payloads"):
            if key not in value:
                continue
            extracted = cls._extract_text(value[key])
            if extracted:
                return extracted
        return ""

    @classmethod
    def _extract_usage(cls, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            usage = value.get("usage")
            if isinstance(usage, dict):
                input_tokens = usage.get(
                    "input_tokens",
                    usage.get("inputTokens", usage.get("prompt_tokens", usage.get("input", 0))),
                )
                output_tokens = usage.get(
                    "output_tokens",
                    usage.get("outputTokens", usage.get("completion_tokens", usage.get("output", 0))),
                )
                return {"input_tokens": int(input_tokens or 0), "output_tokens": int(output_tokens or 0)}
            for nested in value.values():
                found = cls._extract_usage(nested)
                if found.get("input_tokens") or found.get("output_tokens"):
                    return found
        if isinstance(value, list):
            for nested in value:
                found = cls._extract_usage(nested)
                if found.get("input_tokens") or found.get("output_tokens"):
                    return found
        return {"input_tokens": 0, "output_tokens": 0}


openclaw_runtime = OpenClawRuntime()
