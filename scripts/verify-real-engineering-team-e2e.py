from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.app.platform_executor import execute_platform_run
from server.app.agent_runtime_registry import agent_runtime
from server.app.platform_store import PlatformStore, platform_store


async def main() -> None:
    runtime_name = os.getenv("JIANGHU_G5_TEST_RUNTIME", "openclaw").strip() or "openclaw"
    agent_runtime.register(agent_runtime.get(runtime_name), default=True)
    verification_root = Path(".data/verification").resolve()
    verification_root.mkdir(parents=True, exist_ok=True)
    verification_id = uuid4().hex[:10]
    db_path = verification_root / f"real-engineering-team-e2e-{verification_id}.db"
    store = PlatformStore(str(db_path))

    active = platform_store.get_active_model_config(include_secret=True)
    if not active:
        raise RuntimeError("active_model_config_missing")
    store.save_model_config(
        config_id=None,
        name="真实工程验收模型",
        provider=active["provider"],
        base_url=active["base_url"],
        model=active["model"],
        token=active["token"],
        active=True,
    )

    lead = store.create_agent(
        name="林归舟",
        role="Python 工程负责人",
        description="负责合并真实代码、执行测试并交付可独立运行的项目",
        persona="重视简单、可移植和可复验，不接受只写说明不写代码。",
        capabilities=["Python 开发", "代码整合", "自动化测试"],
    )
    reviewer = store.create_agent(
        name="唐照影",
        role="测试与质量工程师",
        description="独立实现测试与边界用例，并公开提交真实文件",
        persona="以失败用例和可重复证据检验实现，不读取他人的私有上下文。",
        capabilities=["单元测试", "边界测试", "缺陷复现"],
    )
    team = store.create_team(
        organization_id="org_jianghu",
        name="真实工程联合作业队",
        purpose="验证同节点隔离开发、公开工程提交、定向通信、合并和测试",
        operating_mode="collaborative",
        members=[
            {"agent_id": lead["id"], "member_role": "leader", "responsibility": "整合代码并最终交付"},
            {"agent_id": reviewer["id"], "member_role": "reviewer", "responsibility": "实现测试和边界验证"},
        ],
    )
    workflow = store.create_workflow(
        f"{runtime_name} 真实多人编码验收流",
        "两位人物各自在隔离工作区写代码，再通过公共提交区协作形成可运行交付。",
        "real_engineering_acceptance",
        {
            "nodes": [
                {
                    "key": "build_calculator",
                    "name": "多人协作开发可运行计算器",
                    "type": "team_task",
                    "execution_mode": "engineering",
                    "purpose": (
                        "在 delivery 项目根目录开发一个仅使用 Python 标准库的 calculator 包。"
                        "必须包含 calculator/__init__.py、calculator/core.py、tests/test_core.py 和 README.md。"
                        "至少实现 add(a,b) 与 safe_divide(a,b)，除数为零时抛出 ValueError。"
                        "每位人物必须真实创建或修改文件并运行 python -m unittest discover -s tests -v。"
                        "负责人必须读取另一人物公开提交区的 manifest 和文件，明确采用或拒绝，"
                        "合并后再次在最终 delivery 根目录执行全部测试。"
                    ),
                    "agent_id": lead["id"],
                    "agent_role": lead["role"],
                    "team_id": team["id"],
                    "participant_agent_ids": [lead["id"], reviewer["id"]],
                    "communication_rounds": 1,
                }
            ],
            "edges": [],
            "policies": {
                "max_parallel_agents": 2,
                "max_debate_rounds": 1,
                "max_revision_rounds": 1,
                "max_run_minutes": 60,
                "max_total_tokens": 240_000,
            },
        },
    )
    run = store.create_run(
        workflow["id"],
        (
            "真实开发并交付一个可下载、可独立复验的 Python calculator 项目。"
            "禁止只输出代码片段或说明；必须写入文件、执行测试、失败则修复后重跑。"
        ),
    )
    print(
        {
            "phase": "started",
            "runtime": runtime_name,
            "db": str(db_path),
            "run_id": run["id"],
            "workflow_id": workflow["id"],
            "agents": 2,
        },
        flush=True,
    )

    await execute_platform_run(store, run["id"])
    result = store.get_run(run["id"])
    if not result:
        raise RuntimeError("verification_run_not_found")

    event_counts: dict[str, int] = {}
    for event in result["events"]:
        event_counts[event["type"]] = event_counts.get(event["type"], 0) + 1
    task = result["tasks"][0]
    validation = task.get("output", {}).get("validation", {})
    code_root = Path(result["workspace"]["code"]).resolve()
    zip_base = verification_root / f"real-engineering-team-e2e-{verification_id}"
    zip_path = Path(shutil.make_archive(str(zip_base), "zip", root_dir=code_root))

    with tempfile.TemporaryDirectory(prefix="jianghu-portable-") as temporary:
        extracted = Path(temporary) / "delivery"
        shutil.unpack_archive(str(zip_path), extracted)
        portable_test = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=extracted,
            capture_output=True,
            text=True,
            timeout=60,
        )
        extracted_files = sorted(
            path.relative_to(extracted).as_posix()
            for path in extracted.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )

    summary = {
        "phase": "completed",
        "runtime": runtime_name,
        "run_id": result["id"],
        "status": result["status"],
        "progress": result["progress"],
        "token_count": result["token_count"],
        "workspace": result["workspace"]["root"],
        "zip": str(zip_path),
        "files": extracted_files,
        "portable_test_exit_code": portable_test.returncode,
        "portable_test_output": (portable_test.stdout + portable_test.stderr)[-2000:],
        "validation": {
            "passed": validation.get("passed"),
            "file_count": validation.get("file_count"),
            "command_count": validation.get("command_count"),
            "successful_test_count": validation.get("successful_test_count"),
            "portable_successful_test_count": validation.get("portable_successful_test_count"),
        },
        "event_counts": {
            key: event_counts.get(key, 0)
            for key in [
                "team.member.completed",
                "team.dossier.published",
                "engineering.submission.published",
                "team.communication.round.started",
                "agent.message.sent",
                "team.synthesis.started",
                "agent.file.created",
                "agent.file.modified",
                "agent.command.completed",
                "agent.test.completed",
                "artifact.validation.passed",
                "run.completed",
                "run.failed",
            ]
        },
    }
    print(summary, flush=True)

    if result["status"] != "completed":
        raise RuntimeError(f"real_engineering_e2e_failed:{result['status']}")
    if event_counts.get("engineering.submission.published", 0) < 2:
        raise RuntimeError("real_engineering_submissions_missing")
    if event_counts.get("agent.message.sent", 0) < 2:
        raise RuntimeError("real_agent_communication_missing")
    if event_counts.get("agent.test.completed", 0) < 1:
        raise RuntimeError("real_test_events_missing")
    if not validation.get("passed"):
        raise RuntimeError("platform_engineering_validation_failed")
    if portable_test.returncode != 0:
        raise RuntimeError("downloaded_delivery_portable_test_failed")
    forbidden = {"AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "HEARTBEAT.md", "TOOLS.md", "MEMORY.md"}
    if forbidden.intersection(Path(item).name for item in extracted_files):
        raise RuntimeError("openclaw_control_files_leaked")


if __name__ == "__main__":
    asyncio.run(main())
