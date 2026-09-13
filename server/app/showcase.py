from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .platform_store import PlatformStore


CASE_ID = "single-vs-multi-runnable-delivery-v1"
TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled", "budget_exhausted", "revision_exhausted"}

CASE_TASK = """开发一个可运行的 Python 3 事件优先级评估器，并形成可下载、可复验的真实工程产物。

正式交付约束：
1. 项目根目录必须包含 incident_priority.py，并提供 classify_incident(record: dict) -> dict。
2. 输入至少包含 incident_id、severity、affected_users、minutes_open；输出必须保留 incident_id，并给出 priority 与 sla_minutes。
3. 优先级规则：critical 为 P0；high 且 affected_users >= 100 为 P0；其余 high 为 P1；medium 且 minutes_open >= 60 为 P1；其余 medium 为 P2；low 为 P3。P0/P1/P2/P3 的 SLA 分别为 15/60/240/1440 分钟。
4. 对缺字段、非法严重级别、错误类型和不合理数值进行可靠处理，不能静默产生错误结论。
5. 必须包含 README、自动化测试和清晰的本地运行方式；真实执行测试并保留命令与结果证据。
6. 仅使用 Python 标准库，使下载后的项目可以在无网络环境复验。

本案例会在 Run 完成后使用平台隐藏验收集进行二次复验。不要只写方案或测试报告，必须真实创建文件、运行测试并交付代码。"""

CASE_MANIFEST: dict[str, Any] = {
    "id": CASE_ID,
    "name": "从需求到可运行交付：单 Agent 与多 Agent 对照实验",
    "summary": "同一模型、同一任务、同一独立裁判和同一隐藏验收集下，对照单 Agent 生产与多 Agent 协作/对抗的质量、效能和成本。",
    "task": CASE_TASK,
    "manual_reference_minutes": 180,
    "quality_dimensions": [
        "隐藏验收通过率",
        "风险发现覆盖率",
        "产出完整度",
        "独立裁判评分",
    ],
    "efficiency_dimensions": [
        "真实耗时",
        "Token 消耗",
        "人物行动数",
        "人工介入次数",
        "按公开假设估算的人工耗时",
    ],
    "fairness_rules": [
        "两组使用相同任务文本、模型配置和运行预算。",
        "两组均由同一位独立裁判使用隔离身份、上下文和 Prompt 裁决。",
        "生产 Agent 看不到平台隐藏验收代码；指标只读取真实 Run、文件、命令、测试和裁决证据。",
        "提升值由本次对照运行实时计算；仓库不预置结果，也不承诺多 Agent 必然获胜。",
    ],
    "risk_topics": [
        {
            "key": "missing_fields",
            "name": "缺字段与输入完整性",
            "keywords": ["缺字段", "必填", "missing", "required", "字段校验"],
        },
        {
            "key": "invalid_severity",
            "name": "非法严重级别",
            "keywords": ["非法严重", "严重级别", "severity", "枚举", "unknown level"],
        },
        {
            "key": "wrong_types",
            "name": "字段类型错误",
            "keywords": ["类型错误", "错误类型", "type", "布尔", "整数校验"],
        },
        {
            "key": "negative_values",
            "name": "负数和不合理数值",
            "keywords": ["负数", "非负", "negative", "不合理数值", "范围校验"],
        },
        {
            "key": "boundary_rules",
            "name": "100 人与 60 分钟边界",
            "keywords": ["边界", "100", "60", "临界", "boundary"],
        },
        {
            "key": "stable_schema",
            "name": "稳定输出契约",
            "keywords": ["输出契约", "输出结构", "schema", "incident_id", "sla_minutes"],
        },
        {
            "key": "determinism",
            "name": "确定性与可复验",
            "keywords": ["确定性", "可复验", "determin", "重复执行", "一致结果"],
        },
        {
            "key": "test_evidence",
            "name": "自动化测试与证据",
            "keywords": ["自动化测试", "测试覆盖", "unittest", "pytest", "测试证据"],
        },
    ],
}


AGENT_SPECS: dict[str, dict[str, Any]] = {
    "solo": {
        "name": "顾青川",
        "role": "单兵全栈交付工程师",
        "description": "独立承担需求理解、设计、开发、测试和交付，用作单 Agent 生产基线。",
        "persona": "顾青川行动迅速、重视端到端闭环，但所有判断都由自己完成；他会留下证据，也可能受单一视角限制。",
        "capabilities": ["需求理解", "软件设计", "Python 开发", "自动化测试", "可运行交付"],
    },
    "product": {
        "name": "沈知微",
        "role": "产品负责人",
        "description": "负责把目标、规则、边界和验收口径转化为可执行约束。",
        "persona": "沈知微关注真实价值和边界条件，会追问模糊表述并拒绝用实现细节掩盖需求缺口。",
        "capabilities": ["需求澄清", "范围管理", "验收设计", "边界分析"],
    },
    "architect": {
        "name": "程观澜",
        "role": "系统架构师",
        "description": "负责模块边界、接口契约、错误模型和可演化性。",
        "persona": "程观澜从整体约束出发做权衡，要求每个设计决定都能被实现和验证。",
        "capabilities": ["系统架构", "接口设计", "错误模型", "技术权衡"],
    },
    "backend": {
        "name": "林砚",
        "role": "后端工程师",
        "description": "负责核心规则、数据校验、命令行接口和真实代码实现。",
        "persona": "林砚审慎务实，优先保证核心逻辑正确、边界明确并可由测试重复验证。",
        "capabilities": ["Python 开发", "领域建模", "输入校验", "自动化测试"],
    },
    "frontend": {
        "name": "周野",
        "role": "前端工程师",
        "description": "在本案例中负责使用体验、输出可读性、README 和交付可用性。",
        "persona": "周野重视用户能否真正理解和运行交付，不接受只有核心函数却没有使用路径的半成品。",
        "capabilities": ["交互设计", "可用性检验", "文档交付", "前端开发"],
    },
    "quality": {
        "name": "唐砚秋",
        "role": "测试与质量工程师",
        "description": "独立设计边界、异常和回归测试，并用真实命令验证候选代码。",
        "persona": "唐砚秋不会把能运行等同于质量合格，会主动构造边界、错误输入和回归场景。",
        "capabilities": ["测试策略", "边界测试", "异常测试", "自动化回归", "缺陷管理"],
    },
    "security": {
        "name": "陆谨言",
        "role": "安全与风险审计师",
        "description": "以攻击者和失效视角检查输入、异常、滥用路径和证据可信度。",
        "persona": "陆谨言尖锐且独立，主动挑战过度乐观的假设，并要求风险有处置结论。",
        "capabilities": ["攻击性验证", "输入安全", "风险审计", "失效分析"],
    },
    "judge": {
        "name": "顾衡",
        "role": "独立裁判",
        "description": "不参与候选产物创作，只依据任务、产物、测试和风险证据裁决。",
        "persona": "顾衡保持独立身份与上下文，不接受参与者的声望替代证据；不通过时给出可执行返工意见。",
        "capabilities": ["独立评审", "证据核验", "验收裁决", "保留意见"],
    },
}


def _ensure_agent(store: PlatformStore, spec: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    existing = next(
        (
            agent
            for agent in store.list_agents()
            if agent["name"] == spec["name"] and agent["role"] == spec["role"]
        ),
        None,
    )
    if existing:
        return existing, False
    return store.create_agent(
        name=spec["name"],
        role=spec["role"],
        description=spec["description"],
        persona=spec["persona"],
        capabilities=list(spec["capabilities"]),
        visibility="private",
        skills=[],
        runtime="claude_code",
        memory_policy={"enabled": True, "max_prompt_items": 8, "write_after_task": True},
    ), True


def _ensure_team(store: PlatformStore, agents: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], bool]:
    name = "可运行交付对照实验组"
    team = next((item for item in store.list_teams("org_jianghu") if item["name"] == name), None)
    member_specs = [
        ("product", "leader", "冻结需求规则、范围和验收口径"),
        ("architect", "member", "设计接口、错误模型和工程边界"),
        ("backend", "member", "实现核心代码并完成集成"),
        ("frontend", "member", "改善使用路径、说明和交付体验"),
        ("quality", "challenger", "独立测试并提交缺陷证据"),
        ("security", "challenger", "从攻击与失效视角提出挑战"),
    ]
    if not team:
        return store.create_team(
            organization_id="org_jianghu",
            name=name,
            purpose="在同一真实开发任务中实行分工协作、公开争辩、攻防审查、返工闭环和独立裁决。",
            operating_mode="red_team",
            members=[
                {
                    "agent_id": agents[key]["id"],
                    "member_role": member_role,
                    "responsibility": responsibility,
                }
                for key, member_role, responsibility in member_specs
            ],
            visibility="private",
        ), True
    existing_ids = {member["id"] for member in team["members"]}
    changed = False
    for key, _, responsibility in member_specs:
        if agents[key]["id"] not in existing_ids:
            team = store.add_team_member(team["id"], agents[key]["id"], responsibility)
            changed = True
    return team, changed


def _workflow_by_source(store: PlatformStore, source: str) -> dict[str, Any] | None:
    return next((workflow for workflow in store.list_workflows() if workflow.get("source") == source), None)


def _ensure_baseline_workflow(store: PlatformStore, agents: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], bool]:
    existing = _workflow_by_source(store, "showcase_single_agent_baseline_v1")
    if existing:
        return existing, False
    nodes = [
        {
            "key": "solo_delivery",
            "name": "单 Agent 端到端真实交付",
            "purpose": "由一位全栈交付工程师独立完成需求理解、设计、代码开发、README、自动化测试和可运行交付。",
            "type": "agent_task",
            "execution_mode": "engineering",
            "agent_id": agents["solo"]["id"],
            "agent_role": agents["solo"]["role"],
            "communication_rounds": 0,
        },
        {
            "key": "judge",
            "name": "独立盲审裁决",
            "purpose": "使用独立身份、上下文和 Prompt 核验真实文件、测试证据、需求覆盖与剩余风险；不通过时定向退回单 Agent 重做。",
            "type": "judge",
            "execution_mode": "document",
            "agent_id": agents["judge"]["id"],
            "agent_role": agents["judge"]["role"],
            "communication_rounds": 0,
        },
    ]
    workflow = store.create_workflow(
        "单 Agent 可运行交付基线",
        "一位生产 Agent 独立完成全部生产工作；独立裁判只负责盲审，不参与创作。",
        source="showcase_single_agent_baseline_v1",
        definition={
            "schema_version": "1.0",
            "showcase": {"case_id": CASE_ID, "variant": "baseline"},
            "inputs": ["task"],
            "outputs": ["runnable_delivery", "judge_decision"],
            "nodes": nodes,
            "edges": [["solo_delivery", "judge"]],
            "policies": {
                "max_parallel_agents": 1,
                "max_debate_rounds": 0,
                "max_revision_rounds": 3,
                "max_run_minutes": 180,
            },
        },
    )
    return workflow, True


def _team_node(
    key: str,
    name: str,
    purpose: str,
    team: dict[str, Any],
    agents: dict[str, dict[str, Any]],
    lead: str,
    participants: list[str],
    *,
    execution_mode: str = "document",
    communication_rounds: int = 1,
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "purpose": purpose,
        "type": "team_task",
        "execution_mode": execution_mode,
        "team_id": team["id"],
        "agent_id": agents[lead]["id"],
        "agent_role": agents[lead]["role"],
        "lead_agent_id": agents[lead]["id"],
        "participant_agent_ids": [agents[key]["id"] for key in participants],
        "communication_rounds": communication_rounds,
    }


def _ensure_multi_workflow(
    store: PlatformStore,
    agents: dict[str, dict[str, Any]],
    team: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    existing = _workflow_by_source(store, "showcase_multi_agent_delivery_v1")
    if existing:
        return existing, False
    nodes = [
        _team_node(
            "requirement",
            "需求规则与验收基线",
            "澄清输入输出契约、业务边界、错误处理和可测试验收项，并主动寻找容易遗漏的条件。",
            team,
            agents,
            "product",
            ["product", "quality"],
            communication_rounds=1,
        ),
        _team_node(
            "architecture",
            "架构与失效路径设计",
            "独立设计模块、接口、错误模型和无网络复验路径，并从滥用与失效视角挑战方案。",
            team,
            agents,
            "architect",
            ["architect", "security"],
            communication_rounds=2,
        ),
        _team_node(
            "implementation",
            "双人隔离开发与合并",
            "两位工程师在隔离工作区分别形成真实代码贡献，公开提交后由负责人合并，并运行自动化测试。",
            team,
            agents,
            "backend",
            ["backend", "frontend"],
            execution_mode="engineering",
            communication_rounds=2,
        ),
        _team_node(
            "quality",
            "独立质量验证",
            "不复述开发者结论，直接检查代码、补充边界和异常测试，并用真实命令形成缺陷与通过证据。",
            team,
            agents,
            "quality",
            ["quality"],
            execution_mode="engineering",
            communication_rounds=0,
        ),
        _team_node(
            "red_team",
            "攻防与失效挑战",
            "从错误输入、规则歧义、静默失败、不可复验和交付滥用角度提出具体挑战，形成红队缺陷清单。",
            team,
            agents,
            "security",
            ["security", "product"],
            communication_rounds=2,
        ),
        _team_node(
            "revision",
            "缺陷整改与候选版封装",
            "逐条处理质量与红队意见，修改真实代码和测试，重新运行验证，形成最终可下载候选版。",
            team,
            agents,
            "backend",
            ["backend", "frontend", "architect"],
            execution_mode="engineering",
            communication_rounds=1,
        ),
        {
            "key": "judge",
            "name": "独立盲审裁决",
            "purpose": "使用与基线相同的独立裁判，核验真实文件、测试证据、需求覆盖、缺陷闭环和剩余风险；不通过时自动退回整改节点。",
            "type": "judge",
            "execution_mode": "document",
            "agent_id": agents["judge"]["id"],
            "agent_role": agents["judge"]["role"],
            "communication_rounds": 0,
        },
    ]
    edges = [
        ["requirement", "implementation"],
        ["architecture", "implementation"],
        ["implementation", "quality"],
        ["implementation", "red_team"],
        ["quality", "revision"],
        ["red_team", "revision"],
        ["revision", "judge"],
    ]
    workflow = store.create_workflow(
        "多 Agent 协作与攻防可运行交付",
        "需求和架构并行，双人隔离开发后由质量与红队并行挑战，整改形成候选版，独立裁判不通过时自动返工。",
        source="showcase_multi_agent_delivery_v1",
        definition={
            "schema_version": "1.0",
            "showcase": {"case_id": CASE_ID, "variant": "multi_agent"},
            "inputs": ["task"],
            "outputs": ["runnable_delivery", "test_evidence", "risk_register", "judge_decision"],
            "nodes": nodes,
            "edges": edges,
            "policies": {
                "max_parallel_agents": 5,
                "max_debate_rounds": 3,
                "max_revision_rounds": 3,
                "max_run_minutes": 180,
            },
        },
    )
    return workflow, True


def ensure_showcase_assets(store: PlatformStore) -> dict[str, Any]:
    agents: dict[str, dict[str, Any]] = {}
    created_agents: list[str] = []
    for key, spec in AGENT_SPECS.items():
        agent, created = _ensure_agent(store, spec)
        agents[key] = agent
        if created:
            created_agents.append(agent["id"])
    team, team_changed = _ensure_team(store, agents)
    baseline, baseline_created = _ensure_baseline_workflow(store, agents)
    multi, multi_created = _ensure_multi_workflow(store, agents, team)
    return {
        "agents": agents,
        "team": team,
        "workflows": {"baseline": baseline, "multi_agent": multi},
        "changes": {
            "created_agent_ids": created_agents,
            "team_created_or_extended": team_changed,
            "baseline_workflow_created": baseline_created,
            "multi_workflow_created": multi_created,
        },
    }


HIDDEN_ACCEPTANCE_SCRIPT = r"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())

results = []

def check(name, fn):
    try:
        fn()
        results.append({"name": name, "passed": True, "detail": "通过"})
    except Exception as exc:
        results.append({"name": name, "passed": False, "detail": f"{type(exc).__name__}: {exc}"})

try:
    import incident_priority as target
except Exception as exc:
    print(json.dumps({"import_error": f"{type(exc).__name__}: {exc}", "results": []}, ensure_ascii=False))
    raise SystemExit(0)

def expect(record, priority, sla):
    result = target.classify_incident(record)
    assert isinstance(result, dict), "返回值必须为 dict"
    assert result.get("incident_id") == record["incident_id"], "incident_id 未保留"
    assert result.get("priority") == priority, (result, priority)
    assert result.get("sla_minutes") == sla, (result, sla)

def expect_invalid(record):
    try:
        target.classify_incident(record)
    except (ValueError, TypeError, KeyError):
        return
    raise AssertionError("非法输入必须显式失败")

check("critical 固定 P0", lambda: expect({"incident_id":"a","severity":"critical","affected_users":0,"minutes_open":0}, "P0", 15))
check("high 100 人边界", lambda: expect({"incident_id":"b","severity":"high","affected_users":100,"minutes_open":0}, "P0", 15))
check("high 99 人边界", lambda: expect({"incident_id":"c","severity":"high","affected_users":99,"minutes_open":0}, "P1", 60))
check("medium 60 分钟边界", lambda: expect({"incident_id":"d","severity":"medium","affected_users":1,"minutes_open":60}, "P1", 60))
check("low 固定 P3", lambda: expect({"incident_id":"e","severity":"low","affected_users":999,"minutes_open":999}, "P3", 1440))
check("缺字段显式失败", lambda: expect_invalid({"incident_id":"f","severity":"high","affected_users":1}))
check("非法 severity 显式失败", lambda: expect_invalid({"incident_id":"g","severity":"urgent","affected_users":1,"minutes_open":1}))
check("负数显式失败", lambda: expect_invalid({"incident_id":"h","severity":"medium","affected_users":-1,"minutes_open":1}))
check("布尔值不能冒充整数", lambda: expect_invalid({"incident_id":"i","severity":"medium","affected_users":True,"minutes_open":1}))

print(json.dumps({"results": results}, ensure_ascii=False))
"""


def _hidden_acceptance(run: dict[str, Any]) -> dict[str, Any]:
    root = Path(str(run.get("workspace", {}).get("code") or ""))
    if not root.is_dir():
        return {"status": "not_available", "passed": 0, "total": 9, "pass_rate": 0, "results": [], "error": "真实代码交付目录不存在"}
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "-c", HIDDEN_ACCEPTANCE_SCRIPT],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "passed": 0, "total": 9, "pass_rate": 0, "results": [], "error": str(exc)}
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.stdout.strip() else {}
    except (json.JSONDecodeError, IndexError):
        payload = {}
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    passed = sum(1 for item in results if item.get("passed"))
    total = 9
    error = str(payload.get("import_error") or completed.stderr.strip() or "")
    return {
        "status": "completed" if len(results) == total else "error",
        "passed": passed,
        "total": total,
        "pass_rate": round(passed / total * 100) if total else 0,
        "results": results,
        "error": error,
        "exit_code": completed.returncode,
    }


def _event_text(event: dict[str, Any]) -> str:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    public_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"content"} or event.get("payload", {}).get("visibility") != "initiator_only"
    }
    return "\n".join(
        [
            str(event.get("title") or ""),
            str(event.get("summary") or ""),
            json.dumps(public_payload, ensure_ascii=False),
        ]
    ).lower()


def _parse_time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _run_metrics(store: PlatformStore, run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if not run:
        return {"run_id": run_id, "status": "missing"}
    workflow = store.get_workflow(str(run["workflow_id"])) or {}
    task_by_id = {str(task["id"]): task for task in run.get("tasks", [])}
    non_judge_artifacts = []
    for artifact in run.get("artifacts", []):
        task = task_by_id.get(str(artifact.get("task_id") or ""), {})
        node_key = str(task.get("node_key") or "")
        if node_key != "judge":
            non_judge_artifacts.append(artifact)
    evidence_text = "\n".join(str(item.get("content") or "") for item in non_judge_artifacts).lower()
    event_text = "\n".join(
        _event_text(event)
        for event in run.get("events", [])
        if str(event.get("type")) not in {"agent.rationale.submitted"}
    )
    discovery_text = f"{evidence_text}\n{event_text}"
    discovered_topics = []
    for topic in CASE_MANIFEST["risk_topics"]:
        if any(str(keyword).lower() in discovery_text for keyword in topic["keywords"]):
            discovered_topics.append({"key": topic["key"], "name": topic["name"]})

    validation_events = [
        event for event in run.get("events", []) if event.get("type") == "artifact.validation.passed"
    ]
    engineering_validations = [event for event in validation_events if event.get("payload", {}).get("engineering")]
    code_files: dict[str, dict[str, Any]] = {}
    successful_tests = 0
    command_count = 0
    for event in engineering_validations:
        payload = event.get("payload", {})
        successful_tests = max(successful_tests, int(payload.get("successful_test_count", 0) or 0))
        command_count = max(command_count, int(payload.get("command_count", 0) or 0))
        for item in payload.get("code_files", []):
            if isinstance(item, dict) and item.get("path"):
                code_files[str(item["path"])] = item

    hidden = _hidden_acceptance(run) if run.get("status") in TERMINAL_RUN_STATUSES else {
        "status": "waiting", "passed": 0, "total": 9, "pass_rate": 0, "results": []
    }
    judge_decisions = [
        task.get("output", {}).get("decision")
        for task in run.get("tasks", [])
        if task.get("output", {}).get("decision")
    ]
    final_decision = judge_decisions[-1] if judge_decisions else {}
    judge_score = int(final_decision.get("score", 0) or 0)
    judge_passed = str(final_decision.get("verdict") or "") == "pass"
    paths = {path.lower() for path in code_files}
    completed_tasks = sum(1 for task in run.get("tasks", []) if task.get("status") == "completed")
    completeness_checks = [
        {"name": "生产流完成", "passed": run.get("status") == "completed"},
        {"name": "核心源码存在", "passed": "incident_priority.py" in paths},
        {"name": "README 存在", "passed": any(Path(path).name.lower().startswith("readme") for path in paths)},
        {"name": "测试文件存在", "passed": any(Path(path).name.lower().startswith("test") and path.endswith(".py") for path in paths)},
        {"name": "真实测试通过", "passed": successful_tests > 0},
        {"name": "全部节点有正式产物", "passed": completed_tasks > 0 and len(run.get("artifacts", [])) >= completed_tasks},
        {"name": "独立裁判通过", "passed": judge_passed},
    ]
    completeness = round(sum(1 for item in completeness_checks if item["passed"]) / len(completeness_checks) * 100)
    hidden_rate = int(hidden.get("pass_rate", 0) or 0)
    quality_score = round(hidden_rate * 0.6 + completeness * 0.25 + judge_score * 0.15)

    events = run.get("events", [])
    actor_ids = {
        str(event.get("payload", {}).get("agent_id"))
        for event in events
        if event.get("payload", {}).get("agent_id")
    }
    messages = [event for event in events if event.get("type") == "agent.message.sent"]
    challenge_messages = [
        event
        for event in messages
        if str(event.get("payload", {}).get("message_type")) in {"challenge", "question", "revision_request"}
    ]
    interventions = run.get("interventions", [])
    created_at = _parse_time(run.get("created_at"))
    finished_at = _parse_time(run.get("updated_at"))
    elapsed_seconds = max(0, round((finished_at - created_at).total_seconds())) if created_at and finished_at else 0
    estimated_human_minutes = 3 + len(interventions) * 5 + (10 if run.get("status") in TERMINAL_RUN_STATUSES and not judge_passed else 0)
    manual_reference = int(CASE_MANIFEST["manual_reference_minutes"])
    human_reduction = max(0, round((manual_reference - estimated_human_minutes) / manual_reference * 100))
    return {
        "run_id": run_id,
        "workflow_id": run["workflow_id"],
        "workflow_name": workflow.get("name", ""),
        "variant": workflow.get("definition", {}).get("showcase", {}).get("variant", ""),
        "status": run.get("status"),
        "progress": run.get("progress", 0),
        "quality_score": quality_score,
        "hidden_acceptance": hidden,
        "risk_discovery": {
            "discovered": len(discovered_topics),
            "total": len(CASE_MANIFEST["risk_topics"]),
            "rate": round(len(discovered_topics) / len(CASE_MANIFEST["risk_topics"]) * 100),
            "topics": discovered_topics,
        },
        "completeness": {"score": completeness, "checks": completeness_checks},
        "judge": {
            "passed": judge_passed,
            "score": judge_score,
            "verdict": final_decision.get("verdict"),
            "summary": final_decision.get("summary", ""),
            "remaining_risks": final_decision.get("remaining_risks", []),
        },
        "evidence": {
            "artifact_count": len(run.get("artifacts", [])),
            "code_file_count": len(code_files),
            "successful_test_count": successful_tests,
            "command_count": command_count,
            "agent_count": len(actor_ids),
            "message_count": len(messages),
            "challenge_count": len(challenge_messages),
            "loop_count": sum(1 for event in events if event.get("type") == "workflow.loop.created"),
            "intervention_count": len(interventions),
        },
        "efficiency": {
            "elapsed_seconds": elapsed_seconds,
            "token_count": int(run.get("token_count", 0) or 0),
            "estimated_cost": float(run.get("estimated_cost", 0) or 0),
            "estimated_human_minutes": estimated_human_minutes,
            "manual_reference_minutes": manual_reference,
            "estimated_human_time_reduction": human_reduction,
            "estimation_note": "人工耗时按启动与复核 3 分钟、每次介入 5 分钟、未通过后的人工处置 10 分钟估算；它不是工时系统实测值。",
        },
    }


def comparison_report(store: PlatformStore, comparison: dict[str, Any]) -> dict[str, Any]:
    baseline = _run_metrics(store, str(comparison["baseline_run_id"]))
    multi = _run_metrics(store, str(comparison["multi_run_id"]))
    statuses = {str(baseline.get("status")), str(multi.get("status"))}
    if statuses.issubset(TERMINAL_RUN_STATUSES):
        status = "completed"
    elif "running" in statuses or "pause_requested" in statuses or "paused" in statuses:
        status = "running"
    else:
        status = "draft"

    comparable = status == "completed"
    delta = {}
    if comparable:
        delta = {
            "quality_score": int(multi.get("quality_score", 0)) - int(baseline.get("quality_score", 0)),
            "hidden_acceptance_rate": int(multi.get("hidden_acceptance", {}).get("pass_rate", 0)) - int(baseline.get("hidden_acceptance", {}).get("pass_rate", 0)),
            "risk_discovery_rate": int(multi.get("risk_discovery", {}).get("rate", 0)) - int(baseline.get("risk_discovery", {}).get("rate", 0)),
            "completeness": int(multi.get("completeness", {}).get("score", 0)) - int(baseline.get("completeness", {}).get("score", 0)),
            "elapsed_seconds": int(multi.get("efficiency", {}).get("elapsed_seconds", 0)) - int(baseline.get("efficiency", {}).get("elapsed_seconds", 0)),
            "token_count": int(multi.get("efficiency", {}).get("token_count", 0)) - int(baseline.get("efficiency", {}).get("token_count", 0)),
            "intervention_count": int(multi.get("evidence", {}).get("intervention_count", 0)) - int(baseline.get("evidence", {}).get("intervention_count", 0)),
        }
    return {
        **comparison,
        "status": status,
        "comparable": comparable,
        "baseline": baseline,
        "multi_agent": multi,
        "delta": delta,
        "interpretation": (
            "正数表示多 Agent 在质量类指标上更高；耗时和 Token 的正数表示付出了更多执行成本。"
            if comparable
            else "两个真实 Run 均进入终态后才生成差异结论；运行中只展示原始证据，不预填提升值。"
        ),
    }


def showcase_snapshot(store: PlatformStore, *, install: bool = False) -> dict[str, Any]:
    assets = ensure_showcase_assets(store) if install else None
    if assets is None:
        baseline = _workflow_by_source(store, "showcase_single_agent_baseline_v1")
        multi = _workflow_by_source(store, "showcase_multi_agent_delivery_v1")
        team = next((item for item in store.list_teams("org_jianghu") if item["name"] == "可运行交付对照实验组"), None)
        assets = {
            "agents": {},
            "team": team,
            "workflows": {"baseline": baseline, "multi_agent": multi},
            "changes": {},
        }
    # 页面只需要最近一轮；避免每次打开案例时重复执行多轮历史代码的隐藏验收。
    comparisons = store.list_showcase_comparisons(CASE_ID, limit=1)
    reports = [comparison_report(store, item) for item in comparisons]
    return {
        "case": CASE_MANIFEST,
        "installed": bool(assets["workflows"]["baseline"] and assets["workflows"]["multi_agent"]),
        "assets": assets,
        "latest_comparison": reports[0] if reports else None,
        "comparisons": reports,
    }
