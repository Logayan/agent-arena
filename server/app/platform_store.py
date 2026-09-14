from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .knowledge_index import SUPPORTED_SUFFIXES, chunk_sections, extract_document, score_chunks
from .run_budget import active_run_seconds, configured_maximum_run_minutes
from .secret_store import protect_secret, unprotect_secret


class _DatabaseConnection:
    """Small DB-API compatibility layer for SQLite and PostgreSQL.

    The domain store intentionally keeps its SQL close to the schema. This
    adapter lets local tests continue using SQLite while production deployments
    use PostgreSQL without duplicating the 3k-line repository implementation.
    """

    def __init__(self, connection: Any, *, postgres: bool) -> None:
        self._connection = connection
        self.postgres = postgres

    def __enter__(self) -> "_DatabaseConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            if exc_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self._connection.close()

    def execute(self, query: str, parameters: tuple[Any, ...] = ()) -> Any:
        if not self.postgres:
            return self._connection.execute(query, parameters)
        normalized = query.strip()
        if normalized.upper().startswith("PRAGMA FOREIGN_KEYS"):
            return self._connection.execute("SELECT 1")
        pragma_match = re.fullmatch(r"PRAGMA\s+table_info\(([^)]+)\)", normalized, re.IGNORECASE)
        if pragma_match:
            return self._connection.execute(
                """SELECT ordinal_position - 1 AS cid, column_name AS name
                   FROM information_schema.columns
                   WHERE table_schema='public' AND table_name=%s
                   ORDER BY ordinal_position""",
                (pragma_match.group(1).strip('"'),),
            )
        normalized = normalized.replace("?", "%s")
        return self._connection.execute(normalized, parameters)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self.execute(statement)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _row_value(row: Any, key: str, index: int = 0) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return row[index]


def workspace_file_category(relative_path: str) -> str:
    """Classify a delivered workspace path for the formal-delivery UI."""
    normalized = relative_path.replace("\\", "/").strip("/")
    path = Path(normalized.lower())
    name = path.name
    parts = set(path.parts)
    suffix = path.suffix

    if (
        name.startswith("dockerfile")
        or name.startswith("compose.")
        or name.startswith("docker-compose.")
        or parts.intersection({"docker", "k8s", "kubernetes", "helm", "deploy", "deployment"})
    ):
        return "deployment"
    if (
        parts.intersection({"test", "tests", "testing", "spec", "specs", "__tests__"})
        or name.startswith("test_")
        or name.endswith(("_test.py", ".test.js", ".test.ts", ".test.tsx", ".spec.js", ".spec.ts", ".spec.tsx"))
    ):
        return "test"
    if parts.intersection({"reports", "report", "audit", "audits", "evidence"}):
        return "report"
    if parts.intersection({"docs", "doc", "documentation"}) or suffix in {".md", ".markdown", ".rst", ".adoc"}:
        return "documentation"
    if (
        name.startswith(".env")
        or name in {"makefile", "pyproject.toml", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
        or suffix in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties"}
    ):
        return "configuration"
    if suffix in {
        ".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".java", ".kt",
        ".kts", ".go", ".rs", ".rb", ".php", ".cs", ".fs", ".fsx", ".c", ".cc", ".cpp", ".h",
        ".hpp", ".swift", ".scala", ".sh", ".ps1", ".bat", ".cmd", ".sql", ".html", ".css", ".scss", ".sass",
    }:
        return "code"
    if suffix in {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp", ".avif", ".mp3", ".wav",
        ".mp4", ".webm", ".woff", ".woff2", ".ttf", ".otf",
    }:
        return "asset"
    return "other"


def workspace_file_media_type(path_value: str) -> str:
    """Return a deterministic media type for immutable workspace artifacts."""
    normalized = str(path_value or "").replace("\\", "/").strip()
    path = Path(normalized)
    name = path.name.lower()
    suffix = path.suffix.lower()
    if (
        name.startswith("dockerfile")
        or name.startswith(".env")
        or name in {"makefile", "procfile", "gemfile", "rakefile"}
    ):
        return "text/plain"
    media_types = {
        ".zip": "application/zip",
        ".json": "application/json",
        ".har": "application/json",
        ".xml": "application/xml",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".txt": "text/plain",
        ".log": "text/plain",
        ".csv": "text/csv",
        ".tsv": "text/tab-separated-values",
        ".toml": "text/plain",
        ".ini": "text/plain",
        ".cfg": "text/plain",
        ".conf": "text/plain",
        ".properties": "text/plain",
        ".example": "text/plain",
        ".py": "text/plain",
        ".pyi": "text/plain",
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".cjs": "text/javascript",
        ".ts": "text/plain",
        ".tsx": "text/plain",
        ".jsx": "text/plain",
        ".vue": "text/plain",
        ".java": "text/plain",
        ".kt": "text/plain",
        ".kts": "text/plain",
        ".go": "text/plain",
        ".rs": "text/plain",
        ".rb": "text/plain",
        ".php": "text/plain",
        ".cs": "text/plain",
        ".fs": "text/plain",
        ".fsx": "text/plain",
        ".c": "text/plain",
        ".cc": "text/plain",
        ".cpp": "text/plain",
        ".h": "text/plain",
        ".hpp": "text/plain",
        ".swift": "text/plain",
        ".scala": "text/plain",
        ".sh": "text/plain",
        ".ps1": "text/plain",
        ".bat": "text/plain",
        ".cmd": "text/plain",
        ".sql": "text/plain",
        ".rst": "text/plain",
        ".adoc": "text/plain",
        ".css": "text/css",
        ".scss": "text/css",
        ".sass": "text/css",
        ".html": "text/html",
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".bmp": "image/bmp",
        ".avif": "image/avif",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".pdf": "application/pdf",
    }
    return media_types.get(suffix, "application/octet-stream")


STARTER_STRATEGIST = {
    "id": "agent_seed_shen_lichuan",
    "name": "沈砺川",
    "role": "科技产品与产业经营者",
    "description": (
        "沈砺川擅长把复杂技术、真实用户需求和商业约束压缩成清晰的产品路线，并亲自推动关键战役落地。"
        "他既能与工程团队讨论架构、质量和交付，也能从品牌、渠道、成本、生态与组织角度判断一项事业能否长期成立；"
        "资源受限时会抓住决定性少数问题，用可运行样品、用户反馈和经营数据持续校正方向。"
    ),
    "persona": (
        "长期主义但行动迅速，尊重工程规律和一线反馈。善于倾听用户、设定高目标、拆解关键路径并组织跨职能协同；"
        "争论时先追问事实、约束和投入产出，不迷信头衔，也不接受只有概念而没有样品、数据和真实交付的方案。"
        "对关键产品体验要求很高，愿意亲自试用、复盘并推动多轮迭代，同时让团队理解目标而不是机械执行命令。"
    ),
    "capabilities": [
        "产品战略与用户洞察",
        "技术趋势与工程判断",
        "从零到一产品创建",
        "商业模式与增长设计",
        "软硬件与服务生态协同",
        "组织搭建与人才识别",
        "成本效率与经营分析",
        "品牌叙事与公众沟通",
        "关键战役统筹与复盘",
        "危机决策与韧性经营",
    ],
    "skills": [
        {
            "key": "user_value_compass",
            "name": "用户价值罗盘",
            "description": "从真实场景、核心痛点和可感知收益判断产品是否值得做。",
            "instructions": "先区分用户表达、真实任务和未满足价值，再给出目标用户、关键场景、价值假设、反证信号和最小验证方案。",
            "enabled": True,
        },
        {
            "key": "product_definition",
            "name": "产品定义与取舍",
            "description": "把复杂机会收敛为清晰产品、关键体验和可执行路线。",
            "instructions": "明确不做什么，优先决定核心体验、技术边界、版本节奏和验收指标；每项取舍说明用户价值、成本、风险和时机。",
            "enabled": True,
        },
        {
            "key": "technology_business_bridge",
            "name": "技术商业化推演",
            "description": "连接技术可行性、产品竞争力、规模交付和经营结果。",
            "instructions": "同时核验技术成熟度、工程成本、供应与交付能力、差异化、定价空间、规模效应和长期维护负担。",
            "enabled": True,
        },
        {
            "key": "campaign_command",
            "name": "关键战役统筹",
            "description": "围绕决定性目标组织跨职能团队并持续清障。",
            "instructions": "形成单一战役目标、责任人、关键路径、并行工作面、里程碑、风险清单和每日可验证进展；阻塞时优先调资源和缩短反馈周期。",
            "enabled": True,
        },
        {
            "key": "cost_efficiency",
            "name": "极致成本效率",
            "description": "在不牺牲核心体验和质量底线的前提下提高投入产出。",
            "instructions": "拆解成本结构、复用空间、自动化机会和规模曲线，区分必须投入、可延后投入与无效投入，并用数据验证降本是否伤害用户价值。",
            "enabled": True,
        },
        {
            "key": "narrative_consensus",
            "name": "叙事与共识动员",
            "description": "把复杂战略转化为团队、合作伙伴和用户能够理解的清晰表达。",
            "instructions": "先讲清问题与受益者，再用事实、样品和关键数字解释方案；避免空泛口号，对限制、风险和未完成事项保持透明。",
            "enabled": True,
        },
    ],
    "memory_policy": {
        "enabled": True,
        "max_prompt_items": 12,
        "write_after_task": True,
        "review_before_promote": True,
    },
}


class PlatformStore:
    """Local durable domain store.

    SQLite is the local development backend. The schema intentionally uses JSON
    payloads at the edges so a PostgreSQL repository can replace this class
    without changing the HTTP/domain contracts.
    """

    def __init__(self, path: str | None = None) -> None:
        self.database_url = os.getenv("JIANGHU_DATABASE_URL", "").strip()
        configured = path or os.getenv("JIANGHU_DB_PATH", ".data/jianghu.db")
        self.path = Path(configured)
        self.is_postgres = bool(self.database_url) and path is None
        data_root = Path(os.getenv("JIANGHU_DATA_ROOT", ".data"))
        default_secret_key = data_root / ".jianghu-secret.key" if self.is_postgres else (self.path.parent / ".jianghu-secret.key" if self.path != Path(":memory:") else data_root / ".jianghu-secret.key")
        self.secret_key_path = Path(os.getenv("JIANGHU_SECRET_KEY_FILE", str(default_secret_key))).resolve()
        default_workspace_root = data_root / "workspaces" if self.is_postgres else (self.path.parent / "workspaces" if self.path != Path(":memory:") else data_root / "workspaces")
        self.workspace_root = Path(os.getenv("JIANGHU_WORKSPACE_ROOT", str(default_workspace_root))).resolve() if self.is_postgres else default_workspace_root.resolve()
        default_knowledge_root = data_root / "knowledge" if self.is_postgres else (self.path.parent / "knowledge" if self.path != Path(":memory:") else data_root / "knowledge")
        self.knowledge_root = Path(os.getenv("JIANGHU_KNOWLEDGE_ROOT", str(default_knowledge_root))).resolve() if self.is_postgres else default_knowledge_root.resolve()
        if not self.is_postgres and self.path != Path(":memory:"):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.knowledge_root.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._ensure_workspace()
        self._repair_managed_file_locations()
        self._backfill_knowledge_indexes()
        self._backfill_run_workspaces()

    def _connect(self) -> _DatabaseConnection:
        if self.is_postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:  # pragma: no cover - exercised in deployment
                raise RuntimeError("PostgreSQL mode requires psycopg[binary]") from exc
            connection = psycopg.connect(self.database_url, row_factory=dict_row)
            return _DatabaseConnection(connection, postgres=True)
        connection = sqlite3.connect(
            self.path.as_posix(),
            check_same_thread=False,
            timeout=30,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return _DatabaseConnection(connection, postgres=False)

    def _init_schema(self) -> None:
        with self._connect() as db:
            if not db.postgres:
                # Long-running Agent execution continuously appends events while
                # browser/API readers inspect the same Run. WAL keeps those
                # readers from blocking writers; a longer busy timeout absorbs
                # short writer bursts instead of failing the whole node.
                db.execute("PRAGMA journal_mode = WAL")
                db.execute("PRAGMA synchronous = NORMAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS organizations (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_name TEXT NOT NULL DEFAULT '发起人',
                    world_type TEXT NOT NULL DEFAULT 'open_society',
                    user_identity TEXT NOT NULL DEFAULT '发起人',
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_blueprints (
                    id TEXT PRIMARY KEY,
                    family_id TEXT,
                    parent_agent_id TEXT,
                    organization_id TEXT NOT NULL DEFAULT 'org_jianghu',
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    persona TEXT NOT NULL DEFAULT '',
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    cognitive_level INTEGER NOT NULL DEFAULT 2,
                    authority_level INTEGER NOT NULL DEFAULT 1,
                    skills_json TEXT NOT NULL DEFAULT '[]',
                    runtime TEXT NOT NULL DEFAULT 'claude_code',
                    memory_policy_json TEXT NOT NULL DEFAULT '{}',
                    version TEXT NOT NULL DEFAULT '1.0.0',
                    visibility TEXT NOT NULL DEFAULT 'private',
                    status TEXT NOT NULL DEFAULT 'active',
                    merged_into_agent_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_teams (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    purpose TEXT NOT NULL DEFAULT '',
                    operating_mode TEXT NOT NULL DEFAULT 'collaborative',
                    knowledge_paths_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'ready',
                    visibility TEXT NOT NULL DEFAULT 'private',
                    version TEXT NOT NULL DEFAULT '1.0.0',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(organization_id) REFERENCES organizations(id)
                );
                CREATE TABLE IF NOT EXISTS team_members (
                    team_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    member_role TEXT NOT NULL DEFAULT 'member',
                    responsibility TEXT NOT NULL DEFAULT '',
                    position_no INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(team_id,agent_id),
                    FOREIGN KEY(team_id) REFERENCES agent_teams(id),
                    FOREIGN KEY(agent_id) REFERENCES agent_blueprints(id)
                );
                CREATE TABLE IF NOT EXISTS company_tasks (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'assessing',
                    selected_team_ids_json TEXT NOT NULL DEFAULT '[]',
                    workflow_id TEXT,
                    run_id TEXT,
                    git_delivery_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(organization_id) REFERENCES organizations(id)
                );
                CREATE TABLE IF NOT EXISTS team_assessments (
                    id TEXT PRIMARY KEY,
                    company_task_id TEXT NOT NULL,
                    team_id TEXT,
                    fit_status TEXT NOT NULL,
                    fit_score INTEGER NOT NULL DEFAULT 0,
                    reasoning TEXT NOT NULL DEFAULT '',
                    missing_capabilities_json TEXT NOT NULL DEFAULT '[]',
                    recommended_agents_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(company_task_id) REFERENCES company_tasks(id),
                    FOREIGN KEY(team_id) REFERENCES agent_teams(id)
                );
                CREATE TABLE IF NOT EXISTS team_proposals (
                    id TEXT PRIMARY KEY,
                    company_task_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    existing_team_id TEXT,
                    name TEXT NOT NULL DEFAULT '',
                    purpose TEXT NOT NULL DEFAULT '',
                    operating_mode TEXT NOT NULL DEFAULT 'collaborative',
                    members_json TEXT NOT NULL DEFAULT '[]',
                    fit_score INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '',
                    missing_capabilities_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'pending',
                    confirmed_team_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(company_task_id) REFERENCES company_tasks(id),
                    FOREIGN KEY(organization_id) REFERENCES organizations(id),
                    FOREIGN KEY(existing_team_id) REFERENCES agent_teams(id),
                    FOREIGN KEY(confirmed_team_id) REFERENCES agent_teams(id)
                );
                CREATE INDEX IF NOT EXISTS idx_team_proposals_task
                ON team_proposals(company_task_id,status,updated_at DESC);
                CREATE TABLE IF NOT EXISTS operation_logs (
                    id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL DEFAULT 'org_jianghu',
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    version TEXT NOT NULL DEFAULT '1.0.0',
                    status TEXT NOT NULL DEFAULT 'draft',
                    source TEXT NOT NULL DEFAULT 'generated',
                    definition_json TEXT NOT NULL,
                    agent_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS clarification_sessions (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    original_requirement TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'questioning',
                    questions_json TEXT NOT NULL DEFAULT '[]',
                    answers_json TEXT NOT NULL DEFAULT '[]',
                    contract_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(workflow_id) REFERENCES workflows(id)
                );
                CREATE TABLE IF NOT EXISTS model_configs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    model TEXT NOT NULL,
                    tier TEXT NOT NULL DEFAULT 'medium',
                    encrypted_token TEXT NOT NULL,
                    token_hint TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS git_delivery_configs (
                    project_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL DEFAULT 'generic',
                    repository_url TEXT NOT NULL DEFAULT '',
                    api_base_url TEXT NOT NULL DEFAULT '',
                    default_branch TEXT NOT NULL DEFAULT 'main',
                    delivery_mode TEXT NOT NULL DEFAULT 'local_commit',
                    username TEXT NOT NULL DEFAULT '',
                    encrypted_token TEXT NOT NULL DEFAULT '',
                    token_hint TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );
                CREATE TABLE IF NOT EXISTS git_credentials (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT 'github',
                    api_base_url TEXT NOT NULL DEFAULT '',
                    username TEXT NOT NULL DEFAULT '',
                    encrypted_token TEXT NOT NULL,
                    token_hint TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_git_repositories (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    repository_url TEXT NOT NULL,
                    default_branch TEXT NOT NULL DEFAULT 'main',
                    credential_id TEXT,
                    default_delivery_mode TEXT NOT NULL DEFAULT 'create_merge_request',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id,repository_url),
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(credential_id) REFERENCES git_credentials(id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_sources (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    uri TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'registered',
                    version INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL,
                    team_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    locator TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    token_estimate INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(source_id) REFERENCES knowledge_sources(id)
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_source
                ON knowledge_chunks(source_id,chunk_index);
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_team
                ON knowledge_chunks(team_id,source_id);
                CREATE TABLE IF NOT EXISTS knowledge_bindings (
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    access_mode TEXT NOT NULL DEFAULT 'read',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(entity_type,entity_id,source_id),
                    FOREIGN KEY(source_id) REFERENCES knowledge_sources(id)
                );
                CREATE TABLE IF NOT EXISTS agent_memories (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'experience',
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    source_run_id TEXT,
                    source_task_id TEXT,
                    visibility TEXT NOT NULL DEFAULT 'private',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(agent_id) REFERENCES agent_blueprints(id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_memories_agent
                ON agent_memories(agent_id,created_at DESC);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    run_family_id TEXT NOT NULL DEFAULT '',
                    run_version INTEGER NOT NULL DEFAULT 1,
                    parent_run_id TEXT,
                    project_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL DEFAULT 'org_jianghu',
                    workflow_id TEXT NOT NULL,
                    task_input TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    progress INTEGER NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL DEFAULT 'created',
                    estimated_cost REAL NOT NULL DEFAULT 0,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(workflow_id) REFERENCES workflows(id)
                );
                CREATE TABLE IF NOT EXISTS run_git_deliveries (
                    run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    repository_id TEXT NOT NULL,
                    repository_name TEXT NOT NULL,
                    repository_url TEXT NOT NULL,
                    target_branch TEXT NOT NULL,
                    delivery_mode TEXT NOT NULL,
                    credential_id TEXT,
                    provider TEXT NOT NULL,
                    api_base_url TEXT NOT NULL DEFAULT '',
                    username TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id),
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(repository_id) REFERENCES project_git_repositories(id),
                    FOREIGN KEY(credential_id) REFERENCES git_credentials(id)
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL DEFAULT 'org_jianghu',
                    node_key TEXT NOT NULL,
                    node_name TEXT NOT NULL,
                    agent_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    input_json TEXT NOT NULL DEFAULT '{}',
                    output_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL DEFAULT 'org_jianghu',
                    task_id TEXT,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL DEFAULT 'org_jianghu',
                    sequence INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, sequence),
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );
                CREATE INDEX IF NOT EXISTS idx_events_artifact_lookup
                ON events(run_id,type,created_at);
                CREATE TABLE IF NOT EXISTS run_interventions (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL DEFAULT 'org_jianghu',
                    task_id TEXT,
                    agent_id TEXT,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    created_at TEXT NOT NULL,
                    applied_at TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id),
                    FOREIGN KEY(task_id) REFERENCES tasks(id),
                    FOREIGN KEY(agent_id) REFERENCES agent_blueprints(id)
                );
                CREATE INDEX IF NOT EXISTS idx_run_interventions_run
                ON run_interventions(run_id,status,created_at);
                CREATE TABLE IF NOT EXISTS showcase_comparisons (
                    id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    baseline_run_id TEXT NOT NULL,
                    multi_run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(baseline_run_id) REFERENCES runs(id),
                    FOREIGN KEY(multi_run_id) REFERENCES runs(id)
                );
                CREATE INDEX IF NOT EXISTS idx_showcase_comparisons_case
                ON showcase_comparisons(case_id,created_at DESC);
                """
            )
            run_columns = {str(_row_value(row, "name", 1)) for row in db.execute("PRAGMA table_info(runs)").fetchall()}
            if "clarification_id" not in run_columns:
                db.execute("ALTER TABLE runs ADD COLUMN clarification_id TEXT")
            if "organization_id" not in run_columns:
                db.execute("ALTER TABLE runs ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'org_jianghu'")
            if "run_family_id" not in run_columns:
                db.execute("ALTER TABLE runs ADD COLUMN run_family_id TEXT NOT NULL DEFAULT ''")
            if "run_version" not in run_columns:
                db.execute("ALTER TABLE runs ADD COLUMN run_version INTEGER NOT NULL DEFAULT 1")
            if "parent_run_id" not in run_columns:
                db.execute("ALTER TABLE runs ADD COLUMN parent_run_id TEXT")
            memory_columns = {str(_row_value(row, "name", 1)) for row in db.execute("PRAGMA table_info(agent_memories)").fetchall()}
            if "status" not in memory_columns:
                db.execute("ALTER TABLE agent_memories ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
            if "version" not in memory_columns:
                db.execute("ALTER TABLE agent_memories ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
            if "supersedes_id" not in memory_columns:
                db.execute("ALTER TABLE agent_memories ADD COLUMN supersedes_id TEXT")
            if "tombstoned_at" not in memory_columns:
                db.execute("ALTER TABLE agent_memories ADD COLUMN tombstoned_at TEXT")
            db.execute("UPDATE runs SET run_family_id=id WHERE run_family_id IS NULL OR run_family_id='' ")
            db.execute("UPDATE runs SET run_version=1 WHERE run_version IS NULL OR run_version < 1")
            retry_events = db.execute(
                "SELECT run_id,payload_json FROM events WHERE type='run.retry_created' ORDER BY created_at"
            ).fetchall()
            for retry_event in retry_events:
                child_id = str(retry_event["run_id"] or "")
                if not child_id:
                    continue
                child = db.execute(
                    "SELECT run_family_id,run_version,parent_run_id FROM runs WHERE id=?",
                    (child_id,),
                ).fetchone()
                if not child or str(child["parent_run_id"] or ""):
                    continue
                try:
                    payload = json.loads(str(retry_event["payload_json"] or "{}"))
                except (TypeError, ValueError):
                    payload = {}
                source_id = str(payload.get("source_run_id") or "")
                if not source_id:
                    continue
                source = db.execute("SELECT run_family_id FROM runs WHERE id=?", (source_id,)).fetchone()
                if not source:
                    continue
                family_id = str(source["run_family_id"] or source_id)
                next_version = db.execute(
                    "SELECT COALESCE(MAX(run_version),0)+1 AS value FROM runs WHERE run_family_id=?",
                    (family_id,),
                ).fetchone()
                db.execute(
                    "UPDATE runs SET run_family_id=?,run_version=?,parent_run_id=? WHERE id=?",
                    (family_id, int(_row_value(next_version, "value") or 1), source_id, child_id),
                )
            task_columns = {str(_row_value(row, "name", 1)) for row in db.execute("PRAGMA table_info(tasks)").fetchall()}
            if "organization_id" not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'org_jianghu'")
            db.execute(
                """UPDATE tasks SET organization_id=COALESCE(
                    (SELECT r.organization_id FROM runs r WHERE r.id=tasks.run_id),
                    organization_id,
                    'org_jianghu'
                )"""
            )
            if "team_id" not in task_columns:
                db.execute("ALTER TABLE tasks ADD COLUMN team_id TEXT")
            db.execute(
                """UPDATE tasks SET status='cancelled',updated_at=?
                WHERE status NOT IN ('completed','failed','cancelled')
                AND run_id IN (SELECT id FROM runs WHERE status='cancelled')""",
                (utc_now(),),
            )
            artifact_columns = {str(_row_value(row, "name", 1)) for row in db.execute("PRAGMA table_info(artifacts)").fetchall()}
            if "organization_id" not in artifact_columns:
                db.execute("ALTER TABLE artifacts ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'org_jianghu'")
            db.execute(
                """UPDATE artifacts SET organization_id=COALESCE(
                    (SELECT r.organization_id FROM runs r WHERE r.id=artifacts.run_id),
                    organization_id,
                    'org_jianghu'
                )"""
            )
            if "relative_path" not in artifact_columns:
                db.execute("ALTER TABLE artifacts ADD COLUMN relative_path TEXT NOT NULL DEFAULT ''")
            if "sha256" not in artifact_columns:
                db.execute("ALTER TABLE artifacts ADD COLUMN sha256 TEXT NOT NULL DEFAULT ''")
            if "media_type" not in artifact_columns:
                db.execute("ALTER TABLE artifacts ADD COLUMN media_type TEXT NOT NULL DEFAULT 'text/markdown'")
            if "size_bytes" not in artifact_columns:
                db.execute("ALTER TABLE artifacts ADD COLUMN size_bytes INTEGER NOT NULL DEFAULT 0")
            event_columns = {str(_row_value(row, "name", 1)) for row in db.execute("PRAGMA table_info(events)").fetchall()}
            if "organization_id" not in event_columns:
                db.execute("ALTER TABLE events ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'org_jianghu'")
            db.execute(
                """UPDATE events SET organization_id=COALESCE(
                    (SELECT r.organization_id FROM runs r WHERE r.id=events.run_id),
                    organization_id,
                    'org_jianghu'
                )"""
            )
            intervention_columns = {str(_row_value(row, "name", 1)) for row in db.execute("PRAGMA table_info(run_interventions)").fetchall()}
            if "organization_id" not in intervention_columns:
                db.execute("ALTER TABLE run_interventions ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'org_jianghu'")
            db.execute(
                """UPDATE run_interventions SET organization_id=COALESCE(
                    (SELECT r.organization_id FROM runs r WHERE r.id=run_interventions.run_id),
                    organization_id,
                    'org_jianghu'
                )"""
            )
            team_columns = {str(_row_value(row, "name", 1)) for row in db.execute("PRAGMA table_info(agent_teams)").fetchall()}
            if "knowledge_paths_json" not in team_columns:
                db.execute("ALTER TABLE agent_teams ADD COLUMN knowledge_paths_json TEXT NOT NULL DEFAULT '[]'")
            agent_columns = {str(_row_value(row, "name", 1)) for row in db.execute("PRAGMA table_info(agent_blueprints)").fetchall()}
            if "organization_id" not in agent_columns:
                db.execute("ALTER TABLE agent_blueprints ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'org_jianghu'")
            if "status" not in agent_columns:
                db.execute("ALTER TABLE agent_blueprints ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
            if "merged_into_agent_id" not in agent_columns:
                db.execute("ALTER TABLE agent_blueprints ADD COLUMN merged_into_agent_id TEXT")
            if "family_id" not in agent_columns:
                db.execute("ALTER TABLE agent_blueprints ADD COLUMN family_id TEXT")
            if "parent_agent_id" not in agent_columns:
                db.execute("ALTER TABLE agent_blueprints ADD COLUMN parent_agent_id TEXT")
            if "skills_json" not in agent_columns:
                db.execute("ALTER TABLE agent_blueprints ADD COLUMN skills_json TEXT NOT NULL DEFAULT '[]'")
            if "runtime" not in agent_columns:
                db.execute("ALTER TABLE agent_blueprints ADD COLUMN runtime TEXT NOT NULL DEFAULT 'claude_code'")
            if "memory_policy_json" not in agent_columns:
                db.execute("ALTER TABLE agent_blueprints ADD COLUMN memory_policy_json TEXT NOT NULL DEFAULT '{}'")
            db.execute("UPDATE agent_blueprints SET runtime='claude_code' WHERE runtime='openclaw'")
            db.execute("UPDATE agent_blueprints SET family_id=id WHERE family_id IS NULL OR family_id='' ")
            workflow_columns = {str(_row_value(row, "name", 1)) for row in db.execute("PRAGMA table_info(workflows)").fetchall()}
            if "family_id" not in workflow_columns:
                db.execute("ALTER TABLE workflows ADD COLUMN family_id TEXT")
            if "parent_workflow_id" not in workflow_columns:
                db.execute("ALTER TABLE workflows ADD COLUMN parent_workflow_id TEXT")
            if "organization_id" not in workflow_columns:
                db.execute("ALTER TABLE workflows ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'org_jianghu'")
            db.execute("UPDATE workflows SET family_id=id WHERE family_id IS NULL OR family_id='' ")
            db.execute(
                """UPDATE runs SET organization_id=COALESCE(
                    (SELECT w.organization_id FROM workflows w WHERE w.id=runs.workflow_id),
                    organization_id,
                    'org_jianghu'
                )"""
            )
            commission_columns = {str(_row_value(row, "name", 1)) for row in db.execute("PRAGMA table_info(company_tasks)").fetchall()}
            if "workflow_id" not in commission_columns:
                db.execute("ALTER TABLE company_tasks ADD COLUMN workflow_id TEXT")
            if "run_id" not in commission_columns:
                db.execute("ALTER TABLE company_tasks ADD COLUMN run_id TEXT")
            if "git_delivery_json" not in commission_columns:
                db.execute("ALTER TABLE company_tasks ADD COLUMN git_delivery_json TEXT NOT NULL DEFAULT '{}'")
            organization_columns = {str(_row_value(row, "name", 1)) for row in db.execute("PRAGMA table_info(organizations)").fetchall()}
            if "world_type" not in organization_columns:
                db.execute("ALTER TABLE organizations ADD COLUMN world_type TEXT NOT NULL DEFAULT 'open_society'")
            if "user_identity" not in organization_columns:
                db.execute("ALTER TABLE organizations ADD COLUMN user_identity TEXT NOT NULL DEFAULT '发起人'")
            model_columns = {str(_row_value(row, "name", 1)) for row in db.execute("PRAGMA table_info(model_configs)").fetchall()}
            if "tier" not in model_columns:
                db.execute("ALTER TABLE model_configs ADD COLUMN tier TEXT NOT NULL DEFAULT 'medium'")
            db.execute("UPDATE model_configs SET tier='medium' WHERE tier IS NULL OR tier NOT IN ('high','medium','low')")
            agent_columns = {str(_row_value(row, "name", 1)) for row in db.execute("PRAGMA table_info(agent_blueprints)").fetchall()}
            if "cognitive_level" not in agent_columns:
                db.execute("ALTER TABLE agent_blueprints ADD COLUMN cognitive_level INTEGER NOT NULL DEFAULT 2")
            if "authority_level" not in agent_columns:
                db.execute("ALTER TABLE agent_blueprints ADD COLUMN authority_level INTEGER NOT NULL DEFAULT 1")
            db.execute("UPDATE agent_blueprints SET cognitive_level=2 WHERE cognitive_level IS NULL OR cognitive_level NOT BETWEEN 1 AND 3")
            db.execute("UPDATE agent_blueprints SET authority_level=1 WHERE authority_level IS NULL OR authority_level NOT BETWEEN 1 AND 3")
            db.execute("UPDATE organizations SET owner_name='发起人' WHERE owner_name='老板'")
            db.execute("UPDATE model_configs SET token_hint=REPLACE(token_hint,'••••','****')")

    def _ensure_workspace(self) -> None:
        """Create the default workspace and its single reusable starter person."""
        now = utc_now()
        with self._connect() as db:
            if db.execute("SELECT 1 FROM projects LIMIT 1").fetchone() is None:
                db.execute(
                    "INSERT INTO projects(id,name,description,created_at) VALUES(?,?,?,?)",
                    ("project_jianghu", "Jianghu Online", "Persistent platform workspace", now),
                )
            if db.execute("SELECT 1 FROM organizations LIMIT 1").fetchone() is None:
                db.execute(
                    "INSERT INTO organizations(id,name,owner_name,world_type,user_identity,description,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    ("org_jianghu", "我的江湖", "发起人", "open_society", "发起人", "由人与 Agent 共同形成、协作、竞争和演化的社会世界。", now, now),
                )
            db.execute(
                """UPDATE organizations SET name='我的江湖',owner_name='发起人',world_type='open_society',
                user_identity='发起人',description='由人与 Agent 共同形成、协作、竞争和演化的社会世界。',updated_at=?
                WHERE id='org_jianghu' AND (name LIKE '%Agent 公司%' OR name LIKE '%公司%' OR world_type!='open_society')""",
                (now,),
            )
            if db.execute("SELECT 1 FROM agent_blueprints LIMIT 1").fetchone() is None:
                db.execute(
                    """INSERT INTO agent_blueprints
                    (id,family_id,parent_agent_id,name,role,description,persona,capabilities_json,skills_json,runtime,
                    memory_policy_json,version,visibility,status,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        STARTER_STRATEGIST["id"], STARTER_STRATEGIST["id"], None,
                        STARTER_STRATEGIST["name"], STARTER_STRATEGIST["role"],
                        STARTER_STRATEGIST["description"], STARTER_STRATEGIST["persona"],
                        json.dumps(STARTER_STRATEGIST["capabilities"], ensure_ascii=False),
                        json.dumps(STARTER_STRATEGIST["skills"], ensure_ascii=False),
                        "claude_code", json.dumps(STARTER_STRATEGIST["memory_policy"], ensure_ascii=False),
                        "1.0.0", "public", "active", now, now,
                    ),
                )
            personified_defaults = {
                "Backend Engineer": ("林砚", "后端工程师", "负责领域逻辑、数据和接口实现。", "林砚是一位审慎务实的后端工程师，重视证据、边界和可恢复性，会直接指出不可执行的设计。"),
                "Experience Designer": ("苏晴", "体验设计师", "负责理解真实用户旅程并检验交互可用性。", "苏晴善于观察人的行为与情绪，会从不同社会身份出发质疑自说自话的设计。"),
                "Frontend Engineer": ("周野", "前端工程师", "负责客户端实现、视觉表达和交互反馈。", "周野重视可感知的真实反馈，愿意为体验与实现复杂度展开有依据的争论。"),
                "Independent Judge": ("顾衡", "独立裁判", "使用独立身份、上下文和标准作出验收判断。", "顾衡不参与候选方案创作，只依据证据、规则和验收标准裁决，并明确保留意见。"),
                "Product Lead": ("沈知微", "产品负责人", "负责澄清目标、范围、价值与验收边界。", "沈知微关注事情为何值得做，善于追问隐含假设，也尊重不同角色的真实利益。"),
                "Red Team Reviewer": ("陆谨言", "安全与风险审计师", "负责红线核查、攻击性验证以及逻辑和交付风险审查。", "陆谨言谨慎、尖锐且独立，会主动寻找失效路径；红线检查是他的工作能力，而不是他的身份。"),
                "System Architect": ("程观澜", "系统架构师", "负责系统边界、接口、约束和技术权衡。", "程观澜习惯从全局关系和长期演化判断方案，能清楚说明每项技术取舍的代价。"),
            }
            for legacy_name, (name, role, description, persona) in personified_defaults.items():
                db.execute(
                    """UPDATE agent_blueprints SET name=?,role=?,description=?,persona=?,updated_at=?
                    WHERE name=? AND visibility='public'""",
                    (name, role, description, persona, now, legacy_name),
                )
            readable_capabilities = {
                "前端工程师": ["前端开发", "交互实现", "结构化表达", "证据追踪"],
                "后端工程师": ["后端开发", "领域建模", "接口设计", "证据追踪"],
                "产品负责人": ["需求澄清", "范围管理", "验收设计", "证据追踪"],
                "系统架构师": ["系统架构", "边界设计", "技术权衡", "证据追踪"],
                "体验设计师": ["用户研究", "体验设计", "可用性检验", "证据追踪"],
                "安全与风险审计师": ["红线核查", "攻击性验证", "风险审计", "证据追踪"],
                "独立裁判": ["独立评审", "证据核验", "验收裁决", "保留意见"],
            }
            for role, capabilities in readable_capabilities.items():
                db.execute(
                    "UPDATE agent_blueprints SET capabilities_json=?,updated_at=? WHERE role=? AND visibility='public'",
                    (json.dumps(capabilities, ensure_ascii=False), now, role),
                )
            duplicate_groups = db.execute(
                """SELECT name,role FROM agent_blueprints WHERE status='active'
                GROUP BY name,role HAVING COUNT(*) > 1"""
            ).fetchall()
            for group in duplicate_groups:
                duplicates = db.execute(
                    "SELECT * FROM agent_blueprints WHERE status='active' AND name=? AND role=?",
                    (group["name"], group["role"]),
                ).fetchall()
                canonical = max(
                    duplicates,
                    key=lambda row: len(row["description"] or "") + len(row["persona"] or "") + len(row["capabilities_json"] or ""),
                )
                for duplicate in duplicates:
                    if duplicate["id"] == canonical["id"]:
                        continue
                    memberships = db.execute("SELECT * FROM team_members WHERE agent_id=?", (duplicate["id"],)).fetchall()
                    for membership in memberships:
                        existing_membership = db.execute(
                            "SELECT 1 FROM team_members WHERE team_id=? AND agent_id=?",
                            (membership["team_id"], canonical["id"]),
                        ).fetchone()
                        if existing_membership:
                            db.execute("DELETE FROM team_members WHERE team_id=? AND agent_id=?", (membership["team_id"], duplicate["id"]))
                        else:
                            db.execute(
                                "UPDATE team_members SET agent_id=? WHERE team_id=? AND agent_id=?",
                                (canonical["id"], membership["team_id"], duplicate["id"]),
                            )
                    db.execute(
                        "UPDATE agent_blueprints SET status='merged',merged_into_agent_id=?,updated_at=? WHERE id=?",
                        (canonical["id"], now, duplicate["id"]),
                    )
                    db.execute(
                        "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                        (new_id("log"), "agent_blueprint", duplicate["id"], "merged", json.dumps({"merged_into_agent_id": canonical["id"]}, ensure_ascii=False), now),
                    )
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_active_agent_identity ON agent_blueprints(name,role) WHERE status='active'"
            )
            # Preserve the original English starter WorkflowVersion as history,
            # but publish a Chinese, selectively staffed successor. This avoids
            # mutating a frozen asset while keeping obsolete demo wording and
            # "everyone attends every node" bindings out of the default view.
            legacy_workflow = db.execute(
                """SELECT * FROM workflows
                WHERE source='seed' AND name='Requirements to Runnable Demo'
                ORDER BY created_at LIMIT 1"""
            ).fetchone()
            if legacy_workflow:
                family_id = str(legacy_workflow["family_id"] or legacy_workflow["id"])
                migrated = db.execute(
                    "SELECT 1 FROM workflows WHERE family_id=? AND source='system_migrated' LIMIT 1",
                    (family_id,),
                ).fetchone()
                active_agents = db.execute(
                    "SELECT id,name,role FROM agent_blueprints WHERE status='active' ORDER BY created_at"
                ).fetchall()
                if not migrated and active_agents:
                    def find_agent(*role_keywords: str) -> sqlite3.Row:
                        return next(
                            (
                                row for row in active_agents
                                if any(keyword in str(row["role"]) for keyword in role_keywords)
                            ),
                            active_agents[0],
                        )

                    product = find_agent("产品负责人", "产品")
                    experience = find_agent("体验设计师", "体验")
                    architect = find_agent("系统架构师", "架构")
                    backend = find_agent("后端工程师", "后端")
                    frontend = find_agent("前端工程师", "前端")
                    quality = find_agent("质量工程师", "测试")
                    security = find_agent("安全与风险审计师", "安全")
                    judge = find_agent("独立裁判", "裁判")
                    team_row = db.execute(
                        "SELECT id FROM agent_teams WHERE status!='disbanded' ORDER BY updated_at DESC LIMIT 1"
                    ).fetchone()
                    team_id = str(team_row["id"]) if team_row else ""
                    team_members = {
                        str(row["agent_id"])
                        for row in db.execute("SELECT agent_id FROM team_members WHERE team_id=?", (team_id,)).fetchall()
                    } if team_id else set()

                    def production_node(
                        key: str,
                        name: str,
                        purpose: str,
                        lead: sqlite3.Row,
                        participants: list[sqlite3.Row],
                    ) -> dict[str, Any]:
                        participant_ids = list(dict.fromkeys(str(item["id"]) for item in participants))
                        node = {
                            "key": key,
                            "name": name,
                            "purpose": purpose,
                            "type": "team_task",
                            "agent_id": str(lead["id"]),
                            "agent_role": str(lead["role"]),
                            "communication_rounds": 1,
                        }
                        if team_id and set(participant_ids).issubset(team_members):
                            node["team_id"] = team_id
                            node["participant_agent_ids"] = participant_ids
                        return node

                    nodes = [
                        production_node(
                            "clarify", "需求澄清与范围基线",
                            "明确目标、边界、约束、验收口径和待确认问题。",
                            product, [product, experience],
                        ),
                        production_node(
                            "acceptance", "验收标准与证据设计",
                            "把需求转化为可执行验收标准、测试场景和证据要求。",
                            quality, [quality, product],
                        ),
                        production_node(
                            "architecture", "架构与接口设计",
                            "形成领域边界、数据与接口契约、技术权衡和部署约束。",
                            architect, [architect, backend],
                        ),
                        production_node(
                            "implementation", "可运行实现",
                            "交付真实源代码、构建配置、数据迁移和可启动版本。",
                            backend, [backend, frontend],
                        ),
                        production_node(
                            "quality", "质量验证与缺陷挑战",
                            "执行功能、集成、回归、性能与异常验证并提交证据。",
                            quality, [quality],
                        ),
                        production_node(
                            "security", "安全与风险审计",
                            "执行权限、输入、敏感数据和滥用路径的攻击性验证。",
                            security, [security],
                        ),
                        production_node(
                            "revision", "缺陷整改与候选版封装",
                            "依据质量与安全意见完成整改并形成可复验候选版本。",
                            backend, [backend, frontend, architect],
                        ),
                        {
                            "key": "judge",
                            "name": "独立验收裁决",
                            "purpose": "由未参与创作的独立裁判核验证据；不通过时定向打回责任节点。",
                            "type": "judge",
                            "agent_id": str(judge["id"]),
                            "agent_role": str(judge["role"]),
                        },
                    ]
                    edges = [
                        ["clarify", "acceptance"], ["clarify", "architecture"],
                        ["acceptance", "implementation"], ["architecture", "implementation"],
                        ["implementation", "quality"], ["implementation", "security"],
                        ["quality", "revision"], ["security", "revision"],
                        ["revision", "judge"],
                    ]
                    definition = {
                        "schema_version": "1.0",
                        "inputs": ["task"],
                        "outputs": ["runnable_delivery", "judge_decision"],
                        "nodes": nodes,
                        "edges": edges,
                        "policies": {
                            "max_parallel_agents": 5,
                            "max_debate_rounds": 3,
                            "max_revision_rounds": 3,
                            "max_run_minutes": 180,
                        },
                    }
                    workflow_id = new_id("workflow")
                    bound_ids = list(dict.fromkeys(str(node["agent_id"]) for node in nodes))
                    db.execute(
                        """INSERT INTO workflows
                        (id,family_id,parent_workflow_id,name,description,version,status,source,
                        definition_json,agent_ids_json,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            workflow_id, family_id, legacy_workflow["id"], "从需求到可运行交付",
                            "需求与验收并行定标，架构与真实开发完成后由质量和安全分别挑战；整改形成候选版本，独立裁判不通过时自动定向打回并重新裁决。",
                            "1.1.0", "ready", "system_migrated",
                            json.dumps(definition, ensure_ascii=False),
                            json.dumps(bound_ids, ensure_ascii=False), now, now,
                        ),
                    )

    @staticmethod
    def _safe_segment(value: object, fallback: str = "item") -> str:
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip(".-")
        return normalized[:96] or fallback

    def _run_workspace(self, project_id: str, run_id: str) -> Path:
        root = self.workspace_root / self._safe_segment(project_id, "project") / "runs" / self._safe_segment(run_id, "run")
        resolved = root.resolve()
        if not resolved.is_relative_to(self.workspace_root):
            raise ValueError("invalid_run_workspace_path")
        return resolved

    @staticmethod
    def _write_bytes_atomic(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    @classmethod
    def _write_text_atomic(cls, path: Path, content: str) -> None:
        cls._write_bytes_atomic(path, content.encode("utf-8"))

    def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        self._write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2))

    def _ensure_run_workspace(
        self,
        run_record: dict[str, Any],
        workflow: dict[str, Any],
        *,
        source_run_id: str | None = None,
    ) -> dict[str, str]:
        root = self._run_workspace(str(run_record["project_id"]), str(run_record["id"]))
        directories = {
            "input": root / "input",
            "workflow": root / "workflow",
            "artifacts": root / "artifacts",
            "code": root / "code",
            "logs": root / "logs",
            "tmp": root / "tmp",
        }
        for directory in directories.values():
            directory.mkdir(parents=True, exist_ok=True)
        task_path = directories["input"] / "task.json"
        workflow_path = directories["workflow"] / "workflow.json"
        if not task_path.exists():
            self._write_json_atomic(
                task_path,
                {
                    "schema_version": "jianghu.run-input.v1",
                    "run_id": run_record["id"],
                    "run_family_id": run_record.get("run_family_id") or run_record["id"],
                    "run_version": run_record.get("run_version") or 1,
                    "project_id": run_record["project_id"],
                    "task_input": run_record["task_input"],
                    "clarification_id": run_record.get("clarification_id"),
                    "source_run_id": source_run_id,
                    "created_at": run_record["created_at"],
                },
            )
        if not workflow_path.exists():
            self._write_json_atomic(
                workflow_path,
                {
                    "schema_version": "jianghu.workflow-snapshot.v1",
                    "workflow_id": workflow["id"],
                    "family_id": workflow.get("family_id") or workflow["id"],
                    "version": workflow["version"],
                    "name": workflow["name"],
                    "description": workflow["description"],
                    "definition": workflow["definition"],
                },
            )
        manifest_path = root / "manifest.json"
        manifest = {
            "schema_version": "jianghu.run-workspace.v1",
            "run_id": run_record["id"],
            "run_family_id": run_record.get("run_family_id") or run_record["id"],
            "run_version": run_record.get("run_version") or 1,
            "project_id": run_record["project_id"],
            "workflow": {
                "id": workflow["id"],
                "family_id": workflow.get("family_id") or workflow["id"],
                "version": workflow["version"],
                "snapshot": "workflow/workflow.json",
            },
            "input": "input/task.json",
            "artifact_root": "artifacts",
            "code_root": "code",
            "log_root": "logs",
            "temporary_root": "tmp",
            "source_run_id": source_run_id,
            "artifacts": [],
        }
        if manifest_path.exists():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    manifest.update(existing)
            except (OSError, ValueError):
                pass
        self._write_json_atomic(manifest_path, manifest)
        return {
            "root": str(root),
            "manifest": str(manifest_path),
            "input": str(directories["input"]),
            "workflow": str(directories["workflow"]),
            "artifacts": str(directories["artifacts"]),
            "code": str(directories["code"]),
            "logs": str(directories["logs"]),
            "tmp": str(directories["tmp"]),
        }

    def _materialize_artifact(self, artifact: dict[str, Any], *, node_key: str) -> dict[str, Any]:
        with self._connect() as db:
            run_row = db.execute("SELECT * FROM runs WHERE id=?", (artifact["run_id"],)).fetchone()
            if not run_row:
                raise ValueError("run_not_found")
            workflow_row = db.execute("SELECT * FROM workflows WHERE id=?", (run_row["workflow_id"],)).fetchone()
            if not workflow_row:
                raise ValueError("workflow_not_found")
        run_record = dict(run_row)
        workflow = self._workflow(workflow_row)
        workspace = self._ensure_run_workspace(run_record, workflow)
        root = Path(workspace["root"])
        node_directory = self._safe_segment(node_key, "node")
        relative_path = Path("artifacts") / node_directory / f"{self._safe_segment(artifact['id'], 'artifact')}.md"
        destination = (root / relative_path).resolve()
        if not destination.is_relative_to(root):
            raise ValueError("invalid_artifact_path")
        content = str(artifact["content"])
        content_bytes = content.encode("utf-8")
        self._write_bytes_atomic(destination, content_bytes)
        digest = hashlib.sha256(content_bytes).hexdigest()
        size_bytes = len(content_bytes)
        artifact.update(
            {
                "relative_path": relative_path.as_posix(),
                "sha256": digest,
                "media_type": "text/markdown",
                "size_bytes": size_bytes,
            }
        )
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = [item for item in manifest.get("artifacts", []) if item.get("id") != artifact["id"]]
        entries.append(
            {
                "id": artifact["id"],
                "task_id": artifact.get("task_id"),
                "kind": artifact["kind"],
                "title": artifact["title"],
                "status": artifact["status"],
                "version": artifact["version"],
                "path": artifact["relative_path"],
                "media_type": artifact["media_type"],
                "size_bytes": artifact["size_bytes"],
                "sha256": artifact["sha256"],
                "created_at": artifact["created_at"],
            }
        )
        manifest["artifacts"] = sorted(entries, key=lambda item: (str(item.get("created_at")), str(item.get("id"))))
        self._write_json_atomic(manifest_path, manifest)
        return artifact

    def _backfill_run_workspaces(self) -> None:
        with self._connect() as db:
            run_rows = db.execute("SELECT * FROM runs ORDER BY created_at").fetchall()
        for run_row in run_rows:
            run_record = dict(run_row)
            workflow = self.get_workflow(str(run_record["workflow_id"]))
            if not workflow:
                continue
            workspace = self._ensure_run_workspace(run_record, workflow)
            with self._connect() as db:
                artifact_rows = db.execute(
                    """SELECT a.*,COALESCE(t.node_key,'artifact') AS node_key
                    FROM artifacts a LEFT JOIN tasks t ON t.id=a.task_id WHERE a.run_id=?""",
                    (run_record["id"],),
                ).fetchall()
            for artifact_row in artifact_rows:
                artifact = dict(artifact_row)
                node_key = str(artifact.pop("node_key", "artifact"))
                if artifact.get("relative_path"):
                    relative_path = Path(str(artifact["relative_path"]))
                    destination = (Path(workspace["root"]) / relative_path).resolve()
                    workspace_root = Path(workspace["root"]).resolve()
                    canonical_bytes = str(artifact.get("content") or "").encode("utf-8")
                    expected_sha256 = str(artifact.get("sha256") or "")
                    if (
                        destination.is_relative_to(workspace_root)
                        and expected_sha256
                        and hashlib.sha256(canonical_bytes).hexdigest() == expected_sha256
                    ):
                        observed_sha256 = (
                            hashlib.sha256(destination.read_bytes()).hexdigest()
                            if destination.is_file()
                            else ""
                        )
                        if observed_sha256 != expected_sha256:
                            self._write_bytes_atomic(destination, canonical_bytes)
                            with self._connect() as repair_db:
                                self._event(
                                    repair_db,
                                    str(artifact["run_id"]),
                                    "artifact.storage.repaired",
                                    "artifact",
                                    f"“{artifact['title']}”的落盘字节已恢复为登记内容",
                                    "平台只修复了由文本换行转换造成的存储字节偏差；Artifact 内容、版本和登记哈希均未改写。",
                                    {
                                        "artifact_id": artifact["id"],
                                        "relative_path": relative_path.as_posix(),
                                        "previous_observed_sha256": observed_sha256,
                                        "registered_sha256": expected_sha256,
                                        "repaired_size_bytes": len(canonical_bytes),
                                        "reason": "platform_text_newline_translation",
                                    },
                                )
                    continue
                materialized = self._materialize_artifact(artifact, node_key=node_key)
                with self._connect() as db:
                    db.execute(
                        "UPDATE artifacts SET relative_path=?,sha256=?,media_type=?,size_bytes=? WHERE id=?",
                        (
                            materialized["relative_path"],
                            materialized["sha256"],
                            materialized["media_type"],
                            materialized["size_bytes"],
                            materialized["id"],
                        ),
                    )

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        return self._artifact(row) if row else None

    def list_run_artifacts(
        self,
        run_id: str,
        organization_id: str | None = None,
        *,
        include_content: bool = False,
    ) -> list[dict[str, Any]] | None:
        """Return Artifact registry rows without building the full Run dossier."""
        with self._connect() as db:
            if organization_id:
                run_row = db.execute(
                    "SELECT organization_id FROM runs WHERE id=? AND organization_id=?",
                    (run_id, organization_id),
                ).fetchone()
            else:
                run_row = db.execute(
                    "SELECT organization_id FROM runs WHERE id=?",
                    (run_id,),
                ).fetchone()
            if not run_row:
                return None
            run_organization_id = str(run_row["organization_id"] or "org_jianghu")
            columns = "*" if include_content else (
                "id,run_id,organization_id,task_id,kind,title,'' AS content,version,status,created_at,"
                "relative_path,sha256,media_type,size_bytes"
            )
            rows = db.execute(
                f"SELECT {columns} FROM artifacts WHERE run_id=? AND organization_id=? ORDER BY created_at",
                (run_id, run_organization_id),
            ).fetchall()
        return [self._artifact(row) for row in rows]

    def get_artifact_provenance(self, artifact_id: str) -> dict[str, Any] | None:
        """Resolve task, Attempt and verification receipts for one Artifact on demand."""
        with self._connect() as db:
            row = db.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
            if not row:
                return None
            artifact = self._artifact(row)
            task = None
            if artifact.get("task_id"):
                task_row = db.execute(
                    "SELECT id,node_key,node_name,agent_id,status,created_at,updated_at FROM tasks WHERE id=? AND run_id=?",
                    (artifact["task_id"], artifact["run_id"]),
                ).fetchone()
                task = dict(task_row) if task_row else None
            artifact_created_at = datetime.fromisoformat(str(artifact["created_at"]))
            event_window_start = (artifact_created_at - timedelta(minutes=5)).isoformat()
            event_window_end = (artifact_created_at + timedelta(minutes=30)).isoformat()
            event_rows = db.execute(
                """SELECT id,sequence,type,title,summary,payload_json,created_at
                   FROM events
                   WHERE run_id=?
                     AND type IN ('artifact.created','artifact.collected','artifact.download.verified','artifact.inherited')
                     AND created_at BETWEEN ? AND ?
                     AND payload_json LIKE ?
                   ORDER BY sequence""",
                (artifact["run_id"], event_window_start, event_window_end, f'%{artifact_id}%'),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for event_row in event_rows:
            try:
                payload = json.loads(str(event_row["payload_json"] or "{}"))
            except json.JSONDecodeError:
                payload = {}
            if str(payload.get("artifact_id") or "") != artifact_id:
                continue
            event = dict(event_row)
            event.pop("payload_json", None)
            event["payload"] = payload
            events.append(event)
        attempt_id = next(
            (str(event["payload"].get("platform_attempt_id")) for event in events if event["payload"].get("platform_attempt_id")),
            "",
        )
        content_source = self.get_artifact_content_source(artifact_id)
        resolved_artifact = content_source["artifact"]
        requested_source_sha256 = self._receipt_source_sha256(artifact)
        resolved_sha256 = str(resolved_artifact.get("sha256") or "")
        content_available = True
        content_error = ""
        try:
            self.artifact_file_path(str(resolved_artifact["id"]))
        except ValueError as exc:
            content_available = False
            content_error = str(exc)
        if requested_source_sha256:
            bytes_are_original = requested_source_sha256 == resolved_sha256
            resolution_state = "resolved" if bytes_are_original else "receipt_only"
        else:
            bytes_are_original = content_available
            resolution_state = "direct" if content_available else "missing"
        return {
            "artifact": artifact,
            "task": task,
            "attempt_id": attempt_id,
            "events": events,
            "content_artifact": resolved_artifact,
            "content_lineage": content_source["lineage"],
            "content_resolution": {
                "state": resolution_state,
                "content_available": content_available,
                "bytes_are_original": bytes_are_original,
                "requested_sha256": requested_source_sha256,
                "resolved_sha256": resolved_sha256,
                "error": content_error,
            },
        }

    def get_latest_run_artifact(self, run_id: str, kind: str) -> dict[str, Any] | None:
        """Fetch one Artifact receipt without hydrating the full Run projection."""
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM artifacts WHERE run_id=? AND kind=? ORDER BY created_at DESC, version DESC LIMIT 1",
                (run_id, kind),
            ).fetchone()
        return self._artifact(row) if row else None

    def artifact_file_path(self, artifact_id: str) -> Path:
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            raise ValueError("artifact_not_found")
        with self._connect() as db:
            run_row = db.execute("SELECT project_id FROM runs WHERE id=?", (artifact["run_id"],)).fetchone()
        if not run_row or not artifact.get("relative_path"):
            raise ValueError("artifact_file_not_found")
        root = self._run_workspace(str(run_row["project_id"]), str(artifact["run_id"]))
        path = (root / str(artifact["relative_path"])).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("artifact_file_not_found")
        return path

    @staticmethod
    def _receipt_source_sha256(artifact: dict[str, Any]) -> str:
        if str(artifact.get("kind") or "") not in {"runtime_file", "runtime_file_change"}:
            return ""
        try:
            metadata = json.loads(str(artifact.get("content") or ""))
        except (TypeError, ValueError):
            return ""
        if not isinstance(metadata, dict) or not metadata.get("source_relative_path"):
            return ""
        if str(metadata.get("change_action") or "") == "deleted":
            return str(metadata.get("previous_sha256") or "")
        return str(metadata.get("sha256") or "")

    def get_artifact_content_source(self, artifact_id: str) -> dict[str, Any]:
        """Resolve legacy retry receipts back to the immutable source-file bytes."""
        lineage: list[dict[str, str]] = []
        seen: set[str] = set()
        current_id = artifact_id
        with self._connect() as db:
            for _ in range(32):
                if current_id in seen:
                    break
                seen.add(current_id)
                row = db.execute("SELECT * FROM artifacts WHERE id=?", (current_id,)).fetchone()
                if not row:
                    break
                artifact = self._artifact(row)
                lineage.append(
                    {
                        "artifact_id": str(artifact["id"]),
                        "run_id": str(artifact["run_id"]),
                        "sha256": str(artifact.get("sha256") or ""),
                    }
                )
                source_sha256 = self._receipt_source_sha256(artifact)
                if not source_sha256 or source_sha256 == str(artifact.get("sha256") or ""):
                    return {"artifact": artifact, "lineage": lineage}
                exact_source_row = db.execute(
                    """SELECT * FROM artifacts
                       WHERE sha256=? AND organization_id=? AND id<>?
                       ORDER BY CASE WHEN title=? THEN 0 ELSE 1 END, created_at DESC
                       LIMIT 1""",
                    (
                        source_sha256,
                        str(artifact.get("organization_id") or "org_jianghu"),
                        current_id,
                        artifact.get("title"),
                    ),
                ).fetchone()
                if exact_source_row:
                    current_id = str(exact_source_row["id"])
                    continue
                event_rows = db.execute(
                    """SELECT payload_json FROM events
                       WHERE run_id=? AND type='artifact.inherited' AND payload_json LIKE ?
                       ORDER BY sequence DESC""",
                    (artifact["run_id"], f'%{current_id}%'),
                ).fetchall()
                source_id = ""
                for event_row in event_rows:
                    try:
                        payload = json.loads(str(event_row["payload_json"] or "{}"))
                    except json.JSONDecodeError:
                        continue
                    if str(payload.get("artifact_id") or "") == current_id:
                        source_id = str(payload.get("source_artifact_id") or "")
                        break
                if not source_id:
                    return {"artifact": artifact, "lineage": lineage}
                current_id = source_id
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            raise ValueError("artifact_not_found")
        return {"artifact": artifact, "lineage": lineage}

    def artifact_content_file_path(self, artifact_id: str) -> tuple[Path, dict[str, Any], list[dict[str, str]]]:
        resolved = self.get_artifact_content_source(artifact_id)
        source_artifact = resolved["artifact"]
        return self.artifact_file_path(str(source_artifact["id"])), source_artifact, resolved["lineage"]

    def inherit_artifact_bytes(
        self,
        run_id: str,
        task_id: str,
        source_artifact: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a retry Artifact by copying source bytes instead of its metadata receipt."""
        source_path, content_artifact, _ = self.artifact_content_file_path(str(source_artifact["id"]))
        data = source_path.read_bytes()
        with self._connect() as db:
            run_row = db.execute("SELECT project_id,organization_id FROM runs WHERE id=?", (run_id,)).fetchone()
            task_row = db.execute("SELECT node_key FROM tasks WHERE id=? AND run_id=?", (task_id, run_id)).fetchone()
            version_row = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 AS value FROM artifacts WHERE run_id=? AND task_id=?",
                (run_id, task_id),
            ).fetchone()
        if not run_row or not task_row:
            raise ValueError("artifact_task_not_found")
        workspace_root = self._run_workspace(str(run_row["project_id"]), run_id).resolve()
        artifact_id = new_id("artifact")
        suffix = Path(str(source_artifact.get("title") or source_path.name)).suffix or source_path.suffix or ".bin"
        relative_path = Path("artifacts") / self._safe_segment(task_row["node_key"], "node") / "files" / f"{artifact_id}{suffix}"
        destination = (workspace_root / relative_path).resolve()
        if not destination.is_relative_to(workspace_root):
            raise ValueError("invalid_artifact_path")
        self._write_bytes_atomic(destination, data)
        now = utc_now()
        artifact = {
            "id": artifact_id,
            "run_id": run_id,
            "organization_id": str(run_row["organization_id"] or "org_jianghu"),
            "task_id": task_id,
            "kind": str(source_artifact.get("kind") or "runtime_file"),
            "title": str(source_artifact.get("title") or source_path.name),
            "content": str(source_artifact.get("content") or ""),
            "version": int(_row_value(version_row, "value") or 1),
            "status": str(source_artifact.get("status") or "candidate"),
            "created_at": now,
            "relative_path": relative_path.as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "media_type": str(content_artifact.get("media_type") or workspace_file_media_type(source_path.name)),
            "size_bytes": len(data),
        }
        with self._connect() as db:
            db.execute(
                """INSERT INTO artifacts
                (id,run_id,organization_id,task_id,kind,title,content,version,status,created_at,relative_path,sha256,media_type,size_bytes)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    artifact["id"], artifact["run_id"], artifact["organization_id"], artifact["task_id"],
                    artifact["kind"], artifact["title"], artifact["content"], artifact["version"], artifact["status"],
                    artifact["created_at"], artifact["relative_path"], artifact["sha256"], artifact["media_type"], artifact["size_bytes"],
                ),
            )
        manifest_path = workspace_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = [item for item in manifest.get("artifacts", []) if item.get("id") != artifact_id]
        entries.append(
            {
                "id": artifact_id, "task_id": task_id, "kind": artifact["kind"], "title": artifact["title"],
                "status": artifact["status"], "version": artifact["version"], "path": artifact["relative_path"],
                "media_type": artifact["media_type"], "size_bytes": artifact["size_bytes"], "sha256": artifact["sha256"],
                "created_at": now, "inherited_from_artifact_id": source_artifact["id"],
            }
        )
        manifest["artifacts"] = sorted(entries, key=lambda item: (str(item.get("created_at")), str(item.get("id"))))
        self._write_json_atomic(manifest_path, manifest)
        return artifact

    def list_agents(self, organization_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            if organization_id:
                rows = db.execute(
                    "SELECT * FROM agent_blueprints WHERE status='active' AND organization_id=? ORDER BY name",
                    (organization_id,),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM agent_blueprints WHERE status='active' ORDER BY name").fetchall()
            renamed = False
            name_pools = {
                "召集人": ["沈砚舟", "顾知衡", "林观澜", "程墨安", "陆行远"],
                "实践者": ["顾行知", "苏砚秋", "周予安", "许明川", "叶知行"],
                "质询者": ["陆闻达", "谢清衡", "裴知远", "唐谨言", "秦见微"],
            }
            for row in rows:
                role = str(row["role"] or "")
                current_name = str(row["name"] or "")
                if role not in name_pools or not (current_name.startswith("需要") or current_name.endswith(role)):
                    continue
                pool = name_pools[role]
                index = int(hashlib.sha1(str(row["id"]).encode("utf-8")).hexdigest()[:8], 16) % len(pool)
                db.execute("UPDATE agent_blueprints SET name=?,updated_at=? WHERE id=?", (pool[index], utc_now(), row["id"]))
                renamed = True
            if renamed:
                if organization_id:
                    rows = db.execute(
                        "SELECT * FROM agent_blueprints WHERE status='active' AND organization_id=? ORDER BY name",
                        (organization_id,),
                    ).fetchall()
                else:
                    rows = db.execute("SELECT * FROM agent_blueprints WHERE status='active' ORDER BY name").fetchall()
        return [self._agent(row) for row in rows]

    def create_agent(
        self,
        *,
        name: str,
        role: str,
        description: str,
        persona: str,
        capabilities: list[str],
        visibility: str = "private",
        skills: list[dict[str, Any]] | None = None,
        runtime: str = "claude_code",
        memory_policy: dict[str, Any] | None = None,
        cognitive_level: int = 2,
        authority_level: int = 1,
        organization_id: str = "org_jianghu",
    ) -> dict[str, Any]:
        now = utc_now()
        agent_id = new_id("agent")
        normalized_skills = self._normalize_skills(skills or [])
        normalized_memory_policy = {
            "enabled": True,
            "max_prompt_items": 8,
            "write_after_task": True,
            **(memory_policy or {}),
        }
        with self._connect() as db:
            db.execute(
                """INSERT INTO agent_blueprints
                (id,family_id,parent_agent_id,organization_id,name,role,description,persona,capabilities_json,cognitive_level,authority_level,skills_json,runtime,memory_policy_json,version,visibility,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    agent_id, agent_id, None, organization_id, name, role, description, persona,
                    json.dumps(capabilities, ensure_ascii=False), max(1, min(3, int(cognitive_level))), max(1, min(3, int(authority_level))), json.dumps(normalized_skills, ensure_ascii=False),
                    runtime, json.dumps(normalized_memory_policy, ensure_ascii=False),
                    "1.0.0", visibility, now, now,
                ),
            )
        return self.get_agent(agent_id)  # type: ignore[return-value]

    @staticmethod
    def _normalize_skills(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, skill in enumerate(skills):
            if not isinstance(skill, dict):
                continue
            name = str(skill.get("name") or "").strip()
            if not name:
                continue
            normalized.append(
                {
                    "key": str(skill.get("key") or f"skill_{index + 1}"),
                    "name": name,
                    "description": str(skill.get("description") or "").strip(),
                    "instructions": str(skill.get("instructions") or "").strip(),
                    "enabled": bool(skill.get("enabled", True)),
                }
            )
        return normalized

    def revise_agent(
        self,
        agent_id: str,
        *,
        name: str,
        role: str,
        description: str,
        persona: str,
        capabilities: list[str],
        visibility: str,
        skills: list[dict[str, Any]],
        runtime: str,
        memory_policy: dict[str, Any],
        knowledge_source_ids: list[str] | None = None,
        cognitive_level: int = 2,
        authority_level: int = 1,
    ) -> dict[str, Any]:
        parent = self.get_agent(agent_id)
        if not parent:
            raise ValueError("agent_not_found")
        family_id = str(parent.get("family_id") or parent["id"])
        effective_knowledge_source_ids = (
            list(parent.get("knowledge_source_ids") or [])
            if knowledge_source_ids is None
            else knowledge_source_ids
        )
        with self._connect() as db:
            versions = [str(_row_value(row, "version")) for row in db.execute("SELECT version FROM agent_blueprints WHERE family_id=?", (family_id,)).fetchall()]
        latest = max(versions or [str(parent.get("version") or "1.0.0")], key=lambda value: tuple(int(part) for part in value.split(".")))
        major, minor, _ = (int(part) for part in latest.split("."))
        next_version = f"{major}.{minor + 1}.0"
        revision_id = new_id("agent")
        now = utc_now()
        with self._connect() as db:
            db.execute(
                """INSERT INTO agent_blueprints
                (id,family_id,parent_agent_id,organization_id,name,role,description,persona,capabilities_json,cognitive_level,authority_level,skills_json,runtime,memory_policy_json,
                version,visibility,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active',?,?)""",
                (
                    revision_id, family_id, agent_id, str(parent.get("organization_id") or "org_jianghu"), name, role, description, persona,
                    json.dumps(capabilities, ensure_ascii=False),
                    max(1, min(3, int(cognitive_level))), max(1, min(3, int(authority_level))),
                    json.dumps(self._normalize_skills(skills), ensure_ascii=False),
                    runtime, json.dumps(memory_policy, ensure_ascii=False), next_version, visibility, now, now,
                ),
            )
            db.execute("UPDATE agent_blueprints SET status='superseded',updated_at=? WHERE family_id=? AND id!=?", (now, family_id, revision_id))
            # Living organizations follow the latest person version. Frozen WorkflowVersions keep their old concrete id.
            db.execute(
                """UPDATE team_members AS member SET agent_id=?
                WHERE member.agent_id IN (SELECT id FROM agent_blueprints WHERE family_id=? AND id!=?)
                AND NOT EXISTS (
                    SELECT 1 FROM team_members AS current
                    WHERE current.team_id=member.team_id AND current.agent_id=?
                )""",
                (revision_id, family_id, revision_id, revision_id),
            )
            db.execute("DELETE FROM team_members WHERE agent_id IN (SELECT id FROM agent_blueprints WHERE family_id=? AND id!=?)", (family_id, revision_id))
            db.execute(
                "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (new_id("log"), "agent_blueprint", revision_id, "version_created", json.dumps({"parent_agent_id": agent_id, "version": next_version}, ensure_ascii=False), now),
            )
        self.set_knowledge_bindings("agent", revision_id, effective_knowledge_source_ids)
        return self.get_agent(revision_id)  # type: ignore[return-value]

    def list_agent_versions(self, agent_id: str) -> list[dict[str, Any]]:
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError("agent_not_found")
        family_id = str(agent.get("family_id") or agent["id"])
        with self._connect() as db:
            rows = db.execute("SELECT * FROM agent_blueprints WHERE family_id=? ORDER BY created_at DESC", (family_id,)).fetchall()
        return [self._agent(row) for row in rows]

    def add_agent_memory(
        self,
        agent_id: str,
        *,
        kind: str,
        title: str,
        content: str,
        source_run_id: str | None = None,
        source_task_id: str | None = None,
        visibility: str = "private",
    ) -> dict[str, Any]:
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError("agent_not_found")
        memory_id = new_id("memory")
        now = utc_now()
        family_id = str(agent.get("family_id") or agent["id"])
        superseded_records: list[dict[str, Any]] = []
        with self._connect() as db:
            if source_task_id:
                previous_rows = db.execute(
                    """SELECT m.* FROM agent_memories m
                    JOIN agent_blueprints a ON a.id=m.agent_id
                    WHERE a.family_id=? AND m.source_task_id=? AND m.kind=? AND COALESCE(m.status,'active')='active'
                    ORDER BY m.version DESC,m.created_at DESC""",
                    (family_id, source_task_id, kind),
                ).fetchall()
                superseded_records = [dict(row) for row in previous_rows]
                if superseded_records:
                    placeholders = ",".join("?" for _ in superseded_records)
                    db.execute(
                        f"UPDATE agent_memories SET status='superseded',tombstoned_at=? WHERE id IN ({placeholders})",
                        [now, *[item["id"] for item in superseded_records]],
                    )
            version = 1 + max((int(item.get("version", 1) or 1) for item in superseded_records), default=0)
            supersedes_id = str(superseded_records[0]["id"]) if superseded_records else None
            db.execute(
                """INSERT INTO agent_memories
                (id,agent_id,kind,title,content,source_run_id,source_task_id,visibility,created_at,status,version,supersedes_id,tombstoned_at)
                VALUES(?,?,?,?,?,?,?,?,?,'active',?,?,NULL)""",
                (memory_id, agent_id, kind, title, content, source_run_id, source_task_id, visibility, now, version, supersedes_id),
            )
        return {
            "id": memory_id, "agent_id": agent_id, "kind": kind, "title": title, "content": content,
            "source_run_id": source_run_id, "source_task_id": source_task_id, "visibility": visibility, "created_at": now,
            "status": "active", "version": version, "supersedes_id": supersedes_id,
            "superseded_records": superseded_records,
        }

    def list_agent_memories(self, agent_id: str, limit: int = 50) -> list[dict[str, Any]]:
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError("agent_not_found")
        family_id = str(agent.get("family_id") or agent["id"])
        with self._connect() as db:
            rows = db.execute(
                """SELECT m.* FROM agent_memories m JOIN agent_blueprints a ON a.id=m.agent_id
                WHERE a.family_id=? AND COALESCE(m.status,'active')='active'
                ORDER BY m.created_at DESC LIMIT ?""",
                (family_id, max(1, min(limit, 200))),
            ).fetchall()
        return [dict(row) for row in rows]

    def read_agent_memory_for(self, reader_agent_id: str, memory_id: str) -> dict[str, Any]:
        """Read one active Memory through the same-family namespace boundary."""
        reader = self.get_agent(reader_agent_id)
        if not reader:
            raise ValueError("agent_not_found")
        with self._connect() as db:
            row = db.execute(
                """SELECT m.*,a.family_id AS owner_family_id FROM agent_memories m
                JOIN agent_blueprints a ON a.id=m.agent_id WHERE m.id=?""",
                (memory_id,),
            ).fetchone()
        if not row:
            raise ValueError("memory_not_found")
        record = dict(row)
        if str(record.get("owner_family_id") or record.get("agent_id") or "") != str(reader.get("family_id") or reader["id"]):
            raise ValueError("memory_namespace_denied")
        if str(record.get("status") or "active") != "active":
            raise ValueError("memory_not_active")
        record.pop("owner_family_id", None)
        return record

    def list_organizations(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM organizations ORDER BY created_at").fetchall()
        return [dict(row) for row in rows]

    def create_organization(
        self,
        *,
        name: str,
        description: str,
        owner_name: str = "发起人",
        world_type: str = "open_society",
        user_identity: str = "发起人",
    ) -> dict[str, Any]:
        organization_id = new_id("org")
        now = utc_now()
        with self._connect() as db:
            db.execute(
                """INSERT INTO organizations
                (id,name,owner_name,world_type,user_identity,description,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (organization_id, name.strip(), owner_name, world_type, user_identity, description.strip(), now, now),
            )
            db.execute(
                "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (new_id("log"), "organization", organization_id, "created", json.dumps({"name": name.strip()}, ensure_ascii=False), now),
            )
        return next(item for item in self.list_organizations() if item["id"] == organization_id)

    def update_organization(self, organization_id: str, *, name: str, description: str) -> dict[str, Any]:
        organization = next((item for item in self.list_organizations() if str(item["id"]) == str(organization_id)), None)
        if not organization:
            raise ValueError("organization_not_found")
        now = utc_now()
        with self._connect() as db:
            db.execute(
                "UPDATE organizations SET name=?,description=?,updated_at=? WHERE id=?",
                (name.strip(), description.strip(), now, organization_id),
            )
            db.execute(
                "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (new_id("log"), "organization", organization_id, "updated", json.dumps({"name": name.strip()}, ensure_ascii=False), now),
            )
        updated = next((item for item in self.list_organizations() if str(item["id"]) == str(organization_id)), None)
        return updated or organization

    def list_teams(self, organization_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            if organization_id:
                rows = db.execute("SELECT * FROM agent_teams WHERE organization_id=? AND status!='disbanded' ORDER BY updated_at DESC", (organization_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM agent_teams WHERE status!='disbanded' ORDER BY updated_at DESC").fetchall()
            result = []
            for row in rows:
                team = dict(row)
                members = db.execute(
                    """SELECT tm.member_role,tm.responsibility,tm.position_no,a.*
                    FROM team_members tm JOIN agent_blueprints a ON a.id=tm.agent_id
                    WHERE tm.team_id=? ORDER BY tm.position_no,a.name""",
                    (team["id"],),
                ).fetchall()
                team["members"] = [self._team_member(member) for member in members]
                team["capabilities"] = sorted({capability for member in team["members"] for capability in member["capabilities"]})
                team["knowledge_paths"] = json.loads(team.pop("knowledge_paths_json", "[]"))
                result.append(team)
        return result

    def get_team(self, team_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM agent_teams WHERE id=?", (team_id,)).fetchone()
            if not row:
                return None
            team = dict(row)
            members = db.execute(
                """SELECT tm.member_role,tm.responsibility,tm.position_no,a.*
                FROM team_members tm JOIN agent_blueprints a ON a.id=tm.agent_id
                WHERE tm.team_id=? ORDER BY tm.position_no,a.name""",
                (team_id,),
            ).fetchall()
        team["members"] = [self._team_member(member) for member in members]
        team["capabilities"] = sorted({capability for member in team["members"] for capability in member["capabilities"]})
        team["knowledge_paths"] = json.loads(team.pop("knowledge_paths_json", "[]"))
        return team

    def update_team(self, team_id: str, *, name: str, purpose: str, operating_mode: str) -> dict[str, Any]:
        team = self.get_team(team_id)
        if not team or team["status"] == "disbanded":
            raise ValueError("team_not_found")
        now = utc_now()
        with self._connect() as db:
            db.execute(
                "UPDATE agent_teams SET name=?,purpose=?,operating_mode=?,updated_at=? WHERE id=?",
                (name.strip(), purpose.strip(), operating_mode, now, team_id),
            )
            db.execute(
                "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (new_id("log"), "agent_team", team_id, "updated", json.dumps({"name": name.strip(), "operating_mode": operating_mode}, ensure_ascii=False), now),
            )
        return self.get_team(team_id) or team

    def disband_team(self, team_id: str) -> dict[str, Any]:
        team = self.get_team(team_id)
        if not team:
            raise ValueError("team_not_found")
        if team["status"] == "disbanded":
            return {"team": team, "workflow_reference_count": 0}
        workflow_reference_count = 0
        for workflow in self.list_workflows():
            if any(str(node.get("team_id")) == team_id for node in workflow["definition"].get("nodes", [])):
                workflow_reference_count += 1
        now = utc_now()
        with self._connect() as db:
            db.execute("UPDATE agent_teams SET status='disbanded',updated_at=? WHERE id=?", (now, team_id))
            db.execute(
                "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (new_id("log"), "agent_team", team_id, "disbanded", json.dumps({"workflow_reference_count": workflow_reference_count}, ensure_ascii=False), now),
            )
        return {"team": self.get_team(team_id), "workflow_reference_count": workflow_reference_count}

    def create_team(self, *, organization_id: str, name: str, purpose: str, operating_mode: str, members: list[dict[str, str]], visibility: str = "private", knowledge_paths: list[str] | None = None) -> dict[str, Any]:
        if not members:
            raise ValueError("team_requires_members")
        now = utc_now()
        team_id = new_id("team")
        with self._connect() as db:
            if db.execute("SELECT 1 FROM organizations WHERE id=?", (organization_id,)).fetchone() is None:
                raise ValueError("organization_not_found")
            db.execute(
                """INSERT INTO agent_teams
                (id,organization_id,name,purpose,operating_mode,knowledge_paths_json,status,visibility,version,created_at,updated_at)
                VALUES(?,?,?,?,?,?,'ready',?,'1.0.0',?,?)""",
                (team_id, organization_id, name, purpose, operating_mode, json.dumps(knowledge_paths or [], ensure_ascii=False), visibility, now, now),
            )
            for index, member in enumerate(members):
                agent_id = str(member.get("agent_id", ""))
                agent_row = db.execute("SELECT organization_id FROM agent_blueprints WHERE id=?", (agent_id,)).fetchone()
                if agent_row is None:
                    raise ValueError("team_member_agent_not_found")
                if str(agent_row["organization_id"]) != str(organization_id):
                    raise ValueError("team_member_organization_mismatch")
                db.execute(
                    "INSERT INTO team_members(team_id,agent_id,member_role,responsibility,position_no) VALUES(?,?,?,?,?)",
                    (team_id, agent_id, member.get("member_role", "member"), member.get("responsibility", ""), index),
                )
        return self.get_team(team_id)  # type: ignore[return-value]

    def add_team_member(self, team_id: str, agent_id: str, responsibility: str = "") -> dict[str, Any]:
        team = self.get_team(team_id)
        if not team or team["status"] == "disbanded":
            raise ValueError("team_not_found")
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError("agent_not_found")
        if str(agent.get("organization_id")) != str(team.get("organization_id")):
            raise ValueError("team_member_organization_mismatch")
        if any(member["id"] == agent_id for member in team["members"]):
            return team
        now = utc_now()
        with self._connect() as db:
            position_row = db.execute("SELECT COALESCE(MAX(position_no),-1)+1 AS value FROM team_members WHERE team_id=?", (team_id,)).fetchone()
            position_no = int(_row_value(position_row, "value"))
            db.execute(
                "INSERT INTO team_members(team_id,agent_id,member_role,responsibility,position_no) VALUES(?,?,?,?,?)",
                (team_id, agent_id, "member", responsibility, position_no),
            )
            db.execute("UPDATE agent_teams SET updated_at=? WHERE id=?", (now, team_id))
            db.execute(
                "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (new_id("log"), "agent_team", team_id, "member_added", json.dumps({"agent_id": agent_id}, ensure_ascii=False), now),
            )
        return self.get_team(team_id)  # type: ignore[return-value]

    def create_company_task(
        self,
        *,
        organization_id: str,
        title: str,
        description: str,
        git_delivery: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        task_id = new_id("company_task")
        with self._connect() as db:
            if db.execute("SELECT 1 FROM organizations WHERE id=?", (organization_id,)).fetchone() is None:
                raise ValueError("organization_not_found")
            db.execute(
                """INSERT INTO company_tasks
                   (id,organization_id,title,description,status,git_delivery_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (task_id, organization_id, title, description, "assessing", json.dumps(git_delivery or {}, ensure_ascii=False), now, now),
            )
        return self.get_company_task(task_id)  # type: ignore[return-value]

    def get_company_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM company_tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                return None
            assessments = db.execute("SELECT * FROM team_assessments WHERE company_task_id=? ORDER BY fit_score DESC", (task_id,)).fetchall()
            proposal = db.execute(
                "SELECT * FROM team_proposals WHERE company_task_id=? AND status='pending' ORDER BY updated_at DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        result = dict(row)
        result["selected_team_ids"] = json.loads(result.pop("selected_team_ids_json"))
        result["git_delivery"] = json.loads(result.pop("git_delivery_json", "{}") or "{}")
        result["assessments"] = [self._assessment(item) for item in assessments]
        result["team_proposal"] = self._team_proposal(proposal) if proposal else None
        return result

    def list_company_tasks(self, organization_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as db:
            if organization_id:
                rows = db.execute(
                    "SELECT id FROM company_tasks WHERE organization_id=? ORDER BY updated_at DESC LIMIT ?",
                    (organization_id, limit),
                ).fetchall()
            else:
                rows = db.execute("SELECT id FROM company_tasks ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [task for row in rows if (task := self.get_company_task(row["id"])) is not None]

    def link_company_task(self, task_id: str, *, workflow_id: str | None = None, run_id: str | None = None) -> dict[str, Any]:
        if not self.get_company_task(task_id):
            raise ValueError("company_task_not_found")
        fields = ["updated_at=?"]
        values: list[Any] = [utc_now()]
        if workflow_id is not None:
            fields.append("workflow_id=?")
            values.append(workflow_id)
        if run_id is not None:
            fields.append("run_id=?")
            values.append(run_id)
        values.append(task_id)
        with self._connect() as db:
            db.execute(f"UPDATE company_tasks SET {', '.join(fields)} WHERE id=?", values)
        return self.get_company_task(task_id)  # type: ignore[return-value]

    def select_company_task_teams(self, task_id: str, team_ids: list[str]) -> dict[str, Any]:
        company_task = self.get_company_task(task_id)
        if not company_task:
            raise ValueError("company_task_not_found")
        normalized = list(dict.fromkeys(str(team_id) for team_id in team_ids if team_id))
        for team_id in normalized:
            team = self.get_team(team_id)
            if not team or str(team.get("organization_id")) != str(company_task["organization_id"]):
                raise ValueError("team_not_found")
        now = utc_now()
        with self._connect() as db:
            db.execute(
                "UPDATE company_tasks SET selected_team_ids_json=?,updated_at=? WHERE id=?",
                (json.dumps(normalized, ensure_ascii=False), now, task_id),
            )
            db.execute(
                "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (new_id("log"), "company_task", task_id, "teams_selected", json.dumps({"team_ids": normalized}, ensure_ascii=False), now),
            )
        return self.get_company_task(task_id)  # type: ignore[return-value]

    def create_team_proposal(
        self,
        *,
        company_task_id: str,
        decision: str,
        existing_team_id: str | None,
        name: str,
        purpose: str,
        operating_mode: str,
        members: list[dict[str, str]],
        fit_score: int,
        reason: str,
        missing_capabilities: list[str],
    ) -> dict[str, Any]:
        company_task = self.get_company_task(company_task_id)
        if not company_task:
            raise ValueError("company_task_not_found")
        if decision not in {"reuse", "create"}:
            raise ValueError("team_proposal_decision_invalid")
        if operating_mode not in {"collaborative", "debate", "red_team", "hierarchical"}:
            raise ValueError("team_proposal_operating_mode_invalid")
        if decision == "reuse":
            existing = self.get_team(str(existing_team_id or ""))
            if not existing or str(existing.get("organization_id")) != str(company_task["organization_id"]):
                raise ValueError("team_not_found")
        elif not members:
            raise ValueError("team_proposal_requires_members")
        proposal_id = new_id("team_proposal")
        now = utc_now()
        with self._connect() as db:
            db.execute(
                "UPDATE team_proposals SET status='superseded',updated_at=? WHERE company_task_id=? AND status='pending'",
                (now, company_task_id),
            )
            db.execute(
                """INSERT INTO team_proposals
                (id,company_task_id,organization_id,decision,existing_team_id,name,purpose,operating_mode,
                 members_json,fit_score,reason,missing_capabilities_json,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    proposal_id,
                    company_task_id,
                    company_task["organization_id"],
                    decision,
                    existing_team_id,
                    name,
                    purpose,
                    operating_mode,
                    json.dumps(members, ensure_ascii=False),
                    max(0, min(100, int(fit_score))),
                    reason,
                    json.dumps(missing_capabilities, ensure_ascii=False),
                    "pending",
                    now,
                    now,
                ),
            )
            db.execute(
                "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (
                    new_id("log"),
                    "company_task",
                    company_task_id,
                    "team_proposal_created",
                    json.dumps({"proposal_id": proposal_id, "decision": decision}, ensure_ascii=False),
                    now,
                ),
            )
        return self.get_team_proposal(proposal_id)  # type: ignore[return-value]

    def get_team_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM team_proposals WHERE id=?", (proposal_id,)).fetchone()
        return self._team_proposal(row) if row else None

    def confirm_team_proposal(
        self,
        proposal_id: str,
        *,
        name: str | None = None,
        purpose: str | None = None,
        operating_mode: str | None = None,
        members: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        proposal = self.get_team_proposal(proposal_id)
        if not proposal:
            raise ValueError("team_proposal_not_found")
        if proposal["status"] != "pending":
            raise ValueError("team_proposal_is_not_pending")
        company_task = self.get_company_task(str(proposal["company_task_id"]))
        if not company_task:
            raise ValueError("company_task_not_found")
        if proposal["decision"] == "reuse":
            team = self.get_team(str(proposal.get("existing_team_id") or ""))
            if not team or team.get("status") == "disbanded":
                raise ValueError("team_not_found")
        else:
            selected_members = members if members is not None else list(proposal.get("members") or [])
            normalized_members: list[dict[str, str]] = []
            seen: set[str] = set()
            for item in selected_members:
                agent_id = str(item.get("agent_id") or "")
                if not agent_id or agent_id in seen or not self.get_agent(agent_id):
                    continue
                seen.add(agent_id)
                normalized_members.append(
                    {
                        "agent_id": agent_id,
                        "member_role": "leader" if not normalized_members else "member",
                        "responsibility": str(item.get("responsibility") or "承担本团队专业职责"),
                    }
                )
            if not normalized_members:
                raise ValueError("team_proposal_requires_members")
            resolved_mode = str(operating_mode or proposal.get("operating_mode") or "collaborative")
            if resolved_mode not in {"collaborative", "debate", "red_team", "hierarchical"}:
                raise ValueError("team_proposal_operating_mode_invalid")
            team = self.create_team(
                organization_id=str(proposal["organization_id"]),
                name=str(name or proposal.get("name") or f"{company_task['title']}行动社").strip(),
                purpose=str(purpose or proposal.get("purpose") or f"协作完成与“{company_task['title']}”同类的生产任务").strip(),
                operating_mode=resolved_mode,
                members=normalized_members,
                visibility="private",
                knowledge_paths=[],
            )
        now = utc_now()
        with self._connect() as db:
            updated = db.execute(
                "UPDATE team_proposals SET status='confirmed',confirmed_team_id=?,updated_at=? WHERE id=? AND status='pending'",
                (team["id"], now, proposal_id),
            )
            if updated.rowcount != 1:
                raise ValueError("team_proposal_is_not_pending")
            db.execute(
                "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (
                    new_id("log"),
                    "company_task",
                    company_task["id"],
                    "team_proposal_confirmed",
                    json.dumps({"proposal_id": proposal_id, "team_id": team["id"]}, ensure_ascii=False),
                    now,
                ),
            )
        previous_assessments = [
            {
                "team_id": item.get("team_id"),
                "fit_status": item.get("fit_status", "gap"),
                "fit_score": item.get("fit_score", 0),
                "reasoning": item.get("reasoning", ""),
                "missing_capabilities": item.get("missing_capabilities", []),
                "recommended_agents": item.get("recommended_agents", []),
            }
            for item in company_task.get("assessments", [])
            if item.get("team_id") and str(item.get("team_id")) != str(team["id"])
        ]
        score = int(proposal.get("fit_score", 0) or 0)
        selected_assessment = {
            "team_id": team["id"],
            "fit_status": "fit" if score >= 70 else ("partial" if score >= 45 else "gap"),
            "fit_score": score,
            "reasoning": proposal.get("reason", ""),
            "missing_capabilities": proposal.get("missing_capabilities", []),
            "recommended_agents": [],
        }
        self.save_team_assessments(company_task["id"], [selected_assessment, *previous_assessments])
        selected_task = self.select_company_task_teams(company_task["id"], [str(team["id"])])
        return {"proposal": self.get_team_proposal(proposal_id), "team": team, "company_task": selected_task}

    def reject_team_proposal(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.get_team_proposal(proposal_id)
        if not proposal:
            raise ValueError("team_proposal_not_found")
        if proposal["status"] != "pending":
            raise ValueError("team_proposal_is_not_pending")
        now = utc_now()
        with self._connect() as db:
            db.execute("UPDATE team_proposals SET status='rejected',updated_at=? WHERE id=?", (now, proposal_id))
            db.execute(
                "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (
                    new_id("log"),
                    "company_task",
                    proposal["company_task_id"],
                    "team_proposal_rejected",
                    json.dumps({"proposal_id": proposal_id}, ensure_ascii=False),
                    now,
                ),
            )
        return {"proposal": self.get_team_proposal(proposal_id), "company_task": self.get_company_task(str(proposal["company_task_id"]))}

    def save_team_assessments(self, task_id: str, assessments: list[dict[str, Any]]) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as db:
            db.execute("DELETE FROM team_assessments WHERE company_task_id=?", (task_id,))
            for assessment in assessments:
                db.execute(
                    """INSERT INTO team_assessments
                    (id,company_task_id,team_id,fit_status,fit_score,reasoning,missing_capabilities_json,recommended_agents_json,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        new_id("assessment"), task_id, assessment.get("team_id"), assessment.get("fit_status", "gap"),
                        int(assessment.get("fit_score", 0)), str(assessment.get("reasoning", "")),
                        json.dumps(assessment.get("missing_capabilities", [])), json.dumps(assessment.get("recommended_agents", [])), now,
                    ),
                )
            best = max((int(item.get("fit_score", 0)) for item in assessments), default=0)
            db.execute("UPDATE company_tasks SET status=?,updated_at=? WHERE id=?", ("team_ready" if best >= 70 else "needs_hiring", now, task_id))
        return self.get_company_task(task_id)  # type: ignore[return-value]

    def list_projects(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM projects ORDER BY created_at").fetchall()]

    def list_runs(self, limit: int = 50, organization_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            if organization_id:
                rows = db.execute(
                    """SELECT r.*,w.name AS workflow_name,
                    (SELECT COUNT(*) FROM tasks t WHERE t.run_id=r.id) AS task_count,
                    (SELECT COUNT(*) FROM artifacts a WHERE a.run_id=r.id) AS artifact_count
                    FROM runs r JOIN workflows w ON w.id=r.workflow_id
                    WHERE r.organization_id=?
                    ORDER BY r.run_version DESC, r.updated_at DESC""",
                    (organization_id,),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT r.*,w.name AS workflow_name,
                    (SELECT COUNT(*) FROM tasks t WHERE t.run_id=r.id) AS task_count,
                    (SELECT COUNT(*) FROM artifacts a WHERE a.run_id=r.id) AS artifact_count
                    FROM runs r JOIN workflows w ON w.id=r.workflow_id
                    ORDER BY r.run_version DESC, r.updated_at DESC""",
                    (),
                ).fetchall()
        versions_by_family: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            record = dict(row)
            family_id = str(record.get("run_family_id") or record.get("id"))
            record["run_family_id"] = family_id
            versions_by_family.setdefault(family_id, []).append(record)
        active_statuses = {"running", "pause_requested", "paused"}
        result = [
            next(
                (record for record in versions if str(record.get("status")) in active_statuses),
                versions[0],
            )
            for versions in versions_by_family.values()
        ]
        result.sort(key=lambda item: (str(item.get("updated_at") or ""), str(item.get("id") or "")), reverse=True)
        with self._connect() as db:
            for record in result:
                family_id = str(record.get("run_family_id") or record["id"])
                count_row = db.execute("SELECT COUNT(*) AS value FROM runs WHERE run_family_id=?", (family_id,)).fetchone()
                record["attempt_count"] = int(_row_value(count_row, "value") or 1)
        return result[: max(1, limit)]

    def list_runs_by_status(self, statuses: set[str]) -> list[dict[str, Any]]:
        if not statuses:
            return []
        normalized = sorted({str(status) for status in statuses})
        placeholders = ",".join("?" for _ in normalized)
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM runs WHERE status IN ({placeholders}) ORDER BY updated_at",
                normalized,
            ).fetchall()
        return [dict(row) for row in rows]

    def create_showcase_comparison(
        self,
        *,
        case_id: str,
        baseline_run_id: str,
        multi_run_id: str,
    ) -> dict[str, Any]:
        if not self.get_run(baseline_run_id) or not self.get_run(multi_run_id):
            raise ValueError("showcase_run_not_found")
        comparison_id = new_id("comparison")
        now = utc_now()
        with self._connect() as db:
            db.execute(
                """INSERT INTO showcase_comparisons
                (id,case_id,baseline_run_id,multi_run_id,created_at,updated_at)
                VALUES(?,?,?,?,?,?)""",
                (comparison_id, case_id, baseline_run_id, multi_run_id, now, now),
            )
            db.execute(
                "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (
                    new_id("log"),
                    "showcase_comparison",
                    comparison_id,
                    "created",
                    json.dumps(
                        {
                            "case_id": case_id,
                            "baseline_run_id": baseline_run_id,
                            "multi_run_id": multi_run_id,
                        },
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
        return self.get_showcase_comparison(comparison_id)  # type: ignore[return-value]

    def get_showcase_comparison(self, comparison_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM showcase_comparisons WHERE id=?", (comparison_id,)).fetchone()
        return dict(row) if row else None

    def list_showcase_comparisons(self, case_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM showcase_comparisons WHERE case_id=? ORDER BY created_at DESC LIMIT ?",
                (case_id, max(1, min(limit, 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_knowledge_sources(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            if project_id:
                rows = db.execute("SELECT * FROM knowledge_sources WHERE project_id=? ORDER BY updated_at DESC", (project_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM knowledge_sources ORDER BY updated_at DESC").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            result.append(item)
        return result

    def list_knowledge_sources_page(
        self,
        *,
        scope_type: str,
        scope_id: str,
        offset: int = 0,
        limit: int = 20,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        safe_offset = max(0, int(offset))
        safe_limit = max(1, min(int(limit), 100))
        matched = []
        for source in self.list_knowledge_sources(project_id):
            metadata = source.get("metadata", {})
            if not metadata.get("managed"):
                continue
            explicit_scope = (
                str(metadata.get("scope_type") or "") == scope_type
                and str(metadata.get("scope_id") or "") == scope_id
            )
            legacy_scope = (
                scope_type == "team" and str(metadata.get("team_id") or "") == scope_id
            ) or (
                scope_type == "organization"
                and str(metadata.get("organization_id") or "") == scope_id
                and not str(metadata.get("team_id") or "")
            )
            if explicit_scope or legacy_scope:
                matched.append(source)
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for source in matched:
            identity = str(source.get("metadata", {}).get("sha256") or source["id"])
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(source)
        items = unique[safe_offset:safe_offset + safe_limit]
        return {
            "items": items,
            "pagination": {
                "offset": safe_offset,
                "limit": safe_limit,
                "total": len(unique),
                "has_more": safe_offset + len(items) < len(unique),
            },
        }

    def get_knowledge_source(self, source_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list_knowledge_sources() if item["id"] == source_id), None)

    def delete_knowledge_source(self, source_id: str) -> dict[str, Any]:
        source = self.get_knowledge_source(source_id)
        if not source:
            raise ValueError("knowledge_source_not_found")
        metadata = dict(source.get("metadata") or {})
        scope_type = str(metadata.get("scope_type") or ("team" if metadata.get("team_id") else "organization"))
        scope_id = str(metadata.get("scope_id") or metadata.get("team_id") or metadata.get("organization_id") or "")
        managed_path: Path | None = None
        managed_directory: Path | None = None
        tombstone: Path | None = None
        if metadata.get("managed"):
            raw_path = str(source.get("uri") or metadata.get("managed_path") or "").strip()
            if raw_path:
                managed_path = Path(raw_path).resolve()
                if not managed_path.is_relative_to(self.knowledge_root):
                    raise ValueError("invalid_knowledge_path")
                managed_directory = managed_path.parent.resolve()
                if managed_directory == self.knowledge_root or not managed_directory.is_relative_to(self.knowledge_root):
                    raise ValueError("invalid_knowledge_path")

        team_knowledge_paths: list[str] | None = None
        if scope_type == "team" and scope_id:
            team = self.get_team(scope_id)
            if team:
                team_knowledge_paths = []
                for item in team.get("knowledge_paths") or []:
                    try:
                        if managed_path and Path(str(item)).resolve() == managed_path:
                            continue
                    except (OSError, ValueError):
                        pass
                    team_knowledge_paths.append(str(item))

        now = utc_now()
        try:
            if managed_directory and managed_directory.exists():
                trash_root = (self.knowledge_root / ".trash").resolve()
                if not trash_root.is_relative_to(self.knowledge_root):
                    raise ValueError("invalid_knowledge_path")
                trash_root.mkdir(parents=True, exist_ok=True)
                tombstone = (trash_root / f"{self._safe_segment(source_id, 'source')}-{uuid4().hex}").resolve()
                if not tombstone.is_relative_to(trash_root):
                    raise ValueError("invalid_knowledge_path")
                managed_directory.replace(tombstone)
            with self._connect() as db:
                db.execute("DELETE FROM knowledge_bindings WHERE source_id=?", (source_id,))
                db.execute("DELETE FROM knowledge_chunks WHERE source_id=?", (source_id,))
                if team_knowledge_paths is not None:
                    db.execute(
                        "UPDATE agent_teams SET knowledge_paths_json=?,updated_at=? WHERE id=?",
                        (json.dumps(team_knowledge_paths, ensure_ascii=False), now, scope_id),
                    )
                db.execute("DELETE FROM knowledge_sources WHERE id=?", (source_id,))
                db.execute(
                    "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        new_id("log"),
                        scope_type or "knowledge_source",
                        scope_id or source_id,
                        "knowledge_deleted",
                        json.dumps(
                            {
                                "knowledge_source_id": source_id,
                                "filename": source.get("name"),
                                "relative_path": metadata.get("relative_path"),
                                "scope_type": scope_type,
                                "scope_id": scope_id,
                            },
                            ensure_ascii=False,
                        ),
                        now,
                    ),
                )
        except Exception:
            if tombstone and managed_directory and tombstone.exists() and not managed_directory.exists():
                tombstone.replace(managed_directory)
            raise

        cleanup_pending = False
        if tombstone and tombstone.exists():
            try:
                shutil.rmtree(tombstone)
            except OSError:
                cleanup_pending = True
        return {
            "deleted": True,
            "source_id": source_id,
            "name": source.get("name"),
            "scope_type": scope_type,
            "scope_id": scope_id,
            "physical_file_deleted": tombstone is not None,
            "cleanup_pending": cleanup_pending,
        }

    def knowledge_source_detail(self, source_id: str, offset: int = 0, limit: int = 12) -> dict[str, Any]:
        source = self.get_knowledge_source(source_id)
        if not source:
            raise ValueError("knowledge_source_not_found")
        safe_offset = max(0, offset)
        safe_limit = max(1, min(limit, 100))
        with self._connect() as db:
            total_row = db.execute("SELECT COUNT(*) AS value FROM knowledge_chunks WHERE source_id=?", (source_id,)).fetchone()
            total = int(_row_value(total_row, "value"))
            rows = db.execute(
                """SELECT id,source_id,chunk_index,title,locator,content,token_estimate,metadata_json
                FROM knowledge_chunks WHERE source_id=? ORDER BY chunk_index LIMIT ? OFFSET ?""",
                (source_id, safe_limit, safe_offset),
            ).fetchall()
        chunks = []
        for row in rows:
            chunk = dict(row)
            chunk["metadata"] = json.loads(chunk.pop("metadata_json"))
            chunks.append(chunk)
        return {
            "source": source,
            "chunks": chunks,
            "pagination": {
                "offset": safe_offset,
                "limit": safe_limit,
                "total": total,
                "has_more": safe_offset + len(chunks) < total,
            },
        }

    def _index_knowledge_source(self, source_id: str) -> dict[str, Any]:
        source = self.get_knowledge_source(source_id)
        if not source:
            raise ValueError("knowledge_source_not_found")
        path = self.knowledge_file_path(source_id)
        metadata = dict(source.get("metadata") or {})
        now = utc_now()
        try:
            content = path.read_bytes()
            parser, sections = extract_document(str(metadata.get("original_filename") or source["name"]), content)
            chunks = chunk_sections(sections)
            if not chunks:
                raise ValueError("knowledge_file_has_no_extractable_text")
            extracted_path = (path.parent / "extracted.txt").resolve()
            if not extracted_path.is_relative_to(path.parent.resolve()):
                raise ValueError("invalid_knowledge_path")
            extracted_text = "\n\n".join(
                f"# {section.title}\n\n{section.text}" for section in sections
            )
            temporary = extracted_path.with_suffix(".txt.tmp")
            temporary.write_text(extracted_text, encoding="utf-8")
            temporary.replace(extracted_path)
            metadata.update(
                {
                    "indexed": True,
                    "index_status": "ready",
                    "parser": parser,
                    "rag_strategy": "hybrid_lexical_char_ngram",
                    "section_count": len(sections),
                    "chunk_count": len(chunks),
                    "character_count": len(extracted_text),
                    "extracted_path": str(extracted_path),
                    "indexed_at": now,
                }
            )
            with self._connect() as db:
                db.execute("DELETE FROM knowledge_chunks WHERE source_id=?", (source_id,))
                for index, chunk in enumerate(chunks):
                    db.execute(
                        """INSERT INTO knowledge_chunks
                        (id,source_id,project_id,organization_id,team_id,chunk_index,title,locator,content,token_estimate,metadata_json,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            new_id("chunk"),
                            source_id,
                            source["project_id"],
                            str(metadata.get("organization_id") or ""),
                            str(metadata.get("team_id") or ""),
                            index,
                            chunk.title,
                            chunk.locator,
                            chunk.content,
                            chunk.token_estimate,
                            json.dumps(chunk.metadata, ensure_ascii=False),
                            now,
                            now,
                        ),
                    )
                db.execute(
                    "UPDATE knowledge_sources SET status='ready',metadata_json=?,updated_at=? WHERE id=?",
                    (json.dumps(metadata, ensure_ascii=False), now, source_id),
                )
                db.execute(
                    "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        new_id("log"),
                        "knowledge_source",
                        source_id,
                        "knowledge_indexed",
                        json.dumps(
                            {
                                "team_id": metadata.get("team_id"),
                                "parser": parser,
                                "section_count": len(sections),
                                "chunk_count": len(chunks),
                            },
                            ensure_ascii=False,
                        ),
                        now,
                    ),
                )
        except Exception as exc:
            metadata.update(
                {
                    "indexed": False,
                    "index_status": "failed",
                    "index_error": str(exc),
                    "indexed_at": now,
                }
            )
            with self._connect() as db:
                db.execute("DELETE FROM knowledge_chunks WHERE source_id=?", (source_id,))
                db.execute(
                    "UPDATE knowledge_sources SET status='index_failed',metadata_json=?,updated_at=? WHERE id=?",
                    (json.dumps(metadata, ensure_ascii=False), now, source_id),
                )
                db.execute(
                    "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        new_id("log"),
                        "knowledge_source",
                        source_id,
                        "knowledge_index_failed",
                        json.dumps({"error": str(exc)}, ensure_ascii=False),
                        now,
                    ),
                )
        return self.get_knowledge_source(source_id)  # type: ignore[return-value]

    def _repair_managed_file_locations(self) -> None:
        """Rebind managed files after moving the data directory or OS.

        Knowledge source URIs are persisted for auditability, but a Docker
        bind mount changes an original Windows path into /app/.data. The
        source id and managed directory layout are stable, so the platform can
        safely rediscover the same bytes and update only the local projection.
        """
        paths_by_team: dict[str, list[str]] = {}
        for source in self.list_knowledge_sources():
            if source.get("source_type") not in {"managed_upload", "managed_note"}:
                continue
            metadata = dict(source.get("metadata") or {})
            organization_id = str(metadata.get("organization_id") or "org_jianghu")
            team_id = str(metadata.get("team_id") or "")
            source_directory = (
                self.knowledge_root
                / self._safe_segment(organization_id, "organization")
                / self._safe_segment(team_id or "_realm", "scope")
                / self._safe_segment(source["id"], "source")
            ).resolve()
            candidates = sorted(source_directory.glob("content.*")) if source_directory.is_dir() else []
            if not candidates:
                candidates = sorted(self.knowledge_root.glob(f"**/{self._safe_segment(source['id'], 'source')}/content.*"))
            managed_path = next((path.resolve() for path in candidates if path.is_file()), None)
            if managed_path is None or not managed_path.is_relative_to(self.knowledge_root):
                continue
            extracted_path = managed_path.parent / "extracted.txt"
            metadata["managed"] = True
            metadata["managed_path"] = str(managed_path)
            if extracted_path.is_file():
                metadata["extracted_path"] = str(extracted_path.resolve())
            with self._connect() as db:
                db.execute(
                    "UPDATE knowledge_sources SET uri=?,metadata_json=? WHERE id=?",
                    (str(managed_path), json.dumps(metadata, ensure_ascii=False), source["id"]),
                )
            if team_id:
                paths_by_team.setdefault(team_id, []).append(str(managed_path))

        if not paths_by_team:
            return
        now = utc_now()
        with self._connect() as db:
            for team_id, managed_paths in paths_by_team.items():
                row = db.execute("SELECT knowledge_paths_json FROM agent_teams WHERE id=?", (team_id,)).fetchone()
                if not row:
                    continue
                raw_paths = json.loads(str(_row_value(row, "knowledge_paths_json")) or "[]")
                existing_paths = [str(Path(item).resolve()) for item in raw_paths if Path(str(item)).is_file()]
                normalized = list(dict.fromkeys([*existing_paths, *managed_paths]))
                db.execute(
                    "UPDATE agent_teams SET knowledge_paths_json=?,updated_at=? WHERE id=?",
                    (json.dumps(normalized, ensure_ascii=False), now, team_id),
                )

    def _backfill_knowledge_indexes(self) -> None:
        for source in self.list_knowledge_sources():
            if source.get("source_type") not in {"managed_upload", "managed_note"}:
                continue
            metadata = source.get("metadata") or {}
            if metadata.get("indexed") and int(metadata.get("chunk_count") or 0) > 0:
                continue
            try:
                self._index_knowledge_source(str(source["id"]))
            except (OSError, ValueError):
                continue

    def search_team_knowledge(self, team_id: str, query: str, limit: int = 8, agent_id: str | None = None) -> dict[str, Any]:
        team = self.get_team(team_id)
        if not team or team.get("status") == "disbanded":
            raise ValueError("team_not_found")
        with self._connect() as db:
            rows = db.execute(
                """SELECT c.id,c.source_id,c.chunk_index,c.title,c.locator,c.content,c.token_estimate,c.metadata_json,
                s.name AS source_name,s.version AS source_version,s.metadata_json AS source_metadata_json
                FROM knowledge_chunks c JOIN knowledge_sources s ON s.id=c.source_id
                WHERE s.status='ready' AND (
                    (c.organization_id=? AND (c.team_id='' OR c.team_id=?))
                    OR (? IS NOT NULL AND c.source_id IN (
                        SELECT source_id FROM knowledge_bindings WHERE entity_type='agent' AND entity_id=?
                    ))
                ) ORDER BY s.updated_at DESC,c.chunk_index""",
                (team["organization_id"], team_id, agent_id, agent_id),
            ).fetchall()
        candidates: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json"))
            item["source_metadata"] = json.loads(item.pop("source_metadata_json"))
            candidates.append(item)
        ranked = score_chunks(query, candidates, limit=max(limit * 2, limit))
        results: list[dict[str, Any]] = []
        seen_content: set[str] = set()
        for item in ranked:
            identity = hashlib.sha256(str(item.get("content") or "").encode("utf-8")).hexdigest()
            if identity in seen_content:
                continue
            seen_content.add(identity)
            results.append(item)
            if len(results) >= max(1, min(limit, 20)):
                break
        return {
            "team_id": team_id,
            "organization_id": team["organization_id"],
            "agent_id": agent_id,
            "query": query,
            "strategy": "hybrid_lexical_char_ngram",
            "candidate_count": len(candidates),
            "results": results,
        }

    def set_knowledge_bindings(self, entity_type: str, entity_id: str, source_ids: list[str]) -> list[str]:
        if entity_type not in {"organization", "team", "agent"}:
            raise ValueError("knowledge_binding_entity_invalid")
        known_sources = {source["id"] for source in self.list_knowledge_sources()}
        normalized = list(dict.fromkeys(str(item) for item in source_ids if str(item)))
        if not set(normalized).issubset(known_sources):
            raise ValueError("knowledge_source_not_found")
        now = utc_now()
        with self._connect() as db:
            db.execute("DELETE FROM knowledge_bindings WHERE entity_type=? AND entity_id=?", (entity_type, entity_id))
            for source_id in normalized:
                db.execute(
                    "INSERT INTO knowledge_bindings(entity_type,entity_id,source_id,access_mode,created_at) VALUES(?,?,?,?,?)",
                    (entity_type, entity_id, source_id, "read", now),
                )
        return normalized

    def list_knowledge_bindings(self, entity_type: str, entity_id: str) -> list[str]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT source_id FROM knowledge_bindings WHERE entity_type=? AND entity_id=? ORDER BY created_at",
                (entity_type, entity_id),
            ).fetchall()
        return [str(_row_value(row, "source_id")) for row in rows]

    def attach_team_knowledge_note(
        self,
        team_id: str,
        title: str,
        content: str,
        project_id: str = "project_jianghu",
    ) -> dict[str, Any]:
        safe_title = re.sub(r"[<>:\"/\\|?*]+", "-", title).strip(" .-") or "组织知识补充"
        document = f"# {title.strip() or safe_title}\n\n{content.strip()}\n".encode("utf-8")
        return self.attach_team_knowledge_file(
            team_id,
            f"{safe_title}.md",
            document,
            "text/markdown",
            project_id,
            source_type="managed_note",
        )

    def create_knowledge_source(self, project_id: str, name: str, source_type: str, uri: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        now = utc_now()
        source_id = new_id("knowledge")
        with self._connect() as db:
            if db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
                raise ValueError("project_not_found")
            db.execute(
                """INSERT INTO knowledge_sources
                (id,project_id,name,source_type,uri,status,version,metadata_json,created_at,updated_at)
                VALUES(?,?,?,?,?,'registered',1,?,?,?)""",
                (source_id, project_id, name, source_type, uri, json.dumps(metadata or {}), now, now),
            )
        return next(item for item in self.list_knowledge_sources(project_id) if item["id"] == source_id)

    def attach_team_knowledge_file(
        self,
        team_id: str,
        filename: str,
        content: bytes,
        media_type: str = "text/plain",
        project_id: str = "project_jianghu",
        source_type: str = "managed_upload",
        relative_path: str = "",
        collection_id: str = "",
    ) -> dict[str, Any]:
        team = self.get_team(team_id)
        if not team or team.get("status") == "disbanded":
            raise ValueError("team_not_found")
        result = self._attach_scoped_knowledge_file(
            scope_type="team",
            scope_id=team_id,
            organization_id=str(team["organization_id"]),
            team_id=team_id,
            filename=filename,
            content=content,
            media_type=media_type,
            project_id=project_id,
            source_type=source_type,
            relative_path=relative_path,
            collection_id=collection_id,
        )
        result["team"] = self.get_team(team_id)
        return result

    def attach_organization_knowledge_file(
        self,
        organization_id: str,
        filename: str,
        content: bytes,
        media_type: str = "text/plain",
        project_id: str = "project_jianghu",
        source_type: str = "managed_upload",
        relative_path: str = "",
        collection_id: str = "",
    ) -> dict[str, Any]:
        if not any(item["id"] == organization_id for item in self.list_organizations()):
            raise ValueError("organization_not_found")
        return self._attach_scoped_knowledge_file(
            scope_type="organization",
            scope_id=organization_id,
            organization_id=organization_id,
            team_id="",
            filename=filename,
            content=content,
            media_type=media_type,
            project_id=project_id,
            source_type=source_type,
            relative_path=relative_path,
            collection_id=collection_id,
        )

    def attach_organization_knowledge_note(
        self,
        organization_id: str,
        title: str,
        content: str,
        project_id: str = "project_jianghu",
    ) -> dict[str, Any]:
        safe_title = re.sub(r"[<>:\"/\\|?*]+", "-", title).strip(" .-") or "大江湖公共知识补充"
        document = f"# {title.strip() or safe_title}\n\n{content.strip()}\n".encode("utf-8")
        return self.attach_organization_knowledge_file(
            organization_id, f"{safe_title}.md", document, "text/markdown", project_id, source_type="managed_note"
        )

    def _attach_scoped_knowledge_file(
        self,
        *,
        scope_type: str,
        scope_id: str,
        organization_id: str,
        team_id: str,
        filename: str,
        content: bytes,
        media_type: str,
        project_id: str,
        source_type: str,
        relative_path: str,
        collection_id: str,
    ) -> dict[str, Any]:
        if not content:
            raise ValueError("knowledge_file_empty")
        if len(content) > 20 * 1024 * 1024:
            raise ValueError("knowledge_file_too_large")
        original_name = Path(filename or "knowledge.txt").name
        normalized_relative_path = str(relative_path or filename or original_name).replace("\\", "/").lstrip("/")
        if ".." in Path(normalized_relative_path).parts:
            raise ValueError("invalid_knowledge_relative_path")
        suffix = Path(original_name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError("knowledge_file_type_not_supported")
        digest = hashlib.sha256(content).hexdigest()
        existing_source = next(
            (
                source
                for source in self.list_knowledge_sources(project_id)
                if source.get("source_type") in {"managed_upload", "managed_note"}
                and source.get("metadata", {}).get("scope_type") == scope_type
                and source.get("metadata", {}).get("scope_id") == scope_id
                and source.get("metadata", {}).get("sha256") == digest
                and Path(str(source.get("uri") or "")).is_file()
            ),
            None,
        )
        if existing_source:
            now = utc_now()
            with self._connect() as db:
                if scope_type == "team":
                    team = self.get_team(scope_id)
                    knowledge_paths = list((team or {}).get("knowledge_paths") or [])
                    existing_path = str(Path(str(existing_source["uri"])).resolve())
                    if existing_path not in knowledge_paths:
                        knowledge_paths.append(existing_path)
                        db.execute(
                            "UPDATE agent_teams SET knowledge_paths_json=?,updated_at=? WHERE id=?",
                            (json.dumps(knowledge_paths, ensure_ascii=False), now, scope_id),
                        )
                db.execute(
                    "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        new_id("log"),
                        scope_type,
                        scope_id,
                        "knowledge_upload_reused",
                        json.dumps(
                            {
                                "knowledge_source_id": existing_source["id"],
                                "filename": original_name,
                                "sha256": digest,
                            },
                            ensure_ascii=False,
                        ),
                        now,
                    ),
                )
            if not existing_source.get("metadata", {}).get("indexed"):
                existing_source = self._index_knowledge_source(str(existing_source["id"]))
            return {
                "source": existing_source,
                "reused": True,
                "index": {
                    "status": existing_source.get("metadata", {}).get("index_status"),
                    "chunk_count": existing_source.get("metadata", {}).get("chunk_count", 0),
                },
            }
        source_id = new_id("knowledge")
        managed_root = (
            self.knowledge_root
            / self._safe_segment(organization_id, "organization")
            / self._safe_segment(team_id or "_realm", "scope")
            / self._safe_segment(source_id, "source")
        ).resolve()
        if not managed_root.is_relative_to(self.knowledge_root):
            raise ValueError("invalid_knowledge_path")
        managed_path = (managed_root / f"content{suffix}").resolve()
        if not managed_path.is_relative_to(managed_root):
            raise ValueError("invalid_knowledge_path")
        managed_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = managed_path.with_suffix(f"{managed_path.suffix}.tmp")
        temporary.write_bytes(content)
        temporary.replace(managed_path)
        now = utc_now()
        metadata = {
            "managed": True,
            "organization_id": organization_id,
            "team_id": team_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "collection_id": collection_id,
            "relative_path": normalized_relative_path,
            "original_filename": original_name,
            "media_type": media_type or "application/octet-stream",
            "size_bytes": len(content),
            "sha256": digest,
            "managed_path": str(managed_path),
        }
        try:
            with self._connect() as db:
                if db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
                    raise ValueError("project_not_found")
                db.execute(
                    """INSERT INTO knowledge_sources
                    (id,project_id,name,source_type,uri,status,version,metadata_json,created_at,updated_at)
                    VALUES(?,?,?,?,?,'processing',1,?,?,?)""",
                    (source_id, project_id, original_name, source_type, str(managed_path), json.dumps(metadata, ensure_ascii=False), now, now),
                )
                db.execute(
                    "INSERT INTO knowledge_bindings(entity_type,entity_id,source_id,access_mode,created_at) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
                    (scope_type, scope_id, source_id, "read", now),
                )
                if scope_type == "team":
                    team = self.get_team(scope_id)
                    knowledge_paths = list((team or {}).get("knowledge_paths") or [])
                    if str(managed_path) not in knowledge_paths:
                        knowledge_paths.append(str(managed_path))
                        db.execute(
                            "UPDATE agent_teams SET knowledge_paths_json=?,updated_at=? WHERE id=?",
                            (json.dumps(knowledge_paths, ensure_ascii=False), now, scope_id),
                        )
                db.execute(
                    "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                    (new_id("log"), scope_type, scope_id, "knowledge_uploaded", json.dumps({"knowledge_source_id": source_id, "filename": original_name, "relative_path": normalized_relative_path, "sha256": digest}, ensure_ascii=False), now),
                )
        except Exception:
            managed_path.unlink(missing_ok=True)
            raise
        source = self._index_knowledge_source(source_id)
        return {
            "source": source,
            "reused": False,
            "index": {
                "status": source.get("metadata", {}).get("index_status"),
                "chunk_count": source.get("metadata", {}).get("chunk_count", 0),
            },
        }

    def knowledge_graph(self, organization_id: str) -> dict[str, Any]:
        organization = next((item for item in self.list_organizations() if item["id"] == organization_id), None)
        if not organization:
            raise ValueError("organization_not_found")
        teams = self.list_teams(organization_id)
        sources = [
            source for source in self.list_knowledge_sources()
            if str(source.get("metadata", {}).get("organization_id") or "") == organization_id
        ]
        nodes_by_id: dict[str, dict[str, Any]] = {}
        edges_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

        def add_node(node_id: str, type_: str, label: str, subtitle: str, **properties: Any) -> dict[str, Any]:
            existing = nodes_by_id.get(node_id)
            if existing:
                existing.setdefault("properties", {}).update({key: value for key, value in properties.items() if value not in (None, "", [])})
                return existing
            node = {
                "id": node_id,
                "type": type_,
                "label": label,
                "subtitle": subtitle,
                "properties": {key: value for key, value in properties.items() if value not in (None, "", [])},
            }
            nodes_by_id[node_id] = node
            return node

        def add_edge(
            source: str,
            target: str,
            type_: str,
            label: str,
            *,
            evidence: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            key = (source, target, type_)
            edge = edges_by_key.get(key)
            if edge is None:
                edge = {
                    "id": f"edge:{hashlib.sha1('|'.join(key).encode('utf-8')).hexdigest()[:14]}",
                    "source": source,
                    "target": target,
                    "type": type_,
                    "label": label,
                    "weight": 0,
                    "evidence": [],
                }
                edges_by_key[key] = edge
            edge["weight"] += 1
            if evidence and len(edge["evidence"]) < 8:
                edge["evidence"].append(evidence)
            return edge

        add_node(
            organization_id,
            "realm",
            organization["name"],
            "大江湖",
            description=organization.get("description"),
            owner_name=organization.get("owner_name"),
            world_type=organization.get("world_type"),
        )
        agent_ids: set[str] = set()
        entity_names: dict[str, str] = {}
        for team in teams:
            add_node(
                team["id"], "team", team["name"], "小江湖",
                purpose=team.get("purpose"), operating_mode=team.get("operating_mode"),
                member_count=len(team.get("members", [])), version=team.get("version"),
            )
            entity_names[str(team["id"])] = str(team["name"])
            add_edge(organization_id, team["id"], "contains", "包含")
            for member in team["members"]:
                if member["id"] not in agent_ids:
                    add_node(
                        member["id"], "agent", member["name"], member["role"],
                        role=member.get("role"), description=member.get("description"),
                        capabilities=member.get("capabilities", []), runtime=member.get("runtime"),
                        memory_count=member.get("memory_count", 0),
                    )
                    agent_ids.add(member["id"])
                    entity_names[str(member["id"])] = str(member["name"])
                add_edge(
                    team["id"], member["id"], "member", "成员",
                    evidence={"responsibility": member.get("responsibility"), "member_role": member.get("member_role")},
                )
        folder_nodes: set[str] = set()
        for source in sources:
            metadata = source.get("metadata") or {}
            relative_path = str(metadata.get("relative_path") or source["name"]).replace("\\", "/")
            scope_id = str(metadata.get("scope_id") or organization_id)
            parent_id = scope_id
            parts = [part for part in relative_path.split("/")[:-1] if part]
            accumulated: list[str] = []
            for part in parts:
                accumulated.append(part)
                folder_id = f"folder:{scope_id}:{'/'.join(accumulated)}"
                if folder_id not in folder_nodes:
                    add_node(
                        folder_id, "folder", part, "知识目录",
                        path="/".join(accumulated), scope_id=scope_id, scope_type=metadata.get("scope_type"),
                    )
                    add_edge(parent_id, folder_id, "contains", "目录")
                    folder_nodes.add(folder_id)
                parent_id = folder_id
            source_node = add_node(
                source["id"], "source", source["name"], f"{metadata.get('chunk_count', 0)} 个片段",
                status=source["status"], relative_path=relative_path, scope_id=scope_id,
                scope_type=metadata.get("scope_type"), media_type=metadata.get("media_type"),
                chunk_count=metadata.get("chunk_count", 0), parser=metadata.get("parser"),
                version=source.get("version"), updated_at=source.get("updated_at"),
            )
            source_node["status"] = source["status"]
            add_edge(parent_id, source["id"], "knowledge", "知识")
            if metadata.get("scope_type") == "organization":
                for team in teams:
                    add_edge(source["id"], team["id"], "inherited_by", "继承")
        with self._connect() as db:
            bindings = db.execute(
                """SELECT b.entity_id,b.source_id FROM knowledge_bindings b JOIN knowledge_sources s ON s.id=b.source_id
                WHERE b.entity_type='agent'"""
            ).fetchall()
            source_ids = [str(source["id"]) for source in sources]
            chunk_rows = []
            if source_ids:
                placeholders = ",".join("?" for _ in source_ids)
                chunk_rows = db.execute(
                    f"""SELECT id,source_id,chunk_index,title,locator,content,token_estimate
                    FROM knowledge_chunks WHERE source_id IN ({placeholders})
                    ORDER BY source_id,chunk_index""",
                    source_ids,
                ).fetchall()
        for binding in bindings:
            if binding["entity_id"] in agent_ids and any(source["id"] == binding["source_id"] for source in sources):
                add_edge(binding["source_id"], binding["entity_id"], "authorized", "授权")

        concept_sources: dict[str, set[str]] = {}
        concepts_per_source: dict[str, int] = {}
        for row in chunk_rows:
            source_id = str(row["source_id"])
            if concepts_per_source.get(source_id, 0) >= 12:
                continue
            raw_title = str(row["title"] or row["locator"] or "知识片段").strip()
            normalized_title = re.sub(r"\s+", " ", raw_title).strip("# -：:")[:72]
            if not normalized_title:
                continue
            normalized_key = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", normalized_title).lower()
            if len(normalized_key) < 2:
                continue
            concept_id = f"concept:{hashlib.sha1(normalized_key.encode('utf-8')).hexdigest()[:14]}"
            concept_sources.setdefault(concept_id, set()).add(source_id)
            add_node(
                concept_id, "concept", normalized_title, "知识实体",
                source_count=len(concept_sources[concept_id]),
                excerpt=str(row["content"] or "")[:360], locator=row["locator"],
            )
            nodes_by_id[concept_id]["properties"]["source_count"] = len(concept_sources[concept_id])
            add_edge(
                source_id, concept_id, "describes", "抽取",
                evidence={"chunk_id": row["id"], "locator": row["locator"], "excerpt": str(row["content"] or "")[:180]},
            )
            concepts_per_source[source_id] = concepts_per_source.get(source_id, 0) + 1
            content = str(row["content"] or "")
            for entity_id, entity_name in entity_names.items():
                if len(entity_name) >= 2 and entity_name in content:
                    add_edge(
                        concept_id, entity_id, "mentions", "提及",
                        evidence={"chunk_id": row["id"], "source_id": source_id, "locator": row["locator"]},
                    )

        nodes = list(nodes_by_id.values())
        edges = list(edges_by_key.values())
        entity_type_counts: dict[str, int] = {}
        relation_type_counts: dict[str, int] = {}
        for node in nodes:
            entity_type_counts[node["type"]] = entity_type_counts.get(node["type"], 0) + 1
        for edge in edges:
            relation_type_counts[edge["type"]] = relation_type_counts.get(edge["type"], 0) + 1
        return {
            "organization": organization,
            "nodes": nodes,
            "edges": edges,
            "entity_types": [{"type": key, "count": value} for key, value in sorted(entity_type_counts.items())],
            "relation_types": [{"type": key, "count": value} for key, value in sorted(relation_type_counts.items())],
            "construction": {
                "mode": "evidence_bound_relationship_projection",
                "stages": ["source", "chunk", "ontology", "entity_relation", "evidence_binding", "visualization"],
                "source_count": len(sources),
                "chunk_count": len(chunk_rows),
                "concept_count": entity_type_counts.get("concept", 0),
                "evidence_edge_count": sum(1 for edge in edges if edge.get("evidence")),
            },
        }

    def knowledge_file_path(self, source_id: str) -> Path:
        source = next((item for item in self.list_knowledge_sources() if item["id"] == source_id), None)
        if not source or source.get("source_type") not in {"managed_upload", "managed_note"}:
            raise ValueError("knowledge_source_not_found")
        path = Path(str(source.get("uri") or "")).resolve()
        if not path.is_relative_to(self.knowledge_root) or not path.is_file():
            raise ValueError("knowledge_file_not_found")
        return path

    @staticmethod
    def _token_hint(token: str) -> str:
        if len(token) <= 8:
            return "********"
        return f"{token[:4]}****{token[-4:]}"

    def list_model_configs(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT id,name,provider,base_url,model,tier,token_hint,active,created_at,updated_at
                   FROM model_configs
                   ORDER BY active DESC,
                            CASE tier WHEN 'medium' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,
                            updated_at DESC"""
            ).fetchall()
        return [dict(row) | {"active": bool(row["active"])} for row in rows]

    def get_model_config(self, config_id: str, include_secret: bool = False) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM model_configs WHERE id=?", (config_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["active"] = bool(result["active"])
        encrypted = result.pop("encrypted_token")
        if include_secret:
            result["token"] = unprotect_secret(encrypted, key_path=self.secret_key_path)
            if not str(encrypted).startswith("fernet:v1:"):
                migrated = protect_secret(result["token"], key_path=self.secret_key_path)
                with self._connect() as db:
                    db.execute("UPDATE model_configs SET encrypted_token=? WHERE id=?", (migrated, result["id"]))
        return result

    def get_active_model_config(self, include_secret: bool = False) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                """SELECT * FROM model_configs
                   WHERE active=1
                   ORDER BY CASE tier WHEN 'medium' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,
                            updated_at DESC LIMIT 1"""
            ).fetchone()
        if not row:
            base_url = os.getenv("ANTHROPIC_BASE_URL", "").strip()
            token = os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()
            model = os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "").strip()
            if not (base_url and token and model):
                return None
            result = {
                "id": "env-default",
                "name": "环境默认模型",
                "provider": "anthropic-compatible",
                "base_url": base_url.rstrip("/"),
                "model": model,
                "tier": "medium",
                "active": True,
            }
            if include_secret:
                result["token"] = token
            else:
                result["token_hint"] = self._token_hint(token)
            return result
        result = dict(row)
        result["active"] = bool(result["active"])
        encrypted = result.pop("encrypted_token")
        if include_secret:
            result["token"] = unprotect_secret(encrypted, key_path=self.secret_key_path)
            if not str(encrypted).startswith("fernet:v1:"):
                migrated = protect_secret(result["token"], key_path=self.secret_key_path)
                with self._connect() as db:
                    db.execute("UPDATE model_configs SET encrypted_token=? WHERE id=?", (migrated, result["id"]))
        return result

    def get_model_config_for_tier(
        self,
        tier: str = "medium",
        include_secret: bool = False,
        allow_fallback: bool = True,
    ) -> dict[str, Any] | None:
        normalized = tier if tier in {"high", "medium", "low"} else "medium"
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM model_configs WHERE tier=? AND active=1 ORDER BY updated_at DESC LIMIT 1",
                (normalized,),
            ).fetchone()
        if not row and allow_fallback and normalized != "medium":
            return self.get_model_config_for_tier("medium", include_secret)
        if not row and allow_fallback:
            return self.get_active_model_config(include_secret)
        if not row:
            return None
        result = dict(row)
        result["active"] = bool(result["active"])
        result["tier"] = str(result.get("tier") or normalized)
        encrypted = result.pop("encrypted_token")
        if include_secret:
            result["token"] = unprotect_secret(encrypted, key_path=self.secret_key_path)
        return result

    def save_model_config(self, *, config_id: str | None, name: str, provider: str, base_url: str, model: str, tier: str = "medium", token: str | None, active: bool) -> dict[str, Any]:
        tier = tier if tier in {"high", "medium", "low"} else "medium"
        now = utc_now()
        with self._connect() as db:
            existing = db.execute("SELECT * FROM model_configs WHERE id=?", (config_id,)).fetchone() if config_id else None
            if existing and not token:
                encrypted_token = existing["encrypted_token"]
                token_hint = existing["token_hint"]
            elif token:
                encrypted_token = protect_secret(token, key_path=self.secret_key_path)
                token_hint = self._token_hint(token)
            else:
                raise ValueError("model_token_required")
            model_id = config_id or new_id("model")
            if active:
                db.execute("UPDATE model_configs SET active=0 WHERE tier=?", (tier,))
            if existing:
                db.execute(
                    "UPDATE model_configs SET name=?,provider=?,base_url=?,model=?,tier=?,encrypted_token=?,token_hint=?,active=?,updated_at=? WHERE id=?",
                    (name, provider, base_url.rstrip("/"), model, tier, encrypted_token, token_hint, int(active), now, model_id),
                )
            else:
                db.execute(
                    """INSERT INTO model_configs
                    (id,name,provider,base_url,model,tier,encrypted_token,token_hint,active,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (model_id, name, provider, base_url.rstrip("/"), model, tier, encrypted_token, token_hint, int(active), now, now),
                )
        return next(item for item in self.list_model_configs() if item["id"] == model_id)

    def delete_model_config(self, config_id: str) -> dict[str, Any]:
        with self._connect() as db:
            existing = db.execute("SELECT id,name,tier,active FROM model_configs WHERE id=?", (config_id,)).fetchone()
            if not existing:
                raise ValueError("model_config_not_found")
            was_active = bool(existing["active"])
            tier = str(existing["tier"] or "medium")
            db.execute("DELETE FROM model_configs WHERE id=?", (config_id,))
            promoted_id: str | None = None
            if was_active:
                replacement = db.execute(
                    "SELECT id FROM model_configs WHERE tier=? ORDER BY updated_at DESC LIMIT 1",
                    (tier,),
                ).fetchone()
                if replacement:
                    promoted_id = str(replacement["id"])
                    db.execute("UPDATE model_configs SET active=1 WHERE id=?", (promoted_id,))
        return {
            "deleted": True,
            "id": config_id,
            "name": str(existing["name"]),
            "promoted_config_id": promoted_id,
        }

    def list_git_delivery_configs(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT project_id,provider,repository_url,api_base_url,default_branch,delivery_mode,
                          username,token_hint,active,created_at,updated_at
                   FROM git_delivery_configs ORDER BY updated_at DESC"""
            ).fetchall()
        return [dict(row) | {"active": bool(row["active"])} for row in rows]

    def list_git_credentials(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT id,name,provider,api_base_url,username,token_hint,active,created_at,updated_at
                   FROM git_credentials ORDER BY active DESC,updated_at DESC"""
            ).fetchall()
        return [dict(row) | {"active": bool(row["active"])} for row in rows]

    def get_git_credential(self, credential_id: str, include_secret: bool = False) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM git_credentials WHERE id=?", (credential_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["active"] = bool(result["active"])
        encrypted = str(result.pop("encrypted_token") or "")
        if include_secret:
            result["token"] = unprotect_secret(encrypted, key_path=self.secret_key_path)
        return result

    def save_git_credential(
        self,
        *,
        credential_id: str | None,
        name: str,
        provider: str,
        api_base_url: str,
        username: str,
        token: str | None,
        active: bool,
    ) -> dict[str, Any]:
        if provider not in {"github", "gitlab", "gitee", "generic"}:
            raise ValueError("git_provider_invalid")
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("git_credential_name_required")
        now = utc_now()
        resolved_id = credential_id or new_id("gitcred")
        with self._connect() as db:
            existing = db.execute("SELECT * FROM git_credentials WHERE id=?", (resolved_id,)).fetchone()
            if existing and not token:
                encrypted_token = str(existing["encrypted_token"])
                token_hint = str(existing["token_hint"])
            elif token:
                encrypted_token = protect_secret(token, key_path=self.secret_key_path)
                token_hint = self._token_hint(token)
            else:
                raise ValueError("git_token_required")
            values = (
                normalized_name, provider, api_base_url.rstrip("/"), username.strip(),
                encrypted_token, token_hint, int(active), now, resolved_id,
            )
            if existing:
                db.execute(
                    """UPDATE git_credentials
                       SET name=?,provider=?,api_base_url=?,username=?,encrypted_token=?,token_hint=?,active=?,updated_at=?
                       WHERE id=?""",
                    values,
                )
            else:
                db.execute(
                    """INSERT INTO git_credentials
                       (name,provider,api_base_url,username,encrypted_token,token_hint,active,updated_at,id,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (*values, now),
                )
        return self.get_git_credential(resolved_id)  # type: ignore[return-value]

    def list_project_git_repositories(self, project_id: str | None = None) -> list[dict[str, Any]]:
        query = """SELECT r.*,c.name AS credential_name,c.token_hint AS credential_token_hint
                   FROM project_git_repositories r
                   LEFT JOIN git_credentials c ON c.id=r.credential_id"""
        values: tuple[Any, ...] = ()
        if project_id:
            query += " WHERE r.project_id=?"
            values = (project_id,)
        query += " ORDER BY r.active DESC,r.updated_at DESC"
        with self._connect() as db:
            rows = db.execute(query, values).fetchall()
        return [dict(row) | {"active": bool(row["active"])} for row in rows]

    def get_project_git_repository(self, repository_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list_project_git_repositories() if item["id"] == repository_id), None)

    def save_project_git_repository(
        self,
        *,
        repository_id: str | None,
        project_id: str,
        name: str,
        repository_url: str,
        default_branch: str,
        credential_id: str | None,
        default_delivery_mode: str,
        active: bool,
    ) -> dict[str, Any]:
        if default_delivery_mode not in {"local_commit", "push_branch", "create_merge_request"}:
            raise ValueError("git_delivery_mode_invalid")
        normalized_url = repository_url.strip()
        if not normalized_url:
            raise ValueError("git_repository_url_required")
        now = utc_now()
        resolved_id = repository_id or new_id("gitrepo")
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise ValueError("project_not_found")
            if credential_id and not db.execute("SELECT 1 FROM git_credentials WHERE id=?", (credential_id,)).fetchone():
                raise ValueError("git_credential_not_found")
            existing = db.execute("SELECT 1 FROM project_git_repositories WHERE id=?", (resolved_id,)).fetchone()
            values = (
                project_id, name.strip() or normalized_url.rsplit("/", 1)[-1].removesuffix(".git"), normalized_url,
                default_branch.strip() or "main", credential_id, default_delivery_mode, int(active), now, resolved_id,
            )
            if existing:
                db.execute(
                    """UPDATE project_git_repositories
                       SET project_id=?,name=?,repository_url=?,default_branch=?,credential_id=?,default_delivery_mode=?,active=?,updated_at=?
                       WHERE id=?""",
                    values,
                )
            else:
                db.execute(
                    """INSERT INTO project_git_repositories
                       (project_id,name,repository_url,default_branch,credential_id,default_delivery_mode,active,updated_at,id,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (*values, now),
                )
        return self.get_project_git_repository(resolved_id)  # type: ignore[return-value]

    def bind_run_git_delivery(
        self,
        run_id: str,
        *,
        repository_id: str,
        target_branch: str | None = None,
        delivery_mode: str | None = None,
    ) -> dict[str, Any]:
        repository = self.get_project_git_repository(repository_id)
        if not repository or not repository.get("active"):
            raise ValueError("git_repository_not_found")
        mode = str(delivery_mode or repository["default_delivery_mode"])
        if mode not in {"local_commit", "push_branch", "create_merge_request"}:
            raise ValueError("git_delivery_mode_invalid")
        now = utc_now()
        with self._connect() as db:
            run = db.execute("SELECT id,project_id FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                raise ValueError("run_not_found")
            if str(run["project_id"]) != str(repository["project_id"]):
                raise ValueError("git_repository_project_mismatch")
            credential = None
            if repository.get("credential_id"):
                credential = db.execute("SELECT * FROM git_credentials WHERE id=?", (repository["credential_id"],)).fetchone()
                if not credential or not bool(credential["active"]):
                    raise ValueError("git_credential_not_available")
            values = (
                str(run["project_id"]), repository_id, str(repository["name"]), str(repository["repository_url"]),
                (target_branch or str(repository["default_branch"])).strip() or "main", mode,
                repository.get("credential_id"), str(credential["provider"] if credential else "generic"),
                str(credential["api_base_url"] if credential else ""), str(credential["username"] if credential else ""),
                now, run_id,
            )
            existing = db.execute("SELECT 1 FROM run_git_deliveries WHERE run_id=?", (run_id,)).fetchone()
            if existing:
                db.execute(
                    """UPDATE run_git_deliveries SET project_id=?,repository_id=?,repository_name=?,repository_url=?,
                       target_branch=?,delivery_mode=?,credential_id=?,provider=?,api_base_url=?,username=?,updated_at=? WHERE run_id=?""",
                    values,
                )
            else:
                db.execute(
                    """INSERT INTO run_git_deliveries
                       (project_id,repository_id,repository_name,repository_url,target_branch,delivery_mode,credential_id,
                        provider,api_base_url,username,updated_at,run_id,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*values, now),
                )
        return self.get_run_git_delivery_config(run_id)  # type: ignore[return-value]

    def get_run_git_delivery_config(self, run_id: str, include_secret: bool = False) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM run_git_deliveries WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["active"] = True
        result["default_branch"] = result["target_branch"]
        if result.get("credential_id"):
            credential = self.get_git_credential(str(result["credential_id"]), include_secret=include_secret)
            if not credential or not credential.get("active"):
                if include_secret:
                    raise ValueError("git_credential_not_available")
            elif include_secret:
                result["token"] = credential.get("token", "")
        return result

    def get_git_delivery_config(self, project_id: str, include_secret: bool = False) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM git_delivery_configs WHERE project_id=?", (project_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["active"] = bool(result["active"])
        encrypted = str(result.pop("encrypted_token") or "")
        if include_secret:
            result["token"] = unprotect_secret(encrypted, key_path=self.secret_key_path) if encrypted else ""
        return result

    def save_git_delivery_config(
        self,
        *,
        project_id: str,
        provider: str,
        repository_url: str,
        api_base_url: str,
        default_branch: str,
        delivery_mode: str,
        username: str,
        token: str | None,
        active: bool,
    ) -> dict[str, Any]:
        if provider not in {"github", "gitlab", "gitee", "generic"}:
            raise ValueError("git_provider_invalid")
        if delivery_mode not in {"local_commit", "push_branch", "create_merge_request"}:
            raise ValueError("git_delivery_mode_invalid")
        if delivery_mode != "local_commit" and not repository_url.strip():
            raise ValueError("git_repository_url_required")
        now = utc_now()
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise ValueError("project_not_found")
            existing = db.execute("SELECT * FROM git_delivery_configs WHERE project_id=?", (project_id,)).fetchone()
            if existing and not token:
                encrypted_token = str(existing["encrypted_token"] or "")
                token_hint = str(existing["token_hint"] or "")
            elif token:
                encrypted_token = protect_secret(token, key_path=self.secret_key_path)
                token_hint = self._token_hint(token)
            else:
                encrypted_token = ""
                token_hint = ""
            values = (
                provider, repository_url.strip(), api_base_url.rstrip("/"), default_branch.strip() or "main",
                delivery_mode, username.strip(), encrypted_token, token_hint, int(active), now, project_id,
            )
            if existing:
                db.execute(
                    """UPDATE git_delivery_configs
                       SET provider=?,repository_url=?,api_base_url=?,default_branch=?,delivery_mode=?,username=?,
                           encrypted_token=?,token_hint=?,active=?,updated_at=? WHERE project_id=?""",
                    values,
                )
            else:
                db.execute(
                    """INSERT INTO git_delivery_configs
                       (provider,repository_url,api_base_url,default_branch,delivery_mode,username,encrypted_token,
                        token_hint,active,updated_at,project_id,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*values, now),
                )
        return self.get_git_delivery_config(project_id)  # type: ignore[return-value]

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM agent_blueprints WHERE id=?", (agent_id,)).fetchone()
        return self._agent(row) if row else None

    def list_workflows(self, include_archived: bool = False, organization_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            clauses: list[str] = []
            values: list[Any] = []
            if not include_archived:
                clauses.append("status!='archived'")
            if organization_id:
                clauses.append("organization_id=?")
                values.append(organization_id)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = db.execute(f"SELECT * FROM workflows{where} ORDER BY updated_at DESC", values).fetchall()
        return [self._workflow(row) for row in rows]

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        return self._workflow(row) if row else None

    def create_clarification(self, workflow_id: str, requirement: str, questions: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.get_workflow(workflow_id):
            raise ValueError("workflow_not_found")
        clarification_id = new_id("clarification")
        now = utc_now()
        with self._connect() as db:
            db.execute(
                """INSERT INTO clarification_sessions
                (id,workflow_id,original_requirement,status,questions_json,answers_json,contract_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (clarification_id, workflow_id, requirement, "questioning", json.dumps(questions), "[]", "{}", now, now),
            )
        return self.get_clarification(clarification_id)  # type: ignore[return-value]

    def get_clarification(self, clarification_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM clarification_sessions WHERE id=?", (clarification_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["questions"] = json.loads(result.pop("questions_json"))
        result["answers"] = json.loads(result.pop("answers_json"))
        result["contract"] = json.loads(result.pop("contract_json"))
        return result

    def finalize_clarification(self, clarification_id: str, answers: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
        if not self.get_clarification(clarification_id):
            raise ValueError("clarification_not_found")
        with self._connect() as db:
            db.execute(
                "UPDATE clarification_sessions SET status='confirmed',answers_json=?,contract_json=?,updated_at=? WHERE id=?",
                (json.dumps(answers), json.dumps(contract), utc_now(), clarification_id),
            )
        return self.get_clarification(clarification_id)  # type: ignore[return-value]

    def create_workflow(
        self,
        name: str,
        description: str,
        source: str = "generated",
        definition: dict[str, Any] | None = None,
        organization_id: str = "org_jianghu",
    ) -> dict[str, Any]:
        now = utc_now()
        workflow_id = new_id("workflow")
        workflow_source = source
        with self._connect() as db:
            if db.execute("SELECT 1 FROM organizations WHERE id=?", (organization_id,)).fetchone() is None:
                raise ValueError("organization_not_found")
            agent_rows = db.execute(
                "SELECT id FROM agent_blueprints WHERE organization_id=? ORDER BY created_at",
                (organization_id,),
            ).fetchall()
            agent_ids = [str(_row_value(row, "agent_id")) for row in agent_rows]
            definition = definition or self._default_definition(agent_ids)
            if not isinstance(definition.get("nodes"), list) or not definition["nodes"]:
                raise ValueError("workflow_definition_has_no_nodes")
            bound_ids: list[str] = []
            node_keys: set[str] = set()
            for node in definition["nodes"]:
                if not isinstance(node, dict) or not node.get("key") or not node.get("name"):
                    raise ValueError("workflow_definition_node_invalid")
                key = str(node["key"])
                if key in node_keys:
                    raise ValueError("workflow_definition_duplicate_node_key")
                node_keys.add(key)
                if node.get("agent_id") and not self.get_agent(str(node["agent_id"])):
                    raise ValueError("workflow_definition_agent_not_bound")
                if node.get("agent_id"):
                    agent = self.get_agent(str(node["agent_id"]))
                    if str((agent or {}).get("organization_id")) != str(organization_id):
                        raise ValueError("workflow_definition_agent_organization_mismatch")
                if node.get("agent_id") and str(node["agent_id"]) not in bound_ids:
                    bound_ids.append(str(node["agent_id"]))
                if node.get("team_id"):
                    team = self.get_team(str(node["team_id"]))
                    if not team:
                        raise ValueError("workflow_definition_team_not_bound")
                    if str(team.get("organization_id")) != str(organization_id):
                        raise ValueError("workflow_definition_team_organization_mismatch")
                    team_agent_ids = {member["id"] for member in team["members"]}
                    participants = {str(item) for item in node.get("participant_agent_ids", [])}
                    if participants and not participants.issubset(team_agent_ids):
                        raise ValueError("workflow_definition_participant_not_in_team")
            definition["nodes"] = [dict(node) for node in definition["nodes"]]
            definition["edges"] = definition.get("edges") if isinstance(definition.get("edges"), list) else []
            # A workflow is a frozen asset: every node must have a concrete Agent binding.
            if any(not node.get("agent_id") for node in definition["nodes"]):
                raise ValueError("workflow_definition_requires_fixed_agent_binding")
            for edge in definition["edges"]:
                if not isinstance(edge, list) or len(edge) != 2 or str(edge[0]) not in node_keys or str(edge[1]) not in node_keys:
                    raise ValueError("workflow_definition_edge_invalid")
            dependency_map = {key: set() for key in node_keys}
            for edge_source, edge_target in definition["edges"]:
                dependency_map[str(edge_target)].add(str(edge_source))
            resolved: set[str] = set()
            while len(resolved) < len(node_keys):
                ready = {key for key, dependencies in dependency_map.items() if key not in resolved and dependencies.issubset(resolved)}
                if not ready:
                    raise ValueError("workflow_definition_cycle_detected")
                resolved.update(ready)
            db.execute(
                """INSERT INTO workflows
                (id,organization_id,name,description,version,status,source,definition_json,agent_ids_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (workflow_id, organization_id, name, description, "1.0.0", "ready", workflow_source, json.dumps(definition), json.dumps(bound_ids), now, now),
            )
            db.execute("UPDATE workflows SET family_id=? WHERE id=?", (workflow_id, workflow_id))
        return self.get_workflow(workflow_id)  # type: ignore[return-value]

    def revise_workflow(
        self,
        workflow_id: str,
        *,
        name: str,
        description: str,
        definition: dict[str, Any],
        source: str = "user_revised",
    ) -> dict[str, Any]:
        parent = self.get_workflow(workflow_id)
        if not parent:
            raise ValueError("workflow_not_found")
        revision = self.create_workflow(
            name,
            description,
            source=source,
            definition=definition,
            organization_id=str(parent.get("organization_id") or "org_jianghu"),
        )
        family_id = str(parent.get("family_id") or parent["id"])
        with self._connect() as db:
            family_versions = [str(_row_value(row, "version")) for row in db.execute("SELECT version FROM workflows WHERE family_id=?", (family_id,)).fetchall()]
        latest_version = max(family_versions or [str(parent.get("version", "1.0.0"))], key=lambda value: tuple(int(part) for part in str(value).split(".")))
        major, minor, patch = (int(part) for part in latest_version.split("."))
        next_version = f"{major}.{minor + 1}.0"
        with self._connect() as db:
            db.execute(
                "UPDATE workflows SET version=?,family_id=?,parent_workflow_id=?,updated_at=? WHERE id=?",
                (next_version, family_id, workflow_id, utc_now(), revision["id"]),
            )
        return self.get_workflow(revision["id"])  # type: ignore[return-value]

    def archive_workflow_family(self, workflow_id: str) -> dict[str, Any]:
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            raise ValueError("workflow_not_found")
        family_id = str(workflow.get("family_id") or workflow["id"])
        with self._connect() as db:
            family_rows = db.execute("SELECT id,status FROM workflows WHERE family_id=? OR id=?", (family_id, family_id)).fetchall()
            workflow_ids = [str(row["id"]) for row in family_rows]
            if not workflow_ids:
                raise ValueError("workflow_not_found")
            placeholders = ",".join("?" for _ in workflow_ids)
            active_runs = db.execute(
                f"SELECT id,status FROM runs WHERE workflow_id IN ({placeholders}) AND status IN ('draft','running','pause_requested','paused') LIMIT 20",
                workflow_ids,
            ).fetchall()
            if active_runs:
                raise ValueError("workflow_has_active_runs")
            now = utc_now()
            db.execute(
                f"UPDATE workflows SET status='archived',updated_at=? WHERE id IN ({placeholders})",
                [now, *workflow_ids],
            )
            db.execute(
                "INSERT INTO operation_logs(id,entity_type,entity_id,action,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (
                    new_id("log"),
                    "workflow_family",
                    family_id,
                    "archived",
                    json.dumps({"workflow_ids": workflow_ids}, ensure_ascii=False),
                    now,
                ),
            )
        return {"family_id": family_id, "workflow_ids": workflow_ids, "status": "archived"}

    def extend_run_time(self, run_id: str, minutes: int, *, hydrate_result: bool = True) -> dict[str, Any]:
        """Extend a runtime-limited run and put it back into the recovery queue.

        Extensions are event-backed so the original run start time, completed
        tasks, and artifacts remain immutable and recoverable.
        """
        if minutes not in {30, 60, 120}:
            raise ValueError("invalid_extension_minutes")
        with self._connect() as db:
            run_row = db.execute(
                "SELECT id,workflow_id,status FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            if not run_row:
                raise ValueError("run_not_found")
            if str(run_row["status"] or "") != "budget_exhausted":
                raise ValueError("run_time_extension_not_allowed")
            workflow_row = db.execute(
                "SELECT definition_json FROM workflows WHERE id=?", (str(run_row["workflow_id"]),)
            ).fetchone()
            if not workflow_row:
                raise ValueError("workflow_not_found")
            event_rows = db.execute(
                """SELECT sequence,type,created_at,payload_json FROM events
                   WHERE run_id=? AND type IN (
                     'run.started','run.recovered','run.resumed','run.time_extended',
                     'run.pause_requested','run.paused','run.budget_exhausted',
                     'run.completed','run.failed','run.cancelled','run.revision_exhausted'
                   ) ORDER BY sequence""",
                (run_id,),
            ).fetchall()
        events = [
            {
                "sequence": int(row["sequence"] or 0),
                "type": str(row["type"] or ""),
                "created_at": str(row["created_at"] or ""),
                "payload": json.loads(str(row["payload_json"] or "{}")),
            }
            for row in event_rows
        ]
        budget_event = next((event for event in reversed(events) if event["type"] == "run.budget_exhausted"), None)
        budget_payload = (budget_event or {}).get("payload", {})
        error_detail = str(budget_payload.get("error_detail") or "")
        budget_kind = str(budget_payload.get("budget_kind") or "")
        definition = json.loads(str(workflow_row["definition_json"] or "{}"))
        policies = definition.get("policies", {})
        base_minutes = int(policies.get("max_run_minutes", 180) or 180)
        previous_extensions = sum(
            int((event.get("payload") or {}).get("minutes", 0) or 0)
            for event in events
            if event.get("type") == "run.time_extended"
        )
        effective_before = base_minutes + previous_extensions
        legacy_time_limit = active_run_seconds(events) >= max(0, effective_before * 60 - 1)
        if (
            budget_kind != "run_time_limit"
            and "run_time_limit" not in error_detail
            and not legacy_time_limit
        ):
            raise ValueError("run_time_extension_not_allowed")
        effective_after = effective_before + minutes
        maximum_minutes = configured_maximum_run_minutes()
        if effective_after > maximum_minutes:
            raise ValueError("run_time_extension_limit_exceeded")
        now = utc_now()
        with self._connect() as db:
            updated = db.execute(
                "UPDATE runs SET status='running',stage='resuming_after_time_extension',updated_at=? WHERE id=? AND status='budget_exhausted'",
                (now, run_id),
            )
            if getattr(updated, "rowcount", 0) != 1:
                raise ValueError("run_time_extension_not_allowed")
            self._event(
                db,
                run_id,
                "run.time_extended",
                "intervention",
                "运行时限已延长",
                f"本次现场增加 {minutes} 分钟，总运行时限为 {effective_after} 分钟；已完成节点和产物继续保留。",
                {
                    "minutes": minutes,
                    "base_minutes": base_minutes,
                    "previous_extensions": previous_extensions,
                    "effective_minutes": effective_after,
                    "maximum_minutes": maximum_minutes,
                    "source_error": "run_time_limit",
                },
            )
        if hydrate_result:
            return self.get_run(run_id)  # type: ignore[return-value]
        return {
            "id": run_id,
            "status": "running",
            "stage": "resuming_after_time_extension",
            "minutes": minutes,
            "base_minutes": base_minutes,
            "previous_extensions": previous_extensions,
            "effective_minutes": effective_after,
            "maximum_minutes": maximum_minutes,
        }

    def recover_run(self, run_id: str, from_task_id: str | None = None) -> dict[str, Any]:
        """Resume a terminal Run in place without replacing its evidence history.

        Completed tasks with registered Artifacts remain completed.  Failed or
        otherwise unfinished tasks are marked for a new execution epoch.  A
        targeted recovery also includes every downstream node, while retaining
        all previous task failures, events, and Artifact versions for audit.
        """
        now = utc_now()
        with self._connect() as db:
            run_row = db.execute(
                "SELECT id,workflow_id,status,progress,stage,run_version FROM runs WHERE id=?",
                (run_id,),
            ).fetchone()
            if not run_row:
                raise ValueError("run_not_found")
            previous_status = str(run_row["status"] or "")
            if previous_status not in {"failed", "cancelled", "revision_exhausted", "budget_exhausted"}:
                raise ValueError("run_is_not_recoverable")
            if previous_status == "budget_exhausted":
                budget_row = db.execute(
                    "SELECT payload_json FROM events WHERE run_id=? AND type='run.budget_exhausted' ORDER BY sequence DESC LIMIT 1",
                    (run_id,),
                ).fetchone()
                budget_payload = json.loads(str(budget_row["payload_json"] or "{}")) if budget_row else {}
                if str(budget_payload.get("budget_kind") or "") != "run_time_limit":
                    raise ValueError("run_is_not_recoverable")

            workflow_row = db.execute(
                "SELECT definition_json FROM workflows WHERE id=?",
                (str(run_row["workflow_id"]),),
            ).fetchone()
            if not workflow_row:
                raise ValueError("workflow_not_found")
            definition = json.loads(str(workflow_row["definition_json"] or "{}"))
            task_rows = db.execute(
                """SELECT t.id,t.node_key,t.node_name,t.status,
                          EXISTS(SELECT 1 FROM artifacts a WHERE a.task_id=t.id AND a.run_id=t.run_id) AS has_artifact
                   FROM tasks t WHERE t.run_id=? ORDER BY t.created_at,t.id""",
                (run_id,),
            ).fetchall()
            task_by_id = {str(row["id"]): row for row in task_rows}
            selected_task = task_by_id.get(str(from_task_id)) if from_task_id else None
            if from_task_id and selected_task is None:
                raise ValueError("recovery_task_not_found")

            node_keys = {str(row["node_key"]) for row in task_rows}
            incomplete_node_keys = {
                str(row["node_key"])
                for row in task_rows
                if str(row["status"]) != "completed" or not bool(row["has_artifact"])
            }
            recovery_node_keys = set(incomplete_node_keys)
            if selected_task is not None:
                outgoing: dict[str, set[str]] = {key: set() for key in node_keys}
                for edge in definition.get("edges", []):
                    if isinstance(edge, (list, tuple)) and len(edge) == 2:
                        source, target = str(edge[0]), str(edge[1])
                        if source in node_keys and target in node_keys:
                            outgoing[source].add(target)
                pending = [str(selected_task["node_key"])]
                visited: set[str] = set()
                while pending:
                    current = pending.pop()
                    if current in visited:
                        continue
                    visited.add(current)
                    recovery_node_keys.add(current)
                    for target in outgoing.get(current, set()):
                        if target not in visited:
                            pending.append(target)
            if not recovery_node_keys:
                raise ValueError("run_has_no_unfinished_tasks")

            placeholders = ",".join("?" for _ in recovery_node_keys)
            db.execute(
                f"UPDATE tasks SET status='retrying',updated_at=? WHERE run_id=? AND node_key IN ({placeholders})",
                [now, run_id, *sorted(recovery_node_keys)],
            )
            preserved_node_keys = node_keys - recovery_node_keys
            recovered_progress = int((len(preserved_node_keys) / max(len(task_rows), 1)) * 100)
            updated = db.execute(
                """UPDATE runs SET status='running',stage='recovery_queued',progress=?,updated_at=?
                   WHERE id=? AND status=?""",
                (recovered_progress, now, run_id, previous_status),
            )
            if getattr(updated, "rowcount", 0) != 1:
                raise ValueError("run_is_not_recoverable")
            failure_row = db.execute(
                """SELECT id,sequence,type FROM events
                   WHERE run_id=? AND type IN ('run.failed','run.cancelled','run.revision_exhausted','run.budget_exhausted')
                   ORDER BY sequence DESC LIMIT 1""",
                (run_id,),
            ).fetchone()
            self._event(
                db,
                run_id,
                "run.recovery_requested",
                "recovery",
                "原 Run 已进入未完成节点恢复队列",
                "保留全部历史事件、失败证据和 Artifact，只在新的 execution epoch 中重新执行未完成节点及受影响下游。",
                {
                    "previous_status": previous_status,
                    "run_version": int(run_row["run_version"] or 1),
                    "source_task_id": str(selected_task["id"]) if selected_task else None,
                    "recovery_from_node_key": str(selected_task["node_key"]) if selected_task else None,
                    "recovery_node_keys": sorted(recovery_node_keys),
                    "preserved_node_keys": sorted(preserved_node_keys),
                    "source_failure_event_id": str(failure_row["id"]) if failure_row else None,
                    "source_failure_sequence": int(failure_row["sequence"] or 0) if failure_row else None,
                },
            )
        return {
            "run_id": run_id,
            "run_version": int(run_row["run_version"] or 1),
            "previous_status": previous_status,
            "status": "running",
            "stage": "recovery_queued",
            "progress": recovered_progress,
            "source_task_id": str(selected_task["id"]) if selected_task else None,
            "recovery_from_node_key": str(selected_task["node_key"]) if selected_task else None,
            "recovery_node_keys": sorted(recovery_node_keys),
            "preserved_node_keys": sorted(preserved_node_keys),
        }

    def validate_retry(self, run_id: str, from_task_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        """Validate a retry without persisting a version or changing existing links."""
        original = self.get_run(run_id)
        if not original:
            raise ValueError("run_not_found")
        if original["status"] not in {"failed", "cancelled", "budget_exhausted", "revision_exhausted"}:
            raise ValueError("run_is_not_retryable")
        workflow = self.get_workflow(str(original["workflow_id"]))
        if not workflow:
            raise ValueError("workflow_not_found")
        if from_task_id and not any(str(task["id"]) == str(from_task_id) for task in original.get("tasks", [])):
            raise ValueError("retry_task_not_found")
        return original, workflow

    def retry_run(self, run_id: str, from_task_id: str | None = None) -> dict[str, Any]:
        original, workflow = self.validate_retry(run_id, from_task_id)
        original_task_by_key = {str(task["node_key"]): task for task in original.get("tasks", [])}
        original_task_by_id = {str(task["id"]): task for task in original.get("tasks", [])}
        latest_artifact_by_task: dict[str, dict[str, Any]] = {}
        for artifact in original.get("artifacts", []):
            task_id = str(artifact.get("task_id") or "")
            current = latest_artifact_by_task.get(task_id)
            if current is None or int(artifact.get("version", 0) or 0) > int(current.get("version", 0) or 0):
                latest_artifact_by_task[task_id] = artifact
        retry_from_task = original_task_by_id.get(str(from_task_id)) if from_task_id else None
        node_keys = {str(node["key"]) for node in workflow["definition"].get("nodes", [])}
        retry_node_keys = set(node_keys)
        if retry_from_task:
            retry_from_key = str(retry_from_task["node_key"])
            outgoing: dict[str, set[str]] = {key: set() for key in node_keys}
            for edge in workflow["definition"].get("edges", []):
                if isinstance(edge, list) and len(edge) == 2:
                    outgoing.setdefault(str(edge[0]), set()).add(str(edge[1]))
            descendants = {retry_from_key}
            pending = [retry_from_key]
            while pending:
                current = pending.pop()
                for target in outgoing.get(current, set()):
                    if target not in descendants:
                        descendants.add(target)
                        pending.append(target)
            incomplete = {
                key for key, task in original_task_by_key.items()
                if str(task.get("status")) != "completed" or str(task.get("id")) not in latest_artifact_by_task
            }
            retry_node_keys = descendants | incomplete
        preserved_node_keys = {
            key for key in node_keys
            if key not in retry_node_keys
            and str(original_task_by_key.get(key, {}).get("status")) == "completed"
            and str(original_task_by_key.get(key, {}).get("id")) in latest_artifact_by_task
        }
        retry_id = new_id("run")
        now = utc_now()
        organization_id = str(original.get("organization_id") or workflow.get("organization_id") or "org_jianghu")
        run_family_id = str(original.get("run_family_id") or original["id"])
        new_task_by_key: dict[str, str] = {}
        with self._connect() as db:
            version_row = db.execute(
                "SELECT COALESCE(MAX(run_version),0)+1 AS value FROM runs WHERE run_family_id=?",
                (run_family_id,),
            ).fetchone()
            run_version = int(_row_value(version_row, "value") or 1)
            db.execute(
                "INSERT INTO runs(id,run_family_id,run_version,parent_run_id,project_id,organization_id,workflow_id,task_input,status,stage,created_at,updated_at,clarification_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    retry_id,
                    run_family_id,
                    run_version,
                    run_id,
                    original["project_id"],
                    original.get("organization_id") or workflow.get("organization_id") or "org_jianghu",
                    original["workflow_id"],
                    original["task_input"],
                    "draft",
                    "created_from_retry",
                    now,
                    now,
                    original.get("clarification_id"),
                ),
            )
            for node in workflow["definition"]["nodes"]:
                node_key = str(node["key"])
                task_id = new_id("task")
                new_task_by_key[node_key] = task_id
                db.execute(
                    "INSERT INTO tasks(id,run_id,organization_id,node_key,node_name,agent_id,team_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        task_id, retry_id, organization_id, node["key"], node["name"], node.get("agent_id"), node.get("team_id"),
                        "completed" if node_key in preserved_node_keys else "pending", now, now,
                    ),
                )
            self._event(
                db,
                retry_id,
                "run.retry_created",
                "system",
                "已创建新的重试现场",
                (
                    f"原失败现场保持不变；本次保留 {len(preserved_node_keys)} 个已完成节点，"
                    f"从“{retry_from_task['node_name']}”及未完成节点继续执行。"
                    if retry_from_task else
                    "原失败现场保持不变；本次将使用同一工作流版本和任务输入重新执行。"
                ),
                {
                    "source_run_id": run_id,
                    "run_family_id": run_family_id,
                    "run_version": run_version,
                    "source_task_id": retry_from_task["id"] if retry_from_task else None,
                    "retry_from_node_key": retry_from_task["node_key"] if retry_from_task else None,
                    "retry_node_keys": sorted(retry_node_keys),
                    "preserved_node_keys": sorted(preserved_node_keys),
                },
            )
            source_delivery = db.execute(
                "SELECT * FROM run_git_deliveries WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if source_delivery:
                db.execute(
                    """INSERT INTO run_git_deliveries
                       (run_id,project_id,repository_id,repository_name,repository_url,target_branch,delivery_mode,
                        credential_id,provider,api_base_url,username,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        retry_id, source_delivery["project_id"], source_delivery["repository_id"],
                        source_delivery["repository_name"], source_delivery["repository_url"], source_delivery["target_branch"],
                        source_delivery["delivery_mode"], source_delivery["credential_id"], source_delivery["provider"],
                        source_delivery["api_base_url"], source_delivery["username"], now, now,
                    ),
                )
        retry_record = {
            "id": retry_id,
            "run_family_id": run_family_id,
            "run_version": run_version,
            "parent_run_id": run_id,
            "project_id": original["project_id"],
            "organization_id": organization_id,
            "workflow_id": original["workflow_id"],
            "task_input": original["task_input"],
            "clarification_id": original.get("clarification_id"),
            "created_at": now,
        }
        self._ensure_run_workspace(retry_record, workflow, source_run_id=run_id)
        for node_key in sorted(preserved_node_keys):
            source_task = original_task_by_key[node_key]
            source_artifact = latest_artifact_by_task[str(source_task["id"])]
            if str(source_artifact.get("kind") or "") in {"runtime_file", "runtime_file_change"}:
                inherited_artifact = self.inherit_artifact_bytes(
                    retry_id,
                    new_task_by_key[node_key],
                    source_artifact,
                )
            else:
                inherited_artifact = self.create_artifact(
                    retry_id,
                    new_task_by_key[node_key],
                    str(source_artifact.get("kind") or "workflow_output"),
                    str(source_artifact.get("title") or source_task["node_name"]),
                    str(source_artifact.get("content") or ""),
                    str(source_artifact.get("status") or "candidate"),
                )
            self.append_run_event(
                retry_id,
                "artifact.inherited",
                "artifact",
                f"已继承“{source_task['node_name']}”的已验证产物",
                "定向重试创建了新的不可变 Artifact，并记录其父 Run 来源和原始字节哈希。",
                {
                    "task_id": new_task_by_key[node_key],
                    "node_key": node_key,
                    "artifact_id": inherited_artifact["id"],
                    "artifact_version": inherited_artifact["version"],
                    "source_run_id": run_id,
                    "source_task_id": source_task["id"],
                    "source_artifact_id": source_artifact["id"],
                    "source_artifact_sha256": source_artifact.get("sha256"),
                    "inherited_artifact_sha256": inherited_artifact.get("sha256"),
                    "source_content_artifact_id": self.get_artifact_content_source(str(source_artifact["id"]))["artifact"]["id"],
                    "source_content_sha256": inherited_artifact.get("sha256"),
                },
            )
        return self.get_run(retry_id)  # type: ignore[return-value]

    def create_run(self, workflow_id: str, task_input: str, project_id: str = "project_jianghu", clarification_id: str | None = None) -> dict[str, Any]:
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            raise ValueError("workflow_not_found")
        if workflow.get("status") != "ready":
            raise ValueError("workflow_not_ready")
        clarification = self.get_clarification(clarification_id) if clarification_id else None
        if clarification_id and (not clarification or clarification["status"] != "confirmed"):
            raise ValueError("requirement_contract_not_confirmed")
        if clarification:
            task_input = json.dumps(
                {"original_requirement": task_input, "requirement_contract": clarification["contract"]},
                ensure_ascii=False,
            )
        run_id = new_id("run")
        now = utc_now()
        organization_id = str(workflow.get("organization_id") or "org_jianghu")
        with self._connect() as db:
            if db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
                raise ValueError("project_not_found")
            db.execute(
                "INSERT INTO runs(id,run_family_id,run_version,parent_run_id,project_id,organization_id,workflow_id,task_input,status,stage,created_at,updated_at,clarification_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    run_id,
                    1,
                    None,
                    project_id,
                    organization_id,
                    workflow_id,
                    task_input,
                    "draft",
                    "created",
                    now,
                    now,
                    clarification_id,
                ),
            )
            for node in workflow["definition"]["nodes"]:
                db.execute(
                    "INSERT INTO tasks(id,run_id,organization_id,node_key,node_name,agent_id,team_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (new_id("task"), run_id, organization_id, node["key"], node["name"], node.get("agent_id"), node.get("team_id"), "pending", now, now),
                )
            self._event(db, run_id, "run.created", "system", "执行事件已经建立", "工作流版本、负责组织和固定人物绑定已经冻结为本次执行快照。")
        run_record = {
            "id": run_id,
            "run_family_id": run_id,
            "run_version": 1,
            "parent_run_id": None,
            "project_id": project_id,
            "organization_id": organization_id,
            "workflow_id": workflow_id,
            "task_input": task_input,
            "clarification_id": clarification_id,
            "created_at": now,
        }
        self._ensure_run_workspace(run_record, workflow)
        return self.get_run(run_id)  # type: ignore[return-value]

    def get_run(
        self,
        run_id: str,
        organization_id: str | None = None,
        *,
        event_limit: int | None = None,
        include_artifact_content: bool = True,
    ) -> dict[str, Any] | None:
        with self._connect() as db:
            if organization_id:
                row = db.execute("SELECT * FROM runs WHERE id=? AND organization_id=?", (run_id, organization_id)).fetchone()
            else:
                row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                return None
            run_organization_id = str(row["organization_id"] or "org_jianghu")
            tasks = db.execute("SELECT * FROM tasks WHERE run_id=? AND organization_id=? ORDER BY created_at", (run_id, run_organization_id)).fetchall()
            artifact_columns = "*" if include_artifact_content else (
                "id,run_id,organization_id,task_id,kind,title,'' AS content,version,status,created_at,"
                "relative_path,sha256,media_type,size_bytes"
            )
            artifacts = db.execute(
                f"SELECT {artifact_columns} FROM artifacts WHERE run_id=? AND organization_id=? ORDER BY created_at",
                (run_id, run_organization_id),
            ).fetchall()
            event_count_row = db.execute(
                "SELECT COUNT(*) AS value FROM events WHERE run_id=? AND organization_id=?",
                (run_id, run_organization_id),
            ).fetchone()
            event_count_total = int(_row_value(event_count_row, "value") or 0)
            normalized_event_limit = max(1, int(event_limit)) if event_limit is not None else None
            if normalized_event_limit is None:
                events = db.execute(
                    "SELECT * FROM events WHERE run_id=? AND organization_id=? ORDER BY sequence",
                    (run_id, run_organization_id),
                ).fetchall()
            else:
                # Browser polling must not hydrate an unbounded event history.
                # Fetch the newest window in descending index order, then restore
                # chronological order for the existing UI/dossier contract.
                events = db.execute(
                    """SELECT * FROM (
                        SELECT * FROM events
                        WHERE run_id=? AND organization_id=?
                        ORDER BY sequence DESC LIMIT ?
                    ) recent_events ORDER BY sequence""",
                    (run_id, run_organization_id, normalized_event_limit),
                ).fetchall()
            interventions = db.execute(
                "SELECT * FROM run_interventions WHERE run_id=? AND organization_id=? ORDER BY created_at",
                (run_id, run_organization_id),
            ).fetchall()
            run_family_id = str(row["run_family_id"] or run_id)
            attempts = db.execute(
                """SELECT id,run_family_id,run_version,parent_run_id,status,progress,stage,created_at,updated_at
                FROM runs WHERE run_family_id=? AND organization_id=? ORDER BY run_version DESC""",
                (run_family_id, run_organization_id),
            ).fetchall()
        result = dict(row)
        result["run_family_id"] = run_family_id
        result["attempts"] = [dict(item) for item in attempts]
        result["attempt_count"] = len(attempts) or 1
        result["tasks"] = [self._task(item) for item in tasks]
        result["artifacts"] = [self._artifact(item) for item in artifacts]
        result["events"] = [self._event_json(item) for item in events]
        result["event_count_total"] = event_count_total
        result["events_truncated"] = len(events) < event_count_total
        result["interventions"] = [dict(item) for item in interventions]
        result["git_delivery"] = self.get_run_git_delivery_config(run_id)
        workspace = self._run_workspace(str(result["project_id"]), str(result["id"]))
        result["workspace"] = {
            "root": str(workspace),
            "manifest": str(workspace / "manifest.json"),
            "input": str(workspace / "input"),
            "workflow": str(workspace / "workflow"),
            "artifacts": str(workspace / "artifacts"),
            "code": str(workspace / "code"),
            "logs": str(workspace / "logs"),
            "tmp": str(workspace / "tmp"),
        }
        result["node_dossiers"] = self._build_node_dossiers(result)
        result["agent_presence"] = self._derive_agent_presence(result)
        return result

    def get_run_execution_snapshot(
        self,
        run_id: str,
        organization_id: str | None = None,
        *,
        include_artifact_content: bool = True,
    ) -> dict[str, Any] | None:
        """Load the durable fields needed by the executor without UI projections.

        Long-lived Runs can contain tens of thousands of events. The executor
        needs that history for recovery and evidence, but it does not need the
        attempts list, node dossiers, agent presence, or Git delivery view that
        ``get_run`` derives for the browser. Keeping this path separate avoids
        repeatedly paying for those large Python projections on every node.
        """
        with self._connect() as db:
            if organization_id:
                row = db.execute(
                    "SELECT * FROM runs WHERE id=? AND organization_id=?",
                    (run_id, organization_id),
                ).fetchone()
            else:
                row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                return None
            run_organization_id = str(row["organization_id"] or "org_jianghu")
            tasks = db.execute(
                "SELECT * FROM tasks WHERE run_id=? AND organization_id=? ORDER BY created_at",
                (run_id, run_organization_id),
            ).fetchall()
            artifact_columns = "*" if include_artifact_content else (
                "id,run_id,organization_id,task_id,kind,title,'' AS content,version,status,created_at,"
                "relative_path,sha256,media_type,size_bytes"
            )
            artifacts = db.execute(
                f"SELECT {artifact_columns} FROM artifacts "
                "WHERE run_id=? AND organization_id=? ORDER BY created_at",
                (run_id, run_organization_id),
            ).fetchall()
            events = db.execute(
                "SELECT * FROM events WHERE run_id=? AND organization_id=? ORDER BY sequence",
                (run_id, run_organization_id),
            ).fetchall()
            interventions = db.execute(
                "SELECT * FROM run_interventions "
                "WHERE run_id=? AND organization_id=? ORDER BY created_at",
                (run_id, run_organization_id),
            ).fetchall()
        result = dict(row)
        result["run_family_id"] = str(row["run_family_id"] or run_id)
        result["tasks"] = [self._task(item) for item in tasks]
        result["artifacts"] = [self._artifact(item) for item in artifacts]
        result["events"] = [self._event_json(item) for item in events]
        result["interventions"] = [dict(item) for item in interventions]
        workspace = self._run_workspace(str(result["project_id"]), str(result["id"]))
        result["workspace"] = {
            "root": str(workspace),
            "manifest": str(workspace / "manifest.json"),
            "input": str(workspace / "input"),
            "workflow": str(workspace / "workflow"),
            "artifacts": str(workspace / "artifacts"),
            "code": str(workspace / "code"),
            "logs": str(workspace / "logs"),
            "tmp": str(workspace / "tmp"),
        }
        return result

    def get_run_state(self, run_id: str, organization_id: str | None = None) -> dict[str, Any] | None:
        """Load only the fields needed by control-plane mutation responses."""
        query = (
            "SELECT id,project_id,workflow_id,organization_id,status,progress,stage,run_version,updated_at FROM runs "
            "WHERE id=? AND organization_id=?"
            if organization_id
            else "SELECT id,project_id,workflow_id,organization_id,status,progress,stage,run_version,updated_at FROM runs WHERE id=?"
        )
        parameters: tuple[Any, ...] = (run_id, organization_id) if organization_id else (run_id,)
        with self._connect() as db:
            row = db.execute(query, parameters).fetchone()
        return dict(row) if row else None

    def get_run_task_summary(self, run_id: str, task_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT id,node_key,node_name,status FROM tasks WHERE id=? AND run_id=?",
                (task_id, run_id),
            ).fetchone()
        return dict(row) if row else None

    def get_run_live_snapshot(
        self, run_id: str, organization_id: str | None = None, *, event_limit: int = 100
    ) -> dict[str, Any] | None:
        """Load a bounded live view without hydrating Artifact bodies or dossiers."""
        state = self.get_run_state(run_id, organization_id)
        if not state:
            return None
        bounded_limit = max(10, min(int(event_limit or 100), 300))
        with self._connect() as db:
            task_rows = db.execute(
                "SELECT id,node_key,node_name,status,updated_at FROM tasks WHERE run_id=? ORDER BY created_at,id",
                (run_id,),
            ).fetchall()
            event_rows = db.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT ?",
                (run_id, bounded_limit),
            ).fetchall()
            event_count_row = db.execute(
                "SELECT COUNT(*) AS value FROM events WHERE run_id=?", (run_id,)
            ).fetchone()
            artifact_rows = db.execute(
                "SELECT title,relative_path,media_type FROM artifacts WHERE run_id=?",
                (run_id,),
            ).fetchall()
        evidence = {
            "cases": 0,
            "results": 0,
            "screenshots": 0,
            "browser_reports": 0,
            "case_documents": 0,
            "junit_reports": 0,
            "manifests": 0,
        }
        for row in artifact_rows:
            title = str(row["title"] or row["relative_path"] or "").replace("\\", "/").lower()
            media_type = str(row["media_type"] or "").lower()
            if re.search(r"(^|/)(test-cases|test_cases|测试用例)(\.|/|$)", title):
                evidence["cases"] += 1
            if re.search(r"(^|/)(test-results|test_results|测试结果)(\.|/|$)", title):
                evidence["results"] += 1
            if media_type.startswith("image/") or re.search(r"\.(png|jpe?g|webp)$", title):
                evidence["screenshots"] += 1
            if re.search(r"playwright|browser-e2e|e2e-report|screenshot-index|\.har$", title):
                evidence["browser_reports"] += 1
            if re.search(r"(^|/)(test-cases|test_cases|测试用例).*\.(md|txt|html)$", title):
                evidence["case_documents"] += 1
            if re.search(r"(^|/)(junit|test-results|test_results).*\.xml$", title):
                evidence["junit_reports"] += 1
            if re.search(r"(^|/)(sha256[-_]?manifest|evidence[-_]?manifest)(\.|/|$)", title):
                evidence["manifests"] += 1
        evidence["materials_present"] = all(
            evidence[key] > 0 for key in ("cases", "results", "screenshots", "browser_reports")
        )
        evidence["complete"] = bool(
            evidence["materials_present"]
            and evidence["case_documents"] > 0
            and evidence["junit_reports"] > 0
            and evidence["manifests"] > 0
        )
        return {
            **state,
            "tasks": [dict(row) for row in task_rows],
            "events": [self._event_json(row) for row in reversed(event_rows)],
            "event_count_total": int(_row_value(event_count_row, "value") or 0),
            "artifact_count": len(artifact_rows),
            "test_evidence": evidence,
        }

    def create_run_intervention(
        self,
        run_id: str,
        *,
        kind: str,
        content: str,
        task_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        allowed_kinds = {"supplement", "correction", "question", "require_rework"}
        if kind not in allowed_kinds:
            raise ValueError("intervention_kind_invalid")
        if kind == "require_rework" and not task_id:
            raise ValueError("require_rework_needs_task")
        normalized_content = content.strip()
        if not normalized_content:
            raise ValueError("intervention_content_required")
        now = utc_now()
        intervention_id = new_id("intervention")
        with self._connect() as db:
            run = db.execute("SELECT id,status,organization_id FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                raise ValueError("run_not_found")
            if str(run["status"]) in {"completed", "cancelled", "budget_exhausted", "revision_exhausted"}:
                raise ValueError("run_is_not_intervenable")
            if task_id:
                task = db.execute("SELECT id FROM tasks WHERE id=? AND run_id=?", (task_id, run_id)).fetchone()
                if not task:
                    raise ValueError("intervention_task_not_found")
            if agent_id:
                agent = db.execute("SELECT id,organization_id FROM agent_blueprints WHERE id=?", (agent_id,)).fetchone()
                if not agent:
                    raise ValueError("intervention_agent_not_found")
                if str(agent["organization_id"]) != str(run["organization_id"]):
                    raise ValueError("intervention_agent_organization_mismatch")
            db.execute(
                """INSERT INTO run_interventions
                (id,run_id,organization_id,task_id,agent_id,kind,content,status,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (intervention_id, run_id, run["organization_id"], task_id, agent_id, kind, normalized_content, "queued", now),
            )
        return next(item for item in self.list_run_interventions(run_id) if item["id"] == intervention_id)

    def list_run_interventions(self, run_id: str, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM run_interventions WHERE run_id=?"
        values: list[Any] = [run_id]
        if status:
            query += " AND status=?"
            values.append(status)
        query += " ORDER BY created_at"
        with self._connect() as db:
            rows = db.execute(query, values).fetchall()
        return [dict(row) for row in rows]

    def mark_run_interventions_applied(self, intervention_ids: list[str]) -> list[dict[str, Any]]:
        if not intervention_ids:
            return []
        applied_at = utc_now()
        placeholders = ",".join("?" for _ in intervention_ids)
        with self._connect() as db:
            db.execute(
                f"UPDATE run_interventions SET status='applied',applied_at=? WHERE id IN ({placeholders}) AND status='queued'",
                [applied_at, *intervention_ids],
            )
            rows = db.execute(
                f"SELECT * FROM run_interventions WHERE id IN ({placeholders}) ORDER BY created_at",
                intervention_ids,
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _build_node_dossiers(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
        dossiers: dict[str, dict[str, Any]] = {}
        for task in run.get("tasks", []):
            dossiers[str(task["id"])] = {
                "task_id": task["id"],
                "node_key": task["node_key"],
                "node_name": task["node_name"],
                "agent_id": task.get("agent_id"),
                "team_id": task.get("team_id"),
                "context": [],
                "initiator_notes": [],
                "knowledge": [],
                "contributions": [],
                "communications": [],
                "coordination": [],
                "integration": [],
                "decisions": [],
                "actions": [],
                "files": [],
                "commands": [],
                "tests": [],
                "validations": [],
                "interventions": [],
                "artifacts": [],
            }
        category_by_type = {
            "agent.context.prepared": "context",
            "agent.rationale.submitted": "initiator_notes",
            "knowledge.retrieved": "knowledge",
            "team.member.completed": "contributions",
            "agent.message.sent": "communications",
            "team.dossier.published": "coordination",
            "team.communication.round.started": "coordination",
            "team.communication.round.completed": "coordination",
            "team.synthesis.started": "coordination",
            "engineering.submission.published": "integration",
            "team.synthesis.completed": "decisions",
            "gate.passed": "decisions",
            "gate.rejected": "decisions",
            "agent.action.started": "actions",
            "agent.action.progress": "actions",
            "agent.tool.started": "actions",
            "agent.tool.completed": "actions",
            "agent.file.created": "files",
            "agent.file.modified": "files",
            "agent.file.deleted": "files",
            "agent.command.started": "commands",
            "agent.command.completed": "commands",
            "agent.test.started": "tests",
            "agent.test.completed": "tests",
            "artifact.validation.started": "validations",
            "artifact.validation.passed": "validations",
            "artifact.validation.failed": "validations",
            "user.intervention.queued": "interventions",
            "user.intervention.applied": "interventions",
        }
        for event in run.get("events", []):
            payload = event.get("payload") or {}
            task_id = str(payload.get("task_id") or "")
            dossier = dossiers.get(task_id)
            event_type = str(event.get("type") or "")
            target = category_by_type.get(event_type)
            if event_type == "agent.action.submitted":
                # Team nodes already publish one canonical team.member.completed
                # event per independent contribution and one synthesis decision.
                # Keeping every internal OpenClaw phase here made the UI look as
                # if the same person had submitted the same opinion repeatedly.
                target = "contributions" if dossier and not dossier.get("team_id") else None
            if dossier and target:
                dossier[target].append(event)
        for intervention in run.get("interventions", []):
            task_id = str(intervention.get("task_id") or "")
            if task_id in dossiers and not any(
                str(item.get("payload", {}).get("intervention_id") or "") == str(intervention["id"])
                for item in dossiers[task_id]["interventions"]
            ):
                dossiers[task_id]["interventions"].append(intervention)
        for artifact in run.get("artifacts", []):
            task_id = str(artifact.get("task_id") or "")
            if task_id in dossiers:
                dossiers[task_id]["artifacts"].append(artifact)
        return dossiers

    def _derive_agent_presence(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        workflow = self.get_workflow(str(run.get("workflow_id") or ""))
        known: dict[str, dict[str, Any]] = {}
        task_by_id = {str(task["id"]): task for task in run.get("tasks", [])}
        for node in (workflow or {}).get("definition", {}).get("nodes", []):
            agent_ids = [node.get("agent_id"), *(node.get("participant_agent_ids") or [])]
            for agent_id in agent_ids:
                if not agent_id or str(agent_id) in known:
                    continue
                agent = self.get_agent(str(agent_id))
                if agent:
                    known[str(agent_id)] = {
                        "agent_id": str(agent_id),
                        "name": agent.get("name"),
                        "role": agent.get("role"),
                        "state": "idle",
                        "state_label": "闲居待命",
                        "task_id": None,
                        "node_key": None,
                        "node_name": None,
                        "latest_event": None,
                    }
        states = {
            "task.started": ("assigned", "已经到场"),
            "agent.context.prepared": ("preparing", "整备知识与技能"),
            "knowledge.retrieved": ("retrieving", "查阅获准卷宗"),
            "team.member.started": ("working", "办事中"),
            "agent.action.started": ("working", "办事中"),
            "agent.action.progress": ("working", "持续行动中"),
            "agent.action.retrying": ("retrying", "人物正在自动重试"),
            "agent.action.failed": ("blocked", "人物行动失败，等待重试"),
            "agent.turn.started": ("working", "行动中"),
            "openclaw.turn.started": ("working", "行动中"),
            "agent.tool.started": ("tooling", "调用工具中"),
            "agent.command.started": ("tooling", "执行命令中"),
            "agent.file.created": ("tooling", "正在落地文件"),
            "agent.file.modified": ("tooling", "正在修改文件"),
            "agent.test.started": ("validating", "运行测试中"),
            "artifact.validation.started": ("validating", "校验交付中"),
            "team.dossier.published": ("communicating", "公共卷宗已打开"),
            "team.communication.round.started": ("communicating", "公开议事中"),
            "team.communication.round.completed": ("communicating", "等待下一轮议事"),
            "agent.message.sent": ("communicating", "议事中"),
            "engineering.submission.published": ("waiting", "工程提交已公开"),
            "team.synthesis.started": ("integrating", "整合团队交付"),
            "team.synthesis.completed": ("reviewing", "整理合议"),
            "artifact.validation.passed": ("reviewing", "交付校验通过"),
            "artifact.validation.failed": ("blocked", "交付校验未通过"),
            "gate.passed": ("reviewing", "裁决完成"),
            "gate.rejected": ("reviewing", "正在退回返工"),
            "task.retrying": ("blocked", "受阻后重试"),
            "task.failed": ("blocked", "行动受阻"),
            "team.member.completed": ("waiting", "已提交，等待合议"),
            "agent.action.submitted": ("waiting", "已交卷，等待验收"),
            "agent.memory.persisted": ("idle", "经历已沉淀"),
        }
        for event in run.get("events", []):
            payload = event.get("payload") or {}
            agent_id = str(payload.get("agent_id") or payload.get("from_agent_id") or "")
            if not agent_id and payload.get("task_id"):
                agent_id = str(task_by_id.get(str(payload.get("task_id")), {}).get("agent_id") or "")
            if not agent_id:
                continue
            if agent_id not in known:
                agent = self.get_agent(agent_id)
                known[agent_id] = {
                    "agent_id": agent_id,
                    "name": agent.get("name") if agent else agent_id,
                    "role": agent.get("role") if agent else "江湖人物",
                    "state": "idle",
                    "state_label": "闲居待命",
                    "task_id": None,
                    "node_key": None,
                    "node_name": None,
                    "latest_event": None,
                }
            state = states.get(str(event.get("type") or ""))
            if state:
                task = task_by_id.get(str(payload.get("task_id") or ""), {})
                known[agent_id].update(
                    {
                        "state": state[0],
                        "state_label": state[1],
                        "task_id": payload.get("task_id"),
                        "node_key": payload.get("node_key") or task.get("node_key"),
                        "node_name": task.get("node_name"),
                        "latest_event": event,
                    }
                )
        run_status = str(run.get("status") or "")
        if run_status in {"pause_requested", "paused"}:
            for presence in known.values():
                if presence["state"] not in {"idle", "offline"}:
                    presence["state"] = "paused"
                    presence["state_label"] = "奉命停手"
        elif run_status in {"failed", "budget_exhausted", "revision_exhausted"}:
            terminal_labels = {
                "failed": "行动受阻，等待处理",
                "budget_exhausted": "预算耗尽，等待处理",
                "revision_exhausted": "返工轮次耗尽，等待处理",
            }
            for presence in known.values():
                if presence["state"] not in {"idle", "offline"}:
                    presence["state"] = "blocked"
                    presence["state_label"] = terminal_labels[run_status]
        elif run_status in {"completed", "cancelled"}:
            for presence in known.values():
                presence["state"] = "idle" if run_status == "completed" else "offline"
                presence["state_label"] = "功成归位" if run_status == "completed" else "已离场"
        return list(known.values())

    def append_run_event(self, run_id: str, type_: str, category: str, title: str, summary: str, payload: dict[str, Any] | None = None) -> None:
        with self._connect() as db:
            self._event(db, run_id, type_, category, title, summary, payload or {})

    def update_run(self, run_id: str, *, status: str | None = None, progress: int | None = None, stage: str | None = None, token_count: int | None = None, estimated_cost: float | None = None) -> None:
        fields: list[str] = ["updated_at=?"]
        values: list[Any] = [utc_now()]
        for name, value in (("status", status), ("progress", progress), ("stage", stage), ("token_count", token_count), ("estimated_cost", estimated_cost)):
            if value is not None:
                fields.append(f"{name}=?")
                values.append(value)
        values.append(run_id)
        with self._connect() as db:
            db.execute(f"UPDATE runs SET {', '.join(fields)} WHERE id=?", values)

    def update_task(self, task_id: str, *, status: str, input_data: dict[str, Any] | None = None, output_data: dict[str, Any] | None = None) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE tasks SET status=?, input_json=COALESCE(?,input_json), output_json=COALESCE(?,output_json), updated_at=? WHERE id=?",
                (status, json.dumps(input_data) if input_data is not None else None, json.dumps(output_data) if output_data is not None else None, utc_now(), task_id),
            )

    def create_artifact(
        self,
        run_id: str,
        task_id: str | None,
        kind: str,
        title: str,
        content: str,
        status: str = "candidate",
        *,
        supersede_candidates: bool = True,
    ) -> dict[str, Any]:
        with self._connect() as db:
            run_row = db.execute("SELECT organization_id FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run_row:
                raise ValueError("run_not_found")
            organization_id = str(run_row["organization_id"] or "org_jianghu")
            if task_id is None:
                version_row = db.execute("SELECT COALESCE(MAX(version),0)+1 AS value FROM artifacts WHERE run_id=? AND task_id IS NULL", (run_id,)).fetchone()
            else:
                version_row = db.execute("SELECT COALESCE(MAX(version),0)+1 AS value FROM artifacts WHERE run_id=? AND task_id=?", (run_id, task_id)).fetchone()
            next_version = int(_row_value(version_row, "value"))
        artifact = {"id": new_id("artifact"), "run_id": run_id, "organization_id": organization_id, "task_id": task_id, "kind": kind, "title": title, "content": content, "version": next_version, "status": status, "created_at": utc_now()}
        if task_id is None:
            node_key = "run"
        else:
            with self._connect() as db:
                task = db.execute("SELECT node_key FROM tasks WHERE id=? AND run_id=?", (task_id, run_id)).fetchone()
            if not task:
                raise ValueError("artifact_task_not_found")
            node_key = str(task["node_key"])
        artifact = self._materialize_artifact(artifact, node_key=node_key)
        with self._connect() as db:
            if supersede_candidates:
                if task_id is None:
                    db.execute("UPDATE artifacts SET status='superseded' WHERE run_id=? AND task_id IS NULL AND status='candidate'", (run_id,))
                else:
                    db.execute("UPDATE artifacts SET status='superseded' WHERE run_id=? AND task_id=? AND status='candidate'", (run_id, task_id))
            db.execute(
                """INSERT INTO artifacts
                (id,run_id,organization_id,task_id,kind,title,content,version,status,created_at,relative_path,sha256,media_type,size_bytes)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    artifact["id"], artifact["run_id"], artifact["organization_id"], artifact["task_id"], artifact["kind"], artifact["title"],
                    artifact["content"], artifact["version"], artifact["status"], artifact["created_at"],
                    artifact["relative_path"], artifact["sha256"], artifact["media_type"], artifact["size_bytes"],
                ),
            )
        return artifact

    def register_workspace_file_artifact(
        self,
        run_id: str,
        task_id: str | None,
        relative_path: str,
        *,
        status: str = "candidate",
        change_action: str = "recorded",
        previous_sha256: str = "",
        file_category: str | None = None,
        source_root: str | Path | None = None,
    ) -> dict[str, Any]:
        """Register a delivered file, or a deletion receipt, as an immutable Artifact.

        Engineering turns normally read from the promoted Run code root. Review,
        audit, and reporting turns keep their files in an isolated Agent delivery
        root; callers may pass that root explicitly. Both locations must remain
        inside the durable Run workspace.
        """
        # This is a hot path after an engineering turn. A mature run can have
        # tens of thousands of events, so hydrating the full run projection
        # once per delivered file causes severe quadratic amplification.
        # Resolve only the run and task fields required for registration.
        with self._connect() as db:
            run_row = db.execute(
                "SELECT id,project_id,organization_id FROM runs WHERE id=?",
                (run_id,),
            ).fetchone()
            if not run_row:
                raise ValueError("run_not_found")
            task_row = (
                db.execute(
                    "SELECT id,node_key FROM tasks WHERE id=? AND run_id=?",
                    (task_id, run_id),
                ).fetchone()
                if task_id is not None
                else None
            )
            if task_id is not None and not task_row:
                raise ValueError("artifact_task_not_found")
        task = dict(task_row) if task_row else {"id": None, "node_key": "run"}
        workspace_root = self._run_workspace(str(run_row["project_id"]), run_id).resolve()
        code_root = (workspace_root / "code").resolve()
        resolved_source_root = Path(source_root).resolve() if source_root else code_root
        if not resolved_source_root.is_relative_to(workspace_root):
            raise ValueError("workspace_artifact_source_root_escape")
        source = (resolved_source_root / relative_path).resolve()
        normalized_action = change_action if change_action in {"created", "modified", "deleted", "recorded"} else "recorded"
        if not source.is_relative_to(resolved_source_root) or (normalized_action != "deleted" and not source.is_file()):
            raise ValueError("workspace_artifact_file_not_found")
        category = file_category or workspace_file_category(relative_path)
        source_data = b"" if normalized_action == "deleted" else source.read_bytes()
        source_digest = hashlib.sha256(source_data).hexdigest() if normalized_action != "deleted" else ""
        metadata = {
            "source_relative_path": relative_path,
            "change_action": normalized_action,
            "file_category": category,
            "sha256": source_digest,
            "previous_sha256": previous_sha256,
        }
        data = (
            json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")
            if normalized_action == "deleted"
            else source_data
        )
        artifact_id = new_id("artifact")
        now = utc_now()
        with self._connect() as db:
            if task_id is None:
                version_row = db.execute(
                    "SELECT COALESCE(MAX(version),0)+1 AS value FROM artifacts WHERE run_id=? AND task_id IS NULL AND kind IN ('runtime_file','runtime_file_change')",
                    (run_id,),
                ).fetchone()
            else:
                version_row = db.execute(
                    "SELECT COALESCE(MAX(version),0)+1 AS value FROM artifacts WHERE run_id=? AND task_id=? AND kind IN ('runtime_file','runtime_file_change')",
                    (run_id, task_id),
                ).fetchone()
        version = int(_row_value(version_row, "value") or 1)
        suffix = (
            ".json"
            if normalized_action == "deleted"
            else (source.suffix if source.suffix and len(source.suffix) <= 16 else ".bin")
        )
        artifact_relative = (
            Path("artifacts")
            / self._safe_segment(task.get("node_key"), "node")
            / "files"
            / f"{self._safe_segment(artifact_id, 'artifact')}{suffix}"
        )
        destination = (workspace_root / artifact_relative).resolve()
        if not destination.is_relative_to(workspace_root):
            raise ValueError("invalid_artifact_path")
        self._write_bytes_atomic(destination, data)
        media_type = (
            "application/json"
            if normalized_action == "deleted"
            else workspace_file_media_type(source.name)
        )
        digest = hashlib.sha256(data).hexdigest()
        artifact = {
            "id": artifact_id,
            "run_id": run_id,
            "organization_id": str(run_row["organization_id"] or "org_jianghu"),
            "task_id": task_id,
            "kind": "runtime_file_change" if normalized_action == "deleted" else "runtime_file",
            "title": relative_path,
            "content": json.dumps(metadata, ensure_ascii=False),
            "version": version,
            "status": status,
            "created_at": now,
            "relative_path": artifact_relative.as_posix(),
            "sha256": digest,
            "media_type": media_type,
            "size_bytes": len(data),
        }
        with self._connect() as db:
            db.execute(
                """INSERT INTO artifacts
                (id,run_id,organization_id,task_id,kind,title,content,version,status,created_at,relative_path,sha256,media_type,size_bytes)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    artifact["id"], artifact["run_id"], artifact["organization_id"], artifact["task_id"],
                    artifact["kind"], artifact["title"], artifact["content"], artifact["version"], artifact["status"],
                    artifact["created_at"], artifact["relative_path"], artifact["sha256"], artifact["media_type"], artifact["size_bytes"],
                ),
            )
        manifest_path = workspace_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = [item for item in manifest.get("artifacts", []) if item.get("id") != artifact_id]
        entries.append(
            {
                "id": artifact_id,
                "task_id": task_id,
                "kind": artifact["kind"],
                "title": artifact["title"],
                "status": status,
                "version": version,
                "path": artifact["relative_path"],
                "media_type": media_type,
                "size_bytes": len(data),
                "sha256": digest,
                "created_at": now,
                "source_relative_path": relative_path,
                "change_action": normalized_action,
                "file_category": category,
                "previous_sha256": previous_sha256,
            }
        )
        manifest["artifacts"] = sorted(entries, key=lambda item: (str(item.get("created_at")), str(item.get("id"))))
        self._write_json_atomic(manifest_path, manifest)
        return artifact

    def verify_artifact_bytes(self, run_id: str, artifact_id: str) -> dict[str, Any]:
        """Re-read a materialized Artifact and compare it with the Registry receipt."""
        with self._connect() as db:
            row = db.execute(
                """SELECT a.id,a.task_id,a.kind,a.title,a.relative_path,a.sha256,a.size_bytes,
                          r.project_id
                   FROM artifacts a JOIN runs r ON r.id=a.run_id
                   WHERE a.run_id=? AND a.id=?""",
                (run_id, artifact_id),
            ).fetchone()
        if not row:
            raise ValueError("artifact_not_found")
        artifact = dict(row)
        workspace_root = self._run_workspace(str(artifact["project_id"]), run_id).resolve()
        artifact_path = (workspace_root / str(artifact["relative_path"] or "")).resolve()
        if not artifact_path.is_relative_to(workspace_root) or not artifact_path.is_file():
            return {**artifact, "matched": False, "observed_sha256": "", "observed_size_bytes": 0}
        data = artifact_path.read_bytes()
        observed_sha256 = hashlib.sha256(data).hexdigest()
        observed_size_bytes = len(data)
        return {
            **artifact,
            "matched": (
                observed_sha256 == str(artifact["sha256"] or "")
                and observed_size_bytes == int(artifact["size_bytes"] or 0)
            ),
            "observed_sha256": observed_sha256,
            "observed_size_bytes": observed_size_bytes,
        }

    def _event(self, db: sqlite3.Connection, run_id: str, type_: str, category: str, title: str, summary: str, payload: dict[str, Any] | None = None) -> None:
        sequence_row = db.execute("SELECT COALESCE(MAX(sequence),0)+1 AS value FROM events WHERE run_id=?", (run_id,)).fetchone()
        sequence = int(_row_value(sequence_row, "value"))
        run_row = db.execute("SELECT organization_id FROM runs WHERE id=?", (run_id,)).fetchone()
        organization_id = str(_row_value(run_row, "organization_id") or "org_jianghu")
        now = utc_now()
        db.execute("INSERT INTO events(id,run_id,organization_id,sequence,type,category,title,summary,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (new_id("evt"), run_id, organization_id, sequence, type_, category, title, summary, json.dumps(payload or {}), now))
        db.execute("UPDATE runs SET updated_at=? WHERE id=?", (now, run_id))

    def _agent(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["cognitive_level"] = max(1, min(3, int(result.get("cognitive_level") or 2)))
        result["authority_level"] = max(1, min(3, int(result.get("authority_level") or 1)))
        result["recommended_model_tier"] = {1: "low", 2: "medium", 3: "high"}[result["cognitive_level"]]
        result["capabilities"] = json.loads(result.pop("capabilities_json"))
        result["skills"] = json.loads(result.pop("skills_json", "[]"))
        result["memory_policy"] = json.loads(result.pop("memory_policy_json", "{}"))
        result["knowledge_source_ids"] = self.list_knowledge_bindings("agent", str(result["id"]))
        with self._connect() as db:
            result["memory_count"] = int(
                _row_value(db.execute(
                    """SELECT COUNT(*) AS value FROM agent_memories m
                    JOIN agent_blueprints a ON a.id=m.agent_id
                    WHERE a.family_id=? AND COALESCE(m.status,'active')='active'""",
                    (str(result.get("family_id") or result["id"]),),
                ).fetchone(), "value")
            )
        return result

    def _team_member(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["cognitive_level"] = max(1, min(3, int(result.get("cognitive_level") or 2)))
        result["authority_level"] = max(1, min(3, int(result.get("authority_level") or 1)))
        result["recommended_model_tier"] = {1: "low", 2: "medium", 3: "high"}[result["cognitive_level"]]
        result["capabilities"] = json.loads(result.pop("capabilities_json"))
        result["skills"] = json.loads(result.pop("skills_json", "[]"))
        result["memory_policy"] = json.loads(result.pop("memory_policy_json", "{}"))
        result["knowledge_source_ids"] = self.list_knowledge_bindings("agent", str(result["id"]))
        with self._connect() as db:
            result["memory_count"] = int(
                _row_value(db.execute(
                    """SELECT COUNT(*) AS value FROM agent_memories m
                    JOIN agent_blueprints a ON a.id=m.agent_id
                    WHERE a.family_id=? AND COALESCE(m.status,'active')='active'""",
                    (str(result.get("family_id") or result["id"]),),
                ).fetchone(), "value")
            )
        return result

    @staticmethod
    def _assessment(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["missing_capabilities"] = json.loads(result.pop("missing_capabilities_json"))
        result["recommended_agents"] = json.loads(result.pop("recommended_agents_json"))
        return result

    @staticmethod
    def _team_proposal(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["members"] = json.loads(result.pop("members_json"))
        result["missing_capabilities"] = json.loads(result.pop("missing_capabilities_json"))
        return result

    @staticmethod
    def _workflow(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["definition"] = json.loads(result.pop("definition_json"))
        result["agent_ids"] = json.loads(result.pop("agent_ids_json"))
        return result

    @staticmethod
    def _task(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["input"] = json.loads(result.pop("input_json"))
        result["output"] = json.loads(result.pop("output_json"))
        return result

    @staticmethod
    def _artifact(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    @staticmethod
    def _event_json(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result


platform_store = PlatformStore()
