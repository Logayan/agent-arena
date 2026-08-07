from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .llm_client import LLMRequestError
from .openclaw_runtime import OpenClawRuntimeError, openclaw_runtime
from .platform_store import PlatformStore


class ArtifactValidationError(RuntimeError):
    pass


ENGINEERING_KEYWORDS = {
    "code", "coding", "implementation", "development", "develop", "build", "test", "testing",
    "deploy", "deployment", "frontend", "backend", "software delivery", "runnable", "软件开发", "代码", "开发实现",
    "编码", "自动化测试", "功能测试", "集成测试", "构建", "部署", "前端开发", "后端开发", "可运行",
}


def _safe_segment(value: object, fallback: str = "item") -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "")).strip("-_").lower()
    return normalized[:64] or fallback


def _is_engineering_node(node: dict[str, Any], agent: dict[str, Any] | None = None) -> bool:
    explicit = str(node.get("execution_mode") or node.get("delivery_mode") or "").lower()
    if explicit in {"code", "engineering", "implementation", "executable"}:
        return True
    if explicit in {"document", "analysis", "text"}:
        return False
    text = " ".join(
        str(value or "")
        for value in (
            node.get("key"), node.get("name"), node.get("purpose"), node.get("type"),
            (agent or {}).get("role"),
        )
    ).lower()
    return any(keyword in text for keyword in ENGINEERING_KEYWORDS)


def _is_test_command(command: str) -> bool:
    lowered = command.lower()
    return any(
        marker in lowered
        for marker in (
            "pytest", "unittest", "npm test", "npm run test", "pnpm test", "yarn test", "vitest", "jest",
            "go test", "cargo test", "mvn test", "gradle test", "dotnet test", "ctest", "playwright test",
            "测试", "test_", " test ",
        )
    )


def _code_manifest(root: Path) -> list[dict[str, Any]]:
    ignored = {".git", "node_modules", "dist", "build", "coverage", "__pycache__", ".pytest_cache", ".venv", "venv"}
    manifest: list[dict[str, Any]] = []
    if not root.is_dir():
        return manifest
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in ignored for part in relative.parts):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        manifest.append(
            {
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        )
    return manifest


def _text(response: dict[str, Any]) -> str:
    blocks = response.get("content", [])
    return "\n".join(
        str(block.get("text", "")) for block in blocks if isinstance(block, dict)
    ).strip()


def _preview(value: str, limit: int = 320) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else f"{compact[:limit].rstrip()}…"


def _extract_initiator_note(value: str) -> tuple[str, str]:
    """Split an agent-authored rationale summary from the public contribution.

    This is deliberately not a hidden chain-of-thought capture.  The model is
    asked to provide a concise, reviewable explanation of facts, trade-offs,
    uncertainty and verification steps.  The note is removed before any team
    contribution or message is shared with other agents.
    """
    matches = list(re.finditer(r"<initiator_note>\s*(.*?)\s*</initiator_note>", value, re.IGNORECASE | re.DOTALL))
    if not matches:
        return value.strip(), ""
    note = "\n\n".join(match.group(1).strip() for match in matches if match.group(1).strip())[:6000]
    public = re.sub(r"<initiator_note>\s*.*?\s*</initiator_note>", "", value, flags=re.IGNORECASE | re.DOTALL).strip()
    return public, note


def _legacy_team_knowledge(team: dict[str, Any]) -> str:
    documents: list[str] = []
    seen_content: set[str] = set()
    suffixes = {
        ".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".html", ".xml",
        ".py", ".js", ".ts", ".tsx", ".vue", ".sql", ".toml", ".ini", ".log",
    }
    for raw_path in team.get("knowledge_paths", [])[:8]:
        path = Path(str(raw_path)).expanduser()
        candidates = [path] if path.is_file() else ([item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in suffixes][:12] if path.is_dir() else [])
        for candidate in candidates:
            try:
                content = candidate.read_text(encoding="utf-8", errors="replace")[:12000]
            except OSError:
                continue
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if digest in seen_content:
                continue
            seen_content.add(digest)
            documents.append(f"## 来源：{candidate}\n{content}")
            if sum(len(item) for item in documents) >= 48000:
                return "\n\n".join(documents)[:48000]
    return "\n\n".join(documents)[:48000]


def _team_knowledge(store: PlatformStore, team: dict[str, Any], query: str, agent_id: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    try:
        retrieval = store.search_team_knowledge(str(team["id"]), query, limit=8, agent_id=agent_id)
    except ValueError:
        retrieval = {"results": []}
    results = retrieval.get("results", [])
    if not results:
        return _legacy_team_knowledge(team), []
    documents = []
    for result in results:
        documents.append(
            "\n".join(
                [
                    f"## 来源：{result.get('source_name', '组织知识')}（{result.get('locator', '片段')}）",
                    f"知识来源 ID：{result.get('source_id', '')}",
                    f"检索相关度：{float(result.get('score', 0)):.3f}",
                    str(result.get("content") or ""),
                ]
            )
        )
    return "\n\n".join(documents)[:48000], results


def _json_object(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _dependencies(workflow: dict[str, Any]) -> dict[str, set[str]]:
    nodes = workflow["definition"].get("nodes", [])
    keys = [str(node["key"]) for node in nodes]
    deps = {key: set() for key in keys}
    edges = workflow["definition"].get("edges", [])
    if not isinstance(edges, list) or not edges:
        # An edgeless DAG means every node is an independent parallel root.
        return deps
    for edge in edges:
        if isinstance(edge, (list, tuple)) and len(edge) == 2:
            source, target = str(edge[0]), str(edge[1])
            if source in deps and target in deps and source != target:
                deps[target].add(source)
    return deps


async def execute_platform_run(store: PlatformStore, run_id: str) -> None:
    run = store.get_run(run_id)
    if not run:
        return
    workflow = store.get_workflow(run["workflow_id"])
    if not workflow:
        store.update_run(run_id, status="failed", stage="workflow_not_found")
        return

    try:
        try:
            run_runtime = openclaw_runtime.for_run(run_id, run.get("workspace", {}).get("root"))
        except TypeError:
            # Keep lightweight test/adaptor runtimes compatible while the real
            # OpenClaw adapter uses the Run-scoped execution root.
            run_runtime = openclaw_runtime.for_run(run_id)
        model_config = store.get_active_model_config(include_secret=True)
        if not model_config:
            raise OpenClawRuntimeError("openclaw_model_config_missing")
        initial_run_status = str(run.get("status") or "draft")
        is_recovery = initial_run_status in {"running", "pause_requested", "paused"}
        tasks = run["tasks"]
        task_by_key = {str(task["node_key"]): task for task in tasks}
        node_def_by_key = {str(node["key"]): node for node in workflow["definition"].get("nodes", [])}
        dependencies = _dependencies(workflow)
        max_parallel = int(workflow["definition"].get("policies", {}).get("max_parallel_agents", 5) or 5)
        max_parallel = max(1, min(max_parallel, 5))
        policies = workflow["definition"].get("policies", {})
        max_run_minutes = int(policies.get("max_run_minutes", 60) or 60)
        max_total_tokens = int(policies.get("max_total_tokens", 0) or 0)
        started_at = time.monotonic()
        first_started_event = next(
            (event for event in run.get("events", []) if event.get("type") == "run.started"),
            None,
        )
        elapsed_before_invocation = 0.0
        if first_started_event:
            try:
                first_started_at = datetime.fromisoformat(str(first_started_event["created_at"]))
                if first_started_at.tzinfo is None:
                    first_started_at = first_started_at.replace(tzinfo=timezone.utc)
                elapsed_before_invocation = max(
                    0.0,
                    (datetime.now(timezone.utc) - first_started_at.astimezone(timezone.utc)).total_seconds(),
                )
            except (TypeError, ValueError):
                elapsed_before_invocation = 0.0
        node_semaphore = asyncio.Semaphore(max_parallel)
        llm_semaphore = asyncio.Semaphore(max_parallel)
        event_lock = asyncio.Lock()
        artifacts_by_key: dict[str, str] = {}
        completed: set[str] = set()
        latest_artifact_by_task: dict[str, dict[str, Any]] = {}
        for artifact in run.get("artifacts", []):
            task_id = str(artifact.get("task_id") or "")
            current = latest_artifact_by_task.get(task_id)
            if current is None or int(artifact.get("version", 0) or 0) > int(current.get("version", 0) or 0):
                latest_artifact_by_task[task_id] = artifact
        interrupted_node_keys: list[str] = []
        for task in tasks:
            node_key = str(task["node_key"])
            artifact = latest_artifact_by_task.get(str(task["id"]))
            if str(task.get("status")) == "completed" and artifact:
                completed.add(node_key)
                artifacts_by_key[node_key] = f"[{artifact['title']}]\n{str(artifact.get('content') or '')[:4000]}"
            elif str(task.get("status")) in {"running", "retrying"}:
                interrupted_node_keys.append(node_key)
                store.update_task(str(task["id"]), status="pending")
        pending = set(task_by_key) - completed
        total_tokens = int(run.get("token_count", 0) or 0)
        max_revision_rounds = int(policies.get("max_revision_rounds", policies.get("max_debate_rounds", 3)) or 3)
        max_revision_rounds = max(1, min(max_revision_rounds, 6))
        revision_counts: dict[str, int] = {}
        revision_feedback: dict[str, list[str]] = {}
        for event in run.get("events", []):
            if event.get("type") != "gate.rejected":
                continue
            payload = event.get("payload") or {}
            gate_key = str(payload.get("node_key") or "")
            if gate_key:
                revision_counts[gate_key] = max(
                    revision_counts.get(gate_key, 0),
                    int(payload.get("revision_round", 0) or 0),
                )
        for task in tasks:
            feedback = (task.get("output") or {}).get("feedback")
            if feedback and str(task["node_key"]) in pending:
                revision_feedback.setdefault(str(task["node_key"]), []).append(str(feedback))
        handled_rework_interventions: set[str] = {
            str(item["id"])
            for item in run.get("interventions", [])
            if item.get("kind") == "require_rework" and item.get("status") == "applied"
        }
        execution_epoch = 1 + sum(
            1 for event in run.get("events", []) if event.get("type") in {"run.started", "run.recovered"}
        )

        runtime_agents: dict[str, dict[str, Any]] = {}
        for task in tasks:
            if task.get("agent_id"):
                bound = store.get_agent(str(task["agent_id"]))
                if bound:
                    runtime_agents[bound["id"]] = bound
            if task.get("team_id"):
                team_snapshot = store.get_team(str(task["team_id"]))
                for member in (team_snapshot or {}).get("members", []):
                    runtime_agents[member["id"]] = member
        memories = {
            agent_id: store.list_agent_memories(agent_id, int(agent.get("memory_policy", {}).get("max_prompt_items", 8) or 8))
            for agent_id, agent in runtime_agents.items()
        }
        engineering_node_keys = {
            key
            for key, node in node_def_by_key.items()
            if _is_engineering_node(node, store.get_agent(str(node.get("agent_id") or "")))
            and str(node.get("type") or "") not in {"judge", "gate", "quality_gate"}
        }
        tool_enabled_agent_ids: set[str] = set()
        for key in engineering_node_keys:
            node = node_def_by_key[key]
            if node.get("agent_id"):
                tool_enabled_agent_ids.add(str(node["agent_id"]))
            tool_enabled_agent_ids.update(str(item) for item in node.get("participant_agent_ids", []) if item)
        try:
            runtime_sync = run_runtime.sync(
                list(runtime_agents.values()),
                memories,
                model_config,
                tool_enabled_agent_ids=tool_enabled_agent_ids,
            )
        except TypeError:
            runtime_sync = run_runtime.sync(list(runtime_agents.values()), memories, model_config)

        async def wait_for_control_boundary() -> None:
            while True:
                current = store.get_run(run_id)
                if not current or current["status"] == "cancelled":
                    raise asyncio.CancelledError
                if current["status"] == "pause_requested":
                    async with event_lock:
                        latest = store.get_run(run_id)
                        if latest and latest["status"] == "pause_requested":
                            store.update_run(run_id, status="paused")
                            store.append_run_event(
                                run_id,
                                "run.paused",
                                "intervention",
                                "江湖现场已经停手",
                                "所有未开始的新回合、公开通信、合议和节点切换均已阻断；正在进行的回合结果仍会留痕。",
                            )
                    continue
                if current["status"] == "paused":
                    await asyncio.sleep(0.5)
                    continue
                return

        async def relevant_interventions(task: dict[str, Any], actor: dict[str, Any] | None = None) -> list[dict[str, Any]]:
            await wait_for_control_boundary()
            actor_id = str((actor or {}).get("id") or "")
            relevant = [
                item
                for item in store.list_run_interventions(run_id)
                if (not item.get("task_id") or str(item["task_id"]) == str(task["id"]))
                and (not item.get("agent_id") or str(item["agent_id"]) == actor_id)
            ]
            queued = [item for item in relevant if item.get("status") == "queued"]
            if queued:
                applied = store.mark_run_interventions_applied([str(item["id"]) for item in queued])
                async with event_lock:
                    for item in applied:
                        store.append_run_event(
                            run_id,
                            "user.intervention.applied",
                            "intervention",
                            f"发起人意见已送达{actor.get('name') if actor else task['node_name']}",
                            str(item["content"]),
                            {
                                "intervention_id": item["id"],
                                "task_id": task["id"],
                                "node_key": task["node_key"],
                                "agent_id": actor_id or None,
                                "kind": item["kind"],
                                "content": item["content"],
                                "status": "applied",
                            },
                        )
                relevant = [
                    item
                    for item in store.list_run_interventions(run_id)
                    if (not item.get("task_id") or str(item["task_id"]) == str(task["id"]))
                    and (not item.get("agent_id") or str(item["agent_id"]) == actor_id)
                ]
            return relevant

        async with event_lock:
            recovered_progress = int((len(completed) / max(len(tasks), 1)) * 100)
            starting_progress = max(1, recovered_progress) if tasks else 0
            store.update_run(run_id, status="running", stage="executing", progress=starting_progress)
            store.append_run_event(
                run_id,
                "run.recovered" if is_recovery else "run.started",
                "system",
                "真实执行已从持久化现场恢复" if is_recovery else "真实执行已经开始",
                (
                    f"已保留 {len(completed)} 个完成节点及其最新产物；"
                    f"{len(interrupted_node_keys)} 个中断节点将在新隔离回合中重新行动，不会覆盖旧事件和产物。"
                    if is_recovery
                    else "工作流已启动，人物将使用独立身份与上下文调用真实模型完成节点。"
                ),
                {
                    "model": model_config["model"], "task_count": len(tasks), "max_parallel_agents": max_parallel,
                    "runtime": "openclaw", "runtime_mode": "embedded-local", "openclaw_sync": runtime_sync,
                    "execution_epoch": execution_epoch,
                    "completed_node_keys": sorted(completed),
                    "interrupted_node_keys": sorted(interrupted_node_keys),
                },
            )
            store.append_run_event(
                run_id,
                "openclaw.runtime.recovered" if is_recovery else "openclaw.runtime.ready",
                "system",
                "OpenClaw 已恢复人物运行现场" if is_recovery else "OpenClaw 已接管本次人物运行",
                f"已为 {len(runtime_agents)} 位人物重新装载隔离工作区、身份、长期 Memory 与启用的 Skills。"
                if is_recovery
                else f"已为 {len(runtime_agents)} 位人物装载隔离工作区、身份、长期 Memory 与启用的 Skills。",
                {"runtime": "openclaw", "mode": "embedded-local", "execution_epoch": execution_epoch, **runtime_sync},
            )

        async def execute_node(
            task: dict[str, Any],
            prior: list[str],
            node_attempt: int = 1,
        ) -> tuple[str, int, dict[str, Any], dict[str, Any] | None]:
            async with node_semaphore:
                node_key = str(task["node_key"])
                node_definition = node_def_by_key.get(node_key, {})
                agent = store.get_agent(str(task.get("agent_id")))
                if not agent:
                    raise RuntimeError(f"agent_not_found:{task.get('agent_id')}")
                team = store.get_team(str(task.get("team_id"))) if task.get("team_id") else None
                knowledge_query = "\n".join(
                    [
                        str(run.get("task_input") or ""),
                        str(task.get("node_name") or ""),
                        str(node_definition.get("purpose") or ""),
                    ]
                )
                loop_round = 1 + sum(1 for item in revision_feedback.get(node_key, []) if item)
                feedback_text = "\n".join(f"- {item}" for item in revision_feedback.get(node_key, []))
                is_engineering = node_key in engineering_node_keys
                node_runtime_responses: list[dict[str, Any]] = []
                store.update_task(
                    task["id"],
                    status="running",
                    input_data={
                        "task": run["task_input"], "previous_artifacts": prior, "node_attempt": node_attempt,
                        "loop_round": loop_round, "revision_feedback": revision_feedback.get(node_key, []),
                    },
                )
                async with event_lock:
                    store.update_run(run_id, stage=task["node_name"])
                    store.append_run_event(
                        run_id,
                        "task.started",
                        "execution",
                        f"“{task['node_name']}”开始执行",
                        f"组织“{team['name']}”正在负责这个节点。" if team else f"人物“{agent['name']}”正在负责这个节点。",
                        {
                            "task_id": task["id"],
                            "node_key": node_key,
                            "node_attempt": node_attempt,
                            "loop_round": loop_round,
                            "agent_id": agent["id"],
                            "agent_role": agent["role"],
                            "team_id": team["id"] if team else None,
                        },
                    )
                async def runtime_call(
                    actor: dict[str, Any],
                    prompt: str,
                    phase: str,
                    suffix: str,
                    *,
                    promote_files: bool = False,
                    capture_initiator_note: bool = False,
                ) -> dict[str, Any]:
                    interventions = await relevant_interventions(task, actor)
                    intervention_text = "\n".join(
                        f"- [{item['kind']}] {item['content']}" for item in interventions
                    ) or "无"
                    effective_prompt = (
                        f"{prompt}\n\n发起人在本次现场已经公开补充的意见（必须执行并说明如何处理）：\n{intervention_text}"
                    )
                    if is_engineering:
                        delivery_dir = run_runtime.workspace_path(actor) / "delivery"
                        effective_prompt += (
                            "\n\n这是工程交付节点，不能只写说明文档或声称已经完成。"
                            f"必须使用 OpenClaw 文件与命令工具在 `{delivery_dir}` 内创建或修改真实项目文件，"
                            "`delivery` 目录本身就是最终下载包的项目根目录；所有构建、启动和测试命令必须把该目录设为 workdir，"
                            "不得依赖它的父目录、不得把 delivery 当作包名导入。运行构建或自动化测试，失败后修复并重跑。"
                            "最终公开回答必须列出文件、命令、workdir、退出码、测试结果和遗留风险。"
                            "不得修改 delivery 目录之外的用户文件，不得读取或输出环境变量、Token、密钥。"
                        )
                    if capture_initiator_note:
                        effective_prompt += (
                            "\n\n在最终公开交付正文之后，另附一个仅供发起人查看的行动说明，格式必须是：\n"
                            "<initiator_note>\n"
                            "事实依据：你实际采用了哪些输入、证据或测试结果。\n"
                            "关键取舍：最终选择了什么，并简述未采用方案。\n"
                            "不确定性：哪些地方仍需核验。\n"
                            "下一步验证：建议发起人如何复查。\n"
                            "</initiator_note>\n"
                            "这不是隐藏思维链，不要输出逐步内心推理、草稿或模型内部状态。"
                            "平台会在分享给其他人物前剥离该段，只保存在发起人私享审计区。"
                        )
                    session_key_base = (
                        f"agent:{actor['id']}:{run_id}-{node_key}-epoch{execution_epoch}"
                        f"-loop{loop_round}-attempt{node_attempt}-{suffix}"
                    )
                    session_key = f"{session_key_base}-agent-attempt1"
                    tool_calls_seen: dict[str, dict[str, Any]] = {}

                    async def record_public_action(action: dict[str, Any]) -> None:
                        kind = str(action.get("kind") or "")
                        common = {
                            "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                            "phase": phase, "session_key": session_key,
                        }
                        async with event_lock:
                            if kind == "progress" and action.get("content"):
                                store.append_run_event(
                                    run_id, "agent.action.progress", "execution",
                                    f"{actor['name']}报告了行动进度", str(action["content"]),
                                    {**common, "content": action["content"]},
                                )
                            elif kind == "tool_call":
                                tool_calls_seen[str(action.get("tool_call_id") or "")] = action
                                tool_name = str(action.get("tool_name") or "unknown")
                                store.append_run_event(
                                    run_id, "agent.tool.started", "tool",
                                    f"{actor['name']}调用 {tool_name}",
                                    str(action.get("arguments_preview") or ""),
                                    {**common, **action},
                                )
                                if tool_name in {"exec", "process"}:
                                    command = str((action.get("arguments") or {}).get("command") or "")
                                    store.append_run_event(
                                        run_id, "agent.command.started", "tool",
                                        f"{actor['name']}开始执行命令", command,
                                        {**common, "tool_call_id": action.get("tool_call_id"), "command": command},
                                    )
                                    if _is_test_command(command):
                                        store.append_run_event(
                                            run_id, "agent.test.started", "validation",
                                            f"{actor['name']}开始运行测试", command,
                                            {**common, "tool_call_id": action.get("tool_call_id"), "command": command},
                                        )
                            elif kind == "tool_result":
                                tool_name = str(action.get("tool_name") or "unknown")
                                store.append_run_event(
                                    run_id, "agent.tool.completed", "tool",
                                    f"{actor['name']}的 {tool_name} 已返回",
                                    str(action.get("output") or action.get("status") or ""),
                                    {**common, **action},
                                )
                                if tool_name in {"exec", "process"}:
                                    call = tool_calls_seen.get(str(action.get("tool_call_id") or ""), {})
                                    command = str((call.get("arguments") or {}).get("command") or "")
                                    store.append_run_event(
                                        run_id, "agent.command.completed", "tool",
                                        f"{actor['name']}的命令{'成功' if action.get('exit_code') == 0 and not action.get('is_error') else '结束'}",
                                        str(action.get("output") or ""),
                                        {**common, "command": command, **action},
                                    )
                                    if _is_test_command(command):
                                        store.append_run_event(
                                            run_id, "agent.test.completed", "validation",
                                            f"{actor['name']}的测试{'通过' if action.get('exit_code') == 0 and not action.get('is_error') else '未通过'}",
                                            str(action.get("output") or ""),
                                            {
                                                **common, "command": command,
                                                "passed": action.get("exit_code") == 0 and not action.get("is_error"), **action,
                                            },
                                        )
                    async with event_lock:
                        store.append_run_event(
                            run_id,
                            "agent.context.prepared",
                            "collaboration",
                            f"{actor['name']}已完成行动前整备",
                            f"已装载节点目标、{len(prior)} 份上游正式产物、获准知识、返工意见和 {len(interventions)} 条用户现场意见。",
                            {
                                "task_id": task["id"],
                                "node_key": node_key,
                                "agent_id": actor["id"],
                                "phase": phase,
                                "upstream_artifacts": prior,
                                "revision_feedback": revision_feedback.get(node_key, []),
                                "interventions": interventions,
                                "context_isolation": "private_agent_session_with_public_dossier",
                                "private_chain_of_thought_exposed": False,
                            },
                        )
                        store.append_run_event(
                            run_id,
                            "agent.action.started",
                            "execution",
                            f"{actor['name']}开始{phase}",
                            "平台记录公开进度、工具、文件、命令、测试与最终提交；原始隐藏思维不采集，人物主动提供的行动依据与决策摘要仅供发起人查看。",
                            {
                                "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                "phase": phase, "session_key": session_key, "engineering": is_engineering,
                            },
                        )
                        store.append_run_event(
                            run_id,
                            "openclaw.turn.started",
                            "execution",
                            f"{actor['name']} 的 OpenClaw 回合已启动",
                            f"正在装载独立身份、长期 Memory、Skills 与获准知识，执行阶段：{phase}。",
                            {
                                "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                "phase": phase, "session_key": session_key, "runtime": "openclaw",
                            },
                        )
                    max_agent_attempts = 2
                    response: dict[str, Any] | None = None
                    for agent_attempt in range(1, max_agent_attempts + 1):
                        session_key = f"{session_key_base}-agent-attempt{agent_attempt}"
                        tool_calls_seen.clear()
                        message_arguments: dict[str, Any] = {
                            "agent": actor,
                            "prompt": effective_prompt,
                            "session_key": session_key,
                            "model_config": model_config,
                            "timeout_seconds": min(600, max_run_minutes * 60),
                        }
                        if is_engineering:
                            message_arguments.update(
                                {
                                    "seed_directory": run.get("workspace", {}).get("code"),
                                    "capture_workspace": True,
                                }
                            )
                        if getattr(run_runtime, "supports_live_actions", False):
                            message_arguments["on_action"] = record_public_action
                        try:
                            async with llm_semaphore:
                                response = await run_runtime.message(**message_arguments)
                            break
                        except (LLMRequestError, OpenClawRuntimeError) as exc:
                            is_final_attempt = agent_attempt >= max_agent_attempts
                            async with event_lock:
                                store.append_run_event(
                                    run_id,
                                    "agent.action.failed" if is_final_attempt else "agent.action.retrying",
                                    "execution",
                                    (
                                        f"{actor['name']}自动重试后仍未完成{phase}"
                                        if is_final_attempt else f"{actor['name']}将重新尝试{phase}"
                                    ),
                                    (
                                        f"人物级自动重试已达到 {max_agent_attempts} 次上限；最终原因：{exc}。"
                                        if is_final_attempt else
                                        f"本次隔离回合失败，平台将在 1 秒后为该人物建立新的独立回合。这是第 {agent_attempt + 1}/{max_agent_attempts} 次人物尝试。原因：{exc}"
                                    ),
                                    {
                                        "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                        "phase": phase, "session_key": session_key, "attempt": agent_attempt,
                                        "next_attempt": None if is_final_attempt else agent_attempt + 1,
                                        "max_attempts": max_agent_attempts, "delay_seconds": 0 if is_final_attempt else 1,
                                        "error_type": type(exc).__name__, "error_detail": str(exc),
                                        "manual_retry_scope": "node_with_agent_context_reset",
                                    },
                                )
                            if is_final_attempt:
                                raise
                            await asyncio.sleep(1)
                    if response is None:
                        raise RuntimeError(f"agent_action_returned_no_response:{actor['id']}")
                    if capture_initiator_note:
                        public_text, initiator_note = _extract_initiator_note(_text(response))
                        response["content"] = [{"type": "text", "text": public_text}]
                        response["initiator_note"] = initiator_note
                        if initiator_note:
                            async with event_lock:
                                store.append_run_event(
                                    run_id,
                                    "agent.rationale.submitted",
                                    "private_audit",
                                    f"{actor['name']}向发起人提交行动依据",
                                    "该摘要只进入发起人私享审计区，不会写入团队公共卷宗或注入其他 Agent。",
                                    {
                                        "task_id": task["id"],
                                        "node_key": node_key,
                                        "agent_id": actor["id"],
                                        "phase": phase,
                                        "session_key": session_key,
                                        "visibility": "initiator_only",
                                        "share_with_agents": False,
                                        "content": initiator_note,
                                        "raw_chain_of_thought_collected": False,
                                    },
                                )
                    workspace_changes = list(response.get("file_changes") or [])
                    changes = workspace_changes
                    if is_engineering and promote_files:
                        if hasattr(run_runtime, "promote_workspace_tree"):
                            changes = run_runtime.promote_workspace_tree(
                                agent=actor,
                                destination=run["workspace"]["code"],
                            )
                        elif workspace_changes:
                            changes = run_runtime.promote_workspace_changes(
                                agent=actor,
                                changes=workspace_changes,
                                destination=run["workspace"]["code"],
                            )
                    response["workspace_file_changes"] = workspace_changes
                    response["recorded_file_changes"] = changes
                    response["actor_id"] = actor["id"]
                    response["delivery_root"] = (
                        str(run_runtime.workspace_path(actor) / "delivery") if is_engineering else ""
                    )
                    response["files_promoted"] = bool(is_engineering and promote_files)
                    actions = list(response.get("actions") or [])
                    for action in actions:
                        if not action.get("live_emitted"):
                            await record_public_action(action)
                    async with event_lock:
                        for change in changes:
                            action_name = str(change.get("action") or "modified")
                            store.append_run_event(
                                run_id, f"agent.file.{action_name}", "artifact",
                                f"{actor['name']}{'新增' if action_name == 'created' else ('删除' if action_name == 'deleted' else '修改')}文件",
                                str(change.get("path") or ""),
                                {
                                    "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                    "phase": phase, **change,
                                },
                            )
                        store.append_run_event(
                            run_id,
                            "openclaw.turn.completed",
                            "execution",
                            f"{actor['name']} 的 OpenClaw 回合已完成",
                            f"{phase} 已返回公开结果；原始隐藏思维未采集，发起人行动说明与团队公共内容保持隔离。",
                            {
                                "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                "phase": phase, "session_key": session_key, "usage": response.get("usage", {}),
                                "runtime": response.get("openclaw", {}),
                                "action_count": len(actions),
                                "file_change_count": len(changes),
                            },
                        )
                        submitted_text = _text(response)
                        store.append_run_event(
                            run_id,
                            "agent.action.submitted",
                            "collaboration",
                            f"{actor['name']}已提交{phase}成果",
                            _preview(submitted_text),
                            {
                                "task_id": task["id"], "node_key": node_key, "agent_id": actor["id"],
                                "phase": phase, "session_key": session_key, "content": submitted_text,
                                "usage": response.get("usage", {}), "file_changes": changes,
                            },
                        )
                    node_runtime_responses.append(response)
                    return response

                base_prompt = (
                    "你正在江湖 Online 中执行一个正式生产节点。直接交付可审查成果，不要暴露私有思维链。"
                    "明确区分事实、假设、决定、证据和待解决风险；需要代码时必须给出可运行实现或明确文件内容，不能只承诺稍后实现。\n\n"
                    f"用户委托：\n{run['task_input']}\n\n"
                    f"当前节点：{task['node_name']}\n"
                    f"节点目的：{node_definition.get('purpose', task.get('node_name'))}\n\n"
                    f"上游正式产物：\n{'\n'.join(prior) or '无'}\n\n"
                    f"本轮定向返工意见：\n{feedback_text or '无；这是首次提交或上轮已经通过。'}"
                )
                is_judge = str(node_definition.get("type") or "") in {"judge", "gate", "quality_gate"} or any(
                    keyword in str(agent.get("role") or "") for keyword in ("裁判", "验收", "仲裁")
                )
                memory_entries: list[tuple[dict[str, Any], str]] = []
                decision: dict[str, Any] | None = None
                if is_judge:
                    judge_knowledge, judge_matches = _team_knowledge(store, team, knowledge_query, agent["id"]) if team else ("", [])
                    allowed_targets = sorted(dependencies.get(node_key, set()))
                    judge_prompt = (
                        f"{base_prompt}\n\n你是独立裁判。你没有参与候选产物创作，必须使用独立身份、独立会话和独立 Prompt。"
                        "只返回 JSON 对象，不要返回 Markdown 围栏。\n"
                        "Schema: {\"verdict\":\"pass|revise\",\"score\":0-100,\"summary\":\"裁判结论\","
                        "\"feedback\":\"可执行修改意见\",\"target_node_keys\":[\"应返工的上游节点 key\"],"
                        "\"acceptance_evidence\":[\"证据\"],\"remaining_risks\":[\"风险\"]}.\n"
                        f"允许定向打回的直接责任节点：{allowed_targets or ['无']}。verdict=revise 时至少选择一个允许的节点。\n\n"
                        f"获准知识：\n{judge_knowledge or '未检索到相关组织知识。'}"
                    )
                    response = await runtime_call(agent, judge_prompt, "独立裁决", "judge")
                    raw_content = _text(response)
                    parsed = _json_object(raw_content)
                    if not parsed or str(parsed.get("verdict")) not in {"pass", "revise"}:
                        raise RuntimeError("judge_output_contract_invalid")
                    targets = [str(item) for item in parsed.get("target_node_keys", []) if str(item) in allowed_targets]
                    if parsed["verdict"] == "revise" and not targets:
                        targets = allowed_targets
                    decision = {**parsed, "target_node_keys": targets}
                    content = "\n".join(
                        [
                            "# 独立裁判结论",
                            "",
                            f"- 结论：{'通过' if parsed['verdict'] == 'pass' else '退回修订'}",
                            f"- 评分：{parsed.get('score', '未给出')}",
                            f"- 摘要：{parsed.get('summary', '')}",
                            f"- 修改意见：{parsed.get('feedback', '')}",
                            f"- 责任节点：{'、'.join(targets) or '无'}",
                            "",
                            "## 验收证据",
                            *[f"- {item}" for item in parsed.get("acceptance_evidence", [])],
                            "",
                            "## 剩余风险",
                            *[f"- {item}" for item in parsed.get("remaining_risks", [])],
                        ]
                    )
                    usage = response.get("usage") or {}
                    memory_entries.append((agent, content))
                    if judge_matches:
                        async with event_lock:
                            store.append_run_event(
                                run_id, "knowledge.retrieved", "knowledge", f"{agent['name']}已独立检索裁决知识",
                                f"裁判只获取了自身获准的 {len(judge_matches)} 个知识片段。",
                                {"task_id": task["id"], "node_key": node_key, "agent_id": agent["id"], "matches": judge_matches},
                            )
                elif team:
                    selected_ids = {str(item) for item in node_definition.get("participant_agent_ids", [])}
                    participating_members = [member for member in team["members"] if member["id"] in selected_ids]
                    if not selected_ids:
                        participating_members = [member for member in team["members"] if member["id"] == agent["id"]]
                    if not participating_members:
                        raise RuntimeError(f"workflow_node_has_no_team_participants:{node_key}")
                    async def contribute(member: dict[str, Any]) -> tuple[dict[str, Any], str]:
                        member_knowledge, member_matches = _team_knowledge(store, team, knowledge_query, member["id"])
                        async with event_lock:
                            store.append_run_event(
                                run_id, "team.member.started", "collaboration",
                                f"{member['name']}开始参与“{task['node_name']}”",
                                f"{member['name']}正以“{member['role']}”身份独立形成自己的贡献。",
                                {
                                    "task_id": task["id"], "node_key": node_key, "team_id": team["id"],
                                    "agent_id": member["id"], "member_role": member["member_role"],
                                    "context_isolation": "private_initial_session",
                                    "memory_count": member.get("memory_count", 0),
                                    "skills": [skill.get("name") for skill in member.get("skills", []) if skill.get("enabled", True)],
                                },
                            )
                            if member_matches:
                                store.append_run_event(
                                    run_id, "knowledge.retrieved", "knowledge", f"{member['name']}已检索获准知识",
                                    f"本人物获得 {len(member_matches)} 个相关片段；其他人物的私有知识不会注入此会话。",
                                    {
                                        "task_id": task["id"], "node_key": node_key, "team_id": team["id"], "agent_id": member["id"],
                                        "matches": [
                                            {"source_id": item.get("source_id"), "source_name": item.get("source_name"), "locator": item.get("locator"), "score": item.get("score")}
                                            for item in member_matches
                                        ],
                                    },
                                )
                        member_prompt = (
                            f"{base_prompt}\n\n你是“{team['name']}”中的“{member['name']}”，职业身份为“{member['role']}”。"
                            f"组织职责：{member['responsibility']}。你必须先在隔离上下文中独立形成意见，此时看不到其他人物的答案。\n\n"
                            f"获准知识（引用时注明文件与章节）：\n{member_knowledge or '未检索到相关知识。'}\n\n"
                            "提交你的独立、可核验贡献；必要时质疑任务或上游产物中的薄弱假设。"
                        )
                        member_response = await runtime_call(
                            member,
                            member_prompt,
                            "隔离独立贡献",
                            "independent",
                            promote_files=is_engineering and len(participating_members) == 1,
                            capture_initiator_note=True,
                        )
                        member_text = _text(member_response)
                        if not member_text:
                            raise RuntimeError(f"empty_team_member_output:{member['name']}")
                        async with event_lock:
                            store.append_run_event(
                                run_id, "team.member.completed", "collaboration",
                                f"{member['name']}已提交独立贡献",
                                f"公开贡献：{_preview(member_text)}",
                                {
                                    "task_id": task["id"],
                                    "node_key": node_key,
                                    "team_id": team["id"],
                                    "agent_id": member["id"],
                                    "contribution_preview": _preview(member_text),
                                    "contribution": member_text,
                                    "usage": member_response.get("usage", {}),
                                    "file_changes": member_response.get("recorded_file_changes", []),
                                },
                            )
                        return member_response, member_text

                    member_results = await asyncio.gather(*(contribute(member) for member in participating_members))
                    member_usage = [item[0].get("usage") or {} for item in member_results]
                    memory_entries.extend((member, text) for member, (_, text) in zip(participating_members, member_results))
                    lead = next((member for member in participating_members if member["id"] == agent["id"]), participating_members[0])
                    async with event_lock:
                        store.append_run_event(
                            run_id,
                            "team.dossier.published",
                            "collaboration",
                            f"“{task['node_name']}”独立贡献已写入公共卷宗",
                            f"{len(participating_members)} 位人物的独立提交现已相互可见；私有会话、私有 Memory 与思维链仍保持隔离。",
                            {
                                "task_id": task["id"],
                                "node_key": node_key,
                                "team_id": team["id"],
                                "agent_id": lead["id"],
                                "participant_agent_ids": [member["id"] for member in participating_members],
                                "participant_names": [member["name"] for member in participating_members],
                                "contribution_count": len(member_results),
                                "shared_fields": ["公开贡献", "引用来源", "文件变更清单", "用户现场意见"],
                                "private_fields_excluded": ["私有思维链", "私有 Memory", "私有会话原文"],
                            },
                        )
                    engineering_submissions: list[dict[str, Any]] = []
                    if is_engineering and len(participating_members) > 1 and hasattr(run_runtime, "publish_workspace_submission"):
                        collaboration_root = (
                            run_runtime.workspace_path(lead)
                            / "collaboration"
                            / _safe_segment(node_key)
                            / f"loop-{loop_round}-attempt-{node_attempt}"
                        )
                        for member, (member_response, _) in zip(participating_members, member_results):
                            submission = run_runtime.publish_workspace_submission(
                                agent=member,
                                changes=list(member_response.get("workspace_file_changes") or member_response.get("recorded_file_changes") or []),
                                destination=collaboration_root / _safe_segment(str(member["id"])),
                            )
                            engineering_submissions.append(submission)
                            async with event_lock:
                                store.append_run_event(
                                    run_id,
                                    "engineering.submission.published",
                                    "artifact",
                                    f"{member['name']}已公开工程提交",
                                    (
                                        f"已将 {submission.get('file_count', 0)} 个真实文件和变更清单发布到负责人可读取的节点协作区。"
                                        if submission.get("file_count")
                                        else "本次公开提交没有形成文件变更，文字意见仍已进入公共卷宗。"
                                    ),
                                    {
                                        "task_id": task["id"],
                                        "node_key": node_key,
                                        "team_id": team["id"],
                                        "agent_id": member["id"],
                                        "lead_agent_id": lead["id"],
                                        **submission,
                                    },
                                )
                    if len(participating_members) == 1:
                        response, content = member_results[0]
                        usage = response.get("usage") or {}
                    else:
                        contribution_text = "\n\n".join(
                            f"## {member['name']} ({member['role']}, {member['member_role']})\n{text}"
                            for member, (_, text) in zip(participating_members, member_results)
                        )
                        public_messages: list[dict[str, Any]] = []
                        default_rounds = 2 if team.get("operating_mode") in {"debate", "red_team"} else 1
                        message_rounds = int(node_definition.get("communication_rounds", default_rounds) or default_rounds)
                        message_rounds = max(1, min(message_rounds, int(policies.get("max_debate_rounds", 3) or 3)))
                        for message_round in range(1, message_rounds + 1):
                            transcript = "\n".join(
                                f"第 {item['round']} 轮 {item['from_name']} → {item['to_name']} [{item['message_type']}]：{item['content']}"
                                for item in public_messages
                            ) or "尚无公开消息。"
                            async with event_lock:
                                store.append_run_event(
                                    run_id,
                                    "team.communication.round.started",
                                    "collaboration",
                                    f"团队公开议事第 {message_round}/{message_rounds} 轮开始",
                                    "每位人物只依据公共卷宗和已经公开的消息发言，仍不能读取他人的私有上下文。",
                                    {
                                        "task_id": task["id"], "node_key": node_key, "team_id": team["id"],
                                        "agent_id": lead["id"], "round": message_round, "total_rounds": message_rounds,
                                        "visible_message_count": len(public_messages),
                                    },
                                )
                            async def communicate(member: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
                                candidates = [item for item in participating_members if item["id"] != member["id"]]
                                prompt = (
                                    f"你已完成自己的独立意见。现在进入受控公开通信第 {message_round}/{message_rounds} 轮。\n\n"
                                    f"所有独立贡献：\n{contribution_text}\n\n已有公开消息：\n{transcript}\n\n"
                                    f"你是 {member['name']}。只返回 JSON：{{\"to_agent_id\":\"目标人物ID\","
                                    "\"message_type\":\"question|challenge|reply|support\",\"content\":\"一条具体公开消息\"}}。"
                                    f"可选择目标：{[{ 'id': item['id'], 'name': item['name'], 'role': item['role']} for item in candidates]}。"
                                    "不得写私有思维链，不得假装已读取其他人物的私有 Memory。"
                                )
                                response = await runtime_call(member, prompt, f"公开通信第 {message_round} 轮", f"message-{message_round}")
                                parsed = _json_object(_text(response)) or {}
                                target_id = str(parsed.get("to_agent_id") or (candidates[0]["id"] if candidates else member["id"]))
                                if target_id not in {item["id"] for item in candidates}:
                                    target_id = candidates[0]["id"] if candidates else member["id"]
                                target = next((item for item in participating_members if item["id"] == target_id), member)
                                message = {
                                    "round": message_round,
                                    "from_agent_id": member["id"], "from_name": member["name"],
                                    "to_agent_id": target_id, "to_name": target["name"],
                                    "message_type": str(parsed.get("message_type") or "challenge"),
                                    "content": str(parsed.get("content") or _preview(_text(response))),
                                }
                                return response, message
                            round_results = await asyncio.gather(*(communicate(member) for member in participating_members))
                            for response_item, message in round_results:
                                public_messages.append(message)
                                member_usage.append(response_item.get("usage") or {})
                                async with event_lock:
                                    store.append_run_event(
                                        run_id, "agent.message.sent", "collaboration",
                                        f"{message['from_name']}向{message['to_name']}发出{message['message_type']}",
                                        message["content"],
                                        {"task_id": task["id"], "node_key": node_key, "team_id": team["id"], **message},
                                    )
                            async with event_lock:
                                store.append_run_event(
                                    run_id,
                                    "team.communication.round.completed",
                                    "collaboration",
                                    f"团队公开议事第 {message_round}/{message_rounds} 轮完成",
                                    f"本轮新增 {len(round_results)} 条定向公开消息，现有公共消息共 {len(public_messages)} 条。",
                                    {
                                        "task_id": task["id"], "node_key": node_key, "team_id": team["id"],
                                        "agent_id": lead["id"], "round": message_round, "total_rounds": message_rounds,
                                        "round_message_count": len(round_results), "message_count": len(public_messages),
                                    },
                                )
                        public_transcript = "\n".join(
                            f"第 {item['round']} 轮 {item['from_name']} → {item['to_name']} [{item['message_type']}]：{item['content']}"
                            for item in public_messages
                        )
                        engineering_submission_text = "\n".join(
                            f"- {item.get('agent_name')}：{item.get('manifest')}（{item.get('file_count', 0)} 个文件）"
                            for item in engineering_submissions
                        ) or "无独立工程文件提交。"
                        synthesis_prompt = (
                            f"{base_prompt}\n\n团队独立贡献：\n{contribution_text}\n\n公开通信记录：\n{public_transcript}\n\n"
                            + (
                                f"公开工程提交区：\n{engineering_submission_text}\n\n"
                                "这些目录只包含各人物主动公开的文件与 manifest，不包含私有会话或 Memory。"
                                "你必须逐份检查、决定采用或拒绝，并把最终可用实现合并进自己的 delivery 项目根目录；"
                                "随后必须在该 delivery 目录运行构建和自动化测试。\n\n"
                                if is_engineering else ""
                            )
                            + "作为本节点负责人形成正式产物。必须保留实质分歧、说明最终决定和未解决风险，不能把冲突静默平均。"
                        )
                        async with event_lock:
                            store.append_run_event(
                                run_id,
                                "team.synthesis.started",
                                "collaboration",
                                f"{lead['name']}开始整合团队正式交付",
                                (
                                    f"负责人将检查 {len(engineering_submissions)} 份公开工程提交，完成合并、测试和正式交付。"
                                    if is_engineering
                                    else "负责人将依据独立贡献与公开议事记录形成正式产物，并保留分歧和风险。"
                                ),
                                {
                                    "task_id": task["id"], "node_key": node_key, "team_id": team["id"],
                                    "agent_id": lead["id"], "submission_count": len(engineering_submissions),
                                    "message_count": len(public_messages),
                                },
                            )
                        response = await runtime_call(
                            lead,
                            synthesis_prompt,
                            "团队合议与正式提交",
                            "synthesis",
                            promote_files=is_engineering,
                            capture_initiator_note=True,
                        )
                        content = _text(response)
                        synthesis_usage = response.get("usage") or {}
                        usage = {
                            "input_tokens": int(synthesis_usage.get("input_tokens", 0) or 0) + sum(int(item.get("input_tokens", 0) or 0) for item in member_usage),
                            "output_tokens": int(synthesis_usage.get("output_tokens", 0) or 0) + sum(int(item.get("output_tokens", 0) or 0) for item in member_usage),
                        }
                    async with event_lock:
                        store.append_run_event(
                            run_id, "team.synthesis.completed", "collaboration",
                            f"{team['name']}已完成团队合议",
                            f"团队已形成正式意见：{_preview(content)}",
                            {
                                "task_id": task["id"],
                                "node_key": node_key,
                                "team_id": team["id"],
                                "agent_id": agent["id"],
                                "contribution_preview": _preview(content),
                                "content": content,
                                "member_count": len(participating_members),
                                "message_count": len(public_messages) if len(participating_members) > 1 else 0,
                                "usage": usage,
                            },
                        )
                else:
                    response = await runtime_call(
                        agent,
                        f"{base_prompt}\n\n你是固定绑定人物“{agent['name']}”，职业身份为“{agent['role']}”。"
                        "请保持自身立场，直接提交可供下游使用的正式产物。",
                        "个人节点交付",
                        "delivery",
                        promote_files=is_engineering,
                        capture_initiator_note=True,
                    )
                    content = _text(response)
                    usage = response.get("usage") or {}
                    memory_entries.append((agent, content))
                if not content:
                    raise RuntimeError(f"empty_llm_output:{task['node_name']}")
                input_tokens = int(usage.get("input_tokens", 0) or 0)
                output_tokens = int(usage.get("output_tokens", 0) or 0)
                if input_tokens <= 0:
                    input_tokens = max(1, len(base_prompt) // 4)
                    usage["input_tokens"] = input_tokens
                    usage["estimated_by_platform"] = True
                if output_tokens <= 0:
                    output_tokens = max(1, len(content) // 4)
                    usage["output_tokens"] = output_tokens
                    usage["estimated_by_platform"] = True
                async with event_lock:
                    store.append_run_event(
                        run_id,
                        "artifact.validation.started",
                        "validation",
                        f"开始校验“{task['node_name']}”的正式交付",
                        "平台正在核对内容、真实文件、命令退出码和自动化测试证据。" if is_engineering else "平台正在核对节点输出是否非空并满足基础产物协议。",
                        {"task_id": task["id"], "node_key": node_key, "engineering": is_engineering},
                    )
                validation: dict[str, Any] = {"engineering": is_engineering, "content_non_empty": bool(content.strip())}
                if is_engineering:
                    code_manifest = _code_manifest(Path(run["workspace"]["code"]))
                    completed_commands: list[dict[str, Any]] = []
                    completed_tests: list[dict[str, Any]] = []
                    for runtime_response in node_runtime_responses:
                        calls = {
                            str(item.get("tool_call_id") or ""): item
                            for item in runtime_response.get("actions", [])
                            if item.get("kind") == "tool_call"
                        }
                        for action in runtime_response.get("actions", []):
                            if action.get("kind") != "tool_result" or action.get("tool_name") not in {"exec", "process"}:
                                continue
                            call = calls.get(str(action.get("tool_call_id") or ""), {})
                            command = str((call.get("arguments") or {}).get("command") or "")
                            record = {
                                "command": command,
                                "actor_id": runtime_response.get("actor_id"),
                                "delivery_root": runtime_response.get("delivery_root"),
                                "files_promoted": runtime_response.get("files_promoted", False),
                                **action,
                            }
                            completed_commands.append(record)
                            if _is_test_command(command):
                                completed_tests.append(record)
                    successful_commands = [
                        item for item in completed_commands
                        if item.get("exit_code") == 0 and not item.get("is_error")
                    ]
                    successful_tests = [
                        item for item in completed_tests
                        if item.get("exit_code") == 0 and not item.get("is_error")
                    ]
                    portable_successful_tests = []
                    for item in successful_tests:
                        try:
                            command_cwd = Path(str(item.get("cwd") or "")).resolve()
                            delivery_root = Path(str(item.get("delivery_root") or "")).resolve()
                            portable = (
                                bool(item.get("files_promoted"))
                                and command_cwd.is_relative_to(delivery_root)
                            )
                        except (OSError, ValueError):
                            portable = False
                        if portable:
                            portable_successful_tests.append(item)
                    validation.update(
                        {
                            "code_files": code_manifest,
                            "file_count": len(code_manifest),
                            "commands": completed_commands,
                            "command_count": len(completed_commands),
                            "successful_command_count": len(successful_commands),
                            "tests": completed_tests,
                            "test_count": len(completed_tests),
                            "successful_test_count": len(successful_tests),
                            "portable_successful_test_count": len(portable_successful_tests),
                        }
                    )
                    failures = []
                    if not code_manifest:
                        failures.append("未在 Run 代码交付区形成真实文件")
                    if not successful_commands:
                        failures.append("没有成功的真实构建或校验命令")
                    if not successful_tests:
                        failures.append("没有通过的自动化测试")
                    elif not portable_successful_tests:
                        failures.append("测试没有在最终可下载项目根目录内执行，交付包脱离 Agent 工作区后可能不可复验")
                    validation["failures"] = failures
                    validation["passed"] = not failures
                else:
                    validation["passed"] = bool(content.strip())
                    validation["failures"] = [] if content.strip() else ["正式输出为空"]
                async with event_lock:
                    store.append_run_event(
                        run_id,
                        "artifact.validation.passed" if validation["passed"] else "artifact.validation.failed",
                        "validation",
                        f"“{task['node_name']}”{'通过' if validation['passed'] else '未通过'}交付校验",
                        (
                            f"已核验 {validation.get('file_count', 0)} 个真实文件、{validation.get('command_count', 0)} 条命令、"
                            f"{validation.get('successful_test_count', 0)} 次通过的自动化测试。"
                            if is_engineering and validation["passed"]
                            else ("；".join(validation.get("failures", [])) or "基础产物协议已通过。")
                        ),
                        {"task_id": task["id"], "node_key": node_key, **validation},
                    )
                if not validation["passed"]:
                    raise ArtifactValidationError(
                        f"artifact_validation_failed:{node_key}:{'|'.join(validation.get('failures', []))}"
                    )
                artifact = store.create_artifact(
                    run_id, task["id"], "workflow_output", task["node_name"], content, "candidate"
                )
                store.update_task(
                    task["id"],
                    status="completed",
                    output_data={
                        "artifact_id": artifact["id"], "artifact_version": artifact["version"], "usage": usage,
                        "model": model_config["model"], "runtime": "openclaw", "decision": decision,
                        "validation": validation,
                    },
                )
                persisted_memories = 0
                for memory_agent, memory_content in memory_entries:
                    if not memory_agent.get("memory_policy", {}).get("write_after_task", True):
                        continue
                    store.add_agent_memory(
                        memory_agent["id"],
                        kind="task_experience",
                        title=f"{task['node_name']} · 第 {loop_round} 轮",
                        content=(
                            f"委托：{str(run['task_input'])[:1200]}\n\n"
                            f"我的公开贡献：{memory_content[:6000]}\n\n"
                            f"节点结果：{content[:3000]}"
                        ),
                        source_run_id=run_id,
                        source_task_id=task["id"],
                        visibility="private",
                    )
                    persisted_memories += 1
                async with event_lock:
                    store.append_run_event(
                        run_id,
                        "artifact.created",
                        "artifact",
                        f"“{task['node_name']}”产物已经形成",
                        "真实模型返回内容已持久化为可查看、可追溯的节点产物。",
                        {
                            "task_id": task["id"],
                            "node_key": node_key,
                            "artifact_id": artifact["id"],
                            "artifact_version": artifact["version"],
                            "artifact_preview": _preview(content),
                            "usage": usage,
                            "model": model_config["model"],
                            "runtime": "openclaw",
                        },
                    )
                    if persisted_memories:
                        store.append_run_event(
                            run_id, "agent.memory.persisted", "collaboration",
                            "人物长期 Memory 已沉淀",
                            f"本节点为 {persisted_memories} 位参与人物分别保存了私有经历；不会写入其他人物的记忆。",
                            {"task_id": task["id"], "node_key": node_key, "memory_count": persisted_memories},
                        )
                return node_key, input_tokens + output_tokens, {
                    "title": task["node_name"],
                    "content": content[:4000],
                }, decision

        async def execute_node_with_retries(
            task: dict[str, Any],
            prior: list[str],
        ) -> tuple[str, int, dict[str, Any], dict[str, Any] | None]:
            max_node_attempts = 2
            for node_attempt in range(1, max_node_attempts + 1):
                try:
                    return await execute_node(task, prior, node_attempt)
                except (LLMRequestError, OpenClawRuntimeError, ArtifactValidationError) as exc:
                    if node_attempt >= max_node_attempts:
                        raise
                    store.update_task(
                        task["id"],
                        status="retrying",
                        output_data={
                            "last_error": str(exc),
                            "error_type": type(exc).__name__,
                            "next_node_attempt": node_attempt + 1,
                        },
                    )
                    async with event_lock:
                        store.append_run_event(
                            run_id,
                            "task.retrying",
                            "execution",
                            f"“{task['node_name']}”将整体重试",
                            f"节点内的模型调用已经连续失败，平台将在 2 秒后从本节点重新开始。这是第 {node_attempt + 1}/{max_node_attempts} 次节点尝试。失败原因：{exc}",
                            {
                                "task_id": task["id"],
                                "node_key": task["node_key"],
                                "attempt": node_attempt,
                                "next_attempt": node_attempt + 1,
                                "max_attempts": max_node_attempts,
                                "delay_seconds": 2,
                                "error_type": type(exc).__name__,
                                "error_detail": str(exc),
                            },
                        )
                    await asyncio.sleep(2)
            raise RuntimeError("unreachable_node_retry_state")

        def downstream_from(start_keys: set[str]) -> set[str]:
            impacted = set(start_keys)
            changed = True
            while changed:
                changed = False
                for candidate, candidate_dependencies in dependencies.items():
                    if candidate not in impacted and candidate_dependencies & impacted:
                        impacted.add(candidate)
                        changed = True
            return impacted

        async def process_rework_interventions() -> None:
            requests = [
                item
                for item in store.list_run_interventions(run_id)
                if item.get("kind") == "require_rework" and str(item["id"]) not in handled_rework_interventions
            ]
            for intervention in requests:
                target_task = next(
                    (item for item in tasks if str(item["id"]) == str(intervention.get("task_id") or "")),
                    None,
                )
                if not target_task:
                    handled_rework_interventions.add(str(intervention["id"]))
                    continue
                was_queued = intervention.get("status") == "queued"
                if was_queued:
                    store.mark_run_interventions_applied([str(intervention["id"])])
                target_key = str(target_task["node_key"])
                impacted = downstream_from({target_key})
                for impacted_key in impacted:
                    completed.discard(impacted_key)
                    pending.add(impacted_key)
                    revision_feedback.setdefault(impacted_key, []).append(
                        str(intervention["content"])
                        if impacted_key == target_key
                        else f"上游节点因发起人介入而返工；请使用新产物重新执行。发起人意见：{intervention['content']}"
                    )
                    store.update_task(
                        task_by_key[impacted_key]["id"],
                        status="pending",
                        output_data={
                            "rework_requested_by_user": True,
                            "intervention_id": intervention["id"],
                            "feedback": revision_feedback[impacted_key][-1],
                        },
                    )
                handled_rework_interventions.add(str(intervention["id"]))
                async with event_lock:
                    if was_queued:
                        store.append_run_event(
                            run_id,
                            "user.intervention.applied",
                            "intervention",
                            f"发起人要求“{target_task['node_name']}”返工",
                            str(intervention["content"]),
                            {
                                "intervention_id": intervention["id"],
                                "task_id": target_task["id"],
                                "node_key": target_key,
                                "kind": "require_rework",
                                "content": intervention["content"],
                                "status": "applied",
                            },
                        )
                    store.append_run_event(
                        run_id,
                        "workflow.loop.created",
                        "revision",
                        "发起人介入触发了定向返工闭环",
                        "责任节点及依赖其产物的下游节点将重新行动，旧产物继续保留为历史版本。",
                        {
                            "source": "user_intervention",
                            "intervention_id": intervention["id"],
                            "target_node_keys": [target_key],
                            "impacted_node_keys": sorted(impacted),
                        },
                    )

        while pending:
            await wait_for_control_boundary()
            await process_rework_interventions()
            current = store.get_run(run_id)
            if not current or current["status"] == "cancelled":
                return
            if elapsed_before_invocation + (time.monotonic() - started_at) > max_run_minutes * 60:
                raise RuntimeError("budget_exhausted:run_time_limit")
            if max_total_tokens and total_tokens >= max_total_tokens:
                raise RuntimeError("budget_exhausted:token_limit")
            ready = [
                key for key in pending if dependencies.get(key, set()).issubset(completed)
            ]
            if not ready:
                raise RuntimeError("workflow_graph_cycle_or_unreachable_node")
            batch = [task_by_key[key] for key in ready]
            prior = [item for key in completed for item in [artifacts_by_key.get(key, "")] if item]
            results = await asyncio.gather(
                *(execute_node_with_retries(task, prior[-4:]) for task in batch), return_exceptions=True
            )
            errors = [result for result in results if isinstance(result, Exception)]
            if errors:
                for task, result in zip(batch, results):
                    if isinstance(result, Exception):
                        store.update_task(task["id"], status="failed", output_data={"error": str(result)})
                        async with event_lock:
                            store.append_run_event(
                                run_id,
                                "task.failed",
                                "execution",
                                f"“{task['node_name']}”在自动重试后仍然失败",
                                f"平台已完成模型请求级重试和节点级重试，仍未成功。最终原因：{result}",
                                {
                                    "task_id": task["id"],
                                    "node_key": task["node_key"],
                                    "error_type": type(result).__name__,
                                    "error_detail": str(result),
                                    "automatic_retry_exhausted": isinstance(result, (LLMRequestError, OpenClawRuntimeError, ArtifactValidationError)),
                                },
                            )
                raise errors[0]
            gate_decisions: list[tuple[str, dict[str, Any]]] = []
            for result in results:
                node_key, used_tokens, artifact, decision = result
                completed.add(node_key)
                pending.remove(node_key)
                total_tokens += used_tokens
                artifacts_by_key[node_key] = f"[{artifact['title']}]\n{artifact['content']}"
                if decision:
                    gate_decisions.append((node_key, decision))
            for gate_key, decision in gate_decisions:
                verdict = str(decision.get("verdict") or "")
                if verdict == "pass":
                    async with event_lock:
                        store.append_run_event(
                            run_id, "gate.passed", "gate", f"“{task_by_key[gate_key]['node_name']}”裁决通过",
                            str(decision.get("summary") or "独立裁判确认本轮产物满足验收要求。"),
                            {"task_id": task_by_key[gate_key]["id"], "node_key": gate_key, "decision": decision},
                        )
                    continue
                target_keys = {str(item) for item in decision.get("target_node_keys", []) if str(item) in task_by_key}
                if not target_keys:
                    target_keys = set(dependencies.get(gate_key, set()))
                if not target_keys:
                    raise RuntimeError(f"judge_rejected_without_target:{gate_key}")
                revision_counts[gate_key] = revision_counts.get(gate_key, 0) + 1
                if revision_counts[gate_key] > max_revision_rounds:
                    raise RuntimeError(f"revision_exhausted:{gate_key}")
                feedback = str(decision.get("feedback") or decision.get("summary") or "根据裁判意见修订并重新提交。")
                impacted = downstream_from(target_keys)
                for impacted_key in impacted:
                    completed.discard(impacted_key)
                    pending.add(impacted_key)
                    revision_feedback.setdefault(impacted_key, []).append(
                        feedback if impacted_key in target_keys else f"上游责任节点已被裁判打回；使用其修订产物重新执行。裁判意见：{feedback}"
                    )
                    store.update_task(
                        task_by_key[impacted_key]["id"],
                        status="pending",
                        output_data={
                            "rework_requested": True,
                            "gate_node_key": gate_key,
                            "revision_round": revision_counts[gate_key],
                            "feedback": revision_feedback[impacted_key][-1],
                        },
                    )
                async with event_lock:
                    store.append_run_event(
                        run_id, "gate.rejected", "gate", f"裁判第 {revision_counts[gate_key]} 次退回修订",
                        feedback,
                        {
                            "task_id": task_by_key[gate_key]["id"], "node_key": gate_key,
                            "target_node_keys": sorted(target_keys), "impacted_node_keys": sorted(impacted),
                            "revision_round": revision_counts[gate_key], "max_revision_rounds": max_revision_rounds,
                            "decision": decision,
                        },
                    )
                    store.append_run_event(
                        run_id, "workflow.loop.created", "revision", "生产流已自动回到责任节点",
                        "责任节点将携带裁判意见重做；其下游节点随后基于新版本产物重新执行，原产物继续保留为历史版本。",
                        {
                            "gate_node_key": gate_key, "target_node_keys": sorted(target_keys),
                            "impacted_node_keys": sorted(impacted), "revision_round": revision_counts[gate_key],
                        },
                    )
                    for target_key in sorted(target_keys):
                        target_task = task_by_key[target_key]
                        target_agent = store.get_agent(str(target_task.get("agent_id")))
                        store.append_run_event(
                            run_id, "agent.message.sent", "revision",
                            f"裁判向{target_agent['name'] if target_agent else target_task['node_name']}发出返工委托",
                            feedback,
                            {
                                "task_id": target_task["id"], "node_key": target_key,
                                "from_agent_id": task_by_key[gate_key].get("agent_id"),
                                "to_agent_id": target_task.get("agent_id"), "message_type": "revision_request",
                                "content": feedback, "round": revision_counts[gate_key],
                            },
                        )
            progress = int((len(completed) / max(len(tasks), 1)) * 100)
            store.update_run(run_id, progress=progress, token_count=total_tokens)

        store.update_run(run_id, status="completed", stage="completed", progress=100, token_count=total_tokens)
        store.append_run_event(
            run_id,
            "run.completed",
            "gate",
            "全部节点已经完成",
            "工作流中的所有固定节点均已返回并保存真实模型产物。",
            {
                "artifact_count": len(artifacts_by_key), "model": model_config["model"], "token_count": total_tokens,
                "runtime": "openclaw", "revision_counts": revision_counts,
            },
        )
    except asyncio.CancelledError:
        current = store.get_run(run_id)
        if current and current.get("status") != "cancelled":
            if current.get("status") == "pause_requested":
                store.update_run(run_id, status="paused", stage="paused")
            elif current.get("status") != "paused":
                store.update_run(run_id, status="running", stage="interrupted_waiting_recovery")
            store.append_run_event(
                run_id,
                "run.interrupted",
                "system",
                "执行器已中断，现场等待恢复",
                "本次不是发起人取消。任务、事件、产物和人物工作区均已保留，后端恢复后将从未完成节点继续。",
                {"recoverable": True},
            )
        raise
    except Exception as exc:
        if str(exc).startswith("budget_exhausted:"):
            status, stage = "budget_exhausted", "budget_exhausted"
        elif str(exc).startswith("revision_exhausted:"):
            status, stage = "revision_exhausted", "revision_exhausted"
        else:
            status, stage = "failed", "execution_failed"
        latest = store.get_run(run_id) or {}
        latest_tasks = latest.get("tasks") or []
        completed_count = sum(1 for item in latest_tasks if item.get("status") == "completed")
        terminal_progress = int((completed_count / max(len(latest_tasks), 1)) * 100)
        if latest_tasks and completed_count == 0:
            terminal_progress = max(1, int(latest.get("progress") or 0))
        store.update_run(run_id, status=status, stage=stage, progress=terminal_progress)
        store.append_run_event(
            run_id,
            "run.budget_exhausted" if status == "budget_exhausted" else ("run.revision_exhausted" if status == "revision_exhausted" else "run.failed"),
            "system",
            "真实执行失败",
            f"执行已停止。平台保留全部重试记录、已完成节点和已有产物。最终原因：{exc}",
            {"error_type": type(exc).__name__, "error_detail": str(exc)},
        )
