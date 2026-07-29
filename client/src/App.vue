<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Boxes,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  Copy,
  Database,
  Download,
  FileStack,
  GitBranch,
  Globe2,
  LayoutGrid,
  Library,
  Link2,
  LockKeyhole,
  MoreHorizontal,
  Network,
  Play,
  Plus,
  Search,
  Star,
  Store,
  Settings2,
  ShieldCheck,
  Sparkles,
  Users,
  Upload,
  WalletCards,
  Workflow,
  X,
  Zap,
} from '@lucide/vue'

type Screen = 'home' | 'builder' | 'library' | 'task' | 'agents' | 'knowledge' | 'market'
type BuilderTab = 'workflow' | 'agents' | 'coverage'

const screen = ref<Screen>('home')
const builderTab = ref<BuilderTab>('workflow')
const buildPrompt = ref('我需要一套从产品需求澄清到可运行 Demo 交付的需求开发流程')
const taskPrompt = ref('开发一个社区物业报修系统，包含居民端和物业管理端，并交付可运行 Demo。')
const selectedWorkflow = ref('需求到可运行 Demo · 标准流程')
const showSaved = ref(false)
const selectedNode = ref('需求澄清')
const taskStarted = ref(false)
const marketTab = ref<'agents' | 'workflows'>('agents')
const knowledgeView = ref<'sources' | 'graph'>('sources')
const selectedAgentProfile = ref('系统架构师')

const workflows = [
  {
    name: '需求到可运行 Demo · 标准流程',
    version: 'v3.2',
    desc: '覆盖需求澄清、方案攻防、开发、真实测试与独立验收。',
    agents: 7,
    nodes: 9,
    quality: 92,
    time: '35–60 分钟',
    tone: 'emerald',
  },
  {
    name: '产品需求评审与方案攻防',
    version: 'v2.7',
    desc: '适合复杂需求评审，强调利益相关方讨论、红队挑战与裁判。',
    agents: 6,
    nodes: 7,
    quality: 89,
    time: '20–35 分钟',
    tone: 'violet',
  },
  {
    name: '轻量功能开发',
    version: 'v1.8',
    desc: '面向边界清晰的小功能，使用最小 Agent 团队快速交付。',
    agents: 4,
    nodes: 6,
    quality: 84,
    time: '15–25 分钟',
    tone: 'amber',
  },
]

const agents = [
  { initials: 'PO', name: '产品负责人', role: '需求主理人', desc: '澄清目标、范围和验收口径', color: '#166a58' },
  { initials: 'UX', name: '体验设计师', role: '用户视角', desc: '质疑流程摩擦和交互可用性', color: '#91611d' },
  { initials: 'AR', name: '系统架构师', role: '技术主张者', desc: '设计系统边界、模块和接口', color: '#345f91' },
  { initials: 'FE', name: '前端工程师', role: '交付成员', desc: '实现客户端与交互并完成自测', color: '#6f54a8' },
  { initials: 'BE', name: '后端工程师', role: '交付成员', desc: '实现领域、数据与服务接口', color: '#336c78' },
  { initials: 'RT', name: '红队审查员', role: '对抗角色', desc: '发现权限、逻辑和验收缺陷', color: '#a34b43' },
  { initials: 'J', name: '独立裁判', role: '终审角色', desc: '独立身份、上下文与 Prompt', color: '#303b45' },
]

const nodes = [
  { name: '需求澄清', agents: ['PO', 'UX'], status: 'ready', x: 8, y: 38 },
  { name: '验收契约', agents: ['PO'], status: 'ready', x: 25, y: 38 },
  { name: '架构方案', agents: ['AR'], status: 'ready', x: 42, y: 20 },
  { name: '开发实现', agents: ['FE', 'BE'], status: 'ready', x: 59, y: 20 },
  { name: '方案攻防', agents: ['AR', 'RT'], status: 'challenge', x: 42, y: 58 },
  { name: '红队测试', agents: ['RT'], status: 'challenge', x: 76, y: 38 },
  { name: '独立验收', agents: ['J'], status: 'judge', x: 91, y: 38 },
]

const currentWorkflow = computed(() => workflows.find((item) => item.name === selectedWorkflow.value) ?? workflows[0])

function go(next: Screen): void {
  screen.value = next
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function openBuilder(): void {
  screen.value = 'builder'
  builderTab.value = 'workflow'
}

function saveWorkflow(): void {
  showSaved.value = true
  window.setTimeout(() => (showSaved.value = false), 2600)
}

function chooseWorkflow(name: string): void {
  selectedWorkflow.value = name
  screen.value = 'task'
}
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <button class="brand" type="button" @click="go('home')">
        <span class="brand-seal">江</span>
        <span><strong>江湖 Online</strong><small>多 Agent 生产流程平台</small></span>
      </button>

      <nav class="main-nav">
        <button :class="{ active: screen === 'home' }" @click="go('home')">工作台</button>
        <button :class="{ active: screen === 'library' }" @click="go('library')">流程资产</button>
        <button :class="{ active: screen === 'agents' }" @click="go('agents')">Agent 江湖</button>
        <button :class="{ active: screen === 'knowledge' }" @click="go('knowledge')">知识空间</button>
        <button :class="{ active: screen === 'market' }" @click="go('market')">公共市场</button>
      </nav>

      <div class="top-actions">
        <button class="icon-button"><Search :size="18" /></button>
        <button class="icon-button"><CircleHelp :size="18" /></button>
        <div class="avatar">林</div>
      </div>
    </header>

    <main v-if="screen === 'home'" class="home-page">
      <section class="hero">
        <div class="hero-copy">
          <span class="eyebrow"><Sparkles :size="14" /> 知识驱动的拟人化 Agent 生产网络</span>
          <h1>先构建你的江湖，<br /><em>再让江湖完成事情。</em></h1>
          <p>把经验沉淀为可复用的 Workflow 与 Agent 团队；需要时选择一套成熟流程，交给真实 Agent 协作、争辩、攻防并完成交付。</p>
        </div>
        <div class="hero-orbit" aria-hidden="true">
          <div class="orbit orbit-one"></div><div class="orbit orbit-two"></div>
          <span class="orbit-center">江湖</span>
          <span class="orbit-agent a1">产品</span><span class="orbit-agent a2">架构</span>
          <span class="orbit-agent a3">红队</span><span class="orbit-agent a4">裁判</span>
        </div>
      </section>

      <section class="primary-paths">
        <article class="path-card build-card">
          <div class="path-index">01</div>
          <div class="path-icon"><Workflow :size="25" /></div>
          <span class="card-kicker">建设生产能力</span>
          <h2>构建或优化一套 Workflow</h2>
          <p>告诉 AI 你需要哪一类生产流程。系统会检索已有资产、生成或派生 Workflow，并把 Agent、关系和规则一起绑定保存。</p>
          <div class="prompt-box">
            <textarea v-model="buildPrompt" rows="3" aria-label="描述流程需求"></textarea>
            <div class="prompt-actions">
              <button class="text-button"><Database :size="15" /> 引用知识</button>
              <button class="text-button"><Copy :size="15" /> 从已有流程优化</button>
              <button class="primary-button dark" @click="openBuilder">开始构建 <ArrowRight :size="16" /></button>
            </div>
          </div>
        </article>

        <article class="path-card use-card">
          <div class="path-index">02</div>
          <div class="path-icon"><Play :size="25" /></div>
          <span class="card-kicker">使用生产能力</span>
          <h2>选择 Workflow 完成具体任务</h2>
          <p>从你的资产库或公共市场选择一套成熟流程，再输入这一次的真实任务。绑定好的 Agent 团队会被实例化并开始工作。</p>
          <div class="selected-flow-mini">
            <span class="mini-flow-icon"><GitBranch :size="18" /></span>
            <span><small>最近使用</small><strong>{{ selectedWorkflow }}</strong></span>
            <ChevronRight :size="18" />
          </div>
          <div class="path-buttons">
            <button class="secondary-button" @click="go('library')"><Library :size="16" /> 选择其他流程</button>
            <button class="primary-button emerald" @click="go('task')">输入具体任务 <ArrowRight :size="16" /></button>
          </div>
        </article>
      </section>

      <section class="recent-section">
        <div class="section-heading"><div><span class="eyebrow">MY ASSETS</span><h2>最近的江湖资产</h2></div><button class="text-link" @click="go('library')">查看全部 <ArrowRight :size="15" /></button></div>
        <div class="asset-row">
          <button v-for="item in workflows" :key="item.name" class="asset-tile" @click="chooseWorkflow(item.name)">
            <span class="asset-mark" :class="item.tone"><Workflow :size="20" /></span>
            <span class="asset-main"><strong>{{ item.name }}</strong><small>{{ item.version }} · {{ item.nodes }} 节点 · {{ item.agents }} Agent</small></span>
            <span class="asset-score">{{ item.quality }}<small>质量分</small></span>
            <ChevronRight :size="18" />
          </button>
        </div>
      </section>
    </main>

    <main v-else-if="screen === 'builder'" class="workspace-page">
      <div class="workspace-header">
        <button class="back-button" @click="go('home')"><ArrowLeft :size="17" /> 返回工作台</button>
        <div class="workspace-title"><span class="draft-badge">草案 v1</span><h1>需求到可运行 Demo · 标准流程</h1><p>由 AI 根据流程需求、知识空间和已有资产生成</p></div>
        <div class="workspace-actions"><button class="secondary-button"><MoreHorizontal :size="17" /></button><button class="primary-button dark" @click="saveWorkflow"><Check :size="16" /> 确认并保存</button></div>
      </div>

      <div class="builder-status">
        <span><CheckCircle2 :size="16" /> 已完成资产检索</span><i></i><span><CheckCircle2 :size="16" /> 7 个 Agent 已绑定</span><i></i><span><ShieldCheck :size="16" /> 编译校验通过</span>
        <div class="estimate"><Clock3 :size="15" /> 预计运行 35–60 分钟 <WalletCards :size="15" /> ¥18–32 / 次</div>
      </div>

      <div class="builder-layout">
        <aside class="builder-sidebar">
          <span class="side-label">构建依据</span>
          <div class="basis-card"><strong>流程需求</strong><p>{{ buildPrompt }}</p><button>查看构建契约</button></div>
          <div class="source-list">
            <span><Check :size="14" /> 软件交付知识空间 <small>12 个来源</small></span>
            <span><Check :size="14" /> 已有 Workflow Registry <small>检索 8 个</small></span>
            <span><Check :size="14" /> 工程质量 Policy <small>v2.4</small></span>
          </div>
          <span class="side-label gap-top">生成摘要</span>
          <div class="summary-grid"><span><b>9</b>节点</span><span><b>7</b>Agent</span><span><b>3</b>并行峰值</span><span><b>2</b>质量门禁</span></div>
          <div class="reuse-note"><GitBranch :size="16" /><span><strong>基于 2 个流程组合优化</strong><small>保留 5 个节点，新建 4 个节点</small></span></div>
        </aside>

        <section class="builder-canvas">
          <div class="canvas-tabs">
            <button :class="{ active: builderTab === 'workflow' }" @click="builderTab = 'workflow'"><Network :size="16" /> Workflow 图</button>
            <button :class="{ active: builderTab === 'agents' }" @click="builderTab = 'agents'"><Users :size="16" /> Agent 团队</button>
            <button :class="{ active: builderTab === 'coverage' }" @click="builderTab = 'coverage'"><LayoutGrid :size="16" /> 能力覆盖</button>
          </div>

          <div v-if="builderTab === 'workflow'" class="flow-canvas">
            <svg class="connections" viewBox="0 0 1000 500" preserveAspectRatio="none">
              <path d="M120 250 L260 250"/><path d="M350 250 L440 150"/><path d="M350 250 L440 350"/><path d="M540 150 L610 150"/><path d="M540 350 L720 250"/><path d="M710 150 L720 250"/><path d="M820 250 L900 250"/>
            </svg>
            <button v-for="node in nodes" :key="node.name" class="flow-node" :class="[node.status, { selected: selectedNode === node.name }]" :style="{ left: node.x + '%', top: node.y + '%' }" @click="selectedNode = node.name">
              <span class="node-type">{{ node.status === 'challenge' ? '对抗节点' : node.status === 'judge' ? '独立裁判' : '生产节点' }}</span>
              <strong>{{ node.name }}</strong>
              <span class="node-agents"><i v-for="agent in node.agents" :key="agent">{{ agent }}</i></span>
            </button>
            <div class="canvas-legend"><span><i class="dot normal"></i>生产</span><span><i class="dot red"></i>对抗</span><span><i class="dot judge"></i>裁判</span></div>
          </div>

          <div v-else-if="builderTab === 'agents'" class="agent-grid">
            <article v-for="agent in agents" :key="agent.name" class="agent-card">
              <span class="agent-avatar" :style="{ background: agent.color }">{{ agent.initials }}</span>
              <div><span class="agent-role">{{ agent.role }}</span><h3>{{ agent.name }}</h3><p>{{ agent.desc }}</p></div>
              <span class="bound-chip"><Check :size="12" /> 已绑定</span>
            </article>
          </div>

          <div v-else class="coverage-panel">
            <div class="coverage-head"><div><span class="eyebrow">CAPABILITY MATRIX</span><h2>流程能力覆盖</h2></div><span class="coverage-total">100% <small>强制能力已覆盖</small></span></div>
            <div class="coverage-row" v-for="(name, index) in ['需求澄清与契约化','架构与接口设计','前后端开发能力','真实构建与 E2E','红队缺陷发现','独立验收裁决']" :key="name">
              <span>{{ name }}</span><div><i :style="{ width: [100,96,100,92,100,100][index] + '%' }"></i></div><strong>{{ ['PO + UX','AR','FE + BE','FE + BE + RT','RT','J'][index] }}</strong><CheckCircle2 :size="16" />
            </div>
          </div>
        </section>

        <aside class="inspector">
          <span class="side-label">当前选中节点</span>
          <h2>{{ selectedNode }}</h2>
          <p class="inspector-desc">把模糊的业务目标转化为可执行、可验证的输入，并标记事实、假设和开放问题。</p>
          <div class="field"><label>绑定 Agent</label><div class="binding"><span class="agent-avatar small">PO</span><span><strong>产品负责人 · v3.4</strong><small>固定 Blueprint 绑定</small></span><ShieldCheck :size="16" /></div><div class="binding"><span class="agent-avatar small gold">UX</span><span><strong>体验设计师 · v2.1</strong><small>固定 Blueprint 绑定</small></span><ShieldCheck :size="16" /></div></div>
          <div class="field"><label>输入</label><span class="contract-chip">用户原始流程需求</span><span class="contract-chip">知识来源</span></div>
          <div class="field"><label>输出 Artifact</label><span class="contract-chip green">WorkflowConstructionContract</span></div>
          <div class="field two"><span><label>执行方式</label><b>双 Agent 协作</b></span><span><label>最大轮次</label><b>2 轮</b></span></div>
          <button class="inspector-edit"><Settings2 :size="15" /> 创建副本后调整配置</button>
        </aside>
      </div>
    </main>

    <main v-else-if="screen === 'library'" class="library-page">
      <div class="page-heading"><div><span class="eyebrow">WORKFLOW REGISTRY</span><h1>流程资产</h1><p>这里保存已经绑定 Agent、关系、产物契约和执行规则的生产流程。</p></div><button class="primary-button dark" @click="openBuilder"><Plus :size="16" /> 构建新 Workflow</button></div>
      <div class="library-toolbar"><div class="search-field"><Search :size="17" /><input placeholder="搜索流程名称、能力或产物…" /></div><button class="filter-button">全部范围</button><button class="filter-button">最近更新</button></div>
      <div class="workflow-grid">
        <article v-for="item in workflows" :key="item.name" class="workflow-card">
          <div class="workflow-card-top"><span class="asset-mark large" :class="item.tone"><Workflow :size="24" /></span><span class="version-chip">{{ item.version }}</span><button class="more-button"><MoreHorizontal :size="18" /></button></div>
          <h2>{{ item.name }}</h2><p>{{ item.desc }}</p>
          <div class="workflow-stats"><span><Boxes :size="15" /> {{ item.nodes }} 节点</span><span><Users :size="15" /> {{ item.agents }} Agent</span><span><Clock3 :size="15" /> {{ item.time }}</span></div>
          <div class="agent-stack"><span v-for="agent in agents.slice(0, Math.min(item.agents, 5))" :key="agent.initials" :style="{ background: agent.color }">{{ agent.initials }}</span><i v-if="item.agents > 5">+{{ item.agents - 5 }}</i><small>Agent 已固定绑定</small></div>
          <div class="workflow-card-actions"><button class="secondary-button"><Copy :size="15" /> 创建副本优化</button><button class="primary-button emerald" @click="chooseWorkflow(item.name)"><Play :size="15" /> 使用此流程</button></div>
        </article>
      </div>
    </main>

    <main v-else-if="screen === 'agents'" class="agents-page">
      <div class="page-heading"><div><span class="eyebrow">AGENT SOCIETY</span><h1>Agent 江湖</h1><p>管理可复用的拟人化 AgentBlueprint，查看他们的能力、立场、关系和参与过的 Workflow。</p></div><button class="primary-button dark"><Plus :size="16" /> 创建 Agent</button></div>
      <div class="agents-dashboard">
        <aside class="agent-directory">
          <div class="search-field agent-search"><Search :size="16" /><input placeholder="搜索身份、能力或知识…" /></div>
          <div class="directory-filter"><button class="active">全部 24</button><button>我的 11</button><button>市场安装 8</button></div>
          <button v-for="agent in agents" :key="agent.name" class="directory-agent" :class="{ active: selectedAgentProfile === agent.name }" @click="selectedAgentProfile = agent.name">
            <span class="agent-avatar" :style="{ background: agent.color }">{{ agent.initials }}</span><span><strong>{{ agent.name }}</strong><small>{{ agent.role }} · {{ agent.initials === 'J' ? '独立身份' : '可复用' }}</small></span><ChevronRight :size="15" />
          </button>
        </aside>
        <section class="society-map">
          <div class="map-heading"><div><span class="side-label">关系视图</span><h2>软件交付江湖</h2></div><div class="map-legend"><span><i class="rel cooperate"></i>协作</span><span><i class="rel challenge"></i>挑战</span><span><i class="rel judge"></i>裁判</span></div></div>
          <div class="relationship-canvas">
            <svg viewBox="0 0 800 510" preserveAspectRatio="none"><path class="cooperate" d="M140 250 C230 100 310 110 400 185"/><path class="cooperate" d="M400 185 C500 90 615 130 665 240"/><path class="cooperate" d="M400 185 C390 285 300 340 230 400"/><path class="challenge" d="M230 400 C360 460 520 430 585 350"/><path class="challenge" d="M665 240 C630 300 620 315 585 350"/><path class="judge" d="M585 350 C670 390 700 420 720 455"/></svg>
            <button class="society-agent sa-po"><span style="background:#166a58">PO</span><strong>产品负责人</strong><small>目标与验收</small></button>
            <button class="society-agent sa-ar active"><span style="background:#345f91">AR</span><strong>系统架构师</strong><small>方案主张者</small></button>
            <button class="society-agent sa-fe"><span style="background:#6f54a8">FE</span><strong>前端工程师</strong><small>交付成员</small></button>
            <button class="society-agent sa-be"><span style="background:#336c78">BE</span><strong>后端工程师</strong><small>交付成员</small></button>
            <button class="society-agent sa-rt"><span style="background:#a34b43">RT</span><strong>红队审查员</strong><small>对抗角色</small></button>
            <button class="society-agent sa-j"><span style="background:#303b45">J</span><strong>独立裁判</strong><small>终审角色</small></button>
            <div class="relation-note">架构师必须回应红队挑战，但红队不能修改主方案；最终裁判拥有独立上下文。</div>
          </div>
        </section>
        <aside class="agent-profile">
          <span class="side-label">AGENT BLUEPRINT</span><div class="profile-hero"><span class="agent-avatar profile-avatar" style="background:#345f91">AR</span><div><h2>{{ selectedAgentProfile }}</h2><span>系统设计与技术决策 · v4.2</span></div></div>
          <div class="profile-badges"><span>私有资产</span><span>已验证</span><span>7 次运行</span></div>
          <section><label>身份与立场</label><p>以系统可演进性、边界清晰和真实可运行为主要利益，对没有证据的技术乐观保持质疑。</p></section>
          <section><label>核心能力</label><div class="skill-tags"><span>领域建模</span><span>系统架构</span><span>接口设计</span><span>技术选型</span></div></section>
          <section><label>知识绑定</label><div class="profile-link"><BookOpen :size="15" /> 软件工程知识空间 <ChevronRight :size="14" /></div></section>
          <section><label>工具与权限</label><p>代码读取、文档编辑、架构图生成；无生产写入权限。</p></section>
          <section><label>参与 Workflow</label><div class="profile-link"><Workflow :size="15" /> 需求到可运行 Demo · 3 个版本</div></section>
          <button class="secondary-button profile-action"><Copy :size="15" /> 创建副本并优化</button>
        </aside>
      </div>
    </main>

    <main v-else-if="screen === 'knowledge'" class="knowledge-page">
      <div class="page-heading"><div><span class="eyebrow">KNOWLEDGE SPACE</span><h1>知识空间</h1><p>组织 Workflow 构建和 Agent 执行所需的文档、网页、证据与知识图谱。</p></div><div class="workspace-actions"><button class="secondary-button"><Link2 :size="16" /> 添加网页</button><button class="primary-button dark"><Upload :size="16" /> 上传知识</button></div></div>
      <div class="knowledge-summary"><article><Database :size="19" /><span><b>4</b><small>知识库</small></span></article><article><FileStack :size="19" /><span><b>186</b><small>来源版本</small></span></article><article><Network :size="19" /><span><b>1,284</b><small>图谱实体</small></span></article><article><ShieldCheck :size="19" /><span><b>91%</b><small>证据绑定率</small></span></article><div class="index-health"><span><i></i>索引健康</span><small>最后更新 6 分钟前</small></div></div>
      <div class="knowledge-layout">
        <aside class="knowledge-tree"><span class="side-label">知识空间</span><button class="tree-root active"><BookOpen :size="16" /><span><strong>软件交付知识</strong><small>82 个来源</small></span></button><button class="tree-child">产品与需求 <small>24</small></button><button class="tree-child">架构与技术 <small>31</small></button><button class="tree-child">测试与安全 <small>27</small></button><button class="tree-root"><LockKeyhole :size="16" /><span><strong>项目私有知识</strong><small>38 个来源</small></span></button><button class="tree-root"><Store :size="16" /><span><strong>场景包知识</strong><small>66 个来源</small></span></button><button class="new-space"><Plus :size="14" /> 新建知识空间</button></aside>
        <section class="knowledge-content">
          <div class="knowledge-tabs"><button :class="{ active: knowledgeView === 'sources' }" @click="knowledgeView = 'sources'"><FileStack :size="15" /> 知识来源</button><button :class="{ active: knowledgeView === 'graph' }" @click="knowledgeView = 'graph'"><Network :size="15" /> 知识图谱</button></div>
          <template v-if="knowledgeView === 'sources'">
            <div class="content-toolbar"><div><h2>软件交付知识</h2><span>用于 Workflow 构建、Agent 生成和运行检索</span></div><div class="search-field compact"><Search :size="15" /><input placeholder="搜索来源…" /></div></div>
            <div class="source-table"><div class="source-head"><span>来源</span><span>类型</span><span>版本</span><span>可信等级</span><span>索引状态</span><span></span></div><div v-for="(source,index) in ['产品需求分析方法.md','系统架构评审规范.pdf','OWASP Web 安全测试指南','端到端测试实践','接口设计规范 v3']" :key="source" class="source-row"><span><i class="file-icon"><BookOpen :size="14" /></i><b>{{ source }}</b></span><span>{{ index === 2 ? '网页' : '文档' }}</span><span>v{{ [4,2,7,3,3][index] }}.0</span><span><i class="trust-dot"></i>{{ index === 2 ? '外部可信' : '已确认' }}</span><span class="indexed"><CheckCircle2 :size="14" /> 已索引</span><button><MoreHorizontal :size="16" /></button></div></div>
            <div class="feedback-card"><Sparkles :size="19" /><div><strong>7 条运行反馈等待审核</strong><span>Agent 在最近运行中发现了可沉淀的新知识和冲突关系。</span></div><button>进入反馈审核</button></div>
          </template>
          <div v-else class="graph-view"><div class="graph-toolbar"><span>实体关系视图 · 1,284 实体 / 3,907 关系</span><button>按证据强度</button></div><div class="knowledge-graph"><svg viewBox="0 0 900 470"><g class="kg-lines"><line x1="450" y1="235" x2="220" y2="120"/><line x1="450" y1="235" x2="675" y2="110"/><line x1="450" y1="235" x2="220" y2="360"/><line x1="450" y1="235" x2="680" y2="350"/><line x1="220" y1="120" x2="675" y2="110"/><line x1="220" y1="360" x2="680" y2="350"/></g></svg><span class="kg-node center">软件交付</span><span class="kg-node n1">需求契约</span><span class="kg-node n2">架构方案</span><span class="kg-node n3">测试证据</span><span class="kg-node n4">安全缺陷</span><span class="kg-node n5">Artifact Contract</span><div class="graph-tip"><strong>每条关系都绑定 Evidence</strong><span>知识图谱是 PostgreSQL 正式知识对象的关系投影。</span></div></div></div>
        </section>
      </div>
    </main>

    <main v-else-if="screen === 'market'" class="market-page">
      <section class="market-hero"><span class="eyebrow">JIANGHU MARKETPLACE</span><h1>把他人的江湖，<br />变成你的生产能力。</h1><p>发现经过验证的 Agent 和 Workflow 场景包。安装后固定版本到本地 Registry，再安全地创建副本、组合或使用。</p><div class="market-search"><Search :size="19" /><input placeholder="搜索 Agent、Workflow、能力或行业…" /><button>搜索市场</button></div></section>
      <div class="market-tabs"><button :class="{ active: marketTab === 'agents' }" @click="marketTab = 'agents'"><Users :size="16" /> Agent 市场</button><button :class="{ active: marketTab === 'workflows' }" @click="marketTab = 'workflows'"><Workflow :size="16" /> Workflow 与场景包</button><span></span><button>全部分类</button><button>最高评分</button></div>
      <section v-if="marketTab === 'agents'" class="market-grid"><article v-for="(item,index) in [{n:'金融风控挑战者',r:'风险审查 / 红队',d:'专注识别信贷、支付和交易流程中的规则漏洞与证据缺口。',p:'观海智能',s:'4.9',u:'2.4k',c:'#765b9e'},{n:'资深用户研究员',r:'用户洞察 / 需求',d:'将访谈、反馈和行为证据转化为结构化需求与机会判断。',p:'灯塔实验室',s:'4.8',u:'1.8k',c:'#a36a2d'},{n:'云原生系统架构师',r:'架构设计 / 技术',d:'面向高可用服务完成边界划分、部署设计和技术风险评审。',p:'StackFoundry',s:'4.9',u:'3.1k',c:'#356a82'},{n:'合规独立裁判',r:'审计 / 终审',d:'以独立身份、上下文和 Prompt 对方案证据与验收条款作出裁决。',p:'清衡科技',s:'4.7',u:'986',c:'#3e4b48'},{n:'增长策略辩手',r:'增长 / 对抗',d:'从商业增长立场挑战保守方案，并要求用数据验证关键假设。',p:'北斗增长',s:'4.6',u:'726',c:'#a44f48'},{n:'高级测试工程师',r:'测试 / 交付',d:'设计可执行测试计划，运行真实 E2E 并输出可追溯测试证据。',p:'质量公社',s:'4.8',u:'1.5k',c:'#40795f'}]" :key="item.n" class="market-card"><div class="publisher"><span class="market-avatar" :style="{background:item.c}">{{ ['FR','UR','CA','CJ','GS','QA'][index] }}</span><span><small>{{ item.p }}</small><strong>{{ item.n }}</strong></span><span class="verified"><ShieldCheck :size="14" /></span></div><span class="market-role">{{ item.r }}</span><p>{{ item.d }}</p><div class="market-metrics"><span><Star :size="14" fill="currentColor" /> {{ item.s }}</span><span><Download :size="14" /> {{ item.u }} 安装</span><span>v{{ index+2 }}.{{ index }}</span></div><div class="permission-note"><LockKeyhole :size="13" /> 安装前展示知识、工具与权限声明</div><button class="install-button"><Download :size="15" /> 安装到我的 Agent 江湖</button></article></section>
      <section v-else class="market-grid workflow-market"><article v-for="(item,index) in [{n:'企业级需求到交付',d:'从业务需求到架构、开发、测试和独立验收的完整生产江湖。',a:9,node:12,p:'千流实验室'},{n:'品牌危机应对演练',d:'多利益相关方模拟、舆情研判、策略争辩和红蓝对抗流程。',a:11,node:8,p:'明镜研究院'},{n:'智能合同审查',d:'法律、业务和风险角色协作，输出条款缺陷、修订建议与裁决。',a:6,node:7,p:'法智工场'},{n:'产品战略攻防会',d:'市场、用户、技术和财务角色围绕产品战略进行结构化攻防。',a:8,node:9,p:'远见工作室'}]" :key="item.n" class="market-card scenario"><div class="scenario-cover" :class="'cover-'+index"><Workflow :size="28" /><span>SCENARIO</span></div><div class="scenario-body"><small>{{ item.p }} <ShieldCheck :size="12" /></small><h2>{{ item.n }}</h2><p>{{ item.d }}</p><div class="workflow-stats"><span><Boxes :size="14" /> {{ item.node }} 节点</span><span><Users :size="14" /> {{ item.a }} Agent</span><span><Star :size="14" /> 4.{{ 9-index }}</span></div><button class="install-button"><Download :size="15" /> 安装场景包</button></div></article></section>
    </main>

    <main v-else class="task-page">
      <button class="back-button task-back" @click="go('library')"><ArrowLeft :size="17" /> 返回流程资产</button>
      <div class="task-layout">
        <section class="task-main">
          <span class="eyebrow">START A NEW RUN</span><h1>使用 Workflow 完成具体任务</h1><p class="lead">流程和 Agent 团队已经确定。现在只需要说明这一次要完成的真实任务。</p>
          <div class="chosen-workflow"><span class="asset-mark emerald large"><Workflow :size="23" /></span><div><small>已选择 Workflow</small><strong>{{ currentWorkflow.name }}</strong><span>{{ currentWorkflow.version }} · {{ currentWorkflow.nodes }} 节点 · {{ currentWorkflow.agents }} Agent 已绑定</span></div><button @click="go('library')">更换</button></div>
          <label class="task-label">这一次具体要完成什么？</label>
          <div class="task-prompt"><textarea v-model="taskPrompt" rows="5"></textarea><div><button class="text-button"><Database :size="15" /> 添加项目知识</button><button class="text-button"><Globe2 :size="15" /> 添加网页</button></div></div>
          <div class="understanding-card">
            <div class="understanding-title"><Sparkles :size="18" /><span><strong>系统理解预览</strong><small>提交后将通过 Grill Me 进一步确认</small></span></div>
            <div class="understanding-grid"><span><label>目标</label>交付社区物业报修系统</span><span><label>交付</label>源代码、可运行 Demo、测试结果</span><span><label>用户</label>居民、物业工作人员</span><span class="missing"><label>尚需确认</label>部署方式、消息渠道、权限范围</span></div>
          </div>
          <button class="primary-button emerald large-action" @click="taskStarted = true"><Zap :size="18" /> 开始需求澄清</button>
        </section>
        <aside class="task-aside">
          <span class="side-label">本次将实例化的江湖</span><div class="mini-agent-list"><div v-for="agent in agents" :key="agent.name"><span class="agent-avatar small" :style="{ background: agent.color }">{{ agent.initials }}</span><span><strong>{{ agent.name }}</strong><small>{{ agent.role }}</small></span><Check :size="15" /></div></div>
          <div class="run-estimate"><h3>运行预估</h3><span><Clock3 :size="15" /> {{ currentWorkflow.time }}</span><span><WalletCards :size="15" /> 预计 ¥18–32</span><span><Users :size="15" /> 最大 5 个并发 Agent</span><span><ShieldCheck :size="15" /> 高风险操作需审批</span></div>
        </aside>
      </div>
    </main>

    <transition name="toast"><div v-if="showSaved" class="toast"><CheckCircle2 :size="19" /><span><strong>Workflow 已保存</strong><small>已进入你的流程资产库，可用于创建具体任务。</small></span><button @click="go('library')">查看资产</button></div></transition>
    <div v-if="taskStarted" class="modal-backdrop" @click.self="taskStarted = false"><div class="clarify-modal"><button class="modal-close" @click="taskStarted = false"><X :size="18" /></button><span class="modal-icon"><Sparkles :size="23" /></span><span class="eyebrow">GRILL ME · 1/4</span><h2>居民提交报修后，需要支持哪些处理状态？</h2><p>这个答案会影响状态机、物业端工作台和最终验收用例。</p><div class="choice-list"><button>待受理 → 处理中 → 待评价 → 已完成</button><button>需要更完整的派单、转派和退回流程</button><button>我不确定，使用系统推荐方案</button></div><div class="modal-foot"><span>答案将创建 RequirementContract 新版本</span><button class="primary-button emerald">继续 <ArrowRight :size="15" /></button></div></div></div>
  </div>
</template>
