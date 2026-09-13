from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .agent_runtime import AgentRuntimeError, AgentRuntimePort, RuntimeHealth
from .claude_code_runtime import claude_code_runtime


class AgentRuntimeRegistry:
    """Stable platform entry point for registered Runtime Adapters."""

    def __init__(self, default_runtime: AgentRuntimePort) -> None:
        self._runtimes: dict[str, AgentRuntimePort] = {}
        self._default_name = ""
        self.register(default_runtime, default=True)

    @property
    def runtime_name(self) -> str:
        return self._default_name

    @property
    def supports_live_actions(self) -> bool:
        return self.default.supports_live_actions

    @property
    def default(self) -> AgentRuntimePort:
        return self._runtimes[self._default_name]

    def register(self, runtime: AgentRuntimePort, *, default: bool = False) -> None:
        name = str(runtime.runtime_name or "").strip()
        if not name:
            raise ValueError("agent_runtime_name_required")
        self._runtimes[name] = runtime
        if default or not self._default_name:
            self._default_name = name

    def get(self, name: str) -> AgentRuntimePort:
        try:
            return self._runtimes[name]
        except KeyError as exc:
            raise AgentRuntimeError("agent_runtime_not_found", category="configuration", retryable=False, details={"runtime": name}) from exc

    def for_run(self, run_id: str, execution_root: str | Path | None = None) -> AgentRuntimePort:
        if execution_root is None:
            return self.default.for_run(run_id)
        return self.default.for_run(run_id, execution_root)

    def health(self) -> RuntimeHealth:
        return self.default.health()

    def workspace_path(self, agent: dict[str, Any]) -> Path:
        return self.default.workspace_path(agent)

    def sync(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.default.sync(*args, **kwargs)


configured_runtime = os.getenv("JIANGHU_AGENT_RUNTIME", "claude_code").strip() or "claude_code"
if configured_runtime != "claude_code":
    raise AgentRuntimeError(
        "agent_runtime_fixed_to_claude_code",
        category="configuration",
        retryable=False,
        details={"configured_runtime": configured_runtime, "supported_runtime": "claude_code"},
    )
agent_runtime = AgentRuntimeRegistry(claude_code_runtime)


__all__ = ["AgentRuntimeError", "AgentRuntimeRegistry", "agent_runtime"]
