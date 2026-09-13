from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict, runtime_checkable


RuntimeErrorCategory = Literal[
    "configuration",
    "provider_auth",
    "provider_billing",
    "provider_rate_limit",
    "provider_failure",
    "timeout",
    "cancelled",
    "security",
    "invalid_output",
    "runtime_failure",
]


class RuntimeHealth(TypedDict, total=False):
    available: bool
    runtime: str
    mode: str
    version: str
    error: str
    state_root: str
    config_ready: bool


class RuntimeAction(TypedDict, total=False):
    kind: Literal["progress", "tool_call", "tool_result"]
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    output: str
    status: str
    is_error: bool
    exit_code: int | None
    cwd: str
    timestamp: str


class RuntimeMessageResult(TypedDict, total=False):
    id: str
    session_id: str
    model: str
    content: list[dict[str, Any]]
    usage: dict[str, int]
    actions: list[RuntimeAction]
    file_changes: list[dict[str, Any]]


RuntimeActionCallback = Callable[[RuntimeAction], Awaitable[None]]


def classify_runtime_error(message: str) -> tuple[RuntimeErrorCategory, bool]:
    normalized = str(message or "").lower()
    if "cancel" in normalized or "aborted" in normalized:
        return "cancelled", False
    if "timeout" in normalized or "timed out" in normalized:
        return "timeout", True
    if "insufficient balance" in normalized or "billing" in normalized or "resource package" in normalized:
        return "provider_billing", False
    if "http 401" in normalized or "http 403" in normalized or "status=401" in normalized or "status=403" in normalized or "reason=auth" in normalized or "unauthorized" in normalized or "forbidden" in normalized:
        return "provider_auth", False
    if "http 429" in normalized or "rate_limit" in normalized or "rate limit" in normalized:
        return "provider_rate_limit", True
    if "token_missing" in normalized or "config_missing" in normalized or "config_incomplete" in normalized or "not_found" in normalized:
        return "configuration", False
    if "path_escape" in normalized or "permission" in normalized or "not allowed" in normalized:
        return "security", False
    if "non_json" in normalized or "empty_output" in normalized or "invalid output" in normalized:
        return "invalid_output", True
    if "provider" in normalized or "llm request failed" in normalized:
        return "provider_failure", True
    return "runtime_failure", True


def public_runtime_error(error: BaseException | str) -> dict[str, Any]:
    """Build user-safe Runtime copy without transport traces or identities."""

    raw = str(error or "")
    normalized = raw.lower()
    if isinstance(error, AgentRuntimeError):
        category, retryable = error.category, error.retryable
        runtime = error.runtime
    else:
        category, retryable = classify_runtime_error(raw)
        runtime = "unknown"

    if "budget_exhausted:run_time_limit" in normalized:
        error_code = "run_time_budget_exhausted"
        message = "本次 Run 已达到当前运行时限。已完成节点、现场和产物均已保留；增加运行时间后可从未完成节点继续。"
        retryable = True
    elif "budget_exhausted:token_limit" in normalized:
        error_code = "run_token_budget_exhausted"
        message = "本次 Run 已达到 Token 预算上限。已完成节点、现场和产物均已保留。"
        retryable = False
    elif any(marker in normalized for marker in (
        "fetch failed", "connection error", "network connection error", "econnrefused",
        "econnreset", "enotfound", "etimedout", "provider-transport-fetch",
    )):
        error_code = "model_service_unreachable"
        category, retryable = "provider_failure", True
        message = "模型服务暂时无法连接。平台已完成自动重试但仍未恢复；可以稍后从当前节点重试，已完成节点和产物不会丢失。"
    elif category == "provider_auth":
        error_code = "model_credential_rejected"
        message = "模型服务拒绝了当前凭据。请检查“模型与凭据”配置后，从当前节点重试；页面不会显示或记录完整凭据。"
    elif category == "provider_billing":
        error_code = "model_quota_unavailable"
        message = "模型服务额度暂不可用。请确认账户额度或资源包后，从当前节点重试。"
    elif category == "provider_rate_limit":
        error_code = "model_rate_limited"
        message = "模型服务当前请求繁忙。平台已完成自动重试；可以稍后从当前节点继续。"
    elif category == "timeout":
        error_code = "model_request_timeout"
        message = "模型响应超时。平台已完成自动重试但本次仍未恢复；可以稍后从当前节点重试。"
    elif category == "configuration":
        error_code = "runtime_configuration_invalid"
        message = "执行底座配置不完整或不可用。请检查模型与运行环境配置后重试。"
    elif category == "security":
        error_code = "runtime_policy_blocked"
        message = "本次操作被执行底座的安全策略阻止。现场和已有产物已保留，请检查授权范围后重试。"
    elif category == "invalid_output":
        error_code = "model_output_invalid"
        message = "模型返回内容不完整或格式无效。平台已保留现场，可以从当前节点重新执行。"
    elif category == "cancelled":
        error_code = "runtime_cancelled"
        message = "本次执行已被中止，现场和已有产物仍然保留。"
    else:
        error_code = "runtime_execution_failed"
        message = "执行底座遇到异常，自动重试后仍未恢复。现场和已有产物已保留，可以从当前节点重试。"

    fingerprint = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
    return {
        "error_code": error_code,
        "error_detail": message,
        "error_category": category,
        "retryable": bool(retryable),
        "runtime": runtime,
        "diagnostic_id": f"diag-{fingerprint}",
    }


class AgentRuntimeError(RuntimeError):
    """Framework-neutral runtime failure surfaced to platform code."""

    def __init__(
        self,
        message: str,
        *,
        category: RuntimeErrorCategory | None = None,
        retryable: bool | None = None,
        runtime: str = "unknown",
        details: dict[str, Any] | None = None,
    ) -> None:
        inferred_category, inferred_retryable = classify_runtime_error(message)
        super().__init__(message)
        self.category = category or inferred_category
        self.retryable = inferred_retryable if retryable is None else retryable
        self.runtime = runtime
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "category": self.category,
            "retryable": self.retryable,
            "runtime": self.runtime,
            "details": self.details,
        }


@runtime_checkable
class AgentRuntimePort(Protocol):
    runtime_name: str
    supports_live_actions: bool

    def for_run(self, run_id: str, execution_root: str | Path | None = None) -> "AgentRuntimePort": ...
    def health(self) -> RuntimeHealth: ...
    def workspace_path(self, agent: dict[str, Any]) -> Path: ...

    def sync(
        self,
        agents: list[dict[str, Any]],
        memories_by_agent: dict[str, list[dict[str, Any]]],
        model_config: dict[str, Any],
        tool_enabled_agent_ids: set[str] | None = None,
        model_configs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...

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
        on_action: RuntimeActionCallback | None = None,
    ) -> RuntimeMessageResult: ...

    def publish_workspace_submission(
        self,
        *,
        agent: dict[str, Any],
        changes: list[dict[str, Any]],
        destination: str | Path,
    ) -> dict[str, Any]: ...

    def promote_workspace_tree(self, *, agent: dict[str, Any], destination: str | Path) -> list[dict[str, Any]]: ...


class FakeAgentRuntime:
    """Deterministic Runtime Port implementation for platform tests."""

    runtime_name = "fake"
    supports_live_actions = True

    def __init__(self, root: str | Path, *, scripted_results: list[RuntimeMessageResult | Exception] | None = None) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.scripted_results = list(scripted_results or [])
        self.synced: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []

    def for_run(self, run_id: str, execution_root: str | Path | None = None) -> "FakeAgentRuntime":
        root = Path(execution_root).resolve() / "tmp" / "fake-agents" if execution_root else self.root / "runs" / str(run_id)
        return FakeAgentRuntime(root, scripted_results=self.scripted_results)

    def health(self) -> RuntimeHealth:
        return {"available": True, "runtime": self.runtime_name, "mode": "deterministic", "version": "test", "state_root": str(self.root), "config_ready": True}

    def workspace_path(self, agent: dict[str, Any]) -> Path:
        workspace = (self.root / "workspaces" / str(agent.get("id") or "agent")).resolve()
        if not workspace.is_relative_to(self.root):
            raise AgentRuntimeError("fake_workspace_path_escape", category="security", retryable=False, runtime=self.runtime_name)
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def sync(
        self,
        agents: list[dict[str, Any]],
        memories_by_agent: dict[str, list[dict[str, Any]]],
        model_config: dict[str, Any],
        tool_enabled_agent_ids: set[str] | None = None,
        model_configs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        record = {
            "agents": [str(item.get("id") or "") for item in agents],
            "memory_agent_ids": sorted(memories_by_agent),
            "model": str(model_config.get("model") or ""),
            "tool_enabled_agent_ids": sorted(tool_enabled_agent_ids or set()),
            "models": [str(item.get("model") or "") for item in model_configs or []],
        }
        self.synced.append(record)
        return {"runtime": self.runtime_name, **record}

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
        on_action: RuntimeActionCallback | None = None,
    ) -> RuntimeMessageResult:
        self.messages.append({"agent_id": str(agent.get("id") or ""), "prompt": prompt, "session_key": session_key, "model": str(model_config.get("model") or "")})
        if not self.scripted_results:
            result: RuntimeMessageResult = {
                "id": f"fake:{len(self.messages)}",
                "session_id": session_key,
                "model": str(model_config.get("model") or "fake-model"),
                "content": [{"type": "text", "text": "FAKE_RUNTIME_OK"}],
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "actions": [],
                "file_changes": [],
            }
        else:
            scripted = self.scripted_results.pop(0)
            if isinstance(scripted, Exception):
                raise scripted
            result = scripted
        if on_action:
            for action in result.get("actions", []):
                await on_action(action)
                await asyncio.sleep(0)
        return result

    def publish_workspace_submission(
        self,
        *,
        agent: dict[str, Any],
        changes: list[dict[str, Any]],
        destination: str | Path,
    ) -> dict[str, Any]:
        return {"agent_id": str(agent.get("id") or ""), "root": str(Path(destination)), "file_count": len([item for item in changes if item.get("action") != "deleted"]), "changes": list(changes)}

    def promote_workspace_tree(self, *, agent: dict[str, Any], destination: str | Path) -> list[dict[str, Any]]:
        return []
