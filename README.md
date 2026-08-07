# Agent Arena

**中文名：多智能体协演场（江湖 Online）**

Agent Arena 是一套面向组织场景的多 Agent 社会操作系统与工作流工厂。用户可以输入员工、研发、客户、运营等场景目标，连接自己的知识和工具，由平台构建可运行、可观察、可干预、可评估的多 Agent 协作与对抗工作流。

当前生产流为：

> 产品需求分析 → 方案设计 → 红队质疑 → 修订 → 裁判验收

项目的调研、需求、设计决策与过程记录见 [docs/README.md](docs/README.md)。

## Docker 部署

需要 Docker Engine 24+，并安装 Docker Compose v2。

在项目根目录运行：

```bash
docker compose up -d --build
```

启动后访问：

- Web：<http://localhost:8000>
- API 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/api/health>

查看状态与日志：

```bash
docker compose ps
docker compose logs -f agent-arena
```

停止服务：

```bash
docker compose down
```

数据库保存在 Docker 命名卷 `agent-arena-postgres` 中；知识库文件、运行工作区和加密密钥保存在 `agent-arena-data` 卷中。普通的 `docker compose down` 不会删除数据。只有确认不再需要数据库、知识库、运行产物及密钥后，才使用 `docker compose down -v` 删除这些卷。

### PostgreSQL database

The Docker Compose deployment runs PostgreSQL 16 as the application database. The database is persisted in the `agent-arena-postgres` volume; file-based knowledge, workspaces, and the encryption key remain in `agent-arena-data`. `agent-arena` waits for the database health check before starting.

Set `POSTGRES_DB`, `POSTGRES_USER`, and a strong `POSTGRES_PASSWORD` in `.env` before deploying. `JIANGHU_DATABASE_URL` is injected by Compose. SQLite remains available for local tests when `JIANGHU_DATABASE_URL` is unset.

Back up the database with `docker compose exec -T db pg_dump -U "${POSTGRES_USER:-agent_arena}" -d "${POSTGRES_DB:-agent_arena}" > agent-arena.sql`. Back up the file volume separately; do not copy only the database and omit the encryption key.

### 配置模型服务

可以在项目根目录创建不纳入 Git 的 `.env` 文件：

```dotenv
ANTHROPIC_BASE_URL=https://your-anthropic-compatible-endpoint.example.com
ANTHROPIC_AUTH_TOKEN=your-token
ANTHROPIC_DEFAULT_SONNET_MODEL=your-model-id
AGENT_ARENA_PORT=8000
POSTGRES_DB=agent_arena
POSTGRES_USER=agent_arena
POSTGRES_PASSWORD=replace-with-a-long-random-password
```

然后重新创建容器：

```bash
docker compose up -d --build
```

也可以启动后在 Web 界面的“模型与凭据”中配置。模型凭据使用 `/app/.data/.jianghu-secret.key` 加密，因此必须同时持久化整个 `agent-arena-data` 卷；不要只复制数据库卷做迁移或备份。

### 备份与恢复

备份 PostgreSQL 数据库：

```bash
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-agent_arena}" -d "${POSTGRES_DB:-agent_arena}" > agent-arena.sql
```

备份文件卷和知识库/运行产物：

```bash
docker run --rm -v agent-arena-data:/data -v "${PWD}:/backup" alpine \
  tar czf /backup/agent-arena-data.tar.gz -C /data .
```

恢复 PostgreSQL：

```bash
cat agent-arena.sql | docker compose exec -T db psql -U "${POSTGRES_USER:-agent_arena}" -d "${POSTGRES_DB:-agent_arena}"
```

恢复文件卷前先停止服务，再将备份解压回同一个数据卷。恢复操作会覆盖卷中的同名文件，执行前请确认目标环境。

### OpenClaw 说明

Web、API、数据管理、知识库与模型配置可以直接通过上述镜像运行。真正启动 Agent 工作流还依赖 OpenClaw CLI；当前镜像没有锁定并内置特定 OpenClaw 版本，因此容器内的 OpenClaw 状态检查会显示不可用。需要正式运行工作流时，请在派生镜像中安装与项目兼容的 OpenClaw，并设置：

```text
JIANGHU_OPENCLAW_NODE_PATH=/path/to/node
JIANGHU_OPENCLAW_ENTRY_PATH=/path/to/openclaw.mjs
```

## 本地开发

环境要求：

- Node.js 22+
- Python 3.13+

首次安装（PowerShell）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
npm install
npm --prefix client install
```

启动 API 和前端开发服务器：

```powershell
npm run dev
```

- Client：<http://127.0.0.1:5173>
- API：<http://127.0.0.1:8000>
- API 文档：<http://127.0.0.1:8000/docs>

验证：

```powershell
npm test
```

生产模式下，Vue 构建产物由 FastAPI 同源托管；Docker 镜像采用同样的运行方式。
