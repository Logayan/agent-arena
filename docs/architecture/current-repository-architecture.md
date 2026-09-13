# Agent Arena 当前仓库技术架构图

> 本图仅依据当前工作区可读取的源码、配置和设计文档整理，不执行应用代码，不把设计文档中尚未落地的组件当作当前实现。

## 1. 当前实现架构

```mermaid
flowchart TB
    USER[用户]
    WEB[Vue 3 + TypeScript + Vite\nclient/src/App.vue\nclient/src/api.ts]
    API[FastAPI HTTP API\nserver/app/main.py\nREST /api/platform/*]
    EXEC[平台运行执行器\nplatform_executor.py\n任务依赖、并行、返工、预算、产物]
    STORE[PlatformStore\nplatform_store.py\n领域服务与持久化]
    SQLITE[(SQLite\n.data/jianghu.db)]
    PG[(PostgreSQL\n可选 JIANGHU_DATABASE_URL)]
    KNOW[Knowledge Index\nknowledge_index.py\n文档解析、分段、关键词检索]
    FILES[(知识文件 / 工作区 / 产物\n.data/knowledge\n.data/workspaces)]
    LLM[平台 LLM Gateway\nllm_client.py\nWorkflow/配置生成]
    REGISTRY[Agent Runtime Registry\nagent_runtime_registry.py\n生产固定 claude_code]
    CLAUDE[ClaudeCodeRuntime\nclaude_code_runtime.py\nRun/Agent workspace、skills、memory]
    BRIDGE[Node Bridge\nClaude Agent SDK 0.3.268\nClaude Code 2.1.268]
    MODEL[外部模型服务\nAnthropic-compatible 或 OpenAI Responses]
    TOOLS[Agent 工具/代码执行\nRead / Write / Edit / Bash\nWorkspace MCP policy]
    SECRETS[Secret Store\n加密模型凭据与本地密钥]
    DOCKER[Docker Compose\njianghu-online]
    SYNAPSE[Synapse + PostgreSQL\nMatrix 协作平面（Compose）]

    USER --> WEB
    WEB -->|同源 JSON REST| API
    API --> STORE
    API --> EXEC
    EXEC --> STORE
    STORE --> SQLITE
    STORE --> PG
    STORE --> KNOW
    KNOW --> FILES
    STORE --> FILES
    STORE --> SECRETS
    API --> LLM
    EXEC --> REGISTRY
    REGISTRY --> CLAUDE
    CLAUDE --> BRIDGE
    LLM --> MODEL
    BRIDGE --> MODEL
    BRIDGE --> TOOLS
    DOCKER --> API
    DOCKER --> SYNAPSE
    DOCKER --> SQLITE
    DOCKER --> BRIDGE
```

## 2. 请求与运行时主链路

```mermaid
sequenceDiagram
    participant U as 用户
    participant V as Vue Client
    participant F as FastAPI main.py
    participant S as PlatformStore
    participant E as platform_executor
    participant R as Agent Runtime Registry
    participant C as ClaudeCodeRuntime / SDK Bridge
    participant M as 外部模型

    U->>V: 创建组织 / Agent / Team / Workflow
    V->>F: POST /api/platform/*
    F->>S: 校验并写入领域对象
    S-->>F: JSON 领域结果
    F-->>V: JSON 响应

    U->>V: 启动 Run
    V->>F: POST /api/platform/runs/{id}/start
    F->>E: execute_platform_run(...)
    E->>S: 读取 workflow、Agent、知识、模型配置
    E->>R: 为 Run 选择固定 claude_code Adapter
    R->>C: 建立隔离状态、Agent workspace、身份、Memory 与 Skills
    C->>M: Claude Agent SDK Query（当前 Endpoint / gpt-5.6-sol）
    M-->>C: 模型输出、SDK 消息与 Tool Use/Result
    C-->>E: 规范化行动、消息、文件变化、候选产物与用量
    E->>S: 追加事件、更新任务、保存 Artifact
    V->>F: 轮询 Run 状态
    F->>S: 查询事件与产物
    S-->>F: 当前 Run 快照
    F-->>V: JSON 状态、事件、产物
```

## 3. 代码分层与职责

| 层 | 当前源码 | 责任 |
|---|---|---|
| 表现层 | `client/src/App.vue`、`client/src/api.ts`、`client/src/components/` | 江湖、组织、Agent、团队、Workflow、Run、知识和设置页面；通过 REST 调用后端 |
| API 层 | `server/app/main.py` | FastAPI 应用、Pydantic 请求模型、平台路由、静态前端托管、运行控制 |
| 领域/应用层 | `server/app/platform_store.py` | 组织、Agent、Team、Workflow、Knowledge Source、Run、Event、Artifact 等对象及事务操作 |
| 执行层 | `server/app/platform_executor.py` | Workflow 依赖解析、节点执行、模型/工具调用、重试、返工、测试命令、代码清单和产物验证 |
| 模型适配层 | `server/app/llm_client.py` | Anthropic Messages 与 OpenAI Responses 协议、JSON 输出解析、网络/HTTP 重试 |
| Agent Runtime Port | `server/app/agent_runtime.py`、`server/app/agent_runtime_registry.py` | 框架无关合同；产品 Registry 固定为 `claude_code`，误配其他 Runtime 明确失败 |
| Claude Agent 运行时 | `server/app/claude_code_runtime.py`、`server/claude_agent_runtime/` | Claude Agent SDK Bridge、运行隔离目录、Agent workspace、身份/规范/记忆/技能同步、工具策略与进程回收 |
| 知识层 | `server/app/knowledge_index.py` | 文本、PDF、DOCX、XLSX、PPTX 解析，分段及检索评分 |
| 安全与存储 | `server/app/secret_store.py`、`.data/` | 模型 Token 加密、本地密钥、SQLite/文件系统持久化 |
| 部署层 | `Dockerfile`、`compose.yaml`、`compose.postgres.yaml` | 单容器平台部署；可选 PostgreSQL；Compose 中附带 Synapse 协作平面 |

## 4. 已实现与规划边界

- **已实现主路径**：Vue → FastAPI → `PlatformStore` → `platform_executor` → Runtime Registry → `ClaudeCodeRuntime` / Claude Agent SDK Bridge → 事件和产物回写。
- **已实现持久化**：默认 SQLite；`PlatformStore` 提供 PostgreSQL 兼容适配，正式切换由 `JIANGHU_DATABASE_URL` 控制。
- **已实现知识处理**：文件上传、格式解析、chunk、简单相关度检索，知识元数据与内容落在 `.data`。
- **已实现 Agent 运行隔离**：每次 Run 有独立 Claude Runtime 状态；Agent 版本拥有独立 workspace，保存技能、身份、规范和记忆文件；平台证据包向获准人物提供安全事件投影、Artifact 原始字节和 Runtime Attestation。
- **OpenClaw 当前边界**：生产 Registry 不导入、不注册 OpenClaw，新 Run 无法选择旧底座；旧状态路由和旧事件名只用于历史读取兼容，基线脚本可直接构造旧 Adapter 做迁移对照。
- **已实现模型适配**：无 Mock/fallback；缺配置、网络异常、模型错误和非 JSON 输出会显式失败。
- **Compose 增强项**：当前 `compose.yaml` 定义了 Synapse 与其 PostgreSQL，但源码目录中未发现对应 `matrix_bridge.py` / `collaboration.py`，因此图中将 Synapse 标注为部署层协作平面，而非已确认的应用领域调用链。
- **设计文档中的未来组件**：Graph Compiler、Loop Engine、Harness Compiler、Evaluation Service、Queue、对象存储等在 `docs/04-design/system-architecture.md` 中有规划，但不应视为当前源码已独立实现的服务。

## 5. 关键技术栈

- 前端：Vue 3、TypeScript、Vite、Lucide Vue。
- 后端：Python 3.13、FastAPI、Pydantic、Uvicorn。
- 数据：SQLite 默认；PostgreSQL 可选；文件系统保存知识、workspace 和运行产物。
- AI：Claude Agent SDK / Claude Code Bridge 承载 Agent 回合；当前已验证用户的 Anthropic-compatible GPT Endpoint 与 `gpt-5.6-sol`。`llm_client.py` 继续服务平台级普通 LLM 生成，不作为 Agent Runtime fallback。
- 文档解析：pypdf、openpyxl、OpenXML 读取 DOCX/PPTX。
- 部署：Docker Compose；默认平台端口 8000，Synapse 默认端口 8008。
- 测试：Pytest Runtime/平台合同、Node Bridge tests、Vue TypeScript 检查与 Vite production build；真实浏览器 UI Run 作为最终 E2E 门禁，Fake 仅做回归辅助。
