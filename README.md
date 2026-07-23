# Agent Arena

**中文名：多智能体协演场**

Agent Arena 是一套面向真实生产流的多 Agent 协作、攻防、裁决与复盘平台，包括：

- 多 Agent 运行与任务编排引擎
- 共享知识、记忆与证据追踪
- 协作、质疑、红队攻击、返工与裁决机制
- 报告、访谈和运行复盘能力
- 类 MiroFish 的可视化 Web Client
- 可复现的示例生产流及评估数据

## 文档入口

项目调研、需求、设计决策与过程记录统一维护在 [docs/README.md](docs/README.md)。

## 当前状态

项目已完成需求与架构 0.1 设计，并实现第一版可运行纵向切片。当前生产流为：

> 产品需求分析 -> 方案设计 -> 红队质疑 -> 修订 -> 裁判验收

当前版本使用内置模拟运行器演示完整事件流，后续将接入真实 LLM Worker、持久化存储和知识检索。

## 本地运行

环境要求：

- Node.js 22+
- Python 3.13

首次安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
npm install
npm --prefix client install
```

启动 API 和 Client：

```powershell
npm run dev
```

- Client：http://127.0.0.1:5173
- API：http://127.0.0.1:8000
- API 文档：http://127.0.0.1:8000/docs

验证：

```powershell
npm test
```
