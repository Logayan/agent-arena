from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


RUN_BUDGET_START_EVENTS = {"run.started", "run.recovered", "run.resumed", "run.time_extended"}
RUN_BUDGET_STOP_EVENTS = {
    "run.pause_requested",
    "run.paused",
    "run.budget_exhausted",
    "run.completed",
    "run.failed",
    "run.cancelled",
    "run.revision_exhausted",
}


def configured_maximum_run_minutes() -> int:
    """Return the deployment ceiling for explicitly extended long-running runs."""
    raw = os.getenv("JIANGHU_MAX_RUN_MINUTES", "360").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 360
    return max(360, min(value, 1440))


def effective_run_minutes(base_minutes: int, extension_minutes: int) -> int:
    return min(max(1, base_minutes) + max(0, extension_minutes), configured_maximum_run_minutes())


def active_run_seconds(events: list[dict[str, Any]], *, now: datetime | None = None) -> float:
    """Calculate active run time without charging paused or intervention wait time.

    A pause request closes the current active interval immediately. The still-running
    agent turn remains bounded by its per-agent timeout, while operators can safely
    checkpoint or restart without silently consuming the whole run-level budget.
    """
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    active_since: datetime | None = None
    elapsed = 0.0
    for event in sorted(events, key=lambda item: int(item.get("sequence", 0) or 0)):
        event_type = str(event.get("type") or "")
        if event_type not in RUN_BUDGET_START_EVENTS | RUN_BUDGET_STOP_EVENTS:
            continue
        try:
            event_time = datetime.fromisoformat(str(event.get("created_at") or ""))
        except ValueError:
            continue
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
        else:
            event_time = event_time.astimezone(timezone.utc)
        if event_type in RUN_BUDGET_START_EVENTS:
            if active_since is None:
                active_since = event_time
            continue
        if active_since is not None:
            elapsed += max(0.0, (event_time - active_since).total_seconds())
            active_since = None
    if active_since is not None:
        elapsed += max(0.0, (current_time.astimezone(timezone.utc) - active_since).total_seconds())
    return elapsed


def active_execution_epoch_seconds(events: list[dict[str, Any]], *, now: datetime | None = None) -> float:
    """Return active time charged to the current execution/recovery epoch.

    Historical epochs remain available to ``active_run_seconds`` for audit and
    cost reporting, but a deliberate in-place recovery receives a fresh bounded
    execution window.  This prevents a recovered Run from exhausting its new
    window immediately because earlier failed epochs already consumed the
    original Run-level allowance.
    """
    ordered = sorted(events, key=lambda item: int(item.get("sequence", 0) or 0))
    boundary_index = 0
    for index, event in enumerate(ordered):
        if str(event.get("type") or "") in {"run.started", "run.recovered", "run.recovery_requested"}:
            boundary_index = index
    return active_run_seconds(ordered[boundary_index:], now=now)
