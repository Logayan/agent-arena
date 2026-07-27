# Agent Arena

**中文名：多智能体协演场**

Agent Arena 是一套面向组织场景的**多 Agent 社会操作系统与工作流工厂**。

用户可以输入员工、研发、客户、运营等场景目标，连接自己的知识和工具，由平台构建可运行、可观察、可干预、可评估的多 Agent 协作与对抗工作流。

平台长期能力包括：

- 多 Agent 运行与任务编排引擎
- 共享知识、记忆与证据追踪
- 协作、质疑、红队攻击、返工与裁决机制
- 报告、访谈和运行复盘能力
- 类 MiroFish 的可视化 Web Client
- Agent 蓝图、组织关系、权限制度和声誉体系
- 场景理解与工作流生成
- 可复现的示例生产流、基线对比及评估数据

## 文档入口

项目调研、需求、设计决策与过程记录统一维护在 [docs/README.md](docs/README.md)。

## 当前状态

项目已完成愿景与架构 0.1 设计，并实现第一版可运行纵向切片。当前生产流为：

> 产品需求分析 -> 方案设计 -> 红队质疑 -> 修订 -> 裁判验收

当前版本使用内置模拟运行器演示完整事件流。“智能需求评审”是首个课题场景模板，不代表平台的最终业务边界。

后续将逐步实现 Workspace、Knowledge Hub、Agent Library、Society Designer、Workflow Studio、真实 LLM Worker 和 Evaluation Lab。

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
