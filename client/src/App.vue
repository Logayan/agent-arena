<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  Bot,
  ChartNetwork,
  Check,
  CheckCircle2,
  ChevronDown,
  Columns2,
  FileText,
  Filter,
  MessageSquare,
  PanelTop,
  Play,
  RefreshCw,
  Search,
  Send,
  ShieldAlert,
  Square,
  Users,
} from '@lucide/vue'
import { api } from './api'
import type { Agent, RunEvent, RunSnapshot } from './types'

type ViewMode = 'graph' | 'split' | 'workbench'
type EventFilter = 'all' | 'collaboration' | 'attack' | 'revision' | 'gate'

const snapshot = ref<RunSnapshot | null>(null)
const loading = ref(true)
const actionPending = ref(false)
const error = ref('')
const viewMode = ref<ViewMode>('split')
const eventFilter = ref<EventFilter>('all')
const selectedAgents = ref<string[]>([])
const question = ref('')
const submittedQuestion = ref('')
let eventSource: EventSource | null = null

const run = computed(() => snapshot.value?.run ?? null)
const events = computed(() => snapshot.value?.events ?? [])
const filteredEvents = computed(() =>
  eventFilter.value === 'all'
    ? events.value
    : events.value.filter((event) => event.category === eventFilter.value),
)
const activeAgent = computed(() => run.value?.agents.find((agent) => agent.status === 'working'))
const canStart = computed(() =>
  run.value ? ['draft', 'cancelled', 'failed'].includes(run.value.status) : false,
)
const isRunning = computed(() =>
  run.value
    ? ['preparing', 'analyzing', 'designing', 'attacking', 'revising', 'verifying', 'judging'].includes(
        run.value.status,
      )
    : false,
)

const stages = ['资料与目标', '知识与角色', '协作与对抗', '结果与终审', '深度交互']
const filters: Array<{ id: EventFilter; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'collaboration', label: '协作' },
  { id: 'attack', label: '红队' },
  { id: 'revision', label: '修订' },
  { id: 'gate', label: '门禁' },
]

const statusLabels: Record<string, string> = {
  draft: '待启动',
  preparing: '准备中',
  analyzing: '需求分析',
  designing: '方案协作',
  attacking: '红队攻击',
  revising: '修订中',
  verifying: '复测中',
  judging: '终审中',
  completed: '已通过',
  blocked: '已阻断',
  failed: '失败',
  cancelled: '已取消',
}

function agentFor(event: RunEvent): Agent | undefined {
  return run.value?.agents.find((agent) => agent.id === event.agent_id)
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

function toggleAgent(agentId: string): void {
  selectedAgents.value = selectedAgents.value.includes(agentId)
    ? selectedAgents.value.filter((id) => id !== agentId)
    : [...selectedAgents.value, agentId]
}

function submitQuestion(): void {
  const trimmed = question.value.trim()
  if (!trimmed || selectedAgents.value.length === 0) return
  submittedQuestion.value = trimmed
  question.value = ''
}

async function refreshRun(): Promise<void> {
  if (!run.value) return
  snapshot.value = await api.getRun(run.value.id)
}

function connectEvents(): void {
  eventSource?.close()
  if (!run.value) return
  const sequence = events.value.at(-1)?.sequence ?? 0
  eventSource = new EventSource(api.eventUrl(run.value.id, sequence))
  eventSource.addEventListener('run-event', () => {
    refreshRun().catch((reason) => {
      error.value = reason instanceof Error ? reason.message : '同步事件失败'
    })
  })
  eventSource.onerror = () => {
    if (run.value?.status === 'completed' || run.value?.status === 'cancelled') {
      eventSource?.close()
    }
  }
}

async function loadDemo(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    snapshot.value = await api.getDemo()
    connectEvents()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '无法连接 API'
  } finally {
    loading.value = false
  }
}

async function createFreshDemo(): Promise<void> {
  actionPending.value = true
  error.value = ''
  try {
    snapshot.value = await api.createDemo()
    selectedAgents.value = []
    submittedQuestion.value = ''
    connectEvents()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '创建演示失败'
  } finally {
    actionPending.value = false
  }
}

async function startRun(): Promise<void> {
  if (!run.value) return
  actionPending.value = true
  error.value = ''
  try {
    snapshot.value = await api.startRun(run.value.id)
    connectEvents()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '启动失败'
  } finally {
    actionPending.value = false
  }
}

async function cancelRun(): Promise<void> {
  if (!run.value) return
  actionPending.value = true
  try {
    snapshot.value = await api.cancelRun(run.value.id)
    eventSource?.close()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '停止失败'
  } finally {
    actionPending.value = false
  }
}

onMounted(loadDemo)
onBeforeUnmount(() => eventSource?.close())
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand-block">
        <div class="brand-mark">MA</div>
        <div>
          <strong>Agent Arena</strong>
          <span>{{ run?.project_name ?? '多智能体协演场' }}</span>
        </div>
      </div>

      <div class="view-segment" aria-label="观察模式">
        <button
          :class="{ active: viewMode === 'graph' }"
          type="button"
          @click="viewMode = 'graph'"
        >
          <ChartNetwork :size="17" />
          图谱
        </button>
        <button
          :class="{ active: viewMode === 'split' }"
          type="button"
          @click="viewMode = 'split'"
        >
          <Columns2 :size="17" />
          双栏
        </button>
        <button
          :class="{ active: viewMode === 'workbench' }"
          type="button"
          @click="viewMode = 'workbench'"
        >
          <PanelTop :size="17" />
          工作台
        </button>
      </div>

      <div class="run-meta">
        <span class="stage-text">Step {{ run?.stage ?? 1 }}/5</span>
        <strong>{{ run?.stage_label ?? '准备中' }}</strong>
        <span class="divider"></span>
        <span class="status-dot" :class="run?.status"></span>
        <span>{{ statusLabels[run?.status ?? 'draft'] }}</span>
      </div>
    </header>

    <div v-if="loading" class="center-state">
      <RefreshCw class="spin" :size="22" />
      正在装载工作台
    </div>

    <div v-else-if="error && !run" class="center-state error-state">
      <ShieldAlert :size="24" />
      <strong>无法打开工作台</strong>
      <span>{{ error }}</span>
      <button type="button" class="primary-button" @click="loadDemo">重新连接</button>
    </div>

    <template v-else-if="run">
      <section class="run-header">
        <div>
          <span class="eyebrow">RUN {{ run.id.slice(-6).toUpperCase() }}</span>
          <h1>{{ run.title }}</h1>
          <div class="stage-track" aria-label="生产流阶段">
            <div
              v-for="(stage, index) in stages"
              :key="stage"
              class="stage-step"
              :class="{ complete: run.stage > index + 1, current: run.stage === index + 1 }"
            >
              <span>{{ run.stage > index + 1 ? '✓' : index + 1 }}</span>
              <small>{{ stage }}</small>
            </div>
          </div>
        </div>
        <div class="run-actions">
          <div class="metric">
            <span>进度</span>
            <strong>{{ run.progress }}%</strong>
          </div>
          <div class="metric">
            <span>Token</span>
            <strong>{{ run.token_count.toLocaleString() }}</strong>
          </div>
          <div class="metric">
            <span>估算成本</span>
            <strong>¥{{ run.estimated_cost.toFixed(2) }}</strong>
          </div>
          <button
            v-if="canStart"
            type="button"
            class="primary-button"
            :disabled="actionPending"
            @click="startRun"
          >
            <Play :size="17" />
            启动演示
          </button>
          <button
            v-if="isRunning"
            type="button"
            class="danger-button"
            :disabled="actionPending"
            @click="cancelRun"
          >
            <Square :size="15" />
            停止
          </button>
          <button
            type="button"
            class="icon-button"
            title="创建新的演示运行"
            :disabled="actionPending"
            @click="createFreshDemo"
          >
            <RefreshCw :size="18" />
          </button>
        </div>
      </section>

      <div v-if="error" class="inline-alert">
        <ShieldAlert :size="17" />
        {{ error }}
      </div>

      <main v-if="viewMode === 'split'" class="split-view">
        <section class="timeline-panel">
          <div class="panel-heading">
            <div>
              <span class="panel-kicker">Live trace</span>
              <h2>协作与对抗时间线</h2>
            </div>
            <div class="filter-row">
              <Filter :size="16" />
              <button
                v-for="item in filters"
                :key="item.id"
                type="button"
                :class="{ active: eventFilter === item.id }"
                @click="eventFilter = item.id"
              >
                {{ item.label }}
              </button>
            </div>
          </div>

          <div class="timeline-scroll">
            <article
              v-for="event in [...filteredEvents].reverse()"
              :key="event.id"
              class="event-row"
              :class="[event.category, event.severity]"
            >
              <div class="event-rail">
                <span class="event-dot"></span>
              </div>
              <div class="event-body">
                <div class="event-meta">
                  <span>{{ formatTime(event.created_at) }}</span>
                  <span v-if="agentFor(event)" class="agent-chip">
                    {{ agentFor(event)?.short_name }}
                    {{ agentFor(event)?.name }}
                  </span>
                  <span class="event-kind">{{ event.type }}</span>
                </div>
                <h3>{{ event.title }}</h3>
                <p>{{ event.summary }}</p>
              </div>
            </article>
          </div>
        </section>

        <aside class="agent-panel">
          <div class="panel-heading compact">
            <div>
              <span class="panel-kicker">Agent roster</span>
              <h2>Agent 与任务</h2>
            </div>
            <span class="agent-count">{{ run.agents.length }} agents</span>
          </div>

          <div v-if="activeAgent" class="active-agent-banner">
            <span class="pulse"></span>
            <div>
              <small>当前执行</small>
              <strong>{{ activeAgent.name }}</strong>
              <span>{{ activeAgent.current_task }}</span>
            </div>
          </div>

          <div class="agent-list">
            <div
              v-for="agent in run.agents"
              :key="agent.id"
              class="agent-row"
              :class="[agent.status, agent.tone]"
            >
              <span class="agent-avatar">{{ agent.short_name }}</span>
              <div class="agent-info">
                <strong>{{ agent.name }}</strong>
                <span>{{ agent.current_task ?? agent.role }}</span>
                <div class="progress-track">
                  <span :style="{ width: `${agent.progress}%` }"></span>
                </div>
              </div>
              <span class="agent-status">{{ agent.status }}</span>
            </div>
          </div>

          <section class="defect-section">
            <div class="section-title">
              <ShieldAlert :size="17" />
              <strong>红队缺陷</strong>
              <span>{{ run.defects.length }}</span>
            </div>
            <div v-if="run.defects.length === 0" class="empty-copy">
              红队阶段开始后，结构化缺陷会显示在这里。
            </div>
            <div v-for="defect in run.defects" :key="defect.id" class="defect-row">
              <span class="severity">{{ defect.severity }}</span>
              <div>
                <strong>{{ defect.title }}</strong>
                <span>{{ defect.category }} · {{ defect.status }} · {{ defect.owner }}</span>
              </div>
            </div>
          </section>
        </aside>
      </main>

      <main v-else-if="viewMode === 'graph'" class="graph-view">
        <div class="graph-toolbar">
          <div>
            <span class="panel-kicker">Relationship map</span>
            <h2>Agent 协作与证据图谱</h2>
          </div>
          <label class="search-box">
            <Search :size="17" />
            <input aria-label="搜索图谱" placeholder="搜索 Agent、产物或缺陷" />
          </label>
        </div>
        <div class="graph-canvas">
          <div class="graph-link horizontal top"></div>
          <div class="graph-link horizontal bottom"></div>
          <div class="graph-link vertical center"></div>
          <div class="graph-node central">
            <FileText :size="21" />
            <strong>需求与方案基线</strong>
            <span>3 个正式产物</span>
          </div>
          <div
            v-for="(agent, index) in run.agents"
            :key="agent.id"
            class="graph-node agent-node"
            :class="[`node-${index + 1}`, agent.tone, agent.status]"
          >
            <span class="agent-avatar">{{ agent.short_name }}</span>
            <strong>{{ agent.name }}</strong>
            <span>{{ agent.status === 'working' ? agent.current_task : agent.role }}</span>
          </div>
          <div v-if="run.defects.length" class="graph-node defect-node">
            <ShieldAlert :size="20" />
            <strong>{{ run.defects[0].title }}</strong>
            <span>{{ run.defects[0].status }}</span>
          </div>
        </div>
        <div class="graph-legend">
          <span><i class="legend-dot collaboration"></i>协作角色</span>
          <span><i class="legend-dot attack"></i>红队角色</span>
          <span><i class="legend-dot gate"></i>裁判角色</span>
          <span><i class="legend-dot working"></i>正在执行</span>
        </div>
      </main>

      <main v-else class="workbench-view">
        <article class="report-pane">
          <div class="report-heading">
            <span class="report-index">01</span>
            <div>
              <span class="panel-kicker">Final report · v1</span>
              <h2>核心结论：以权限可追溯为边界推进企业知识助手</h2>
            </div>
            <ChevronDown :size="20" />
          </div>
          <p class="report-lead">
            本轮多 Agent 评审认为，企业知识助手具备明确的效率价值，但发布前必须将检索权限、引用权限与审计事件统一到资源级授权模型中。
          </p>
          <h3>协作形成的方案</h3>
          <p>
            产品与技术 Agent 共同提出分层知识空间、可解释引用和渐进交付方案。需求 Agent
            将原始输入整理为 12 项可验证需求，并登记 3 个需要业务确认的假设。
          </p>
          <blockquote>
            任何被模型检索到的内容，都不等于当前用户有权在答案中看到。授权必须在召回后、回答生成前再次执行。
          </blockquote>
          <h3>红队发现与修订</h3>
          <p>
            红队构造跨空间引用场景，发现初版方案仅在检索入口校验空间权限，引用链接仍可能暴露受限文档。修订方案增加资源级过滤与脱敏摘要，复测后缺陷关闭。
          </p>
          <h3>终审结果</h3>
          <div class="score-grid">
            <div v-for="score in run.scores" :key="score.name">
              <span>{{ score.name }}</span>
              <strong>{{ score.score }}</strong>
              <i><b :style="{ width: `${score.score}%` }"></b></i>
            </div>
            <div v-if="run.scores.length === 0" class="score-placeholder">
              终审阶段将生成六个维度的评分。
            </div>
          </div>
        </article>

        <aside class="interaction-pane">
          <div class="interaction-heading">
            <MessageSquare :size="25" />
            <div>
              <strong>Interactive Tools</strong>
              <span>{{ run.agents.length }} agents available</span>
            </div>
          </div>

          <div class="interaction-modes">
            <button type="button" class="active"><Bot :size="17" />与裁判 Agent 对话</button>
            <button type="button"><Users :size="17" />多 Agent 问卷</button>
          </div>

          <div class="selection-heading">
            <strong>选择调查对象</strong>
            <span>已选 {{ selectedAgents.length }} / {{ run.agents.length }}</span>
          </div>
          <div class="agent-selector">
            <button
              v-for="agent in run.agents"
              :key="agent.id"
              type="button"
              :class="{ selected: selectedAgents.includes(agent.id) }"
              @click="toggleAgent(agent.id)"
            >
              <span class="agent-avatar">{{ agent.short_name }}</span>
              <span>
                <strong>{{ agent.name }}</strong>
                <small>{{ agent.role }}</small>
              </span>
              <i><Check v-if="selectedAgents.includes(agent.id)" :size="17" /></i>
            </button>
          </div>
          <div class="selection-actions">
            <button type="button" @click="selectedAgents = run.agents.map((agent) => agent.id)">
              全选
            </button>
            <button type="button" @click="selectedAgents = []">清空</button>
          </div>

          <label class="question-field">
            <span>问卷问题</span>
            <textarea
              v-model="question"
              rows="4"
              placeholder="例如：你在本轮中最不同意哪项决策？请引用证据。"
            ></textarea>
          </label>
          <button
            type="button"
            class="primary-button send-button"
            :disabled="!question.trim() || selectedAgents.length === 0"
            @click="submitQuestion"
          >
            <Send :size="17" />
            发送给 {{ selectedAgents.length || 0 }} 个 Agent
          </button>

          <div v-if="submittedQuestion" class="question-result">
            <CheckCircle2 :size="20" />
            <div>
              <strong>问卷已加入交互队列</strong>
              <span>{{ submittedQuestion }}</span>
            </div>
          </div>
        </aside>
      </main>
    </template>
  </div>
</template>
