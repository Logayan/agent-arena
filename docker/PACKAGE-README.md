# 江湖 Online Docker 交付包

这个交付包包含：

- `jianghu-online-image.tar`：前端、FastAPI 后端、Node.js、npm 和固定版本 OpenClaw；
- `jianghu-online-source.tar.gz`：可在另一台 Docker 主机直接重新构建的完整源码与部署文件；
- `compose.yaml`：使用独立持久化目录的默认启动方式；
- `compose.postgres.yaml`：新建 PostgreSQL 正式环境时使用的覆盖文件；
- `SHA256SUMS.txt`：交付文件校验值。

交付包不会包含 `.data`、SQLite 数据库、知识文件、运行产物、模型 Token、真实 `.env` 或本地加密密钥。

## 启动全新的江湖环境

1. 将交付包放入一个空目录。
2. 导入镜像：

   ```bash
   docker load -i jianghu-online-image.tar
   ```

   如果交付包中没有 `jianghu-online-image.tar`，先解压源码并构建：

   ```bash
   tar xzf jianghu-online-source.tar.gz
   docker compose --env-file .env.docker.example build
   ```

3. 复制并检查环境文件：

   ```bash
   cp .env.docker.example .env.docker
   ```

4. 启动：

   ```bash
   docker compose --env-file .env.docker up -d --no-build
   ```

5. 访问 `http://localhost:8000`，并检查：

   ```bash
   docker compose ps
   docker compose logs -f jianghu-online
   ```

## 敏感信息提示

交付包已排除平台数据和模型凭据。部署后请通过平台的“模型与凭据”页面配置 Token，或写入不会提交到 Git 的 `.env.docker`。禁止把真实 Token、`.data`、数据库文件或 `.jianghu-secret.key` 放入源码包、Git 提交或公共镜像层。

## PostgreSQL 模式

默认模式会在部署机器的 `.data` 中创建新的 SQLite 环境。若要使用 PostgreSQL，先修改 `.env.docker` 中的强密码，再运行：

```bash
docker compose --env-file .env.docker -f compose.yaml -f compose.postgres.yaml up -d --no-build
```

PostgreSQL 模式会建立新的正式数据库；知识文件、人物工作区和加密密钥仍使用部署机器自己的 `.data`，不会从交付包导入任何个人数据。
