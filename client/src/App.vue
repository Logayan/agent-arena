<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from './api'
import KnowledgeRelationGraph from './components/KnowledgeRelationGraph.vue'
import {
  BookOpen, Bot, Compass,
  Download, FileText, FolderOpen, LoaderCircle, Maximize2, Minimize2, Minus, MousePointer2, Network, Play, Plus, RefreshCw,
  Search, Settings2, Sparkles, Trash2, UploadCloud, Users, Workflow, XCircle, Zap,
} from '@lucide/vue'

type Json = Record<string, any>
type Screen = 'jianghu' | 'teams' | 'agents' | 'flows' | 'showcase' | 'runs' | 'settings'

const showcaseEnabled = import.meta.env.VITE_ENABLE_SHOWCASE === 'true'
const screen = ref<Screen>('jianghu')
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const overview = ref<Json>({})
const organizations = ref<Json[]>([])
const activeOrganizationId = ref('')
const organizationSwitching = ref(false)
const agents = ref<Json[]>([])
const teams = ref<Json[]>([])
const workflows = ref<Json[]>([])
const runs = ref<Json[]>([])
const commissions = ref<Json[]>([])
const modelConfigs = ref<Json[]>([])
const knowledgeSources = ref<Json[]>([])
const openClawStatus = ref<Json>({ available: false, mode: 'embedded-local' })
const knowledgeGraph = ref<Json>({ nodes: [], edges: [] })
const showcase = ref<Json>({})
const showcaseBusy = ref(false)
const showcasePolling = ref(false)
const currentTask = ref<Json | null>(null)
const activeRun = ref<Json | null>(null)
const runPolling = ref(false)
const selectedAssessmentTeams = ref<string[]>([])
const recommendationLoading = ref('')
const teamResolutionLoading = ref(false)
const lastTeamResolution = ref<Json | null>(null)
const teamProposal = ref<Json | null>(null)
const teamProposalDraft = ref<Json>({ name: '', purpose: '', operating_mode: 'collaborative', members: [], member_ids: [] })
const teamProposalSaving = ref(false)
const highlightedAgentId = ref('')
const selectedWorkflowVersions = ref<Record<string, string>>({})

const taskForm = ref({ title: '', description: '' })
const agentRequirement = ref('')
const organizationForm = ref({ source_type: 'intent', world_type: 'small', name: '', purpose: '', operating_mode: 'collaborative', intent: '' })
const organizationCreating = ref(false)
const teamForm = ref({ name: '', purpose: '', operating_mode: 'collaborative', member_ids: [] as string[] })
const teamInviteDraft = ref<Record<string, string>>({})
const teamInviteLoading = ref('')
const teamKnowledgeFiles = ref<Record<string, File[]>>({})
const teamKnowledgeInputKeys = ref<Record<string, number>>({})
const knowledgeUploadingTeamId = ref('')
const teamKnowledgeUploadProgress = ref<Record<string, Json>>({})
const organizationKnowledgeUploadProgress = ref<Json>({ completed: 0, total: 0 })
const knowledgeSourcePages = ref<Record<string, Json>>({})
const knowledgeUploadPreviewLimits = ref<Record<string, number>>({})
const selectedKnowledgeDetail = ref<Json | null>(null)
const knowledgeDetailLoading = ref('')
const knowledgeDetailLoadingMore = ref(false)
const knowledgeDeletingSourceId = ref('')
const knowledgeNoteTeam = ref<Json | null>(null)
const knowledgeNoteForm = ref({ title: '', content: '' })
const knowledgeNoteSaving = ref(false)
const knowledgeSearchQuery = ref<Record<string, string>>({})
const knowledgeSearchResults = ref<Record<string, Json[]>>({})
const knowledgeSearchingTeamId = ref('')
const organizationKnowledgeFiles = ref<File[]>([])
const organizationKnowledgeInputKey = ref(0)
const organizationKnowledgeUploading = ref(false)
const editingOrganization = ref<Json | null>(null)
const organizationDraft = ref({ name: '', description: '' })
const organizationSaving = ref(false)
const editingTeam = ref<Json | null>(null)
const teamEditDraft = ref({ name: '', purpose: '', operating_mode: 'collaborative' })
const teamEditingSaving = ref(false)
const editingAgent = ref<Json | null>(null)
const agentDraft = ref<Json>({})
const agentVersions = ref<Json[]>([])
const agentMemories = ref<Json[]>([])
const agentEditorLoading = ref(false)
const editingWorkflow = ref<Json | null>(null)
const workflowDraft = ref<Json>({ name: '', description: '', nodes: [], edges: [] })
const selectedWorkflowNodeKey = ref('')
const workflowZoom = ref(1)
const showAllWorkflowEdges = ref(false)
const selectedSceneTaskId = ref('')
const flowsPage = ref<HTMLElement | null>(null)
const runsPage = ref<HTMLElement | null>(null)
const fullscreenTarget = ref<'flows' | 'runs' | ''>('')
const scenePanelTab = ref<'dossier' | 'actions' | 'messages' | 'evidence' | 'rationale' | 'intervene'>('dossier')
const sceneTabs: { id: 'dossier' | 'actions' | 'messages' | 'evidence' | 'rationale' | 'intervene'; label: string }[] = [
  { id: 'dossier', label: '公共卷宗' }, { id: 'actions', label: '人物行动' }, { id: 'messages', label: '议事通信' },
  { id: 'evidence', label: '文件与测试' }, { id: 'rationale', label: '发起人私享' }, { id: 'intervene', label: '介入现场' },
]
const interventionForm = ref({ kind: 'supplement', content: '', agent_id: '' })
const interventionSaving = ref(false)
const extensionMinutes = ref(60)
const teamToDisband = ref<Json | null>(null)
const disbandingTeamId = ref('')
const workflowToDelete = ref<Json | null>(null)
const workflowDeletingId = ref('')
const modelForm = ref({ id: '', name: '', provider: 'openai-responses', base_url: '', model: '', tier: 'medium', token: '', token_hint: '', active: true })
const modelMessage = ref('')
const modelDeletingId = ref('')
let runPollTimer: ReturnType<typeof setInterval> | null = null
let showcasePollTimer: ReturnType<typeof setInterval> | null = null

const organization = computed(() => organizations.value.find(item => String(item.id) === activeOrganizationId.value) ?? organizations.value[0] ?? null)
const currentOrganizationId = computed(() => String(organization.value?.id ?? ''))
const organizationName = computed(() => {
  const name = String(organization.value?.name ?? '')
  return name.includes('公司') ? '我的江湖' : (name || '我的江湖')
})
const currentRealmOverview = computed(() => ({
  teams: teams.value.length,
  agents: agents.value.length,
  workflows: workflowFamilies.value.length,
  runs: runs.value.length,
}))
const teamById = computed(() => Object.fromEntries(teams.value.map(team => [team.id, team])))
const agentById = computed(() => Object.fromEntries(agents.value.map(agent => [agent.id, agent])))
const activeRunEvents = computed(() => [...(activeRun.value?.events ?? [])].reverse())
const activePresenceCount = computed(() => (activeRun.value?.agent_presence ?? []).filter((item: Json) =>
  ['assigned', 'preparing', 'retrieving', 'working', 'retrying', 'tooling', 'validating', 'communicating', 'integrating'].includes(String(item.state)),
).length)
const worldBroadcasts = computed(() => activeRunEvents.value
  .filter((event: Json) => event.payload?.visibility !== 'initiator_only')
  .slice(0, 8))
const latestFailureEvent = computed(() => activeRunEvents.value.find((event: Json) => [
  'task.failed', 'run.failed', 'run.cancelled', 'run.budget_exhausted', 'run.revision_exhausted',
].includes(String(event.type))))
const runTimeLimitExhausted = computed(() => Boolean(
  activeRun.value?.status === 'budget_exhausted'
    && String(latestFailureEvent.value?.payload?.error_detail ?? '').includes('run_time_limit'),
))
const runConclusionArtifact = computed(() => (activeRun.value?.artifacts ?? []).find((artifact: Json) =>
  String(artifact.title ?? '') === '一页纸结论'
))
const latestShowcaseComparison = computed(() => showcase.value?.latest_comparison ?? null)
const workflowFamilies = computed(() => {
  const groups: Record<string, Json[]> = {}
  for (const flow of workflows.value) {
    const familyId = String(flow.family_id || flow.id)
    ;(groups[familyId] ??= []).push(flow)
  }
  return Object.entries(groups).map(([familyId, versions]) => {
    versions.sort((left, right) => compareVersions(String(right.version), String(left.version)))
    return { familyId, latest: versions[0], versions }
  })
})
const workflowDraftFlow = computed(() => {
  const nodes = workflowDraft.value.nodes ?? []
  const validKeys = new Set(nodes.map((node: Json) => String(node.key)))
  const edges = nodes.flatMap((node: Json) => (node.depends_on ?? [])
    .filter((key: string) => validKeys.has(String(key)) && String(key) !== String(node.key))
    .map((key: string) => [String(key), String(node.key)]))
  return { id: 'workflow-draft', definition: { nodes, edges } }
})

function teamManagedKnowledge(teamId: string): Json[] {
  const seen = new Set<string>()
  return knowledgeSources.value.filter(source => {
    if (String(source.metadata?.team_id ?? '') !== teamId || !source.metadata?.managed) return false
    const identity = String(source.metadata?.sha256 || source.id)
    if (seen.has(identity)) return false
    seen.add(identity)
    return true
  })
}

const realmManagedKnowledge = computed(() => knowledgeSources.value.filter(source => {
  const metadata = source.metadata ?? {}
  return metadata.managed && (
    (metadata.scope_type === 'organization' && metadata.scope_id === organization.value?.id)
    || (metadata.organization_id === organization.value?.id && !metadata.team_id)
  )
}))
function scopeKnowledgeSources(sources: Json[], organizationId = currentOrganizationId.value): Json[] {
  return sources.filter(source => {
    const metadata = source.metadata ?? {}
    return String(metadata.organization_id ?? '') === organizationId
      || (metadata.scope_type === 'organization' && String(metadata.scope_id ?? '') === organizationId)
  })
}

function fileSizeLabel(size: number): string {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  if (size >= 1024) return `${Math.ceil(size / 1024)} KB`
  return `${size} B`
}

function fileRelativePath(file: File): string {
  return (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
}

function selectTeamKnowledgeFiles(teamId: string, event: Event): void {
  const input = event.target as HTMLInputElement
  teamKnowledgeFiles.value = { ...teamKnowledgeFiles.value, [teamId]: Array.from(input.files ?? []) }
}

function selectOrganizationKnowledgeFiles(event: Event): void {
  const input = event.target as HTMLInputElement
  organizationKnowledgeFiles.value = Array.from(input.files ?? [])
}

function fileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result ?? '')
      resolve(result.includes(',') ? result.slice(result.indexOf(',') + 1) : result)
    }
    reader.onerror = () => reject(reader.error ?? new Error('知识文件读取失败'))
    reader.readAsDataURL(file)
  })
}

function knowledgeScopeKey(scopeType: 'organization' | 'team', scopeId: string): string {
  return `${scopeType}:${scopeId}`
}

function knowledgePage(scopeType: 'organization' | 'team', scopeId: string): Json {
  return knowledgeSourcePages.value[knowledgeScopeKey(scopeType, scopeId)] ?? {
    items: [], pagination: { offset: 0, limit: 20, total: 0, has_more: true }, loading: false,
  }
}

async function loadKnowledgeSourcePage(scopeType: 'organization' | 'team', scopeId: string, reset = false): Promise<void> {
  const key = knowledgeScopeKey(scopeType, scopeId)
  const current = knowledgePage(scopeType, scopeId)
  if (current.loading || (!reset && current.items.length && !current.pagination?.has_more)) return
  knowledgeSourcePages.value = { ...knowledgeSourcePages.value, [key]: { ...current, loading: true } }
  try {
    const offset = reset ? 0 : Number(current.items?.length ?? 0)
    const response = await api.knowledgeSourcesPage(scopeType, scopeId, offset, 20) as Json
    knowledgeSourcePages.value = {
      ...knowledgeSourcePages.value,
      [key]: {
        items: reset ? (response.items ?? []) : [...(current.items ?? []), ...(response.items ?? [])],
        pagination: response.pagination,
        loading: false,
      },
    }
  } catch (cause) {
    knowledgeSourcePages.value = { ...knowledgeSourcePages.value, [key]: { ...current, loading: false } }
    error.value = cause instanceof Error ? cause.message : '知识目录读取失败'
  }
}

function invalidateKnowledgeSourcePage(scopeType: 'organization' | 'team', scopeId: string): void {
  const key = knowledgeScopeKey(scopeType, scopeId)
  const next = { ...knowledgeSourcePages.value }
  delete next[key]
  knowledgeSourcePages.value = next
}

function toggleKnowledgeSourceList(event: Event, scopeType: 'organization' | 'team', scopeId: string): void {
  if ((event.currentTarget as HTMLDetailsElement).open) void loadKnowledgeSourcePage(scopeType, scopeId, true)
}

function scrollKnowledgeSourceList(event: Event, scopeType: 'organization' | 'team', scopeId: string): void {
  const target = event.currentTarget as HTMLElement
  if (target.scrollTop + target.clientHeight >= target.scrollHeight - 28) void loadKnowledgeSourcePage(scopeType, scopeId)
}

function uploadPreviewFiles(files: File[], key: string): File[] {
  return files.slice(0, knowledgeUploadPreviewLimits.value[key] ?? 30)
}

function scrollUploadPreview(event: Event, files: File[], key: string): void {
  const target = event.currentTarget as HTMLElement
  const limit = knowledgeUploadPreviewLimits.value[key] ?? 30
  if (limit < files.length && target.scrollTop + target.clientHeight >= target.scrollHeight - 24) {
    knowledgeUploadPreviewLimits.value = { ...knowledgeUploadPreviewLimits.value, [key]: Math.min(files.length, limit + 30) }
  }
}

function knowledgeUploadBatches(files: File[]): File[][] {
  const batches: File[][] = []
  let current: File[] = []
  let currentBytes = 0
  const maxFiles = 20
  const maxBytes = 6 * 1024 * 1024
  for (const file of files) {
    if (current.length && (current.length >= maxFiles || currentBytes + file.size > maxBytes)) {
      batches.push(current)
      current = []
      currentBytes = 0
    }
    current.push(file)
    currentBytes += file.size
  }
  if (current.length) batches.push(current)
  return batches
}

async function uploadKnowledgeFiles(
  files: File[],
  folderName: string,
  send: (payload: Json) => Promise<Json>,
  onProgress: (completed: number, total: number) => void,
): Promise<Json> {
  const collectionId = `folder_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`
  const uploaded: Json[] = []
  const failed: Json[] = []
  let completed = 0
  for (const batch of knowledgeUploadBatches(files)) {
    try {
      const payloadFiles = await Promise.all(batch.map(async file => ({
        filename: file.name,
        relative_path: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
        media_type: file.type || 'application/octet-stream',
        content_base64: await fileBase64(file),
      })))
      const result = await send({ folder_name: folderName, collection_id: collectionId, files: payloadFiles })
      uploaded.push(...(result.uploaded ?? []))
      failed.push(...(result.failed ?? []))
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : '该批次上传失败'
      failed.push(...batch.map(file => ({ relative_path: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name, error: message })))
    }
    completed += batch.length
    onProgress(completed, files.length)
  }
  if (!uploaded.length) throw new Error(failed[0]?.error || '目录没有成功保存任何文件')
  return { collection_id: collectionId, uploaded, failed }
}

async function uploadTeamKnowledge(team: Json): Promise<void> {
  const files = teamKnowledgeFiles.value[team.id] ?? []
  if (!files.length) return
  knowledgeUploadingTeamId.value = team.id
  teamKnowledgeUploadProgress.value = { ...teamKnowledgeUploadProgress.value, [team.id]: { completed: 0, total: files.length } }
  error.value = ''
  try {
    const firstPath = (files[0] as File & { webkitRelativePath?: string }).webkitRelativePath || files[0].name
    const folderName = firstPath.split('/')[0] || '补充文件'
    const result = await uploadKnowledgeFiles(
      files,
      folderName,
      payload => api.uploadTeamKnowledgeFolder(team.id, payload) as Promise<Json>,
      (completed, total) => { teamKnowledgeUploadProgress.value = { ...teamKnowledgeUploadProgress.value, [team.id]: { completed, total } } },
    )
    const uploaded = (result.uploaded ?? []) as Json[]
    const [updatedTeams, updatedKnowledge] = await Promise.all([api.teams(organization.value?.id), api.knowledgeSources()])
    teams.value = updatedTeams
    knowledgeSources.value = scopeKnowledgeSources(updatedKnowledge as Json[])
    invalidateKnowledgeSourcePage('team', team.id)
    teamKnowledgeFiles.value = { ...teamKnowledgeFiles.value, [team.id]: [] }
    teamKnowledgeInputKeys.value = { ...teamKnowledgeInputKeys.value, [team.id]: (teamKnowledgeInputKeys.value[team.id] ?? 0) + 1 }
    const chunks = uploaded.reduce((total, item) => total + Number(item.index?.chunk_count ?? 0), 0)
    const failed = (result.failed ?? []).length + uploaded.filter((item: Json) => item.index?.status === 'failed').length
    notice.value = failed
      ? `已成功保存 ${uploaded.length} 份文件，另有 ${failed} 份上传或索引失败；可打开知识详情查看原因。`
      : `已将 ${files.length} 份知识保存到“${team.name}”，并建立 ${chunks} 个可检索片段。`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '组织知识上传失败'
  } finally {
    knowledgeUploadingTeamId.value = ''
  }
}

async function uploadOrganizationKnowledge(): Promise<void> {
  if (!organization.value || !organizationKnowledgeFiles.value.length) return
  organizationKnowledgeUploading.value = true
  organizationKnowledgeUploadProgress.value = { completed: 0, total: organizationKnowledgeFiles.value.length }
  error.value = ''
  try {
    const files = organizationKnowledgeFiles.value
    const firstPath = (files[0] as File & { webkitRelativePath?: string }).webkitRelativePath || files[0].name
    const result = await uploadKnowledgeFiles(
      files,
      firstPath.split('/')[0] || '大江湖公共知识',
      payload => api.uploadOrganizationKnowledgeFolder(organization.value.id, payload) as Promise<Json>,
      (completed, total) => { organizationKnowledgeUploadProgress.value = { completed, total } },
    )
    const [sources, graph] = await Promise.all([api.knowledgeSources(), api.knowledgeGraph(organization.value.id)])
    knowledgeSources.value = scopeKnowledgeSources(sources as Json[])
    knowledgeGraph.value = graph
    invalidateKnowledgeSourcePage('organization', organization.value.id)
    const chunkCount = (result.uploaded ?? []).reduce((sum: number, item: Json) => sum + Number(item.index?.chunk_count ?? 0), 0)
    const failedCount = (result.failed ?? []).length
    notice.value = failedCount
      ? `已递归保存 ${(result.uploaded ?? []).length} 份大江湖公共知识，${failedCount} 份失败，并建立 ${chunkCount} 个 RAG 片段。`
      : `已递归保存 ${(result.uploaded ?? []).length} 份大江湖公共知识，并建立 ${chunkCount} 个 RAG 片段；全部小江湖可按权限继承检索。`
    organizationKnowledgeFiles.value = []
    organizationKnowledgeInputKey.value += 1
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '大江湖知识目录上传失败'
  } finally {
    organizationKnowledgeUploading.value = false
  }
}

async function openAgentEditor(agent: Json): Promise<void> {
  editingAgent.value = agent
  agentDraft.value = JSON.parse(JSON.stringify({
    name: agent.name,
    role: agent.role,
    description: agent.description,
    persona: agent.persona,
    cognitive_level: agent.cognitive_level ?? 2,
    authority_level: agent.authority_level ?? 1,
    capabilities: agent.capabilities ?? [],
    visibility: agent.visibility ?? 'private',
    runtime: 'openclaw',
    skills: agent.skills ?? [],
    memory_policy: agent.memory_policy ?? { enabled: true, max_prompt_items: 8, write_after_task: true },
    knowledge_source_ids: agent.knowledge_source_ids ?? [],
  }))
  agentEditorLoading.value = true
  try {
    ;[agentVersions.value, agentMemories.value] = await Promise.all([api.agentVersions(agent.id), api.agentMemories(agent.id)])
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '人物详情读取失败'
  } finally {
    agentEditorLoading.value = false
  }
}

function addAgentSkill(): void {
  ;(agentDraft.value.skills ??= []).push({ name: '新技能', description: '', instructions: '', enabled: true })
}

function removeAgentSkill(index: number): void {
  agentDraft.value.skills.splice(index, 1)
}

function addAgentCapability(): void {
  ;(agentDraft.value.capabilities ??= []).push('新能力')
}

function removeAgentCapability(index: number): void {
  agentDraft.value.capabilities.splice(index, 1)
}

async function saveAgentRevision(): Promise<void> {
  if (!editingAgent.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await api.reviseAgent(editingAgent.value.id, agentDraft.value)
    notice.value = `已创建“${(result.agent as Json).name}”第 ${(result.agent as Json).version} 版；所在小江湖跟随最新版，历史 Workflow 仍保持冻结绑定。`
    agents.value = await api.platformAgents(currentOrganizationId.value)
    teams.value = await api.teams(organization.value?.id)
    editingAgent.value = null
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '人物版本保存失败'
  } finally {
    busy.value = false
  }
}

function knowledgeStatusLabel(source: Json): string {
  if (source.status === 'ready' && source.metadata?.indexed) return `已建立 RAG · ${source.metadata.chunk_count ?? 0} 个片段`
  if (source.status === 'index_failed') return '解析或索引失败'
  return '正在解析与建立索引'
}

async function openKnowledgeDetail(source: Json): Promise<void> {
  knowledgeDetailLoading.value = source.id
  error.value = ''
  try {
    selectedKnowledgeDetail.value = await api.knowledgeSourceDetail(source.id, 0, 20)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '读取知识内容失败'
  } finally {
    knowledgeDetailLoading.value = ''
  }
}

async function scrollKnowledgeDetail(event: Event): Promise<void> {
  if (!selectedKnowledgeDetail.value?.pagination?.has_more || knowledgeDetailLoadingMore.value) return
  const target = event.currentTarget as HTMLElement
  if (target.scrollTop + target.clientHeight < target.scrollHeight - 32) return
  knowledgeDetailLoadingMore.value = true
  try {
    const current = selectedKnowledgeDetail.value
    const next = await api.knowledgeSourceDetail(current.source.id, current.chunks.length, 20) as Json
    selectedKnowledgeDetail.value = {
      ...current,
      chunks: [...current.chunks, ...(next.chunks ?? [])],
      pagination: next.pagination,
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '继续读取知识内容失败'
  } finally {
    knowledgeDetailLoadingMore.value = false
  }
}

async function deleteKnowledgeSource(source: Json): Promise<void> {
  const sourceId = String(source.id ?? '')
  const metadata = source.metadata ?? {}
  const scopeType: 'organization' | 'team' = metadata.scope_type === 'organization' ? 'organization' : 'team'
  const scopeId = String(metadata.scope_id || metadata.team_id || metadata.organization_id || '')
  const displayName = String(metadata.relative_path || source.name || '该知识文件')
  if (!sourceId || !scopeId) {
    error.value = '该知识缺少归属信息，无法安全删除。'
    return
  }
  if (!window.confirm(`确定删除“${displayName}”吗？\n\n平台保存的原文件、RAG 切片、知识图谱关系和授权记录会一并删除，此操作不可撤销。`)) return
  knowledgeDeletingSourceId.value = sourceId
  error.value = ''
  try {
    const result = await api.deleteKnowledgeSource(sourceId) as Json
    if (selectedKnowledgeDetail.value?.source?.id === sourceId) selectedKnowledgeDetail.value = null
    knowledgeSearchResults.value = Object.fromEntries(
      Object.entries(knowledgeSearchResults.value).map(([teamId, items]) => [
        teamId,
        (items ?? []).filter((item: Json) => String(item.source_id) !== sourceId),
      ]),
    )
    invalidateKnowledgeSourcePage(scopeType, scopeId)
    const [sources, refreshedTeams, graph] = await Promise.all([
      api.knowledgeSources(),
      scopeType === 'team' ? api.teams(organization.value?.id) : Promise.resolve(null),
      organization.value?.id ? api.knowledgeGraph(String(organization.value.id)) : Promise.resolve(null),
    ])
    knowledgeSources.value = scopeKnowledgeSources(sources as Json[])
    if (refreshedTeams) teams.value = refreshedTeams as Json[]
    if (graph) knowledgeGraph.value = graph as Json
    await loadKnowledgeSourcePage(scopeType, scopeId, true)
    notice.value = result.cleanup_pending
      ? `“${displayName}”已从知识库移除；磁盘临时清理将在后台继续处理。`
      : `已删除“${displayName}”，并同步清理 RAG 切片、知识图谱关系和授权记录。`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '删除知识文件失败'
  } finally {
    knowledgeDeletingSourceId.value = ''
  }
}

function openKnowledgeNote(team: Json): void {
  knowledgeNoteTeam.value = team
  knowledgeNoteForm.value = { title: '', content: '' }
}

async function saveKnowledgeNote(): Promise<void> {
  if (!knowledgeNoteTeam.value || !knowledgeNoteForm.value.title.trim() || !knowledgeNoteForm.value.content.trim()) return
  knowledgeNoteSaving.value = true
  error.value = ''
  try {
    const result = await api.addTeamKnowledgeNote(
      knowledgeNoteTeam.value.id,
      knowledgeNoteForm.value.title.trim(),
      knowledgeNoteForm.value.content.trim(),
    ) as Json
    knowledgeSources.value = scopeKnowledgeSources(await api.knowledgeSources() as Json[])
    notice.value = `已补充“${knowledgeNoteForm.value.title.trim()}”，并建立 ${result.index?.chunk_count ?? 0} 个可检索知识片段。`
    knowledgeNoteTeam.value = null
    knowledgeNoteForm.value = { title: '', content: '' }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '补充组织知识失败'
  } finally {
    knowledgeNoteSaving.value = false
  }
}

async function searchTeamKnowledge(team: Json): Promise<void> {
  const query = String(knowledgeSearchQuery.value[team.id] ?? '').trim()
  if (!query) return
  knowledgeSearchingTeamId.value = team.id
  error.value = ''
  try {
    const response = await api.searchTeamKnowledge(team.id, query)
    knowledgeSearchResults.value = { ...knowledgeSearchResults.value, [team.id]: response.results ?? [] }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '检索组织知识失败'
  } finally {
    knowledgeSearchingTeamId.value = ''
  }
}
const selectedWorkflowNode = computed(() => workflowDraft.value.nodes?.find((node: Json) => node.key === selectedWorkflowNodeKey.value) ?? null)
const selectedSceneTask = computed(() => activeRun.value?.tasks?.find((task: Json) => task.id === selectedSceneTaskId.value) ?? activeRun.value?.tasks?.[0] ?? null)
const selectedNodeDossier = computed(() => selectedSceneTask.value
  ? activeRun.value?.node_dossiers?.[selectedSceneTask.value.id] ?? null
  : null)

function initials(name: string): string {
  return name.split(/\s+/).map(part => part[0]).join('').slice(0, 2).toUpperCase()
}

function modeLabel(mode: string): string {
  return ({ collaborative: '同心协作', debate: '议事争辩', red_team: '攻守对抗', hierarchical: '统领协作' } as Record<string, string>)[mode] ?? '自定章法'
}

function teamIcon(index: number): string {
  return ['🏯', '⛩️', '🏘️', '🛡️', '🏕️'][index % 5]
}

function enabledSkillCount(agent: Json): number {
  return (agent.skills ?? []).filter((skill: Json) => skill.enabled !== false).length
}

function compareVersions(left: string, right: string): number {
  const a = left.split('.').map(Number)
  const b = right.split('.').map(Number)
  for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
    const difference = (a[index] ?? 0) - (b[index] ?? 0)
    if (difference) return difference
  }
  return 0
}

function displayedWorkflow(family: Json): Json {
  const selectedId = selectedWorkflowVersions.value[family.familyId]
  return family.versions.find((flow: Json) => flow.id === selectedId) ?? family.latest
}

function dependencyMeta(flow: Json, node: Json): Json {
  const sourceKeys = (flow.definition?.edges ?? []).filter((edge: string[]) => edge[1] === node.key).map((edge: string[]) => String(edge[0]))
  const names = sourceKeys.map((key: string) => flow.definition.nodes.find((item: Json) => String(item.key) === key)?.name ?? key)
  return sourceKeys.length
    ? { empty: false, label: `接收 ${sourceKeys.length} 个上游产物`, detail: names.join('、') }
    : { empty: true, label: '流程起点', detail: '无需等待上游产物' }
}

function hasAlternatePath(source: string, target: string, edges: string[][], ignoredIndex: number): boolean {
  const outgoing: Record<string, string[]> = {}
  edges.forEach((edge, index) => {
    if (index === ignoredIndex) return
    ;(outgoing[String(edge[0])] ??= []).push(String(edge[1]))
  })
  const pending = [...(outgoing[source] ?? [])]
  const visited = new Set<string>()
  while (pending.length) {
    const current = pending.shift() as string
    if (current === target) return true
    if (visited.has(current)) continue
    visited.add(current)
    pending.push(...(outgoing[current] ?? []))
  }
  return false
}

function workflowGraph(flow: Json, showAllEdges = false): Json {
  const rawNodes = (flow.definition?.nodes ?? []) as Json[]
  const rawEdges = (flow.definition?.edges ?? []) as string[][]
  const keys = new Set(rawNodes.map(node => String(node.key)))
  const validEdges = rawEdges.filter(edge => edge.length === 2 && keys.has(String(edge[0])) && keys.has(String(edge[1])))
  const structuralEdges = showAllEdges
    ? validEdges
    : validEdges.filter(([source, target], index) => !hasAlternatePath(String(source), String(target), validEdges, index))
  const levels: Record<string, number> = Object.fromEntries(rawNodes.map(node => [String(node.key), 0]))
  for (let pass = 0; pass < rawNodes.length; pass += 1) {
    let changed = false
    for (const [source, target] of validEdges) {
      const next = (levels[String(source)] ?? 0) + 1
      if (next > (levels[String(target)] ?? 0)) {
        levels[String(target)] = next
        changed = true
      }
    }
    if (!changed) break
  }
  const grouped: Record<number, Json[]> = {}
  rawNodes.forEach((node, index) => (grouped[levels[String(node.key)] ?? 0] ??= []).push({ ...node, originalIndex: index }))
  const nodeWidth = 220
  const nodeHeight = 192
  const columnGap = 126
  const rowGap = 68
  const padding = 52
  const maxLevel = Math.max(0, ...Object.values(levels))
  const maxRows = Math.max(1, ...Object.values(grouped).map(items => items.length))
  const canvasHeight = padding * 2 + maxRows * nodeHeight + (maxRows - 1) * rowGap
  const positioned: Json[] = []
  for (let level = 0; level <= maxLevel; level += 1) {
    const items = grouped[level] ?? []
    const contentHeight = items.length * nodeHeight + Math.max(0, items.length - 1) * rowGap
    const startY = Math.max(padding, (canvasHeight - contentHeight) / 2)
    items.forEach((node, row) => positioned.push({
      ...node,
      level,
      x: padding + level * (nodeWidth + columnGap),
      y: startY + row * (nodeHeight + rowGap),
      width: nodeWidth,
      height: nodeHeight,
    }))
  }
  const byKey = Object.fromEntries(positioned.map(node => [String(node.key), node]))
  const outgoing: Record<string, string[][]> = {}
  const incoming: Record<string, string[][]> = {}
  structuralEdges.forEach(edge => {
    ;(outgoing[String(edge[0])] ??= []).push(edge)
    ;(incoming[String(edge[1])] ??= []).push(edge)
  })
  const edges = structuralEdges.map(([source, target], index) => {
    const from = byKey[String(source)]
    const to = byKey[String(target)]
    const x1 = from.x + nodeWidth
    const sourceEdges = outgoing[String(source)] ?? []
    const sourceIndex = sourceEdges.findIndex(edge => edge[0] === source && edge[1] === target)
    const y1 = from.y + ((sourceIndex + 1) / (sourceEdges.length + 1)) * nodeHeight
    const x2 = to.x
    const targetEdges = incoming[String(target)] ?? []
    const targetIndex = targetEdges.findIndex(edge => edge[0] === source && edge[1] === target)
    const y2 = to.y + ((targetIndex + 1) / (targetEdges.length + 1)) * nodeHeight
    const laneX = x1 + Math.max(50, (x2 - x1) * .5) + (sourceIndex - targetIndex) * 9
    const spansMultipleStages = Number(to.level) - Number(from.level) > 1
    if (spansMultipleStages) {
      const topLane = 24 + (index % 4) * 8
      return {
        id: `${source}-${target}-${index}`,
        path: `M ${x1} ${y1} C ${x1 + 28} ${y1}, ${x1 + 32} ${topLane}, ${x1 + 64} ${topLane} L ${x2 - 64} ${topLane} C ${x2 - 32} ${topLane}, ${x2 - 28} ${y2}, ${x2} ${y2}`,
        express: true,
      }
    }
    return {
      id: `${source}-${target}-${index}`,
      path: `M ${x1} ${y1} C ${x1 + 34} ${y1}, ${laneX - 24} ${y1}, ${laneX} ${y1} L ${laneX} ${y2} C ${laneX + 24} ${y2}, ${x2 - 34} ${y2}, ${x2} ${y2}`,
      express: false,
    }
  })
  const stages = Array.from({ length: maxLevel + 1 }, (_, level) => ({
    level,
    x: padding - 22 + level * (nodeWidth + columnGap),
    width: nodeWidth + 44,
    count: grouped[level]?.length ?? 0,
  }))
  return {
    nodes: positioned,
    edges,
    stages,
    hiddenEdgeCount: validEdges.length - structuralEdges.length,
    width: padding * 2 + (maxLevel + 1) * nodeWidth + maxLevel * columnGap,
    height: canvasHeight,
  }
}

function workflowDependencyCandidates(node: Json): Json[] {
  return workflowDraft.value.nodes.filter((item: Json) => item.key !== node.key)
}

function nodeParticipants(node: Json): Json[] {
  const members = teamById.value[node.team_id]?.members ?? []
  const selected = new Set(node.participant_agent_ids ?? [])
  return selected.size
    ? members.filter((member: Json) => selected.has(member.id))
    : members.filter((member: Json) => member.id === node.agent_id)
}

function runStatusLabel(status: string): string {
  return ({
    draft: '等待启动', pending: '等待前置节点', retrying: '正在重试', running: '正在执行', completed: '已完成', failed: '执行失败',
    pause_requested: '正在停手', paused: '已暂停', cancelled: '已取消', budget_exhausted: '预算已耗尽', revision_exhausted: '返工轮次已耗尽',
  } as Record<string, string>)[status] ?? status
}

function eventTypeLabel(type: string): string {
  return ({
    'run.created': '事件建立', 'run.started': '开始执行', 'run.recovered': '断点恢复', 'run.interrupted': '等待恢复', 'run.completed': '全部完成',
    'run.retry_created': '重试现场建立', 'run.failed': '执行失败', 'run.cancelled': '已取消', 'run.budget_exhausted': '预算耗尽', 'run.time_extended': '运行时限延长',
    'run.pause_requested': '请求停手', 'run.paused': '现场已暂停', 'run.resumed': '恢复行动',
    'run.revision_exhausted': '返工轮次耗尽', 'openclaw.runtime.ready': '执行底座已接管', 'openclaw.runtime.recovered': '执行底座已恢复',
    'openclaw.turn.started': '人物行动回合启动', 'openclaw.turn.completed': '人物行动回合完成',
    'task.started': '节点启动', 'task.retrying': '节点整体重试', 'task.failed': '节点失败', 'llm.retrying': '模型连接重试',
    'agent.action.retrying': '人物自动重试', 'agent.action.failed': '人物行动失败',
    'team.member.started': '人物开始行动', 'team.member.completed': '人物完成贡献',
    'team.dossier.published': '公共卷宗开放', 'team.communication.round.started': '公开议事开始',
    'team.communication.round.completed': '公开议事完成', 'team.synthesis.started': '负责人开始整合',
    'team.synthesis.completed': '团队完成合议', 'engineering.submission.published': '工程提交已公开',
    'artifact.created': '产物形成', 'agent.message.sent': '人物公开通信',
    'agent.memory.persisted': '人物记忆沉淀', 'gate.passed': '裁判通过', 'gate.rejected': '裁判退回',
    'workflow.loop.created': '自动返工循环',
    'agent.context.prepared': '行动前整备', 'agent.action.started': '开始行动', 'agent.action.progress': '公开进度',
    'agent.rationale.submitted': '发起人行动说明',
    'agent.action.submitted': '完整提交', 'agent.tool.started': '工具开始', 'agent.tool.completed': '工具返回',
    'agent.file.created': '新增文件', 'agent.file.modified': '修改文件', 'agent.file.deleted': '删除文件',
    'agent.command.started': '命令开始', 'agent.command.completed': '命令完成',
    'agent.test.started': '测试开始', 'agent.test.completed': '测试完成',
    'artifact.validation.started': '交付校验', 'artifact.validation.passed': '校验通过', 'artifact.validation.failed': '校验失败',
    'user.intervention.queued': '用户意见待送达', 'user.intervention.applied': '用户意见已送达',
  } as Record<string, string>)[type] ?? type
}

function runWorkflow(run: Json): Json | undefined {
  return workflows.value.find(flow => flow.id === run.workflow_id)
}

function runTaskTeam(task: Json): Json | undefined {
  return teams.value.find(team => team.id === task.team_id)
}

function runTaskAgent(task: Json): Json | undefined {
  return agents.value.find(agent => agent.id === task.agent_id)
}

function runTaskParticipants(task: Json): Json[] {
  if (!activeRun.value) return []
  const workflow = runWorkflow(activeRun.value)
  const node = workflow?.definition?.nodes?.find((item: Json) => item.key === task.node_key)
  const selectedIds = new Set((node?.participant_agent_ids ?? []).map((item: unknown) => String(item)))
  const members = runTaskTeam(task)?.members ?? []
  if (selectedIds.size) return members.filter((member: Json) => selectedIds.has(String(member.id)))
  const lead = runTaskAgent(task)
  return lead ? [lead] : []
}

function eventAgent(event: Json): Json | undefined {
  return agents.value.find(agent => agent.id === (event.payload?.agent_id ?? event.payload?.from_agent_id))
}

function uiRuntimeText(value: unknown): string {
  return String(value ?? '').replace(/openclaw/gi, '执行底座')
}

function taskEvents(task: Json): Json[] {
  return (activeRun.value?.events ?? []).filter((event: Json) => event.payload?.task_id === task.id)
}

function taskRetryEvents(task: Json): Json[] {
  return taskEvents(task).filter((event: Json) => [
    'llm.retrying', 'agent.action.retrying', 'agent.action.failed', 'task.retrying', 'task.failed',
  ].includes(String(event.type)))
}

function taskActionEvents(task: Json): Json[] {
  return taskEvents(task).filter((event: Json) => [
    'agent.action.started', 'agent.action.progress', 'agent.tool.started', 'agent.tool.completed',
    'agent.action.retrying', 'agent.action.failed',
    'agent.file.created', 'agent.file.modified', 'agent.file.deleted',
    'agent.command.started', 'agent.command.completed', 'agent.test.started', 'agent.test.completed',
    'artifact.validation.started', 'artifact.validation.passed', 'artifact.validation.failed',
  ].includes(String(event.type)))
}

function taskMessageEvents(task: Json): Json[] {
  return taskEvents(task).filter((event: Json) => [
    'team.dossier.published', 'team.communication.round.started', 'team.communication.round.completed',
    'agent.message.sent', 'team.synthesis.started', 'team.synthesis.completed',
    'engineering.submission.published', 'gate.passed', 'gate.rejected', 'workflow.loop.created',
  ].includes(String(event.type)))
}

function taskEvidenceEvents(task: Json): Json[] {
  return taskEvents(task).filter((event: Json) => [
    'agent.file.created', 'agent.file.modified', 'agent.file.deleted', 'agent.command.completed', 'agent.test.completed',
    'engineering.submission.published', 'artifact.validation.passed', 'artifact.validation.failed', 'artifact.created',
  ].includes(String(event.type)))
}

function publicEventContent(event: Json): string {
  return uiRuntimeText(event.payload?.content ?? event.payload?.contribution ?? event.payload?.output ?? event.payload?.command ?? event.payload?.contribution_preview ?? event.summary ?? '')
}

function actionEventPreview(event: Json): string {
  return speechPreview(publicEventContent(event) || event.summary || event.title, '已留下公开行动记录。')
}

function contributionPreview(event: Json, limit = 240): string {
  const normalized = String(publicEventContent(event) || event.summary || '已提交公开贡献。')
    .replace(/[#*_`>\[\]]/g, '').replace(/\s+/g, ' ').trim()
  return normalized.length > limit ? `${normalized.slice(0, limit)}…` : normalized
}

function collaborationSpeaker(event: Json): string {
  if (event.payload?.from_name) return `${event.payload.from_name} → ${event.payload.to_name}`
  return eventAgent(event)?.name ?? (event.payload?.team_id ? teamById.value[event.payload.team_id]?.name : '平台') ?? '平台'
}

function sceneParticipants(task: Json): Json[] {
  const people = runTaskParticipants(task)
  const lead = runTaskAgent(task)
  return people.length ? people : (lead ? [lead] : [])
}

function eventParticipantIds(event: Json): string[] {
  return [event.payload?.agent_id, event.payload?.from_agent_id, event.payload?.to_agent_id]
    .filter((value: unknown) => value !== undefined && value !== null && String(value).trim())
    .map((value: unknown) => String(value))
}

function sceneArrivedParticipants(task: Json): Json[] {
  const bound = sceneParticipants(task)
  const arrivedIds = new Set(taskEvents(task).flatMap(eventParticipantIds))
  return bound.filter((person: Json) => arrivedIds.has(String(person.id)))
}

function sceneWaitingParticipants(task: Json): Json[] {
  const arrivedIds = new Set(sceneArrivedParticipants(task).map((person: Json) => String(person.id)))
  return sceneParticipants(task).filter((person: Json) => !arrivedIds.has(String(person.id)))
}

function participantDuty(task: Json, person: Json): string {
  const teamMember = (runTaskTeam(task)?.members ?? []).find((member: Json) => String(member.id) === String(person.id))
  const node = runWorkflow(activeRun.value ?? {})?.definition?.nodes?.find((item: Json) => item.key === task.node_key)
  if (teamMember?.responsibility) return String(teamMember.responsibility)
  if (String(node?.agent_id ?? '') === String(person.id)) return `主持“${task.node_name}”并对正式交付负责`
  return `参与“${task.node_name}”的独立行动与公开协作`
}

function initiatorNoteSections(content: unknown): Json[] {
  const text = String(content ?? '').trim()
  if (!text) return []
  const labels = ['事实依据', '关键取舍', '不确定性', '下一步验证']
  const pattern = new RegExp(`(?:^|\\n)(${labels.join('|')})[：:]\\s*([\\s\\S]*?)(?=\\n(?:${labels.join('|')})[：:]|$)`, 'g')
  const sections = [...text.matchAll(pattern)].map(match => ({ label: match[1], content: match[2].trim() })).filter(item => item.content)
  return sections.length ? sections : [{ label: '行动说明', content: text }]
}

function presenceTask(presence: Json): Json | undefined {
  return activeRun.value?.tasks?.find((task: Json) => task.id === presence.task_id)
}

function presencePreview(presence: Json): string {
  return speechPreview(
    presence.latest_event?.payload?.content
      ?? presence.latest_event?.payload?.contribution_preview
      ?? presence.latest_event?.payload?.command
      ?? presence.latest_event?.summary,
    presence.node_name ? `正在“${presence.node_name}”处理事务。` : '当前没有分配中的节点。',
  )
}

function agentSocietyPresence(agent: Json): Json {
  const isLive = ['running', 'pause_requested', 'paused'].includes(String(activeRun.value?.status))
  const presence = isLive
    ? activeRun.value?.agent_presence?.find((item: Json) => item.agent_id === agent.id)
    : null
  return presence ?? { state: 'idle', state_label: '闲居待命', node_name: '', latest_event: null }
}

function selectPresence(presence: Json): void {
  const task = presenceTask(presence)
  if (task) selectSceneTask(task)
}

function failedAgentEvent(task: Json, person: Json): Json | undefined {
  return [...taskEvents(task)].reverse().find((event: Json) =>
    event.type === 'agent.action.failed' && String(event.payload?.agent_id ?? '') === String(person.id),
  )
}

function canRetryFailedAgent(task: Json, person: Json): boolean {
  return Boolean(
    activeRun.value
      && ['failed', 'cancelled', 'budget_exhausted', 'revision_exhausted'].includes(String(activeRun.value.status))
      && failedAgentEvent(task, person),
  )
}

async function retryFailedAgent(task: Json, person: Json): Promise<void> {
  if (!canRetryFailedAgent(task, person)) return
  await retryActiveRun(task)
  notice.value = `已为“${person.name}”建立新的隔离行动现场；从其所在节点重新执行，同节点协作者会重新装载独立上下文，上游已完成产物继续保留。`
}

function nodeCollaborationPhase(task: Json): Json {
  const dossier = activeRun.value?.node_dossiers?.[task.id] ?? {}
  const events = taskEvents(task)
  if (task.status === 'completed' || events.some((event: Json) => event.type === 'artifact.validation.passed')) {
    return { step: 5, label: '节点完成并流转', tone: 'completed' }
  }
  if (events.some((event: Json) => event.type === 'artifact.validation.failed')) return { step: 5, label: '校验未通过，准备重做', tone: 'failed' }
  if (events.some((event: Json) => event.type === 'artifact.validation.started')) return { step: 5, label: '真实产物校验', tone: 'working' }
  if (events.some((event: Json) => event.type === 'team.synthesis.started')) return { step: 4, label: '负责人整合正式交付', tone: 'working' }
  if ((dossier.communications?.length ?? 0) > 0 || events.some((event: Json) => event.type === 'team.communication.round.started')) return { step: 3, label: '公开议事与质询', tone: 'working' }
  if ((dossier.contributions?.length ?? 0) > 0) return { step: 2, label: '独立贡献写入公共卷宗', tone: 'working' }
  if (task.status === 'running') return { step: 1, label: '隔离上下文独立办事', tone: 'working' }
  return { step: 0, label: '等待上游正式产物', tone: 'waiting' }
}

function speechPreview(value: unknown, fallback: string): string {
  const normalized = uiRuntimeText(value ?? fallback).replace(/[#*_`>|\[\]]/g, '').replace(/\s+/g, ' ').trim() || fallback
  return normalized.length > 84 ? `${normalized.slice(0, 84)}…` : normalized
}

function personActivity(task: Json, person: Json): Json {
  if (task.status === 'completed') {
    return { state: '本节点已完成', speech: '正式产物已经交付并进入下游。', tone: 'completed' }
  }
  const presence = (activeRun.value?.agent_presence ?? []).find((item: Json) => item.agent_id === person.id)
  if (presence && (!presence.task_id || presence.task_id === task.id)) {
    const tone = ({ blocked: 'failed', paused: 'waiting', waiting: 'waiting', reviewing: 'completed', idle: 'completed' } as Record<string, string>)[presence.state] ?? 'working'
    return { state: uiRuntimeText(presence.state_label), speech: speechPreview(presence.latest_event?.payload?.content ?? presence.latest_event?.summary, `我正在“${task.node_name}”处理公开事务。`), tone }
  }
  const events = taskEvents(task).filter((event: Json) => event.payload?.agent_id === person.id).reverse()
  const latest = events[0]
  if (latest?.type === 'agent.message.sent') return { state: `正在${latest.payload?.message_type ?? '交流'}`, speech: speechPreview(latest.payload?.content ?? latest.summary, '我正在向协作者发出公开消息。'), tone: 'working' }
  if (latest?.type === 'openclaw.turn.started') return { state: '正在执行', speech: speechPreview(latest.summary, '正在装载我的身份、记忆和技能。'), tone: 'working' }
  if (latest?.type === 'agent.memory.persisted') return { state: '经历已沉淀', speech: '本次公开贡献已进入我的独立长期记忆。', tone: 'completed' }
  if (latest?.type === 'llm.retrying') return { state: '正在重连模型', speech: speechPreview(latest.summary, '模型连接不稳定，正在自动恢复。'), tone: 'retrying' }
  if (latest?.type === 'agent.action.retrying') return { state: '人物正在自动重试', speech: speechPreview(latest.summary, '本次独立行动失败，正在使用新的隔离回合重试。'), tone: 'retrying' }
  if (latest?.type === 'agent.action.failed') return { state: '人物行动失败', speech: speechPreview(latest.payload?.error_detail ?? latest.summary, '人物自动重试后仍未完成，等待发起人重新行动。'), tone: 'failed' }
  if (latest?.type === 'team.member.completed') return { state: '已提交意见', speech: speechPreview(latest.payload?.contribution_preview ?? latest.summary, '我的独立意见已经提交，正在等待团队合议。'), tone: 'completed' }
  if (latest?.type === 'team.synthesis.completed') return { state: '正在主持合议', speech: speechPreview(latest.payload?.contribution_preview ?? latest.summary, '团队意见已经汇总为正式产物。'), tone: 'completed' }
  if (latest?.type === 'team.member.started') return { state: '正在独立工作', speech: speechPreview(latest.summary, `我正在负责“${task.node_name}”。`), tone: 'working' }
  if (task.status === 'failed') return { state: '行动受阻', speech: speechPreview(task.output?.error, '节点执行失败，等待发起人处理。'), tone: 'failed' }
  if (task.status === 'completed') return { state: '本节点已完成', speech: '正式产物已经交付并进入下游。', tone: 'completed' }
  if (task.status === 'running') return { state: '正在处理任务', speech: `我正在负责“${task.node_name}”。`, tone: 'working' }
  if (task.status === 'retrying') return { state: '正在准备重试', speech: task.output?.last_error ?? '连接不稳定，平台正在自动恢复。', tone: 'retrying' }
  return { state: '等待前置产物', speech: '前置节点完成后，我会立刻开始。', tone: 'waiting' }
}

function scenePlaceIcon(index: number): string {
  return ['🏛️', '🧭', '🛠️', '📚', '⚖️', '🧪', '🛡️', '🎯'][index % 8]
}

function sceneMapSize(taskCount: number): Json {
  const columns = Math.min(4, Math.max(2, Math.ceil(Math.sqrt(Math.max(taskCount, 1)))))
  const rows = Math.ceil(Math.max(taskCount, 1) / columns)
  return { columns, width: Math.max(980, 110 + columns * 260), height: Math.max(620, 130 + rows * 230) }
}

function sceneBuildingPosition(index: number, taskCount: number): Json {
  const map = sceneMapSize(taskCount)
  const column = index % map.columns
  const row = Math.floor(index / map.columns)
  return { left: 88 + column * 260, top: 92 + row * 230 }
}

function sceneActorStyle(taskIndex: number, personIndex: number, taskCount: number): Record<string, string> {
  const building = sceneBuildingPosition(taskIndex, taskCount)
  const offsets = [[42, 144], [104, 151], [166, 139], [72, 185], [142, 187]]
  const offset = offsets[personIndex % offsets.length]
  const direction = personIndex % 2 ? -1 : 1
  return {
    left: `${building.left + offset[0]}px`,
    top: `${building.top + offset[1]}px`,
    '--walk-x': `${direction * (28 + (personIndex % 3) * 12)}px`,
    '--walk-y': `${(personIndex % 2 ? 1 : -1) * (10 + (personIndex % 3) * 4)}px`,
    '--wander-x': `${direction * (20 + (personIndex % 3) * 9)}px`,
    '--wander-y': `${(personIndex % 2 ? -1 : 1) * (7 + (personIndex % 3) * 3)}px`,
    '--walk-delay': `${-(taskIndex * .7 + personIndex * .55)}s`,
  }
}

function selectSceneTask(task: Json): void {
  selectedSceneTaskId.value = task.id
  scenePanelTab.value = 'dossier'
  interventionForm.value = { kind: 'supplement', content: '', agent_id: '' }
}

function preferredRunTask(tasks: Json[] = []): Json | undefined {
  return tasks.find((task: Json) => ['running', 'retrying', 'failed'].includes(String(task.status)))
    ?? tasks.find((task: Json) => String(task.status) === 'pending')
    ?? tasks[0]
}

function focusCurrentTask(): void {
  const current = preferredRunTask(activeRun.value?.tasks ?? [])
  if (current) selectSceneTask(current)
}

function eventDetail(event: Json | undefined): string {
  const detail = uiRuntimeText(event?.payload?.error_detail ?? event?.summary ?? '').trim()
  if (!detail || /(?:failure|error)\s*:\s*$/i.test(detail)) {
    return '这是一条旧执行记录，当时没有保存底层异常正文，无法还原更具体的网络错误；当前模型连接测试已经恢复正常。请创建新的重试现场，新执行会完整记录请求次数、HTTP 状态、异常类型与失败详情。'
  }
  return detail
}

function retryEventDetail(event: Json): string {
  const parts = [event?.payload?.error_type]
  if (event?.payload?.http_status) parts.push(`HTTP ${event.payload.http_status}`)
  else if (event?.payload?.reason) parts.push(event.payload.reason)
  if (event?.payload?.attempt) parts.push(`第 ${event.payload.attempt} 次`)
  return parts.filter(Boolean).join(' · ') || '旧记录未保存结构化错误详情'
}

function friendlyFailureReason(event: Json): string {
  const detail = eventDetail(event)
  if (detail.includes('openclaw_empty_output')) return '执行回合已完成，但暂未收到正式文本。公开行动仍然保留，平台会从可见输出恢复，避免把已完成行动误判为空。'
  if (/network failure|connection attempts failed|timeout/i.test(detail)) return '模型服务连接超时或中断。平台会先自动重试模型请求，再重试整个节点；全部失败后才停止本次 Run。'
  if (detail.includes('artifact_validation_failed')) return `真实交付校验未通过：${detail.split(':').slice(2).join('；') || '缺少文件、成功命令或通过的自动化测试。'}`
  if (/401|403|credential|token/i.test(detail)) return '模型服务拒绝了当前凭据。请在“模型与凭据”检查配置；页面不会显示或记录完整 Token。'
  return speechPreview(detail, '节点执行遇到异常，平台已保留全部已完成行动和重试证据。')
}

function runWorkflowVersionNote(run: Json): string {
  const flow = runWorkflow(run)
  if (!flow) return '本现场固定使用创建时的生产流快照。'
  const family = workflowFamilies.value.find(item => item.familyId === String(flow.family_id || flow.id))
  const historical = family && family.latest.id !== flow.id
  return `本现场固定使用“${flow.name}”第 ${flow.version} 版${historical ? '（历史版本）' : ''}；流程后续升级不会改写本次人物绑定和执行记录。`
}

async function copyWorkspacePath(path: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(path)
    notice.value = '产物工作区地址已复制。'
  } catch {
    notice.value = `产物工作区：${path}`
  }
}

function stopRunPolling(): void {
  if (runPollTimer) clearInterval(runPollTimer)
  runPollTimer = null
  runPolling.value = false
}

async function refreshActiveRun(runId: string): Promise<void> {
  try {
    const result = await api.getPlatformRun(runId, currentOrganizationId.value)
    activeRun.value = result.run as Json
    if (!activeRun.value.tasks?.some((task: Json) => task.id === selectedSceneTaskId.value)) {
      selectedSceneTaskId.value = preferredRunTask(activeRun.value.tasks ?? [])?.id ?? ''
    }
    const terminal = ['completed', 'failed', 'cancelled', 'budget_exhausted', 'revision_exhausted'].includes(String(activeRun.value.status))
    if (terminal) {
      stopRunPolling()
      runs.value = await api.platformRuns(currentOrganizationId.value)
    }
  } catch (cause) {
    stopRunPolling()
    error.value = cause instanceof Error ? cause.message : '事件现场刷新失败'
  }
}

function beginRunPolling(runId: string): void {
  stopRunPolling()
  runPolling.value = true
  runPollTimer = setInterval(() => { void refreshActiveRun(runId) }, 1500)
}

function stopShowcasePolling(): void {
  if (showcasePollTimer) clearInterval(showcasePollTimer)
  showcasePollTimer = null
  showcasePolling.value = false
}

async function refreshShowcaseComparison(comparisonId: string): Promise<void> {
  try {
    const result = await api.getProductionFlowComparison(comparisonId)
    const comparison = result.comparison as Json
    showcase.value = { ...showcase.value, latest_comparison: comparison }
    if (comparison.status === 'completed') {
      stopShowcasePolling()
      runs.value = await api.platformRuns(currentOrganizationId.value)
    }
  } catch (cause) {
    stopShowcasePolling()
    error.value = cause instanceof Error ? cause.message : '对照实验状态读取失败'
  }
}

function beginShowcasePolling(comparisonId: string): void {
  stopShowcasePolling()
  showcasePolling.value = true
  void refreshShowcaseComparison(comparisonId)
  showcasePollTimer = setInterval(() => { void refreshShowcaseComparison(comparisonId) }, 1800)
}

function formatDuration(seconds: number): string {
  if (!seconds) return '尚未形成'
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分钟`
}

function signedMetric(value: number, suffix = ''): string {
  const numeric = Number(value || 0)
  return `${numeric > 0 ? '+' : ''}${numeric}${suffix}`
}

function showcaseRun(variant: string): Json {
  return latestShowcaseComparison.value?.[variant] ?? {}
}

function showcaseWorkflow(variant: string): Json {
  return showcase.value?.assets?.workflows?.[variant] ?? {}
}

async function installShowcase(): Promise<void> {
  showcaseBusy.value = true
  error.value = ''
  try {
    showcase.value = await api.installProductionFlowShowcase()
    const [a, t, w] = await Promise.all([
      api.platformAgents(currentOrganizationId.value),
      api.teams(currentOrganizationId.value),
      api.platformWorkflows(currentOrganizationId.value),
    ])
    agents.value = a
    teams.value = t
    workflows.value = w
    notice.value = '完整案例已经安装为真实人物、团队和两套冻结生产流；尚未调用模型，也未产生费用。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '案例安装失败'
  } finally {
    showcaseBusy.value = false
  }
}

async function startShowcaseComparison(comparisonId?: string): Promise<void> {
  const confirmed = window.confirm(
    comparisonId
      ? '将使用当前真实模型配置同时启动两个 Run。会产生真实 Token 与费用，是否继续？'
      : '将创建并启动“单 Agent 基线”和“多 Agent 协作/对抗”两个真实 Run。会产生真实 Token 与费用，是否继续？',
  )
  if (!confirmed) return
  showcaseBusy.value = true
  error.value = ''
  notice.value = ''
  try {
    if (!showcase.value.installed) showcase.value = await api.installProductionFlowShowcase()
    let targetId = comparisonId
    if (!targetId) {
      const created = await api.createProductionFlowComparison()
      const comparison = created.comparison as Json
      showcase.value = { ...showcase.value, latest_comparison: comparison }
      targetId = String(comparison.id)
    }
    const started = await api.startProductionFlowComparison(String(targetId))
    const comparison = started.comparison as Json
    showcase.value = { ...showcase.value, latest_comparison: comparison }
    runs.value = await api.platformRuns(currentOrganizationId.value)
    beginShowcasePolling(String(targetId))
    notice.value = String(started.message || '真实对照实验已经启动。')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '真实对照实验启动失败；已创建的草稿 Run 会保留，可直接重试启动'
    if (latestShowcaseComparison.value?.id) beginShowcasePolling(String(latestShowcaseComparison.value.id))
  } finally {
    showcaseBusy.value = false
  }
}

async function hydrateRun(runId: string, navigate = false): Promise<void> {
  error.value = ''
  const result = await api.getPlatformRun(runId, currentOrganizationId.value)
  activeRun.value = result.run as Json
  selectedSceneTaskId.value = preferredRunTask(activeRun.value.tasks ?? [])?.id ?? ''
  if (navigate) {
    screen.value = 'runs'
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  if (screen.value === 'runs' && ['running', 'pause_requested', 'paused'].includes(String(activeRun.value.status))) beginRunPolling(runId)
  else stopRunPolling()
}

async function openRun(runId: string): Promise<void> {
  await hydrateRun(runId, true)
}

function go(next: Screen): void {
  if (next === 'showcase' && !showcaseEnabled) return
  if (screen.value !== next && (fullscreenTarget.value || document.fullscreenElement)) {
    if (typeof document.exitFullscreen === 'function') void document.exitFullscreen().catch(() => undefined)
    fullscreenTarget.value = ''
  }
  if (next !== 'runs') stopRunPolling()
  if (next !== 'showcase') stopShowcasePolling()
  screen.value = next
  error.value = ''
  window.scrollTo({ top: 0, behavior: 'smooth' })
  if (next === 'runs') {
    const liveRun = runs.value.find(run => ['running', 'pause_requested', 'paused'].includes(String(run.status)))
    const targetRun = liveRun ?? activeRun.value ?? runs.value.find(run => run.status !== 'draft') ?? runs.value[0]
    if (targetRun?.id && targetRun.id !== activeRun.value?.id) void openRun(String(targetRun.id))
    else if (['running', 'pause_requested', 'paused'].includes(String(activeRun.value?.status))) {
      focusCurrentTask()
      beginRunPolling(String(activeRun.value?.id ?? ''))
    }
  }
  if (next === 'showcase' && latestShowcaseComparison.value?.status === 'running') {
    beginShowcasePolling(String(latestShowcaseComparison.value.id))
  }
}

function syncFullscreenTarget(): void {
  const current = document.fullscreenElement
  fullscreenTarget.value = current === flowsPage.value ? 'flows' : current === runsPage.value ? 'runs' : ''
}

async function togglePageFullscreen(target: 'flows' | 'runs'): Promise<void> {
  const element = target === 'flows' ? flowsPage.value : runsPage.value
  if (!element) return
  try {
    const active = fullscreenTarget.value === target || document.fullscreenElement === element
    if (active) {
      if (document.fullscreenElement && typeof document.exitFullscreen === 'function') await document.exitFullscreen()
      fullscreenTarget.value = ''
    } else if (typeof element.requestFullscreen === 'function') {
      if (document.fullscreenElement && typeof document.exitFullscreen === 'function') await document.exitFullscreen()
      await element.requestFullscreen()
      fullscreenTarget.value = target
    } else {
      fullscreenTarget.value = target
    }
  } catch {
    notice.value = '当前浏览器未允许全屏显示，请检查页面权限后重试。'
  }
}

function organizationIdFromLocation(): string {
  return new URLSearchParams(window.location.search).get('realm') ?? ''
}

function rememberOrganization(organizationId: string, replace = false): void {
  localStorage.setItem('jianghu.activeOrganizationId', organizationId)
  const url = new URL(window.location.href)
  url.searchParams.set('realm', organizationId)
  if (replace) window.history.replaceState({ organizationId }, '', url)
  else window.history.pushState({ organizationId }, '', url)
}

async function loadOrganizationContext(organizationId: string): Promise<void> {
  const [a, t, w, r, c, k] = await Promise.all([
    api.platformAgents(organizationId),
    api.teams(organizationId),
    api.platformWorkflows(organizationId),
    api.platformRuns(organizationId),
    api.commissions(organizationId),
    api.knowledgeSources(),
  ])
  agents.value = a
  teams.value = t
  workflows.value = w
  runs.value = r
  commissions.value = c
  knowledgeSources.value = scopeKnowledgeSources(k as Json[], organizationId)
  const restored = c.find(item => item.id === currentTask.value?.id) ?? c[0] ?? null
  currentTask.value = restored
  if (restored) {
    taskForm.value = { title: String(restored.title ?? ''), description: String(restored.description ?? '') }
    selectedAssessmentTeams.value = Array.isArray(restored.selected_team_ids) ? [...restored.selected_team_ids] : []
    setTeamProposal(restored.team_proposal ?? null)
  } else {
    taskForm.value = { title: '', description: '' }
    selectedAssessmentTeams.value = []
    setTeamProposal(null)
  }
  const preferredRun = r.find(item => ['running', 'pause_requested', 'paused'].includes(String(item.status)))
    ?? r.find(item => item.id === restored?.run_id)
    ?? r.find(item => item.status !== 'draft')
  if (preferredRun?.id) await hydrateRun(String(preferredRun.id), false)
  else {
    activeRun.value = null
    selectedSceneTaskId.value = ''
  }
  try {
    knowledgeGraph.value = await api.knowledgeGraph(organizationId)
  } catch (cause) {
    knowledgeGraph.value = { nodes: [], edges: [] }
    error.value = cause instanceof Error ? `知识图谱暂时不可用：${cause.message}` : '知识图谱暂时不可用'
  }
}

async function switchOrganization(organizationId: string, replaceHistory = false): Promise<void> {
  if (!organizationId || !organizations.value.some(item => String(item.id) === organizationId)) return
  organizationSwitching.value = true
  error.value = ''
  stopRunPolling()
  stopShowcasePolling()
  editingOrganization.value = null
  editingTeam.value = null
  editingAgent.value = null
  editingWorkflow.value = null
  selectedKnowledgeDetail.value = null
  activeOrganizationId.value = organizationId
  rememberOrganization(organizationId, replaceHistory)
  try {
    await loadOrganizationContext(organizationId)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '大江湖切换失败'
  } finally {
    organizationSwitching.value = false
  }
}

async function loadAll(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [o, orgs, configs, demo] = await Promise.all([
      api.platformOverview(), api.organizations(), api.modelConfigs(),
      showcaseEnabled ? api.productionFlowShowcase() : Promise.resolve({}),
    ])
    overview.value = o
    organizations.value = orgs
    modelConfigs.value = configs
    showcase.value = demo
    const requestedId = organizationIdFromLocation()
    const rememberedId = localStorage.getItem('jianghu.activeOrganizationId') ?? ''
    const selectedOrganization = orgs.find(item => item.id === requestedId)
      ?? orgs.find(item => item.id === rememberedId)
      ?? orgs[0]
    if (selectedOrganization?.id) {
      activeOrganizationId.value = String(selectedOrganization.id)
      rememberOrganization(activeOrganizationId.value, true)
      await loadOrganizationContext(activeOrganizationId.value)
    } else {
      knowledgeSources.value = []
    }
    try {
      openClawStatus.value = await api.openClawStatus()
    } catch (cause) {
      openClawStatus.value = { available: false, mode: 'unavailable', error: '执行底座健康检查失败' }
    }
    const selected = configs.find(item => item.id === modelForm.value.id)
      ?? configs.find(item => item.active)
      ?? configs[0]
    if (selected) selectModel(selected)
    else beginNewModel()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '平台数据加载失败'
  } finally {
    loading.value = false
  }
}

function handleRealmPopState(): void {
  const requestedId = organizationIdFromLocation()
  if (requestedId && requestedId !== activeOrganizationId.value) void switchOrganization(requestedId, true)
}

async function assessTask(): Promise<void> {
  if (!taskForm.value.title.trim() || !taskForm.value.description.trim()) return
  busy.value = true
  error.value = ''
  notice.value = ''
  lastTeamResolution.value = null
  setTeamProposal(null)
  try {
    const result = await api.assessCommission(taskForm.value.title.trim(), taskForm.value.description.trim(), organization.value?.id)
    currentTask.value = (result.commission ?? result.company_task) as Json
    selectedAssessmentTeams.value = []
    teamResolutionLoading.value = true
    try {
      const resolved = await api.resolveCommissionTeam(String(currentTask.value.id), false)
      applyTeamProposal(resolved)
    } catch (cause) {
      error.value = cause instanceof Error
        ? `需求已经保存，但团队建议生成失败：${cause.message}`
        : '需求已经保存，但团队建议生成失败；可以在下方直接重试。'
    } finally {
      teamResolutionLoading.value = false
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '团队评估失败'
  } finally {
    busy.value = false
  }
}

function setTeamProposal(proposal: Json | null): void {
  teamProposal.value = proposal
  if (!proposal) {
    teamProposalDraft.value = { name: '', purpose: '', operating_mode: 'collaborative', members: [], member_ids: [] }
    return
  }
  const members = (proposal.members ?? []).map((member: Json, index: number) => ({
    ...member,
    member_role: index === 0 ? 'leader' : 'member',
    responsibility: member.responsibility ?? '',
  }))
  teamProposalDraft.value = {
    name: proposal.name ?? '',
    purpose: proposal.purpose ?? '',
    operating_mode: proposal.operating_mode ?? 'collaborative',
    members,
    member_ids: members.map((member: Json) => member.agent_id),
  }
}

function applyTeamProposal(result: Json): void {
  currentTask.value = result.company_task as Json
  const resolution = result.team_resolution as Json
  setTeamProposal(result.team_proposal as Json)
  const mode = resolution.mode === 'reuse' ? '已形成复用建议' : '已形成新团队草案'
  const gaps = (resolution.missing_capabilities ?? []).length
    ? `；仍需留意缺口：${resolution.missing_capabilities.join('、')}`
    : ''
  notice.value = `${mode}“${teamProposal.value?.name ?? ''}”：${resolution.reason}${gaps}。尚未创建或选定，等待你确认。`
}

async function resolveTaskTeam(forceCreate = false): Promise<void> {
  if (!currentTask.value?.id) return
  teamResolutionLoading.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await api.resolveCommissionTeam(String(currentTask.value.id), forceCreate)
    applyTeamProposal(result)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '团队建议生成失败；原委托和已有评估仍然保留'
  } finally {
    teamResolutionLoading.value = false
  }
}

async function confirmTeamProposal(): Promise<void> {
  if (!currentTask.value?.id || !teamProposal.value?.id) return
  const selectedMembers = (teamProposalDraft.value.members ?? [])
    .filter((member: Json) => teamProposalDraft.value.member_ids.includes(member.agent_id))
    .map((member: Json, index: number) => ({
      agent_id: member.agent_id,
      member_role: index === 0 ? 'leader' : 'member',
      responsibility: member.responsibility,
    }))
  if (teamProposal.value.decision === 'create' && !selectedMembers.length) {
    error.value = '新团队至少需要选择一位江湖人物。'
    return
  }
  teamProposalSaving.value = true
  error.value = ''
  try {
    const result = await api.confirmCommissionTeamProposal(currentTask.value.id, teamProposal.value.id, {
      name: teamProposalDraft.value.name,
      purpose: teamProposalDraft.value.purpose,
      operating_mode: teamProposalDraft.value.operating_mode,
      members: selectedMembers,
    }) as Json
    currentTask.value = result.company_task as Json
    lastTeamResolution.value = result.team_resolution as Json
    selectedAssessmentTeams.value = [...(currentTask.value.selected_team_ids ?? [])]
    ;[teams.value, commissions.value] = await Promise.all([api.teams(organization.value?.id), api.commissions(organization.value?.id)])
    const confirmedTeam = result.team as Json
    notice.value = teamProposal.value.decision === 'reuse'
      ? `已确认复用“${confirmedTeam.name}”，现在可以基于该团队生成生产流。`
      : `已按你的确认创建“${confirmedTeam.name}”，现在可以基于该团队生成生产流。`
    setTeamProposal(null)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '团队建议确认失败'
  } finally {
    teamProposalSaving.value = false
  }
}

async function rejectTeamProposal(): Promise<void> {
  if (!currentTask.value?.id || !teamProposal.value?.id) return
  teamProposalSaving.value = true
  error.value = ''
  try {
    const result = await api.rejectCommissionTeamProposal(currentTask.value.id, teamProposal.value.id) as Json
    currentTask.value = result.company_task as Json
    setTeamProposal(null)
    notice.value = '已放弃本次团队建议，没有创建团队，也没有改变当前委托已选团队。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '放弃团队建议失败'
  } finally {
    teamProposalSaving.value = false
  }
}

async function hireRecommended(spec: Json, assessment: Json): Promise<void> {
  if (!currentTask.value?.id) return
  busy.value = true
  recommendationLoading.value = String(spec.role ?? '')
  error.value = ''
  notice.value = ''
  try {
    const requirement = `${spec.role ?? '专业人员'}。职责：${spec.purpose ?? ''}。需要能力：${(spec.capabilities ?? []).join('、')}`
    const result = await api.generateAgent(requirement, organization.value?.id, String(spec.role ?? ''), spec.capabilities ?? [])
    const created = result.agent as Json
    highlightedAgentId.value = created.id
    agents.value = await api.platformAgents(currentOrganizationId.value)
    let targetTeamId = String(assessment.team_id ?? '')
    if (targetTeamId) {
      await api.addTeamMember(targetTeamId, created.id, String(spec.purpose ?? created.description ?? ''))
    }
    teams.value = await api.teams(organization.value?.id)
    const reassessed = await api.assessCommission(
      String(currentTask.value.title), String(currentTask.value.description), organization.value?.id, String(currentTask.value.id),
    )
    currentTask.value = (reassessed.commission ?? reassessed.company_task) as Json
    commissions.value = await api.commissions(organization.value?.id)
    selectedAssessmentTeams.value = [...(currentTask.value.selected_team_ids ?? [])]
    const proposed = await api.resolveCommissionTeam(String(currentTask.value.id), false)
    applyTeamProposal(proposed)
    const teamName = targetTeamId ? teamById.value[targetTeamId]?.name : ''
    const reused = (result.generation as Json | undefined)?.mode === 'reused'
    notice.value = targetTeamId
      ? `${reused ? '已复用' : '已创建'}人物“${created.name}（${created.role}）”，已加入“${teamName}”；新的团队建议等待你确认。`
      : `${reused ? '已复用' : '已创建'}人物“${created.name}（${created.role}）”；平台只生成了组队草案，确认前不会创建团队。`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '人物引入与重新评估失败；原委托仍已保留，可直接重试'
  } finally {
    busy.value = false
    recommendationLoading.value = ''
  }
}

async function generateAgent(): Promise<void> {
  if (!agentRequirement.value.trim()) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await api.generateAgent(agentRequirement.value.trim(), organization.value?.id)
    const created = result.agent as Json
    highlightedAgentId.value = created.id
    notice.value = (result.generation as Json | undefined)?.mode === 'reused'
      ? `没有重复创建：人物册中已有“${created.name}（${created.role}）”。`
      : `人物“${created.name}（${created.role}）”已创建并保存。`
    agents.value = await api.platformAgents(currentOrganizationId.value)
    agentRequirement.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Agent 生成失败'
  } finally {
    busy.value = false
  }
}

async function generateOrganization(): Promise<void> {
  if (!organizationForm.value.intent.trim()) return
  organizationCreating.value = true
  error.value = ''
  try {
    const result = await api.generateOrganization({
      ...organizationForm.value,
      organization_id: organization.value?.id,
      knowledge_source_ids: organizationForm.value.source_type === 'knowledge'
        ? knowledgeSources.value.filter(source => {
          const metadata = source.metadata ?? {}
          return String(metadata.organization_id ?? '') === currentOrganizationId.value
            || (metadata.scope_type === 'organization' && String(metadata.scope_id ?? '') === currentOrganizationId.value)
        }).map(source => source.id)
        : [],
    }) as Json
    if (result.organization) {
      organizations.value = await api.organizations()
      await switchOrganization(String(result.organization.id))
      notice.value = `已创建大江湖“${result.organization.name}”；后续可在其中继续生成小江湖和人物。`
    } else if (result.team) {
      teams.value = await api.teams(organization.value?.id)
      agents.value = await api.platformAgents(currentOrganizationId.value)
      notice.value = `已创建小江湖“${result.team.name}”，并自动生成 ${result.team.members?.length ?? 0} 位随组织行动的人物。`
    }
    organizationForm.value.intent = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '组织生成失败'
  } finally {
    organizationCreating.value = false
  }
}

function openOrganizationEditor(): void {
  if (!organization.value) return
  editingOrganization.value = organization.value
  organizationDraft.value = {
    name: String(organization.value.name ?? ''),
    description: String(organization.value.description ?? ''),
  }
}

async function saveOrganization(): Promise<void> {
  if (!editingOrganization.value || !organizationDraft.value.name.trim()) return
  organizationSaving.value = true
  error.value = ''
  try {
    const result = await api.updateOrganization(editingOrganization.value.id, organizationDraft.value) as Json
    organizations.value = await api.organizations()
    editingOrganization.value = null
    notice.value = `大江湖“${(result.organization as Json).name}”已更新。`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '组织保存失败'
  } finally {
    organizationSaving.value = false
  }
}

function openTeamEditor(team: Json): void {
  editingTeam.value = team
  teamEditDraft.value = {
    name: String(team.name ?? ''),
    purpose: String(team.purpose ?? ''),
    operating_mode: String(team.operating_mode ?? 'collaborative'),
  }
}

async function saveTeamEdit(): Promise<void> {
  if (!editingTeam.value || !teamEditDraft.value.name.trim()) return
  teamEditingSaving.value = true
  error.value = ''
  try {
    const result = await api.updateTeam(editingTeam.value.id, teamEditDraft.value) as Json
    teams.value = await api.teams(organization.value?.id)
    editingTeam.value = null
    notice.value = `小江湖“${(result.team as Json).name}”已更新，后续新生产流将使用新的组织契约。`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '小江湖保存失败'
  } finally {
    teamEditingSaving.value = false
  }
}

async function createTeam(): Promise<void> {
  if (!teamForm.value.name.trim() || !teamForm.value.member_ids.length) return
  busy.value = true
  error.value = ''
  try {
    await api.createTeam({
      organization_id: organization.value?.id,
      name: teamForm.value.name,
      purpose: teamForm.value.purpose,
      operating_mode: teamForm.value.operating_mode,
      knowledge_paths: [],
      members: teamForm.value.member_ids.map((agentId, index) => ({
        agent_id: agentId,
        member_role: index === 0 ? 'leader' : 'member',
        responsibility: agents.value.find(agent => agent.id === agentId)?.description ?? '',
      })),
    })
    teams.value = await api.teams(organization.value?.id)
    teamForm.value = { name: '', purpose: '', operating_mode: 'collaborative', member_ids: [] }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '团队创建失败'
  } finally {
    busy.value = false
  }
}

function availableTeamAgents(team: Json): Json[] {
  const memberIds = new Set((team.members ?? []).map((member: Json) => String(member.id)))
  return agents.value.filter(agent => !memberIds.has(String(agent.id)))
}

async function inviteAgentToTeam(team: Json): Promise<void> {
  const agentId = String(teamInviteDraft.value[team.id] ?? '')
  if (!agentId) return
  const person = agents.value.find(agent => String(agent.id) === agentId)
  if (!person) return
  teamInviteLoading.value = team.id
  error.value = ''
  try {
    await api.addTeamMember(team.id, agentId, String(person.description ?? '承担本团队的专业职责'))
    teams.value = await api.teams(organization.value?.id)
    teamInviteDraft.value = { ...teamInviteDraft.value, [team.id]: '' }
    notice.value = `已邀请“${person.name}”加入“${team.name}”，后续生产流可以使用这位同行者。`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '邀请同行者失败'
  } finally {
    teamInviteLoading.value = ''
  }
}

async function confirmDisbandTeam(): Promise<void> {
  if (!teamToDisband.value) return
  const disbanding = teamToDisband.value
  disbandingTeamId.value = disbanding.id
  error.value = ''
  try {
    const result = await api.disbandTeam(disbanding.id)
    const references = Number(result.workflow_reference_count ?? 0)
    notice.value = references
      ? `组织“${disbanding.name}”已解散。${references} 个历史流程仍保留该组织快照，不受影响。`
      : `组织“${disbanding.name}”已解散并从当前江湖移除。`
    teams.value = await api.teams(organization.value?.id)
    teamToDisband.value = null
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '组织解散失败'
  } finally { disbandingTeamId.value = '' }
}

async function confirmDeleteWorkflow(): Promise<void> {
  if (!workflowToDelete.value) return
  const deleting = workflowToDelete.value
  workflowDeletingId.value = deleting.id
  error.value = ''
  try {
    const result = await api.deleteWorkflow(deleting.id) as Json
    workflows.value = await api.platformWorkflows(currentOrganizationId.value)
    workflowToDelete.value = null
    notice.value = result.deletion?.message ?? `生产流“${deleting.name}”已归档。`
  } catch (cause) {
    error.value = cause instanceof Error
      ? (cause.message === 'workflow_has_active_runs' ? '该生产流仍有未结束的运行现场，请先结束或取消后再删除。' : cause.message)
      : '生产流删除失败'
  } finally {
    workflowDeletingId.value = ''
  }
}

async function generateFlow(): Promise<void> {
  if (!currentTask.value?.id || !selectedAssessmentTeams.value.length) return
  busy.value = true
  error.value = ''
  try {
    const result = await api.generateTeamWorkflow(currentTask.value.id, selectedAssessmentTeams.value)
    currentTask.value = (result.company_task ?? currentTask.value) as Json
    commissions.value = await api.commissions(organization.value?.id)
    workflows.value = await api.platformWorkflows(currentOrganizationId.value)
    const decision = result.workflow_decision as Json | undefined
    const labels: Record<string, string> = { reuse: '已复用现有生产流', revise: '已在原生产流家族中生成新版本', create: '已新建生产流' }
    notice.value = `${labels[String(decision?.mode)] ?? '生产流已准备完成'}：${decision?.reason ?? ''}`
    const flow = result.workflow as Json
    if (flow?.family_id) selectedWorkflowVersions.value[String(flow.family_id)] = String(flow.id)
    go('flows')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '团队生产流生成失败'
  } finally {
    busy.value = false
  }
}

async function startWorkflow(flow: Json): Promise<void> {
  const commission = commissions.value.find(item => item.workflow_id === flow.id)
    ?? (currentTask.value?.id ? currentTask.value : null)
  if (!commission) {
    error.value = '请先在江湖总览发布具体委托，再用这套生产流执行。'
    return
  }
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const task = `${commission.title}\n\n${commission.description}`
    const created = await api.createPlatformRun(flow.id, task, undefined, 'project_jianghu', commission.id)
    const run = created.run as Json
    await api.startPlatformRun(run.id, currentOrganizationId.value)
    currentTask.value = (created.commission ?? commission) as Json
    runs.value = await api.platformRuns(currentOrganizationId.value)
    await openRun(run.id)
    beginRunPolling(run.id)
    notice.value = `真实执行已启动：${run.id}。人物行动、节点状态、事件与正式产物会持续出现在下方。`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '真实执行启动失败'
  } finally {
    busy.value = false
  }
}

async function startExistingRun(run: Json): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    await api.startPlatformRun(run.id, currentOrganizationId.value)
    await openRun(run.id)
    beginRunPolling(run.id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '事件启动失败'
  } finally { busy.value = false }
}

async function cancelActiveRun(): Promise<void> {
  if (!activeRun.value || !['running', 'pause_requested', 'paused'].includes(String(activeRun.value.status))) return
  busy.value = true
  error.value = ''
  try {
    const result = await api.cancelPlatformRun(activeRun.value.id, currentOrganizationId.value)
    activeRun.value = result.run as Json
    stopRunPolling()
    runs.value = await api.platformRuns(currentOrganizationId.value)
    notice.value = '本次真实执行已取消；已经形成的事件和产物仍然保留。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '取消执行失败'
  } finally { busy.value = false }
}

async function pauseActiveRun(): Promise<void> {
  if (!activeRun.value || activeRun.value.status !== 'running') return
  busy.value = true
  error.value = ''
  try {
    const result = await api.pausePlatformRun(activeRun.value.id, currentOrganizationId.value)
    activeRun.value = result.run as Json
    beginRunPolling(activeRun.value.id)
    notice.value = '停手请求已发出：正在进行的模型回合会完成，下一个受控边界不会继续。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '暂停现场失败'
  } finally { busy.value = false }
}

async function resumeActiveRun(): Promise<void> {
  if (!activeRun.value || !['pause_requested', 'paused'].includes(String(activeRun.value.status))) return
  busy.value = true
  error.value = ''
  try {
    const result = await api.resumePlatformRun(activeRun.value.id, currentOrganizationId.value)
    activeRun.value = result.run as Json
    beginRunPolling(activeRun.value.id)
    notice.value = '现场已经恢复，人物会沿用原 Run 和已有产物继续行动。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '恢复现场失败'
  } finally { busy.value = false }
}

async function submitRunIntervention(): Promise<void> {
  if (!activeRun.value || !selectedSceneTask.value || !interventionForm.value.content.trim()) return
  interventionSaving.value = true
  error.value = ''
  try {
    const payload: Json = {
      kind: interventionForm.value.kind,
      content: interventionForm.value.content.trim(),
      task_id: selectedSceneTask.value.id,
      agent_id: interventionForm.value.agent_id || undefined,
    }
    const result = await api.intervenePlatformRun(activeRun.value.id, payload, currentOrganizationId.value)
    activeRun.value = result.run as Json
    interventionForm.value.content = ''
    notice.value = payload.kind === 'require_rework'
      ? '返工意见已进入现场；平台会在受控边界回到该节点并重跑下游。'
      : '补充意见已进入节点公共卷宗，并会注入后续相关人物回合。'
    if (['running', 'pause_requested', 'paused'].includes(String(activeRun.value.status))) beginRunPolling(activeRun.value.id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '现场介入失败'
  } finally { interventionSaving.value = false }
}

async function retryActiveRun(fromTask?: Json): Promise<void> {
  if (!activeRun.value || !['failed', 'cancelled', 'budget_exhausted', 'revision_exhausted'].includes(String(activeRun.value.status))) return
  busy.value = true
  error.value = ''
  try {
    const sourceRunId = activeRun.value.id
    const result = await api.retryPlatformRun(sourceRunId, fromTask?.id, currentOrganizationId.value)
    const run = result.run as Json
    const retryInfo = result.retry as Json | undefined
    runs.value = await api.platformRuns(currentOrganizationId.value)
    await openRun(run.id)
    beginRunPolling(run.id)
    notice.value = fromTask
      ? `已在同一事件现场建立第 ${retryInfo?.run_version ?? run.run_version ?? 2} 版定向重试；已完成且不受影响的上游节点及产物会直接保留。`
      : `已在同一事件现场建立第 ${retryInfo?.run_version ?? run.run_version ?? 2} 版完整重试；历史版本和失败证据保持不变。`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '创建重试执行失败'
  } finally { busy.value = false }
}

async function extendActiveRun(): Promise<void> {
  if (!activeRun.value || !runTimeLimitExhausted.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await api.extendPlatformRun(activeRun.value.id, extensionMinutes.value, currentOrganizationId.value)
    activeRun.value = result.run as Json
    const extension = result.extension as Json | undefined
    runs.value = await api.platformRuns(currentOrganizationId.value)
    beginRunPolling(activeRun.value.id)
    notice.value = `已增加 ${extension?.minutes ?? extensionMinutes.value} 分钟运行时限；已完成节点和产物保留，现场继续执行未完成节点。`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '延长运行时限失败'
  } finally { busy.value = false }
}

function editWorkflow(flow: Json, nodeKey = ''): void {
  editingWorkflow.value = flow
  workflowDraft.value = {
    name: flow.name,
    description: flow.description,
    nodes: (flow.definition?.nodes ?? []).map((node: Json) => ({
      ...node,
      participant_agent_ids: [...(node.participant_agent_ids ?? (teamById.value[node.team_id]?.members ?? []).map((member: Json) => member.id))],
      depends_on: (flow.definition?.edges ?? []).filter((edge: string[]) => edge[1] === node.key).map((edge: string[]) => edge[0]),
    })),
    edges: (flow.definition?.edges ?? []).map((edge: string[]) => [...edge]),
    policies: { ...(flow.definition?.policies ?? {}) },
    inputs: [...(flow.definition?.inputs ?? [])],
    outputs: [...(flow.definition?.outputs ?? [])],
    schema_version: flow.definition?.schema_version ?? '2.0-team',
  }
  selectedWorkflowNodeKey.value = nodeKey || workflowDraft.value.nodes?.[0]?.key || ''
  workflowZoom.value = 1
  showAllWorkflowEdges.value = false
}

function addWorkflowNode(): void {
  const team = teams.value[0]
  if (!team) return
  const index = workflowDraft.value.nodes.length + 1
  const leader = team.members.find((member: Json) => member.member_role === 'leader') ?? team.members[0]
  const node = { key: `node_${Date.now()}`, name: `新增步骤 ${index}`, purpose: '填写这个步骤要交付的正式产物', type: 'team_task', communication_rounds: 1, team_id: team.id, team_name: team.name, agent_id: leader.id, agent_role: leader.role, participant_agent_ids: [leader.id], depends_on: [] }
  workflowDraft.value.nodes.push(node)
  selectedWorkflowNodeKey.value = node.key
}

function removeWorkflowNode(nodeKey: string): void {
  workflowDraft.value.nodes = workflowDraft.value.nodes
    .filter((node: Json) => node.key !== nodeKey)
    .map((node: Json) => ({ ...node, depends_on: (node.depends_on ?? []).filter((key: string) => key !== nodeKey) }))
  selectedWorkflowNodeKey.value = workflowDraft.value.nodes?.[0]?.key ?? ''
}

function syncNodeTeam(node: Json): void {
  const team = teamById.value[node.team_id]
  if (!team) return
  const leader = team.members.find((member: Json) => member.member_role === 'leader') ?? team.members[0]
  node.team_name = team.name
  node.agent_id = leader.id
  node.agent_role = leader.role
  node.participant_agent_ids = [leader.id]
}

async function saveWorkflowRevision(): Promise<void> {
  if (!editingWorkflow.value) return
  busy.value = true
  error.value = ''
  try {
    const nodes = workflowDraft.value.nodes
    const validKeys = new Set(nodes.map((node: Json) => node.key))
    const edges = nodes.flatMap((node: Json) => (node.depends_on ?? []).filter((key: string) => validKeys.has(key) && key !== node.key).map((key: string) => [key, node.key]))
    const normalizedNodes = nodes.map((node: Json) => {
      const { depends_on: _dependsOn, ...definitionNode } = node
      if (definitionNode.type === 'judge') {
        definitionNode.participant_agent_ids = [definitionNode.agent_id]
        definitionNode.communication_rounds = 0
      } else {
        definitionNode.communication_rounds = Math.max(1, Math.min(3, Number(definitionNode.communication_rounds ?? 1)))
      }
      return definitionNode
    })
    const result = await api.reviseWorkflow(editingWorkflow.value.id, {
      name: workflowDraft.value.name,
      description: workflowDraft.value.description,
      definition: { ...workflowDraft.value, nodes: normalizedNodes, edges },
    })
    notice.value = `已创建新的流程版本 ${(result.workflow as Json).version}，历史版本保持不变。`
    workflows.value = await api.platformWorkflows(currentOrganizationId.value)
    selectedWorkflowVersions.value[(result.workflow as Json).family_id] = (result.workflow as Json).id
    editingWorkflow.value = null
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '流程版本保存失败'
  } finally { busy.value = false }
}

function selectModel(config: Json): void {
  modelForm.value = { id: config.id, name: config.name, provider: config.provider, base_url: config.base_url, model: config.model, tier: config.tier ?? 'medium', token: '', token_hint: config.token_hint ?? '', active: Boolean(config.active) }
  modelMessage.value = ''
}

function beginNewModel(): void {
  modelForm.value = { id: '', name: '', provider: 'openai-responses', base_url: '', model: '', tier: 'medium', token: '', token_hint: '', active: true }
  modelMessage.value = '正在新建模型配置；保存后原有配置仍会保留。'
}

async function testModel(): Promise<void> {
  busy.value = true
  try {
    await api.testModelConfig(modelForm.value.id && !modelForm.value.token ? { id: modelForm.value.id } : modelForm.value)
    modelMessage.value = '真实连接测试成功'
  } catch (cause) {
    modelMessage.value = cause instanceof Error ? cause.message : '连接测试失败'
  } finally { busy.value = false }
}

async function saveModel(): Promise<void> {
  busy.value = true
  try {
    const saved = await api.saveModelConfig({ ...modelForm.value, id: modelForm.value.id || undefined, token: modelForm.value.token || undefined })
    modelConfigs.value = await api.modelConfigs()
    const config = saved.config as Json
    const refreshed = modelConfigs.value.find(item => item.id === config?.id) ?? config
    if (refreshed) selectModel(refreshed)
    modelMessage.value = '模型配置已安全保存'
  } catch (cause) {
    modelMessage.value = cause instanceof Error ? cause.message : '保存失败'
  } finally { busy.value = false }
}

async function deleteModel(config: Json): Promise<void> {
  if (!config?.id || modelDeletingId.value) return
  const warning = config.active
    ? `“${config.name}”当前处于启用状态。删除后，同档位最近更新的配置会自动接替；确认删除吗？`
    : `确认删除模型配置“${config.name}”吗？`
  if (!window.confirm(warning)) return
  modelDeletingId.value = String(config.id)
  try {
    await api.deleteModelConfig(String(config.id))
    modelConfigs.value = await api.modelConfigs()
    const next = modelConfigs.value.find(item => item.active) ?? modelConfigs.value[0]
    if (next) selectModel(next)
    else beginNewModel()
    modelMessage.value = '模型配置已删除'
  } catch (cause) {
    modelMessage.value = cause instanceof Error ? cause.message : '删除失败'
  } finally {
    modelDeletingId.value = ''
  }
}

onMounted(() => {
  document.addEventListener('fullscreenchange', syncFullscreenTarget)
  window.addEventListener('popstate', handleRealmPopState)
  loadAll()
})
onUnmounted(() => {
  stopRunPolling()
  stopShowcasePolling()
  document.removeEventListener('fullscreenchange', syncFullscreenTarget)
  window.removeEventListener('popstate', handleRealmPopState)
})
</script>

<template>
  <div class="jh-shell">
    <aside class="jh-sidebar">
      <button class="jh-brand" @click="go('jianghu')"><span>江</span><div><strong>江湖 Online</strong><small>LIVING AGENT SOCIETY</small></div></button>
      <nav>
        <button :class="{ active: screen === 'jianghu' }" @click="go('jianghu')"><Compass />江湖总览</button>
        <button :class="{ active: screen === 'teams' }" @click="go('teams')"><Users />组织与队伍</button>
        <button :class="{ active: screen === 'agents' }" @click="go('agents')"><Bot />江湖人物</button>
        <button :class="{ active: screen === 'flows' }" @click="go('flows')"><Workflow />行事章法</button>
        <button v-if="showcaseEnabled" :class="{ active: screen === 'showcase' }" @click="go('showcase')"><Zap />实战擂台</button>
        <button :class="{ active: screen === 'runs' }" @click="go('runs')"><Play />事件现场</button>
      </nav>
      <button class="sidebar-setting" @click="go('settings')"><Settings2 />模型与凭据</button>
    </aside>

    <div class="jh-main">
      <header class="jh-topbar">
        <div class="realm-switcher">
          <span>当前大江湖</span>
          <select v-model="activeOrganizationId" :disabled="organizationSwitching" aria-label="切换大江湖" @change="switchOrganization(activeOrganizationId)">
            <option v-for="realm in organizations" :key="realm.id" :value="realm.id">{{ realm.name }}</option>
          </select>
          <small>{{ organization?.user_identity ?? '发起人' }} · {{ teams.length }} 个小江湖 · {{ agents.length }} 位人物</small>
        </div>
        <button title="刷新当前大江湖数据" :disabled="loading || organizationSwitching" @click="loadAll"><LoaderCircle v-if="organizationSwitching" class="spin" /><RefreshCw v-else /></button>
      </header>
      <div v-if="error" class="jh-error"><XCircle /><span>{{ error }}</span><button @click="error = ''">关闭</button></div>
      <div v-if="notice" class="jh-notice"><Sparkles /><span>{{ notice }}</span><button @click="notice = ''">知道了</button></div>
      <div v-if="loading" class="jh-loading"><LoaderCircle class="spin" />正在读取江湖状态</div>

      <main v-else-if="screen === 'jianghu'" class="jh-page company-page">
        <section class="company-hero">
          <div class="hero-copy"><span>{{ organizationName }} · 江湖事件入口</span><h1>今天想在这个大江湖中促成什么事？</h1><p>你可以是任何身份。当前大江湖中的组织会根据使命、能力与立场自主判断是否承接；切换大江湖后，人物、知识、生产流和事件现场也会一并切换。</p><div class="company-stats"><article><b>{{ currentRealmOverview.teams }}</b><span>小江湖</span></article><article><b>{{ currentRealmOverview.agents }}</b><span>江湖人物</span></article><article><b>{{ currentRealmOverview.workflows }}</b><span>行事章法</span></article></div></div>
          <div class="company-map">
            <div class="map-cloud cloud-one"></div><div class="map-cloud cloud-two"></div>
            <div class="map-road road-a"></div><div class="map-road road-b"></div>
            <div class="map-building boss-building"><i>🏯</i><strong>你的落脚处</strong><small>{{ organization?.user_identity ?? '发起人' }}</small></div>
            <div v-for="(team, index) in teams.slice(0, 3)" :key="team.id" class="map-building team-building" :class="`lot-${index + 1}`"><i>{{ ['🏘️','⛩️','🛡️'][index % 3] }}</i><strong>{{ team.name }}</strong><small>{{ team.members.length }} 名成员</small></div>
            <button class="empty-lot" @click="go('teams')"><Plus /><strong>{{ teams.length ? '建立新组织' : '建立第一个组织' }}</strong><small>已有组织不影响继续组建新的队伍</small></button>
          </div>
        </section>
        <section class="boss-command"><label>委托或事件名称<input v-model="taskForm.title" placeholder="例如：开发产品、组织公益行动、调解争端或完成研究" /></label><label>事情说明<textarea v-model="taskForm.description" placeholder="说明目标、期望结果、约束、相关角色和你愿意提供的知识。江湖中的组织会先判断是否适合承接。"></textarea></label><button class="jh-primary" :disabled="busy || !taskForm.title.trim() || !taskForm.description.trim()" @click="assessTask"><LoaderCircle v-if="busy" class="spin" /><Sparkles v-else />发布需求并获得团队建议</button></section>

        <section v-if="currentTask" class="assessment-board"><header><div><span>江湖响应议事堂 · 委托已保存</span><h2>{{ currentTask.title }}</h2><small>{{ currentTask.id }} · 先确定执行团队，再依据团队生成生产流</small></div><strong :data-status="currentTask.selected_team_ids?.length ? 'team_ready' : currentTask.status">{{ currentTask.selected_team_ids?.length ? '执行团队已确定' : (currentTask.status === 'team_ready' ? '存在可复用团队' : '需要按需求重新组队') }}</strong></header>
          <section v-if="currentTask.selected_team_ids?.length" class="team-resolution-strip"><div><Users /><span><strong>{{ lastTeamResolution?.mode === 'create' ? '平台已根据需求新组建执行团队' : '本委托已确定执行团队' }}</strong><small>{{ lastTeamResolution?.reason || '平台会把需求与这些团队一起用于生产流复用、优化或新建判断。' }}</small></span></div><b v-for="teamId in currentTask.selected_team_ids" :key="teamId">{{ teamById[teamId]?.name ?? teamId }}</b></section>
          <section v-if="teamProposal" class="team-proposal-card">
            <header><div><Users /><span><small>待你确认 · 当前没有创建或切换团队</small><h3>{{ teamProposal.decision === 'reuse' ? '建议复用已有团队' : '建议组建一支新团队' }}</h3></span></div><b>{{ teamProposal.fit_score }} 分</b></header>
            <p>{{ teamProposal.reason }}</p>
            <div v-if="teamProposal.missing_capabilities?.length" class="gap-list"><span v-for="gap in teamProposal.missing_capabilities" :key="gap">仍有缺口：{{ gap }}</span></div>
            <div v-if="teamProposal.decision === 'create'" class="team-proposal-editor">
              <label>团队名称<input v-model="teamProposalDraft.name" /></label>
              <label>共同使命<textarea v-model="teamProposalDraft.purpose"></textarea></label>
              <label>协作方式<select v-model="teamProposalDraft.operating_mode"><option value="collaborative">同心协作</option><option value="debate">议事争辩</option><option value="red_team">攻守对抗</option><option value="hierarchical">统领协作</option></select></label>
              <section class="proposal-members"><strong>拟到场人物，可在确认前调整</strong><label v-for="member in teamProposalDraft.members" :key="member.agent_id" :class="{ selected: teamProposalDraft.member_ids.includes(member.agent_id) }"><input v-model="teamProposalDraft.member_ids" type="checkbox" :value="member.agent_id" /><i>{{ initials(agentById[member.agent_id]?.name ?? '人') }}</i><span><b>{{ agentById[member.agent_id]?.name ?? member.agent_id }}</b><small>{{ agentById[member.agent_id]?.role ?? '江湖人物' }}</small><input v-model="member.responsibility" placeholder="在本团队中的职责" /></span></label></section>
            </div>
            <div v-else class="team-proposal-reuse"><strong>{{ teamProposalDraft.name }}</strong><span>{{ teamProposalDraft.purpose }}</span><small>{{ teamProposalDraft.members.map((member: Json) => agentById[member.agent_id]?.name ?? member.agent_id).join('、') }}</small></div>
            <footer><button class="jh-secondary" :disabled="teamProposalSaving" @click="rejectTeamProposal">放弃建议</button><button class="jh-primary" :disabled="teamProposalSaving || (teamProposal.decision === 'create' && !teamProposalDraft.member_ids.length)" @click="confirmTeamProposal"><LoaderCircle v-if="teamProposalSaving" class="spin" />{{ teamProposal.decision === 'reuse' ? '确认选用此团队' : '确认后创建团队' }}</button></footer>
          </section>
          <div class="assessment-list"><article v-for="assessment in currentTask.assessments" :key="assessment.id" class="assessment-card" :class="{ selected: selectedAssessmentTeams.includes(assessment.team_id) }" :data-fit="assessment.fit_status"><div class="score"><b>{{ assessment.fit_score }}</b><span>适配分</span></div><div class="assessment-main"><h3>{{ assessment.team_id ? teamById[assessment.team_id]?.name : '当前江湖没有可响应的组织' }}</h3><p>{{ assessment.reasoning }}</p><div v-if="assessment.missing_capabilities?.length" class="gap-list"><span v-for="gap in assessment.missing_capabilities" :key="gap">缺口：{{ gap }}</span></div><div v-if="assessment.recommended_agents?.length" class="hire-list"><div v-for="(spec, index) in assessment.recommended_agents" :key="index"><div><strong>建议引入：{{ spec.role }}</strong><small>{{ spec.purpose }}</small></div><button :disabled="busy || teamResolutionLoading" @click="hireRecommended(spec, assessment)"><LoaderCircle v-if="recommendationLoading === spec.role" class="spin" /><Plus v-else />{{ recommendationLoading === spec.role ? '正在创建、入队并重评…' : '引入并重新评估' }}</button></div></div></div><label v-if="assessment.team_id" class="team-pick"><input v-model="selectedAssessmentTeams" type="checkbox" :value="assessment.team_id" />手工选用</label></article></div>
          <footer><button class="jh-secondary team-resolve-action" :disabled="busy || teamResolutionLoading || teamProposalSaving" @click="resolveTaskTeam(false)"><LoaderCircle v-if="teamResolutionLoading" class="spin" /><Users v-else />{{ teamResolutionLoading ? '正在比较并形成建议…' : '重新生成团队建议' }}</button><button class="jh-secondary force-team-action" :disabled="busy || teamResolutionLoading || teamProposalSaving" @click="resolveTaskTeam(true)"><Plus />生成全新组队建议</button><button v-if="currentTask.status === 'needs_hiring'" class="jh-secondary" @click="go('agents')"><Bot />补充新人物</button><button class="jh-primary" :disabled="busy || teamResolutionLoading || !selectedAssessmentTeams.length" @click="generateFlow"><Network />用已确认团队生成生产流</button></footer>
        </section>
      </main>

      <main v-else-if="screen === 'teams'" class="jh-page team-world"><section class="page-heading team-heading"><div><span>大小江湖组织图谱</span><h1>{{ organizationName }}的大江湖与小江湖</h1><p>大江湖保存共同知识、规则和人物资源；其下每个小江湖都能独立承接事情，也能继承当前大江湖获准的公共知识。</p></div><div class="team-summary"><b>{{ organizations.length }}</b><span>个可切换大江湖</span><i>·</i><b>{{ teams.length }}</b><span>个活跃小江湖</span><i>·</i><b>{{ agents.length }}</b><span>位人物</span></div></section>
        <section class="organization-forge">
          <header><div><span>组织生成器</span><h2>一句话立下一个江湖</h2><p>组织先确定共同使命，再由组织内部生成人物；人物跟随组织，不把权力误当成数据权限。</p></div><b>意图 / 知识库 → 组织 → 人物</b></header>
          <div class="organization-forge-form">
            <section class="organization-forge-step"><header><b>1</b><div><strong>先选生成依据</strong><small>组织要从什么出发？</small></div></header><div class="organization-choice-grid"><button type="button" :class="{ selected: organizationForm.source_type === 'intent' }" @click="organizationForm.source_type = 'intent'"><span>✦</span><div><strong>一句话意图</strong><small>用目标、使命或愿景直接生成</small></div><i v-if="organizationForm.source_type === 'intent'">✓</i></button><button type="button" :class="{ selected: organizationForm.source_type === 'knowledge' }" @click="organizationForm.source_type = 'knowledge'"><span>▤</span><div><strong>知识库</strong><small>从大江湖已有知识生成</small></div><i v-if="organizationForm.source_type === 'knowledge'">✓</i></button></div></section>
            <section v-if="organizationForm.source_type === 'knowledge'" class="organization-knowledge-inline"><header><div><BookOpen /><span><strong>上传组织知识库</strong><small>上传后会解析、切片并建立 RAG，生成组织时自动参考这些内容。</small></span></div><b>知识库 → 组织</b></header><label class="organization-knowledge-picker"><input :key="organizationKnowledgeInputKey" type="file" multiple webkitdirectory directory @change="selectOrganizationKnowledgeFiles" /><FolderOpen /><span>{{ organizationKnowledgeFiles.length ? `已选择 ${organizationKnowledgeFiles.length} 个文件` : '选择知识库目录' }}</span></label><div v-if="organizationKnowledgeFiles.length" class="organization-knowledge-selected"><span>已选 {{ organizationKnowledgeFiles.length }} 个文件</span><small>确认上传后，知识会成为当前大江湖的公共知识。</small></div><button class="jh-secondary" :disabled="organizationKnowledgeUploading || !organizationKnowledgeFiles.length" @click="uploadOrganizationKnowledge"><LoaderCircle v-if="organizationKnowledgeUploading" class="spin" /><UploadCloud v-else />{{ organizationKnowledgeUploading ? `正在建立 RAG ${organizationKnowledgeUploadProgress.completed}/${organizationKnowledgeUploadProgress.total}` : '上传并建立知识索引' }}</button></section>
            <section class="organization-forge-step"><header><b>2</b><div><strong>再选组织层级</strong><small>决定它在江湖中的位置</small></div></header><div class="organization-choice-grid"><button type="button" :class="{ selected: organizationForm.world_type === 'large' }" @click="organizationForm.world_type = 'large'"><span>🌏</span><div><strong>大江湖</strong><small>公共共同体，沉淀规则与共享知识</small></div><i v-if="organizationForm.world_type === 'large'">✓</i></button><button type="button" :class="{ selected: organizationForm.world_type === 'small' }" @click="organizationForm.world_type = 'small'"><span>⌂</span><div><strong>小江湖</strong><small>任务组织，围绕使命快速行动</small></div><i v-if="organizationForm.world_type === 'small'">✓</i></button></div></section>
            <section v-if="organizationForm.world_type === 'small'" class="organization-small-attributes">
              <header><b>3</b><div><strong>填写小江湖属性</strong><small>这些内容会成为团队的长期契约</small></div></header>
              <label>小江湖名称<input v-model="organizationForm.name" placeholder="例如：观澜营造社、青禾调解会" /></label>
              <label>共同使命<textarea v-model="organizationForm.purpose" placeholder="这个小江湖长期愿意承接什么事情？"></textarea></label>
              <label>行事方式<select v-model="organizationForm.operating_mode"><option value="collaborative">同心协作</option><option value="debate">议事争辩</option><option value="red_team">攻守对抗</option><option value="hierarchical">统领协作</option></select></label>
            </section>
            <label class="organization-intent">{{ organizationForm.world_type === 'small' ? '4. 补充生成意图' : '补充组织意图或知识描述' }}<textarea v-model="organizationForm.intent" placeholder="例如：围绕 AI 产品交付建立一支重视证据、能快速试错的产品与工程组织"></textarea></label>
            <button class="jh-primary organization-forge-submit" :disabled="organizationCreating || !organizationForm.intent.trim()" @click="generateOrganization"><LoaderCircle v-if="organizationCreating" class="spin" /><Sparkles v-else />{{ organizationCreating ? '正在生成组织与人物…' : '生成组织' }}</button>
          </div>
        </section>
        <section class="realm-hub">
          <header><div><span>🌏</span><div><small>大江湖 · 社会级共同体</small><h2>{{ organizationName }}</h2><p>{{ organization?.description }}</p></div></div><div class="realm-header-actions"><b>{{ teams.length }} 个小江湖共享此上层边界</b><button class="organization-edit-button" @click="openOrganizationEditor"><Settings2 />编辑大江湖</button></div></header>
          <div class="realm-knowledge-panel"><div><BookOpen /><span><strong>大江湖公共知识维护</strong><small>这是组织创建完成后的持续维护入口，可补充、更新和整理公共知识；下属小江湖执行时自动继承，人物专属知识仍需单独授权。</small></span></div><label><input :key="organizationKnowledgeInputKey" type="file" multiple webkitdirectory directory @change="selectOrganizationKnowledgeFiles" /><FolderOpen /><span>{{ organizationKnowledgeFiles.length ? `已选择 ${organizationKnowledgeFiles.length} 个文件` : '补充一个公共知识目录' }}</span></label><button class="jh-primary" :disabled="organizationKnowledgeUploading || !organizationKnowledgeFiles.length" @click="uploadOrganizationKnowledge"><LoaderCircle v-if="organizationKnowledgeUploading" class="spin" /><UploadCloud v-else />{{ organizationKnowledgeUploading ? `分批保存 ${organizationKnowledgeUploadProgress.completed}/${organizationKnowledgeUploadProgress.total}` : '补充知识并建立 RAG' }}</button></div>
          <details v-if="organizationKnowledgeFiles.length" class="knowledge-selection-dropdown"><summary><FolderOpen /><span><strong>待上传目录 · {{ organizationKnowledgeFiles.length }} 个文件</strong><small>点击展开；列表按滚动逐批显示，不会一次铺满页面</small></span></summary><div class="knowledge-upload-file-scroll" @scroll="scrollUploadPreview($event, organizationKnowledgeFiles, 'organization')"><span v-for="file in uploadPreviewFiles(organizationKnowledgeFiles, 'organization')" :key="`${file.name}-${file.size}`"><FileText /><b>{{ fileRelativePath(file) }}</b><small>{{ fileSizeLabel(file.size) }}</small></span><em v-if="(knowledgeUploadPreviewLimits.organization ?? 30) < organizationKnowledgeFiles.length">继续向下滚动加载更多</em></div></details>
          <details v-if="realmManagedKnowledge.length" class="knowledge-source-dropdown" @toggle="toggleKnowledgeSourceList($event, 'organization', organization.id)"><summary><BookOpen /><span><strong>已保存 {{ realmManagedKnowledge.length }} 份公共知识</strong><small>点击下拉查看，滚动时按 start/limit 继续加载</small></span></summary><div class="knowledge-source-scroll" @scroll="scrollKnowledgeSourceList($event, 'organization', organization.id)"><div v-for="source in knowledgePage('organization', organization.id).items" :key="source.id" class="managed-knowledge-item" :data-status="source.status"><button :disabled="knowledgeDetailLoading === source.id || knowledgeDeletingSourceId === source.id" @click="openKnowledgeDetail(source)"><LoaderCircle v-if="knowledgeDetailLoading === source.id" class="spin" /><FileText v-else /><span><strong>{{ source.metadata?.relative_path || source.name }}</strong><small>{{ fileSizeLabel(source.metadata?.size_bytes ?? 0) }} · {{ knowledgeStatusLabel(source) }}</small></span><BookOpen /></button><a :href="api.knowledgeDownloadUrl(source.id)" title="下载原文件"><Download /></a><button class="knowledge-delete" :disabled="knowledgeDeletingSourceId === source.id" :aria-label="`删除知识 ${source.metadata?.relative_path || source.name}`" title="删除知识文件" @click.stop="deleteKnowledgeSource(source)"><LoaderCircle v-if="knowledgeDeletingSourceId === source.id" class="spin" /><Trash2 v-else /></button></div><div v-if="knowledgePage('organization', organization.id).loading" class="knowledge-page-loading"><LoaderCircle class="spin" />正在读取下一页</div><small v-else-if="knowledgePage('organization', organization.id).pagination?.has_more" class="knowledge-scroll-hint">继续向下滚动加载更多</small></div></details>
          <KnowledgeRelationGraph :graph="knowledgeGraph" @open-source="openKnowledgeDetail" />
        </section>
        <section class="assembly-camp"><div class="assembly-scroll"><div class="scroll-title"><span>📜</span><div><small>小江湖组建契约</small><h2>建立新的小江湖</h2></div></div><label>小江湖名称<input v-model="teamForm.name" placeholder="例如：观澜营造社、青禾调解会" /></label><label>共同使命<textarea v-model="teamForm.purpose" placeholder="这个小江湖为何存在，愿意独立承接什么事情？"></textarea></label><label>行事方式<select v-model="teamForm.operating_mode"><option value="collaborative">同心协作</option><option value="debate">议事争辩</option><option value="red_team">攻守对抗</option><option value="hierarchical">统领协作</option></select></label><div class="knowledge-create-note"><UploadCloud /><div><strong>继承大江湖知识，也可拥有自己的知识</strong><small>小江湖可补充仅本组织使用的文件；执行时按大江湖 → 小江湖 → 人物授权依次检索。</small></div></div><button class="jh-primary" :disabled="busy || !teamForm.name || !teamForm.member_ids.length" @click="createTeam"><Plus />立下小江湖契约</button></div><div class="roster-board"><header><div><small>人物名册</small><h3>邀请同行者</h3></div><div class="roster-actions"><strong>已选 {{ teamForm.member_ids.length }} 人</strong><button @click="go('agents')"><Plus />创建新人物</button></div></header><p class="roster-hint">第一位被选中的人物担任召集人；人物可加入多个小江湖，但每次执行仍使用自己的独立 Memory 与会话。</p><div class="member-picker"><label v-for="agent in agents" :key="agent.id" :class="{ chosen: teamForm.member_ids.includes(agent.id) }"><input v-model="teamForm.member_ids" type="checkbox" :value="agent.id" /><span class="mini-avatar">{{ initials(agent.name) }}</span><div><strong>{{ agent.name }}</strong><small>{{ agent.role }}</small><em>{{ agent.capabilities.slice(0, 2).join(' · ') }}</em></div></label><div v-if="!agents.length" class="empty-roster"><span>👤</span><p>江湖人物册为空</p><button class="jh-primary" @click="go('agents')"><Plus />创建第一个人物</button></div></div></div></section>
        <section v-if="!teams.length" class="empty-settlement"><span>🏕️</span><h2>这里还是一片空地</h2><p>从上方人物名册邀请同行者，建立江湖中的第一个组织。</p></section><section v-else class="settlement-grid"><article v-for="(team, index) in teams" :key="team.id" class="settlement-card"><div class="settlement-scene"><span class="settlement-icon">{{ teamIcon(Number(index)) }}</span><i v-for="member in team.members.slice(0, 5)" :key="member.id" :title="`${member.name} · ${member.role}`">{{ initials(member.name) }}</i></div><header><div><span>{{ modeLabel(team.operating_mode) }}</span><h2>{{ team.name }}</h2></div><div class="settlement-card-header-actions"><b>{{ team.members.length }} 人</b><button class="team-edit-button" @click="openTeamEditor(team)"><Settings2 />编辑组织</button></div></header><p>{{ team.purpose || '这个组织还没有写下共同使命。' }}</p>
          <section class="team-roster-inline"><header><div><small>团队人物名册</small><strong>邀请同行者</strong></div><b>{{ team.members.length }} 人</b></header><div class="team-roster-members"><span v-for="member in team.members" :key="member.id"><i>{{ initials(member.name) }}</i><div><strong>{{ member.name }}</strong><small>{{ member.role }} · {{ member.member_role === 'leader' ? '召集人' : '成员' }}</small></div></span></div><div v-if="availableTeamAgents(team).length" class="team-invite-row"><select v-model="teamInviteDraft[team.id]"><option value="">选择一位可加入的人物</option><option v-for="person in availableTeamAgents(team)" :key="person.id" :value="person.id">{{ person.name }} · {{ person.role }}</option></select><button class="jh-secondary" :disabled="teamInviteLoading === team.id || !teamInviteDraft[team.id]" @click="inviteAgentToTeam(team)"><LoaderCircle v-if="teamInviteLoading === team.id" class="spin" /><Plus v-else />{{ teamInviteLoading === team.id ? '正在邀请…' : '邀请加入团队' }}</button><button class="team-create-person" @click="go('agents')"><Bot />创建新人物</button></div><small v-else class="team-roster-complete">当前人物库中的同行者都已在这个团队里。</small></section>
          <section class="team-knowledge-vault">
            <header><div><BookOpen /><span><strong>组织公共知识库</strong><small>平台解析、切片并检索相关知识，Agent 不再盲目读取全部文件</small></span></div><div class="knowledge-vault-actions"><b>{{ teamManagedKnowledge(team.id).length }} 份</b><button @click="openKnowledgeNote(team)"><Plus />补充知识</button></div></header>
            <details v-if="teamManagedKnowledge(team.id).length" class="knowledge-source-dropdown compact" @toggle="toggleKnowledgeSourceList($event, 'team', team.id)"><summary><BookOpen /><span><strong>查看已保存的 {{ teamManagedKnowledge(team.id).length }} 份知识</strong><small>下拉后滚动分页加载</small></span></summary><div class="knowledge-source-scroll" @scroll="scrollKnowledgeSourceList($event, 'team', team.id)"><div v-for="source in knowledgePage('team', team.id).items" :key="source.id" class="managed-knowledge-item" :data-status="source.status"><button :disabled="knowledgeDetailLoading === source.id || knowledgeDeletingSourceId === source.id" @click="openKnowledgeDetail(source)"><LoaderCircle v-if="knowledgeDetailLoading === source.id" class="spin" /><FileText v-else /><span><strong>{{ source.metadata?.relative_path || source.name }}</strong><small>{{ fileSizeLabel(source.metadata?.size_bytes ?? 0) }} · {{ knowledgeStatusLabel(source) }}</small></span><BookOpen /></button><a :href="api.knowledgeDownloadUrl(source.id)" title="下载原文件"><Download /></a><button class="knowledge-delete" :disabled="knowledgeDeletingSourceId === source.id" :aria-label="`删除知识 ${source.metadata?.relative_path || source.name}`" title="删除知识文件" @click.stop="deleteKnowledgeSource(source)"><LoaderCircle v-if="knowledgeDeletingSourceId === source.id" class="spin" /><Trash2 v-else /></button></div><div v-if="knowledgePage('team', team.id).loading" class="knowledge-page-loading"><LoaderCircle class="spin" />正在读取下一页</div><small v-else-if="knowledgePage('team', team.id).pagination?.has_more" class="knowledge-scroll-hint">继续向下滚动加载更多</small></div></details>
            <div v-else class="knowledge-vault-empty">尚未上传公共知识。可以上传文件或直接补充文字，平台会建立可检索的组织 RAG。</div>
            <div class="knowledge-rag-search"><Search /><input v-model="knowledgeSearchQuery[team.id]" placeholder="验证 Agent 能否检索到某项知识" @keyup.enter="searchTeamKnowledge(team)" /><button :disabled="knowledgeSearchingTeamId === team.id || !knowledgeSearchQuery[team.id]?.trim()" @click="searchTeamKnowledge(team)"><LoaderCircle v-if="knowledgeSearchingTeamId === team.id" class="spin" />检索</button></div>
            <div v-if="knowledgeSearchResults[team.id]" class="knowledge-search-results"><span v-if="!knowledgeSearchResults[team.id].length">没有找到相关片段，可以继续补充知识或换个问法。</span><button v-for="result in knowledgeSearchResults[team.id]" :key="result.id" @click="openKnowledgeDetail({ id: result.source_id })"><strong>{{ result.source_name }}</strong><small>{{ result.locator }} · 相关度 {{ Number(result.score).toFixed(3) }}</small><p>{{ result.content }}</p></button></div>
            <label class="knowledge-upload-drop"><input :key="`${team.id}-${teamKnowledgeInputKeys[team.id] ?? 0}`" type="file" multiple webkitdirectory directory @change="selectTeamKnowledgeFiles(team.id, $event)" /><FolderOpen /><span><strong>选择并递归上传知识目录</strong><small>目录下全部受支持的子目录和文件会保留相对路径并建立 RAG，单文件最大 20 MB</small></span></label>
            <div v-if="teamKnowledgeFiles[team.id]?.length" class="knowledge-upload-queue"><details class="knowledge-selection-dropdown compact"><summary><FolderOpen /><span><strong>待上传 {{ teamKnowledgeFiles[team.id].length }} 个文件</strong><small>点击展开并滚动查看</small></span></summary><div class="knowledge-upload-file-scroll" @scroll="scrollUploadPreview($event, teamKnowledgeFiles[team.id], `team:${team.id}`)"><span v-for="file in uploadPreviewFiles(teamKnowledgeFiles[team.id], `team:${team.id}`)" :key="`${file.name}-${file.size}`"><FileText /><b>{{ fileRelativePath(file) }}</b><small>{{ fileSizeLabel(file.size) }}</small></span><em v-if="(knowledgeUploadPreviewLimits[`team:${team.id}`] ?? 30) < teamKnowledgeFiles[team.id].length">继续向下滚动加载更多</em></div></details><button class="jh-primary" :disabled="knowledgeUploadingTeamId === team.id" @click="uploadTeamKnowledge(team)"><LoaderCircle v-if="knowledgeUploadingTeamId === team.id" class="spin" /><UploadCloud v-else />{{ knowledgeUploadingTeamId === team.id ? `分批保存 ${teamKnowledgeUploadProgress[team.id]?.completed ?? 0}/${teamKnowledgeUploadProgress[team.id]?.total ?? teamKnowledgeFiles[team.id].length}` : `上传、解析并保存 ${teamKnowledgeFiles[team.id].length} 份` }}</button></div>
          </section>
          <div class="team-members"><span v-for="member in team.members" :key="member.id"><i>{{ initials(member.name) }}</i><small><b>{{ member.name }}</b>{{ member.role }} · {{ member.member_role === 'leader' ? '召集人' : '成员' }}</small></span></div><div class="capability-tags"><span v-for="capability in team.capabilities" :key="capability">{{ capability }}</span></div><footer class="settlement-actions"><button @click="teamToDisband = team">解散组织</button></footer></article></section>
        <div v-if="editingOrganization" class="organization-editor-mask" @click.self="editingOrganization = null"><section class="organization-editor-dialog"><header><div><span>🌏</span><div><small>大江湖属性编辑</small><h2>编辑“{{ organizationDraft.name }}”</h2></div></div><button @click="editingOrganization = null"><XCircle /></button></header><label>大江湖名称<input v-model="organizationDraft.name" placeholder="例如：我的江湖" /></label><label>共同描述<textarea v-model="organizationDraft.description" placeholder="这个大江湖如何形成、协作和演化？"></textarea></label><footer><button class="jh-secondary" @click="editingOrganization = null">取消</button><button class="jh-primary" :disabled="organizationSaving || !organizationDraft.name.trim()" @click="saveOrganization"><LoaderCircle v-if="organizationSaving" class="spin" />{{ organizationSaving ? '正在保存…' : '保存大江湖' }}</button></footer></section></div>
        <div v-if="editingTeam" class="organization-editor-mask" @click.self="editingTeam = null"><section class="organization-editor-dialog"><header><div><span>🏘️</span><div><small>小江湖属性编辑</small><h2>编辑“{{ teamEditDraft.name }}”</h2></div></div><button @click="editingTeam = null"><XCircle /></button></header><label>小江湖名称<input v-model="teamEditDraft.name" placeholder="例如：观澜营造社" /></label><label>共同使命<textarea v-model="teamEditDraft.purpose" placeholder="这个小江湖长期愿意承接什么事情？"></textarea></label><label>行事方式<select v-model="teamEditDraft.operating_mode"><option value="collaborative">同心协作</option><option value="debate">议事争辩</option><option value="red_team">攻守对抗</option><option value="hierarchical">统领协作</option></select></label><footer><button class="jh-secondary" @click="editingTeam = null">取消</button><button class="jh-primary" :disabled="teamEditingSaving || !teamEditDraft.name.trim()" @click="saveTeamEdit"><LoaderCircle v-if="teamEditingSaving" class="spin" />{{ teamEditingSaving ? '正在保存…' : '保存小江湖' }}</button></footer></section></div>
        <div v-if="teamToDisband" class="confirm-mask"><section class="confirm-dialog"><span>⚠️</span><h2>确认解散“{{ teamToDisband.name }}”吗？</h2><p>组织会从当前江湖和后续流程选择中移除；已经产生的 Workflow 版本、Run、人物贡献和产物证据不会删除。</p><div><button class="jh-secondary" :disabled="Boolean(disbandingTeamId)" @click="teamToDisband = null">暂不解散</button><button class="danger-action" :disabled="Boolean(disbandingTeamId)" @click="confirmDisbandTeam"><LoaderCircle v-if="disbandingTeamId" class="spin" />{{ disbandingTeamId ? '正在解散…' : '确认解散' }}</button></div></section></div>
        <div v-if="selectedKnowledgeDetail" class="knowledge-modal-mask" @click.self="selectedKnowledgeDetail = null"><section class="knowledge-detail-dialog"><header><div><BookOpen /><span><small>组织知识详情</small><h2>{{ selectedKnowledgeDetail.source.name }}</h2></span></div><button @click="selectedKnowledgeDetail = null"><XCircle /></button></header><div class="knowledge-detail-meta"><span>{{ knowledgeStatusLabel(selectedKnowledgeDetail.source) }}</span><span>{{ fileSizeLabel(selectedKnowledgeDetail.source.metadata?.size_bytes ?? 0) }}</span><span>{{ selectedKnowledgeDetail.source.metadata?.parser ?? '未解析' }}</span><span>版本 {{ selectedKnowledgeDetail.source.version }}</span></div><p v-if="selectedKnowledgeDetail.source.status === 'index_failed'" class="knowledge-index-error">索引失败：{{ selectedKnowledgeDetail.source.metadata?.index_error }}</p><div class="knowledge-chunk-list" @scroll="scrollKnowledgeDetail"><article v-for="chunk in selectedKnowledgeDetail.chunks" :key="chunk.id"><header><strong>{{ chunk.title }}</strong><small>{{ chunk.locator }} · 约 {{ chunk.token_estimate }} tokens</small></header><p>{{ chunk.content }}</p></article><p v-if="!selectedKnowledgeDetail.chunks.length">该文件暂时没有可预览的知识片段。</p><div v-if="knowledgeDetailLoadingMore" class="knowledge-page-loading"><LoaderCircle class="spin" />正在读取更多片段</div></div><footer><span>已显示 {{ selectedKnowledgeDetail.chunks.length }}/{{ selectedKnowledgeDetail.pagination.total }} 个知识片段，向下滚动继续加载。</span><button v-if="selectedKnowledgeDetail.source.metadata?.managed" class="knowledge-detail-delete" :disabled="knowledgeDeletingSourceId === selectedKnowledgeDetail.source.id" @click="deleteKnowledgeSource(selectedKnowledgeDetail.source)"><LoaderCircle v-if="knowledgeDeletingSourceId === selectedKnowledgeDetail.source.id" class="spin" /><Trash2 v-else />删除知识</button><a :href="api.knowledgeDownloadUrl(selectedKnowledgeDetail.source.id)"><Download />下载原文件</a></footer></section></div>
        <div v-if="knowledgeNoteTeam" class="knowledge-modal-mask" @click.self="knowledgeNoteTeam = null"><section class="knowledge-note-dialog"><header><div><Plus /><span><small>补充组织公共知识</small><h2>{{ knowledgeNoteTeam.name }}</h2></span></div><button @click="knowledgeNoteTeam = null"><XCircle /></button></header><label>知识标题<input v-model="knowledgeNoteForm.title" placeholder="例如：生产发布与回滚规则" /></label><label>知识正文<textarea v-model="knowledgeNoteForm.content" placeholder="写下组织成员都应了解的背景、规范、事实或经验。平台会保存来源、切片并建立检索索引。"></textarea></label><footer><button class="jh-secondary" @click="knowledgeNoteTeam = null">取消</button><button class="jh-primary" :disabled="knowledgeNoteSaving || !knowledgeNoteForm.title.trim() || !knowledgeNoteForm.content.trim()" @click="saveKnowledgeNote"><LoaderCircle v-if="knowledgeNoteSaving" class="spin" /><Plus v-else />保存并建立 RAG</button></footer></section></div>
      </main>

      <main v-else-if="screen === 'agents'" class="jh-page">
        <section class="page-heading"><div><span>江湖人物志</span><h1>创建与管理江湖人物</h1><p>人物不是一次性档案：每个人都拥有独立经历、专属知识、技艺与持续演化的版本，并能在不同组织和事件中承担真实职责。</p></div><div class="runtime-seal" :data-ready="openClawStatus.available"><span>⚔️</span><div><small>人物行动状态</small><strong>{{ openClawStatus.available ? '行动底座已就绪' : '行动底座不可用' }}</strong><em>{{ openClawStatus.available ? '可独立办事、使用工具并积累经历' : '等待执行底座恢复' }}</em></div></div></section>
        <section class="agent-creator"><div class="creator-sign"><span>🪪</span><div><small>人物创建处</small><h2>引入一位新人物</h2><p>根据你的需要形成完整中文人物设定，并为他建立独立经历、专属知识和技艺空间。</p></div></div><label>人物需求<textarea v-model="agentRequirement" placeholder="例如：需要一位谨慎但敢于质疑共识、熟悉安全审计、面对压力仍坚持证据的人"></textarea></label><button class="jh-primary" :disabled="busy || !agentRequirement.trim()" @click="generateAgent"><LoaderCircle v-if="busy" class="spin" /><Sparkles v-else />创建江湖人物</button></section>
        <section v-if="!agents.length" class="jh-empty">江湖中还没有可复用人物。</section>
        <section v-else class="agent-grid"><article v-for="agent in agents" :key="agent.id" :class="{ highlighted: highlightedAgentId === agent.id }"><div class="agent-avatar">{{ initials(agent.name) }}</div><div class="agent-live-status" :data-state="agentSocietyPresence(agent).state"><i></i><span><b>{{ agentSocietyPresence(agent).state_label }}</b><small>{{ agentSocietyPresence(agent).node_name || '当前没有承接中的节点' }}</small></span></div><span>职业身份：{{ agent.role }} · 第 {{ agent.version }} 版</span><h2>{{ agent.name }}</h2><p>{{ agent.description }}</p><div class="agent-runtime-facts"><b>⚔️ 可独立行动</b><b>🧠 {{ agent.memory_count ?? 0 }} 段经历</b><b>🧰 {{ enabledSkillCount(agent) }} 项技艺</b><b>📚 {{ agent.knowledge_source_ids?.length ?? 0 }} 份专属知识</b></div><div class="agent-model-badges"><span>思考能力：{{ ['','执行型','综合型','高阶判断型'][agent.cognitive_level ?? 2] }}</span><span>影响力：{{ ['','建议','可影响团队','结论更易被遵守'][agent.authority_level ?? 1] }}</span><b>建议模型：{{ ({ high: '高', medium: '中', low: '低' } as Json)[agent.recommended_model_tier ?? 'medium'] }}</b></div><div class="capability-tags"><span v-for="capability in agent.capabilities" :key="capability">擅长：{{ capability }}</span></div><button class="agent-edit-button" @click="openAgentEditor(agent)"><Settings2 />编辑人物并创建新版本</button></article></section>
        <div v-if="editingAgent" class="agent-editor-mask" @click.self="editingAgent = null"><section class="agent-editor-dialog"><header><div><span class="agent-avatar">{{ initials(agentDraft.name) }}</span><div><small>人物版本编辑 · 历史版本不会覆盖</small><h2>{{ agentDraft.name }}</h2></div></div><button @click="editingAgent = null"><XCircle /></button></header><div v-if="agentEditorLoading" class="jh-loading"><LoaderCircle class="spin" />正在读取人物版本、经历与知识授权</div><div v-else class="agent-editor-body"><div class="agent-editor-form"><label>姓名<input v-model="agentDraft.name" /></label><label>职业身份<input v-model="agentDraft.role" /></label><label>职责说明<textarea v-model="agentDraft.description"></textarea></label><label>性格、立场与协作方式<textarea v-model="agentDraft.persona"></textarea></label><section class="editor-list"><header><strong>专业能力</strong><button @click="addAgentCapability"><Plus />增加</button></header><div v-for="(_, index) in agentDraft.capabilities" :key="index"><input v-model="agentDraft.capabilities[index]" /><button @click="removeAgentCapability(Number(index))"><Trash2 /></button></div></section><section class="editor-list skill-editor"><header><strong>人物技艺</strong><button @click="addAgentSkill"><Plus />增加技艺</button></header><article v-for="(skill, index) in agentDraft.skills" :key="index"><label><input v-model="skill.enabled" type="checkbox" />启用</label><input v-model="skill.name" placeholder="技艺名称" /><input v-model="skill.description" placeholder="什么时候使用" /><textarea v-model="skill.instructions" placeholder="该项技艺的具体行动规范"></textarea><button @click="removeAgentSkill(Number(index))"><Trash2 />移除</button></article></section><section class="editor-list knowledge-binding-editor"><header><strong>人物专属知识授权</strong><small>大江湖与所在小江湖的公共知识会按层级继承；这里选择只授权给该人物的来源。</small></header><label v-for="source in knowledgeSources" :key="source.id"><input v-model="agentDraft.knowledge_source_ids" type="checkbox" :value="source.id" /><span><b>{{ source.metadata?.relative_path || source.name }}</b><small>{{ source.metadata?.scope_type === 'organization' ? '大江湖' : source.metadata?.scope_type === 'team' ? '小江湖' : '知识来源' }}</small></span></label></section></div><aside class="agent-history"><section><header><strong>版本沿革</strong><b>{{ agentVersions.length }} 版</b></header><article v-for="version in agentVersions" :key="version.id"><b>第 {{ version.version }} 版 · {{ version.status === 'active' ? '当前' : '历史' }}</b><small>{{ version.role }} · {{ version.created_at }}</small></article></section><section><header><strong>独立长期经历</strong><b>{{ agentMemories.length }} 条</b></header><article v-for="memory in agentMemories.slice(0, 20)" :key="memory.id"><b>{{ memory.title }}</b><p>{{ memory.content }}</p><small>{{ memory.kind }} · {{ memory.created_at }}</small></article><p v-if="!agentMemories.length">这个人物尚未完成可沉淀的真实任务。</p></section></aside></div><footer><span>保存后创建新的不可变人物版本；活跃小江湖跟随新版，已冻结生产流不会被暗改。</span><button class="jh-primary" :disabled="busy" @click="saveAgentRevision"><LoaderCircle v-if="busy" class="spin" /><Settings2 v-else />保存为新版本</button></footer></section></div>
      </main>

      <main v-else-if="screen === 'flows'" ref="flowsPage" :class="['jh-page', { 'page-fallback-fullscreen': fullscreenTarget === 'flows' }]">
        <section class="page-heading"><div><span>团队行事章法</span><h1>团队生产流</h1><p>每个节点由一支人物队伍负责，成员在节点内部协作、争辩或攻防。</p></div><button class="jh-secondary page-fullscreen-toggle" :aria-label="fullscreenTarget === 'flows' ? '退出全屏' : '全屏查看行事章法'" @click="togglePageFullscreen('flows')"><Minimize2 v-if="fullscreenTarget === 'flows'" /> <Maximize2 v-else />{{ fullscreenTarget === 'flows' ? '退出全屏' : '全屏查看' }}</button></section>
        <section v-if="!workflows.length" class="jh-empty">尚未形成行事章法。请先从江湖总览发布委托或事件。</section>
        <section v-else class="flow-list">
          <template v-for="family in workflowFamilies" :key="family.familyId">
            <article v-for="flow in [displayedWorkflow(family)]" :key="flow.id" class="workflow-detail">
              <header>
                <div><span>{{ flow.source }} · 当前查看第 {{ flow.version }} 版</span><h2>{{ flow.name }}</h2><p>{{ flow.description }}</p></div>
                <div class="flow-actions">
                  <label v-if="family.versions.length > 1">历史版本<select v-model="selectedWorkflowVersions[family.familyId]"><option v-for="version in family.versions" :key="version.id" :value="version.id">第 {{ version.version }} 版{{ version.id === family.latest.id ? '（最新）' : '' }}</option></select></label>
                  <b>{{ flow.definition?.nodes?.length ?? 0 }} 个节点</b>
                  <button class="jh-secondary" @click="editWorkflow(flow)"><MousePointer2 />进入图形编辑</button>
                  <button class="workflow-delete-action" @click="workflowToDelete = flow"><Trash2 />删除生产流</button>
                  <button class="jh-primary" :disabled="busy" @click="startWorkflow(flow)"><Play />用当前委托开始执行</button>
                </div>
              </header>
              <div class="graph-guide"><MousePointer2 /><span>点击任意节点即可进入该节点的图形编辑器；连线表示正式产物依赖，同列节点可并行。</span></div>
              <div v-for="graph in [workflowGraph(flow)]" :key="`${flow.id}-graph`" class="workflow-graph-scroll">
                <div v-if="graph.hiddenEdgeCount" class="graph-simplify-note">为保持清晰，已折叠 {{ graph.hiddenEdgeCount }} 条可由其他路径推导的重复连线；节点详情仍保留全部真实依赖。</div>
                <div class="workflow-graph-canvas" :style="{ width: `${graph.width}px`, height: `${graph.height}px` }">
                  <div v-for="stage in graph.stages" :key="`stage-${stage.level}`" class="workflow-stage-band" :style="{ left: `${stage.x}px`, width: `${stage.width}px` }"><span>第 {{ stage.level + 1 }} 阶段</span><small>{{ stage.count > 1 ? `${stage.count} 个节点并行` : '单节点推进' }}</small></div>
                  <svg class="workflow-links" :width="graph.width" :height="graph.height" aria-hidden="true"><defs><marker :id="`arrow-${flow.id}`" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs><path v-for="edge in graph.edges" :key="edge.id" :class="{ express: edge.express }" :d="edge.path" :marker-end="`url(#arrow-${flow.id})`" /></svg>
                  <article v-for="node in graph.nodes" :key="node.key" class="workflow-graph-node" role="button" tabindex="0" :style="{ left: `${node.x}px`, top: `${node.y}px`, width: `${node.width}px`, height: `${node.height}px` }" @click="editWorkflow(flow, node.key)" @keydown.enter="editWorkflow(flow, node.key)">
                    <header><span>{{ Number(node.originalIndex) + 1 }}</span><small>第 {{ Number(node.level) + 1 }} 层{{ graph.nodes.filter((item: Json) => item.level === node.level).length > 1 ? ' · 并行' : '' }}</small></header>
                    <h3>{{ node.name }}</h3><p>{{ node.purpose }}</p><b>{{ node.team_name ?? '单人物节点' }}</b>
                    <div class="graph-node-people"><i v-for="member in nodeParticipants(node).slice(0, 4)" :key="member.id" :title="member.role">{{ initials(member.name) }}<em>{{ member.name }} · {{ member.role }}</em></i><span v-if="nodeParticipants(node).length > 4">+{{ nodeParticipants(node).length - 4 }}</span></div>
                    <footer class="node-dependency" :class="{ empty: dependencyMeta(flow, node).empty }" :title="dependencyMeta(flow, node).detail"><Network /><div><strong>{{ dependencyMeta(flow, node).label }}</strong><span>{{ dependencyMeta(flow, node).detail }}</span></div></footer>
                  </article>
                </div>
              </div>
            </article>
          </template>
        </section>

        <div v-if="editingWorkflow" class="workflow-editor-mask">
          <section class="workflow-studio">
            <header class="studio-header">
              <div><small>图形编辑器 · 保存后创建新版本，不覆盖历史</small><input v-model="workflowDraft.name" aria-label="流程名称" /><textarea v-model="workflowDraft.description" aria-label="流程说明"></textarea></div>
              <div><button class="jh-secondary" @click="editingWorkflow = null">关闭</button><button class="jh-primary" :disabled="busy || !workflowDraft.nodes.length" @click="saveWorkflowRevision">保存为新版本</button></div>
            </header>
            <div class="studio-body">
              <section class="studio-stage">
                <div class="studio-toolbar"><span><MousePointer2 />点击节点，右侧立即编辑</span><button @click="showAllWorkflowEdges = !showAllWorkflowEdges"><Network />{{ showAllWorkflowEdges ? '精简连线' : '全部依赖' }}</button><button @click="workflowZoom = Math.max(.65, workflowZoom - .1)"><Minus /></button><b>{{ Math.round(workflowZoom * 100) }}%</b><button @click="workflowZoom = Math.min(1.35, workflowZoom + .1)"><Plus /></button><button @click="workflowZoom = 1"><Maximize2 />复位</button><button :disabled="!teams.length" @click="addWorkflowNode"><Plus />新增节点</button></div>
                <div v-for="graph in [workflowGraph(workflowDraftFlow, showAllWorkflowEdges)]" :key="`draft-${workflowDraft.nodes.length}-${showAllWorkflowEdges}`" class="studio-graph-viewport">
                  <div :style="{ width: `${graph.width * workflowZoom}px`, height: `${graph.height * workflowZoom}px` }">
                    <div class="workflow-graph-canvas studio-graph-canvas" :style="{ width: `${graph.width}px`, height: `${graph.height}px`, transform: `scale(${workflowZoom})` }">
                      <div v-for="stage in graph.stages" :key="`draft-stage-${stage.level}`" class="workflow-stage-band" :style="{ left: `${stage.x}px`, width: `${stage.width}px` }"><span>第 {{ stage.level + 1 }} 阶段</span><small>{{ stage.count > 1 ? `${stage.count} 个节点并行` : '单节点推进' }}</small></div>
                      <svg class="workflow-links" :width="graph.width" :height="graph.height" aria-hidden="true"><defs><marker id="arrow-workflow-draft" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs><path v-for="edge in graph.edges" :key="edge.id" :class="{ express: edge.express }" :d="edge.path" marker-end="url(#arrow-workflow-draft)" /></svg>
                      <article v-for="node in graph.nodes" :key="node.key" :class="['workflow-graph-node', { selected: selectedWorkflowNodeKey === node.key }]" role="button" tabindex="0" :style="{ left: `${node.x}px`, top: `${node.y}px`, width: `${node.width}px`, height: `${node.height}px` }" @click="selectedWorkflowNodeKey = node.key" @keydown.enter="selectedWorkflowNodeKey = node.key">
                        <header><span>{{ Number(node.originalIndex) + 1 }}</span><small>{{ graph.nodes.filter((item: Json) => item.level === node.level).length > 1 ? '可并行' : `第 ${Number(node.level) + 1} 层` }}</small></header>
                        <h3>{{ node.name }}</h3><p>{{ node.purpose }}</p><b>{{ node.team_name ?? '未选择组织' }}</b>
                        <div class="graph-node-people"><i v-for="member in nodeParticipants(node).slice(0, 4)" :key="member.id">{{ initials(member.name) }}</i></div><footer class="node-dependency" :class="{ empty: dependencyMeta(workflowDraftFlow, node).empty }" :title="dependencyMeta(workflowDraftFlow, node).detail"><Network /><div><strong>{{ dependencyMeta(workflowDraftFlow, node).label }}</strong><span>{{ dependencyMeta(workflowDraftFlow, node).detail }}</span></div></footer>
                      </article>
                    </div>
                  </div>
                </div>
              </section>
              <aside v-if="selectedWorkflowNode" class="node-inspector">
                <header><span>节点属性</span><strong>{{ selectedWorkflowNode.name }}</strong></header>
                <label>节点名称<input v-model="selectedWorkflowNode.name" /></label>
                <label>正式交付目的<textarea v-model="selectedWorkflowNode.purpose"></textarea></label>
                <label>节点执行类型<select v-model="selectedWorkflowNode.type"><option value="team_task">团队生产节点</option><option value="judge">独立裁判 Gate</option></select></label>
                <label v-if="selectedWorkflowNode.type !== 'judge'">公开通信轮数<input v-model.number="selectedWorkflowNode.communication_rounds" type="number" min="1" max="3" /></label>
                <p v-else class="dependency-empty-note">裁判使用独立身份、独立会话和独立指令；不参加候选产物创作。不通过时自动定向打回责任节点。</p>
                <label>负责组织<select v-model="selectedWorkflowNode.team_id" @change="syncNodeTeam(selectedWorkflowNode)"><option v-for="team in teams" :key="team.id" :value="team.id">{{ team.name }}</option></select></label>
                <fieldset class="dependency-picker">
                  <legend><strong>上游产物连接</strong><small>勾选后，来源节点完成交付，当前节点才具备启动条件</small></legend>
                  <div class="dependency-target"><Network /><div><span>当前接收节点</span><strong>{{ selectedWorkflowNode.name }}</strong></div><b>{{ selectedWorkflowNode.depends_on?.length ?? 0 }} 条连接</b></div>
                  <div class="dependency-option-list">
                    <label v-for="candidate in workflowDependencyCandidates(selectedWorkflowNode)" :key="candidate.key" :class="{ connected: selectedWorkflowNode.depends_on?.includes(candidate.key) }">
                      <input v-model="selectedWorkflowNode.depends_on" type="checkbox" :value="candidate.key" />
                      <span class="dependency-node-number">{{ workflowDraft.nodes.findIndex((node: Json) => node.key === candidate.key) + 1 }}</span>
                      <div><strong>{{ candidate.name }}</strong><small>{{ candidate.team_name ?? '尚未绑定负责组织' }}</small></div>
                      <i>→</i><em>{{ selectedWorkflowNode.depends_on?.includes(candidate.key) ? '已连接' : '连接' }}</em>
                    </label>
                  </div>
                  <p v-if="!selectedWorkflowNode.depends_on?.length" class="dependency-empty-note">当前没有上游连接，因此它会作为流程起点直接启动；若同层还有其他起点，可并行执行。</p>
                </fieldset>
                <fieldset class="participant-picker"><legend>本节点实际到场人物</legend><label v-for="member in teamById[selectedWorkflowNode.team_id]?.members ?? []" :key="member.id"><input v-model="selectedWorkflowNode.participant_agent_ids" type="checkbox" :value="member.id" /><span>{{ initials(member.name) }}</span>{{ member.name }} · {{ member.role }}</label></fieldset>
                <button class="remove-node" @click="removeWorkflowNode(selectedWorkflowNode.key)"><Trash2 />删除此节点</button>
              </aside>
              <aside v-else class="node-inspector empty"><MousePointer2 /><strong>选择一个节点</strong><p>点击画布上的节点后，可修改名称、产物、依赖、组织和实际到场人物。</p></aside>
            </div>
          </section>
        </div>
        <div v-if="workflowToDelete" class="confirm-mask"><section class="confirm-dialog"><span>🗃️</span><h2>删除“{{ workflowToDelete.name }}”吗？</h2><p>会归档这套生产流的全部版本，并从默认列表和后续选择中移除；历史 Run、流程快照、人物行动和产物不会删除。若仍有未结束的现场，系统会阻止删除。</p><div><button class="jh-secondary" :disabled="Boolean(workflowDeletingId)" @click="workflowToDelete = null">暂不删除</button><button class="danger-action" :disabled="Boolean(workflowDeletingId)" @click="confirmDeleteWorkflow"><LoaderCircle v-if="workflowDeletingId" class="spin" />{{ workflowDeletingId ? '正在归档…' : '确认删除' }}</button></div></section></div>
      </main>

      <main v-else-if="showcaseEnabled && screen === 'showcase'" class="jh-page showcase-page">
        <section class="page-heading showcase-heading">
          <div><span>真实生产流演示案例</span><h1>单 Agent vs 多 Agent 协作 / 对抗</h1><p>同一模型、同一开发任务、同一独立裁判和同一隐藏验收集。仓库只内置案例规范与生产流，不预置运行结果；差异必须由真实执行现场产生。</p></div>
          <span v-if="showcasePolling" class="live-badge"><i></i>对照实验进行中</span>
        </section>

        <section class="showcase-contract">
          <div class="showcase-scroll-mark">⚔️</div>
          <div><small>{{ showcase.case?.id }}</small><h2>{{ showcase.case?.name }}</h2><p>{{ showcase.case?.summary }}</p></div>
          <aside><b>真实模型</b><b>真实执行现场</b><b>真实文件与测试</b><b>独立裁判回路</b></aside>
        </section>

        <section class="showcase-task-card">
          <header><div><span>同题任务</span><h3>开发事件优先级评估器</h3></div><b>隐藏验收 9 项</b></header>
          <pre>{{ showcase.case?.task }}</pre>
          <details><summary>查看公平性与指标口径</summary><div class="showcase-method-grid"><article><strong>公平性规则</strong><p v-for="item in showcase.case?.fairness_rules ?? []" :key="item">{{ item }}</p></article><article><strong>质量指标</strong><span v-for="item in showcase.case?.quality_dimensions ?? []" :key="item">{{ item }}</span></article><article><strong>效能指标</strong><span v-for="item in showcase.case?.efficiency_dimensions ?? []" :key="item">{{ item }}</span></article></div></details>
        </section>

        <section v-if="!showcase.installed" class="showcase-install">
          <div><span>📦</span><div><strong>案例尚未安装到你的江湖</strong><p>安装只会创建或复用人物、团队和两套可编辑复用的 WorkflowVersion，不会调用模型，不会写入演示结果。</p></div></div>
          <button class="jh-primary" :disabled="showcaseBusy" @click="installShowcase"><LoaderCircle v-if="showcaseBusy" class="spin" /><Plus v-else />安装完整案例</button>
        </section>

        <section v-else class="showcase-flow-arena">
          <header><div><span>生产流对照</span><h2>相同任务，两种生产组织方式</h2><p>卡片展示冻结 DAG；节点实际人物绑定、并行关系、讨论轮次和裁判返工都可以进入“行事章法”查看与另存新版本。</p></div><button class="jh-primary" :disabled="showcaseBusy || latestShowcaseComparison?.status === 'running'" @click="startShowcaseComparison()"><LoaderCircle v-if="showcaseBusy" class="spin" /><Play v-else />发起新一轮真实对照</button></header>
          <div class="showcase-flow-grid">
            <article v-for="variant in ['baseline','multi_agent']" :key="variant" :data-variant="variant">
              <header><div><small>{{ variant === 'baseline' ? '生产基线' : '协作 / 对抗组' }}</small><h3>{{ showcaseWorkflow(variant)?.name }}</h3><p>{{ showcaseWorkflow(variant)?.description }}</p></div><b>{{ showcaseWorkflow(variant)?.definition?.nodes?.length ?? 0 }} 节点</b></header>
              <div v-if="showcaseWorkflow(variant).id" v-for="graph in [workflowGraph(showcaseWorkflow(variant))]" :key="`${variant}-showcase-graph`" class="showcase-graph-viewport">
                <div class="workflow-graph-canvas" :style="{ width: `${graph.width}px`, height: `${graph.height}px`, transform: variant === 'multi_agent' ? 'scale(.72)' : 'scale(.82)' }">
                  <div v-for="stage in graph.stages" :key="`${variant}-stage-${stage.level}`" class="workflow-stage-band" :style="{ left: `${stage.x}px`, width: `${stage.width}px` }"><span>第 {{ stage.level + 1 }} 阶段</span><small>{{ stage.count > 1 ? `${stage.count} 节点并行` : '单节点' }}</small></div>
                  <svg class="workflow-links" :width="graph.width" :height="graph.height"><defs><marker :id="`showcase-arrow-${variant}`" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs><path v-for="edge in graph.edges" :key="edge.id" :d="edge.path" :marker-end="`url(#showcase-arrow-${variant})`" /></svg>
                  <article v-for="node in graph.nodes" :key="node.key" class="workflow-graph-node" :style="{ left: `${node.x}px`, top: `${node.y}px`, width: `${node.width}px`, height: `${node.height}px` }"><header><span>{{ Number(node.originalIndex) + 1 }}</span><small>{{ node.type === 'judge' ? '独立裁判' : (graph.nodes.filter((item: Json) => item.level === node.level).length > 1 ? '可并行' : '生产节点') }}</small></header><h3>{{ node.name }}</h3><p>{{ node.purpose }}</p><b>{{ node.team_name ?? node.agent_role }}</b><div class="graph-node-people"><i v-for="member in nodeParticipants(node).slice(0, 4)" :key="member.id">{{ initials(member.name) }}</i></div></article>
                </div>
              </div>
              <footer><span v-if="variant === 'baseline'">1 位生产 Agent 独立闭环；裁判只评审不创作</span><span v-else>需求 / 架构并行，开发协作，质量 / 红队并行挑战，失败自动返工</span><button class="jh-secondary" @click="go('flows')">查看与编辑生产流</button></footer>
            </article>
          </div>
        </section>

        <section v-if="latestShowcaseComparison" class="showcase-result-board">
          <header><div><span>最近一轮 · {{ latestShowcaseComparison.id }}</span><h2>真实对照运行与证据</h2><p>{{ latestShowcaseComparison.interpretation }}</p></div><div><b :data-status="latestShowcaseComparison.status">{{ latestShowcaseComparison.status === 'completed' ? '已形成对照结论' : (latestShowcaseComparison.status === 'running' ? '真实运行中' : '等待启动') }}</b><button v-if="latestShowcaseComparison.status === 'draft'" class="jh-primary" :disabled="showcaseBusy" @click="startShowcaseComparison(latestShowcaseComparison.id)"><Play />启动这轮实验</button></div></header>
          <div class="showcase-run-pair">
            <article v-for="variant in ['baseline','multi_agent']" :key="`run-${variant}`" :data-variant="variant">
              <header><div><small>{{ variant === 'baseline' ? '单 Agent 生产基线' : '多 Agent 协作 / 对抗' }}</small><strong>{{ showcaseRun(variant).workflow_name }}</strong><code>{{ showcaseRun(variant).run_id }}</code></div><b :data-status="showcaseRun(variant).status">{{ runStatusLabel(showcaseRun(variant).status) }}</b></header>
              <progress :value="showcaseRun(variant).progress ?? 0" max="100"></progress>
              <div class="showcase-score-row"><span><b>{{ showcaseRun(variant).quality_score ?? 0 }}</b><small>综合质量</small></span><span><b>{{ showcaseRun(variant).hidden_acceptance?.pass_rate ?? 0 }}%</b><small>隐藏验收</small></span><span><b>{{ showcaseRun(variant).risk_discovery?.rate ?? 0 }}%</b><small>问题发现</small></span><span><b>{{ showcaseRun(variant).completeness?.score ?? 0 }}%</b><small>产出完整</small></span></div>
              <div class="showcase-evidence-strip"><span>{{ showcaseRun(variant).evidence?.agent_count ?? 0 }} 人真实行动</span><span>{{ showcaseRun(variant).evidence?.message_count ?? 0 }} 条公开通信</span><span>{{ showcaseRun(variant).evidence?.successful_test_count ?? 0 }} 次测试通过</span><span>{{ showcaseRun(variant).evidence?.loop_count ?? 0 }} 次自动返工</span></div>
              <dl><div><dt>真实耗时</dt><dd>{{ formatDuration(showcaseRun(variant).efficiency?.elapsed_seconds ?? 0) }}</dd></div><div><dt>Token</dt><dd>{{ showcaseRun(variant).efficiency?.token_count ?? 0 }}</dd></div><div><dt>人工介入</dt><dd>{{ showcaseRun(variant).evidence?.intervention_count ?? 0 }} 次</dd></div><div><dt>人工耗时估算</dt><dd>{{ showcaseRun(variant).efficiency?.estimated_human_minutes ?? 0 }} 分钟</dd></div></dl>
              <details><summary>查看隐藏验收与完整度明细</summary><div class="showcase-checks"><span v-for="item in showcaseRun(variant).hidden_acceptance?.results ?? []" :key="item.name" :class="{ passed: item.passed }"><i>{{ item.passed ? '✓' : '×' }}</i><b>{{ item.name }}</b><small>{{ item.detail }}</small></span><span v-for="item in showcaseRun(variant).completeness?.checks ?? []" :key="`complete-${item.name}`" :class="{ passed: item.passed }"><i>{{ item.passed ? '✓' : '×' }}</i><b>{{ item.name }}</b><small>产物完整度检查</small></span></div></details>
              <button class="jh-secondary" :disabled="!showcaseRun(variant).run_id" @click="openRun(showcaseRun(variant).run_id)">进入真实事件现场</button>
            </article>
          </div>

          <section v-if="latestShowcaseComparison.comparable" class="showcase-delta">
            <header><div><span>多 Agent 相对单 Agent</span><h3>效果差异与代价同时展示</h3></div><small>质量类正数代表提升；耗时 / Token 正数代表成本增加</small></header>
            <div><article><b>{{ signedMetric(latestShowcaseComparison.delta.quality_score, ' 分') }}</b><span>综合质量</span></article><article><b>{{ signedMetric(latestShowcaseComparison.delta.hidden_acceptance_rate, 'pp') }}</b><span>隐藏验收通过率</span></article><article><b>{{ signedMetric(latestShowcaseComparison.delta.risk_discovery_rate, 'pp') }}</b><span>问题发现率</span></article><article><b>{{ signedMetric(latestShowcaseComparison.delta.completeness, 'pp') }}</b><span>产出完整度</span></article><article data-cost><b>{{ signedMetric(latestShowcaseComparison.delta.elapsed_seconds, ' 秒') }}</b><span>真实耗时差</span></article><article data-cost><b>{{ signedMetric(latestShowcaseComparison.delta.token_count) }}</b><span>Token 差</span></article></div>
            <p>人工耗时降低采用公开估算口径：以本案例人工完成参考值 {{ showcaseRun('multi_agent').efficiency?.manual_reference_minutes }} 分钟为基准，启动与复核计 3 分钟、每次用户介入计 5 分钟、终态未通过后的人工处置计 10 分钟。页面会明确标注它不是工时系统实测值。</p>
          </section>
        </section>
      </main>

      <main v-else-if="screen === 'runs'" ref="runsPage" :class="['jh-page', 'run-scene-page', { 'page-fallback-fullscreen': fullscreenTarget === 'runs' }]">
        <section v-if="runTimeLimitExhausted" class="run-failure-station run-time-extension-card"><div><span>⏱</span><div><strong>运行时限已耗尽，可以继续这个现场</strong><p>增加运行时限后，系统会保留已完成节点和正式产物，只继续执行尚未完成的节点。</p><small>单次可增加 30、60 或 120 分钟；总运行时限最多 360 分钟。</small></div></div><div class="failure-retry-actions"><label>增加时限<select v-model.number="extensionMinutes"><option :value="30">30 分钟</option><option :value="60">60 分钟</option><option :value="120">120 分钟</option></select></label><button class="jh-primary" :disabled="busy" @click="extendActiveRun">延长并继续</button></div></section>
        <section class="page-heading"><div><span>江湖正在行动</span><h1>事件现场</h1><p>这里展示真实模型调用产生的人物行动、节点状态、协作事件和正式产物。</p></div><div class="page-heading-actions"><span v-if="runPolling" class="live-badge"><i></i>现场更新中</span><button class="jh-secondary page-fullscreen-toggle" :aria-label="fullscreenTarget === 'runs' ? '退出全屏' : '全屏查看事件现场'" @click="togglePageFullscreen('runs')"><Minimize2 v-if="fullscreenTarget === 'runs'" /> <Maximize2 v-else />{{ fullscreenTarget === 'runs' ? '退出全屏' : '全屏查看' }}</button></div></section>
        <section v-if="!runs.length" class="jh-empty">还没有正式运行的事件。请先选择一套生产流，并用具体委托开始执行。</section>
        <section v-else class="run-list"><article v-for="run in runs" :key="run.run_family_id || run.id" :class="{ selected: activeRun?.run_family_id === run.run_family_id || activeRun?.id === run.id }"><div><strong>{{ run.workflow_name }}</strong><small>事件 {{ run.run_family_id || run.id }} · 当前第 {{ run.run_version || 1 }} 版</small></div><span :data-status="run.status">{{ runStatusLabel(run.status) }}</span><b>{{ run.progress }}%</b><small>{{ run.task_count }} 个节点 · {{ run.artifact_count }} 份产物 · {{ run.attempt_count || 1 }} 个版本</small><button v-if="run.status === 'draft'" class="jh-primary" :disabled="busy" @click="startExistingRun(run)"><Play />开始执行</button><button v-else class="jh-secondary" @click="openRun(run.id)">查看现场</button></article></section>

        <section v-if="activeRun" class="live-run-panel">
          <header><div><span>事件 {{ activeRun.run_family_id || activeRun.id }} · 第 {{ activeRun.run_version || 1 }} 版</span><h2>{{ runWorkflow(activeRun)?.name ?? '真实执行现场' }}</h2><p>{{ activeRun.task_input }}</p></div><div class="run-meter"><strong>{{ runStatusLabel(activeRun.status) }}</strong><b>{{ activeRun.progress }}%</b><small>当前阶段：{{ activeRun.stage }}</small><progress :value="activeRun.progress" max="100"></progress><div class="run-control-actions"><button v-if="activeRun.status === 'running'" class="run-pause" :disabled="busy" @click="pauseActiveRun">⏸ 暂停并介入</button><button v-if="['pause_requested','paused'].includes(activeRun.status)" class="jh-primary" :disabled="busy" @click="resumeActiveRun">▶ 恢复行动</button><button v-if="['running','pause_requested','paused'].includes(activeRun.status)" class="run-cancel" :disabled="busy" @click="cancelActiveRun">停止本次执行</button></div></div></header>
          <section v-if="activeRun.attempts?.length > 1" class="run-version-history"><div><strong>同一事件的执行版本</strong><small>重试不会创建新事件；每次执行作为不可覆盖的版本保留。</small></div><button v-for="attempt in activeRun.attempts" :key="attempt.id" :class="{ active: attempt.id === activeRun.id }" @click="openRun(attempt.id)">第 {{ attempt.run_version }} 版 · {{ runStatusLabel(attempt.status) }}</button></section>
          <section v-if="['failed','cancelled','budget_exhausted','revision_exhausted'].includes(activeRun.status)" class="run-failure-station"><div><span>🚨</span><div><strong>{{ activeRun.status === 'revision_exhausted' ? '自动返工已达到配置上限' : (activeRun.status === 'budget_exhausted' ? '预算或运行时限已经耗尽' : (activeRun.status === 'cancelled' ? '本次现场已停止' : '本次现场在自动重试后仍然中断')) }}</strong><p>{{ eventDetail(latestFailureEvent) }}</p><small>原 Run、失败证据和已有产物不会被覆盖；可以从当前未完成节点定向重试，也可以完整重跑。</small></div></div><div class="failure-retry-actions"><button v-if="selectedSceneTask" class="jh-primary" :disabled="busy" @click="retryActiveRun(selectedSceneTask)"><RefreshCw />从“{{ selectedSceneTask.node_name }}”重试</button><button class="jh-secondary" :disabled="busy" @click="retryActiveRun()"><RefreshCw />完整重跑</button></div></section>
          <section v-if="runConclusionArtifact" class="run-conclusion-card"><header><div><span>事件结案摘要</span><h3>一页纸结论</h3></div><a v-if="runConclusionArtifact.relative_path" :href="api.artifactDownloadUrl(runConclusionArtifact.id, currentOrganizationId)"><Download />下载</a></header><pre>{{ runConclusionArtifact.content }}</pre></section>
          <section v-if="activeRun.workspace" class="run-workspace-ribbon"><FolderOpen /><div><span>本次 Run 的独立交付工作区</span><strong>{{ activeRun.workspace.root }}</strong><small>输入、流程快照、产物、代码、日志和临时文件相互隔离；工程节点的真实文件统一进入 code 目录。</small></div><a v-if="activeRun.events?.some((event: Json) => String(event.type).startsWith('agent.file.'))" :href="api.runCodeDownloadUrl(activeRun.id, currentOrganizationId)"><Download />下载真实工程产物</a><button @click="copyWorkspacePath(activeRun.workspace.root)">复制地址</button></section>
          <section class="society-duty-board">
            <header><div><span>人物当值榜</span><h3>谁在忙、忙什么、最近留下了什么</h3><p>状态由真实 Run 事件推导，不靠前端模拟；点击人物可定位到他当前所在的生产节点。</p></div><b>{{ activePresenceCount }} 人在办事</b></header>
            <div><button v-for="presence in activeRun.agent_presence ?? []" :key="presence.agent_id" :data-state="presence.state" :disabled="!presence.task_id" @click="selectPresence(presence)"><i>{{ initials(presence.name) }}</i><span><strong>{{ presence.name }} · {{ presence.role }}</strong><b>{{ uiRuntimeText(presence.state_label) }}</b><small>{{ presence.node_name || '暂无负责节点' }}</small><em>{{ presencePreview(presence) }}</em></span></button></div>
          </section>
          <section class="society-run-scene">
            <header><div><span>江湖实景沙盘</span><h3>人物正在城镇中真实行动</h3><p>建筑代表生产节点，人物会在负责场所附近移动；点击建筑或人物查看当前行动和公开发言。</p><small class="run-version-note">{{ runWorkflowVersionNote(activeRun) }}</small></div><div class="scene-focus-actions"><b>{{ activeRun.tasks.filter((task: Json) => ['running','retrying'].includes(task.status)).length }} 处正在行动</b><button v-if="activeRun.tasks.some((task: Json) => ['running','retrying','failed'].includes(String(task.status)))" @click="focusCurrentTask">定位当前行动</button></div></header>
            <div class="game-world-layout">
              <div class="game-world-scroll">
                <div v-for="map in [sceneMapSize(activeRun.tasks.length)]" :key="`${activeRun.id}-map`" class="game-world-map" :style="{ width: `${map.width}px`, height: `${map.height}px` }">
                  <div class="map-water"></div><div class="map-bridge"></div><div class="map-square"></div>
                  <i v-for="tree in 18" :key="`tree-${tree}`" class="map-tree" :style="{ left: `${38 + ((tree * 173) % (map.width - 90))}px`, top: `${42 + ((tree * 97) % (map.height - 100))}px` }">♣</i>
                  <div v-for="row in Math.ceil(activeRun.tasks.length / map.columns)" :key="`road-row-${row}`" class="map-road horizontal" :style="{ top: `${262 + (row - 1) * 230}px`, width: `${map.width - 80}px` }"></div>
                  <div v-for="column in map.columns" :key="`road-column-${column}`" class="map-road vertical" :style="{ left: `${305 + (column - 1) * 260}px`, height: `${map.height - 80}px` }"></div>
                  <article v-for="(task, taskIndex) in activeRun.tasks" :key="task.id" :class="['map-building', { selected: selectedSceneTask?.id === task.id }]" :data-status="task.status" :style="{ left: `${sceneBuildingPosition(Number(taskIndex), activeRun.tasks.length).left}px`, top: `${sceneBuildingPosition(Number(taskIndex), activeRun.tasks.length).top}px` }" @click="selectSceneTask(task)">
                    <div class="building-roof"><span>{{ scenePlaceIcon(Number(taskIndex)) }}</span></div><div class="building-body"><small>{{ runTaskTeam(task)?.name ?? '独立人物驻地' }}</small><strong>{{ task.node_name }}</strong><em>{{ runStatusLabel(task.status) }}</em><span v-if="sceneParticipants(task).length > 4">另有 {{ sceneParticipants(task).length - 4 }} 人在室内</span></div>
                  </article>
                  <template v-for="(task, taskIndex) in activeRun.tasks" :key="`${task.id}-people`">
                    <button v-for="(person, personIndex) in sceneParticipants(task).slice(0, 4)" :key="`${task.id}-${person.id}`" :class="['map-person', { walking: activeRun.status === 'running' && ['running','retrying'].includes(String(task.status)), wandering: task.status === 'completed', waiting: ['draft','pending','pause_requested','paused'].includes(String(activeRun.status)) || ['draft','pending'].includes(String(task.status)), selected: selectedSceneTask?.id === task.id }]" :data-tone="personActivity(task, person).tone" :style="sceneActorStyle(Number(taskIndex), Number(personIndex), activeRun.tasks.length)" :title="`${person.name} · ${personActivity(task, person).state}`" @click.stop="selectSceneTask(task)">
                      <span v-if="Number(personIndex) < 2 && (selectedSceneTask?.id === task.id || ['running','retrying'].includes(String(task.status)))" class="map-speech">{{ personActivity(task, person).speech }}</span>
                      <i class="sprite-shadow"></i><i class="sprite-head"><b></b></i><i class="sprite-body"></i><i class="sprite-arm left"></i><i class="sprite-arm right"></i><i class="sprite-leg left"></i><i class="sprite-leg right"></i><em>{{ person.name }}</em>
                    </button>
                  </template>
                </div>
              </div>
              <aside v-if="selectedSceneTask" class="scene-command-panel action-observatory">
                <header><span>{{ scenePlaceIcon(activeRun.tasks.findIndex((task: Json) => task.id === selectedSceneTask.id)) }}</span><div><small>{{ runTaskTeam(selectedSceneTask)?.name ?? '独立人物驻地' }}</small><h4>{{ selectedSceneTask.node_name }}</h4></div><b>{{ runStatusLabel(selectedSceneTask.status) }}</b></header>
                <div v-if="['failed','cancelled','budget_exhausted','revision_exhausted'].includes(activeRun.status)" class="node-retry-entry"><div><RefreshCw /><span><strong>这个节点可以重新行动</strong><small>新建定向重试 Run，保留不受影响的已完成上游节点和产物。</small></span></div><button class="jh-primary" :disabled="busy" @click="retryActiveRun(selectedSceneTask)">从此节点重试</button></div>
                <p>{{ runWorkflow(activeRun)?.definition?.nodes?.find((node: Json) => node.key === selectedSceneTask.node_key)?.purpose ?? selectedSceneTask.node_name }}</p>
                <nav class="scene-panel-tabs"><button v-for="tab in sceneTabs" :key="tab.id" :class="{ active: scenePanelTab === tab.id }" @click="scenePanelTab = tab.id">{{ tab.label }}</button></nav>

                <div v-if="scenePanelTab === 'dossier'" class="scene-tab-content dossier-panel">
                  <section class="collaboration-protocol" :data-tone="nodeCollaborationPhase(selectedSceneTask).tone"><header><div><small>节点协作协议 · 当前第 {{ nodeCollaborationPhase(selectedSceneTask).step }}/5 阶段</small><strong>{{ nodeCollaborationPhase(selectedSceneTask).label }}</strong></div><b>私有思考隔离 · 公开事实共享</b></header><div><span :class="{ reached: nodeCollaborationPhase(selectedSceneTask).step >= 1 }"><i>1</i>独立办事</span><span :class="{ reached: nodeCollaborationPhase(selectedSceneTask).step >= 2 }"><i>2</i>公开提交</span><span :class="{ reached: nodeCollaborationPhase(selectedSceneTask).step >= 3 }"><i>3</i>定向议事</span><span :class="{ reached: nodeCollaborationPhase(selectedSceneTask).step >= 4 }"><i>4</i>负责人整合</span><span :class="{ reached: nodeCollaborationPhase(selectedSceneTask).step >= 5 }"><i>5</i>测试与裁决</span></div><p>公共卷宗只保存节点目标、上游正式产物、获准知识、人物主动公开的贡献与文件、定向消息、用户意见和校验证据；每个人的私有 Memory、私有会话和思维链都不会互相注入。</p></section>
                  <section class="node-attendance-board">
                    <header><div><strong>本节点实际到场人物</strong><small>依据本 Run 的真实行动事件确认，不按 Workflow 预绑定名单虚报到场。</small></div><b>{{ sceneArrivedParticipants(selectedSceneTask).length }} 人已到场</b></header>
                    <div v-if="sceneArrivedParticipants(selectedSceneTask).length" class="attendance-grid">
                      <article v-for="person in sceneArrivedParticipants(selectedSceneTask)" :key="person.id" class="attendance-card" :data-tone="personActivity(selectedSceneTask, person).tone">
                        <i class="attendance-avatar">{{ initials(person.name) }}</i>
                        <div class="attendance-main"><header><div><b>{{ person.name }}</b><small>{{ person.role }}</small></div><span>{{ personActivity(selectedSceneTask, person).state }}</span></header><p class="attendance-duty">本节点职责 · {{ participantDuty(selectedSceneTask, person) }}</p><blockquote>{{ personActivity(selectedSceneTask, person).speech }}</blockquote><footer><span>⚙️ 执行底座</span><span>🧠 {{ person.memory_count ?? 0 }} 条经历</span><span>🧰 {{ enabledSkillCount(person) }} 项技艺</span><button v-if="canRetryFailedAgent(selectedSceneTask, person)" :disabled="busy" @click="retryFailedAgent(selectedSceneTask, person)"><RefreshCw />让此人物重新行动</button></footer></div>
                      </article>
                    </div>
                    <div v-else class="empty-room">节点尚未产生任何人物行动事件，当前没有可确认的实际到场者。</div>
                    <div v-if="sceneWaitingParticipants(selectedSceneTask).length" class="attendance-waiting"><b>候场人物</b><span v-for="person in sceneWaitingParticipants(selectedSceneTask)" :key="person.id">{{ person.name }} · {{ person.role }}</span><small>已绑定本节点，但尚未产生上下文整备、执行回合、工具、通信或提交事件。</small></div>
                  </section>
                  <section class="dossier-summary"><strong>节点公共卷宗</strong><div><span>获准知识 <b>{{ selectedNodeDossier?.knowledge?.length ?? 0 }}</b></span><span>独立提交 <b>{{ selectedNodeDossier?.contributions?.length ?? 0 }}</b></span><span>公开消息 <b>{{ selectedNodeDossier?.communications?.length ?? 0 }}</b></span><span>工程提交 <b>{{ selectedNodeDossier?.integration?.length ?? 0 }}</b></span><span>用户意见 <b>{{ selectedNodeDossier?.interventions?.length ?? 0 }}</b></span><span>正式产物 <b>{{ selectedNodeDossier?.artifacts?.length ?? 0 }}</b></span></div><p>卷宗中的每条内容都有来源人物、节点、时间和事件类型；点击下方记录可查看实际注入了哪些上游产物、知识和发起人意见。</p></section>
                  <details v-for="event in selectedNodeDossier?.context ?? []" :key="event.id" class="ledger-detail"><summary><b>{{ collaborationSpeaker(event) }}</b><span>{{ eventTypeLabel(event.type) }}</span><small>{{ new Date(event.created_at).toLocaleTimeString('zh-CN') }}</small></summary><pre>{{ publicEventContent(event) || uiRuntimeText(event.summary) }}</pre><div v-if="event.payload?.interventions?.length" class="intervention-chips"><span v-for="item in event.payload.interventions" :key="item.id">{{ item.kind }} · {{ item.content }}</span></div></details>
                  <details v-for="event in selectedNodeDossier?.knowledge ?? []" :key="event.id" class="ledger-detail knowledge-entry"><summary><b>{{ collaborationSpeaker(event) }}</b><span>{{ eventTypeLabel(event.type) }}</span><small>{{ new Date(event.created_at).toLocaleTimeString('zh-CN') }}</small></summary><pre>{{ publicEventContent(event) || event.summary }}</pre><div v-if="event.payload?.matches?.length" class="knowledge-match-list"><span v-for="match in event.payload.matches" :key="`${match.source_id}-${match.locator}`"><b>{{ match.source_name }}</b><small>{{ match.locator }} · 相关度 {{ Number(match.score ?? 0).toFixed(3) }}</small></span></div></details>
                  <details v-if="taskRetryEvents(selectedSceneTask).length" class="retry-ledger" open><summary>重试与失败记录</summary><div v-for="event in taskRetryEvents(selectedSceneTask)" :key="event.id"><b>{{ eventTypeLabel(event.type) }}</b><span>{{ new Date(event.created_at).toLocaleTimeString('zh-CN') }}</span><p>{{ friendlyFailureReason(event) }}</p><code>{{ retryEventDetail(event) }}</code><details><summary>查看技术详情</summary><pre>{{ eventDetail(event) }}</pre></details></div></details>
                </div>

                <div v-else-if="scenePanelTab === 'actions'" class="scene-tab-content action-ledger">
                  <div v-if="!taskActionEvents(selectedSceneTask).length" class="empty-room">人物开始行动后，公开进度、工具使用和校验步骤会逐条出现。</div>
                  <details v-for="event in [...taskActionEvents(selectedSceneTask)].reverse()" :key="event.id" class="ledger-detail" :data-type="event.type"><summary class="action-summary"><b>{{ collaborationSpeaker(event) }}</b><span>{{ eventTypeLabel(event.type) }}</span><small>{{ new Date(event.created_at).toLocaleTimeString('zh-CN') }}</small><em>{{ actionEventPreview(event) }}</em></summary><pre>{{ publicEventContent(event) || event.summary }}</pre><code v-if="event.payload?.tool_name">工具：{{ event.payload.tool_name }}</code><code v-if="event.payload?.command">命令：{{ event.payload.command }}</code><code v-if="event.payload?.cwd">工作目录：{{ event.payload.cwd }}</code><code v-if="event.payload?.exit_code !== undefined && event.payload?.exit_code !== null">退出码：{{ event.payload.exit_code }} · {{ event.payload.duration_ms ?? 0 }}ms</code></details>
                </div>

                <div v-else-if="scenePanelTab === 'messages'" class="scene-tab-content collaboration-ledger">
                  <div v-if="!(selectedNodeDossier?.contributions?.length || taskMessageEvents(selectedSceneTask).length)" class="empty-room">独立贡献完成后才会公开；人物在隔离阶段看不到彼此私有草稿。</div>
                  <section v-if="selectedNodeDossier?.contributions?.length" class="public-contribution-board"><header><strong>人物独立交卷</strong><small>以下是人物主动公开的完整提交，不是平台生成的状态文案</small></header><article v-for="event in selectedNodeDossier.contributions" :key="event.id"><div><i>{{ initials(eventAgent(event)?.name ?? '人') }}</i><span><b>{{ collaborationSpeaker(event) }}</b><small>{{ eventAgent(event)?.role ?? event.payload?.phase ?? '江湖人物' }} · {{ new Date(event.created_at).toLocaleTimeString('zh-CN') }}</small></span><em>独立形成</em></div><p>{{ contributionPreview(event) }}</p><details><summary>查看完整提交与文件清单</summary><pre>{{ publicEventContent(event) }}</pre><code v-if="event.payload?.file_changes?.length">文件变更：{{ event.payload.file_changes.map((item: Json) => `${item.action} ${item.path}`).join('；') }}</code></details></article></section>
                  <article v-for="event in taskMessageEvents(selectedSceneTask)" :key="event.id" :data-type="event.type"><header><b>{{ collaborationSpeaker(event) }}</b><small>{{ eventTypeLabel(event.type) }} · {{ new Date(event.created_at).toLocaleTimeString('zh-CN') }}</small></header><p>{{ publicEventContent(event) }}</p><code v-if="event.payload?.manifest">公开提交清单：{{ event.payload.manifest }}</code><em v-if="event.payload?.round">第 {{ event.payload.round }} 轮</em></article>
                </div>

                <div v-else-if="scenePanelTab === 'evidence'" class="scene-tab-content evidence-ledger">
                  <div v-if="!taskEvidenceEvents(selectedSceneTask).length" class="empty-room">工程人物真实修改文件、执行命令或运行测试后，证据会在这里出现。</div>
                  <details v-for="event in [...taskEvidenceEvents(selectedSceneTask)].reverse()" :key="event.id" class="ledger-detail" :data-type="event.type"><summary><b>{{ eventTypeLabel(event.type) }}</b><span>{{ event.payload?.path ?? event.payload?.command ?? uiRuntimeText(event.summary) }}</span><small>{{ new Date(event.created_at).toLocaleTimeString('zh-CN') }}</small></summary><code v-if="event.payload?.sha256">SHA-256：{{ event.payload.sha256 }}</code><code v-if="event.payload?.exit_code !== undefined && event.payload?.exit_code !== null">退出码：{{ event.payload?.exit_code }} · {{ event.payload?.passed === false ? '未通过' : '已完成' }}</code><pre>{{ publicEventContent(event) || uiRuntimeText(event.summary) }}</pre></details>
                  <a v-if="activeRun.events?.some((event: Json) => String(event.type).startsWith('agent.file.'))" class="code-package-link" :href="api.runCodeDownloadUrl(activeRun.id, currentOrganizationId)"><Download />下载本 Run 的真实工程代码包</a>
                </div>

                <div v-else-if="scenePanelTab === 'rationale'" class="scene-tab-content initiator-rationale-panel">
                  <section class="private-rationale-intro"><div><strong>发起人私享行动说明</strong><span class="private-visibility-badge">仅发起人可见</span></div><p>这里展示人物主动提交的事实依据、关键取舍、不确定性和下一步验证，不是模型原始隐藏思维链。内容不会进入公共卷宗、江湖播报，也不会注入其他 Agent 的上下文。</p></section>
                  <div v-if="!selectedNodeDossier?.initiator_notes?.length" class="empty-room">新的人物回合完成后，若人物提交了行动说明，将在这里单独归档；旧 Run 不会伪造或补写私享内容。</div>
                  <article v-for="event in [...(selectedNodeDossier?.initiator_notes ?? [])].reverse()" :key="event.id" class="rationale-card"><header><div><i>{{ initials(eventAgent(event)?.name ?? '人') }}</i><span><b>{{ collaborationSpeaker(event) }}</b><small>{{ eventAgent(event)?.role ?? '江湖人物' }} · {{ event.payload?.phase ?? '行动交付' }}</small></span></div><time>{{ new Date(event.created_at).toLocaleTimeString('zh-CN') }}</time></header><dl><div v-for="section in initiatorNoteSections(event.payload?.content)" :key="section.label"><dt>{{ section.label }}</dt><dd>{{ section.content }}</dd></div></dl><footer><span>不向其他 Agent 分享</span><span>未采集原始思维链</span></footer></article>
                </div>

                <div v-else-if="scenePanelTab === 'intervene'" class="scene-tab-content intervention-panel">
                  <section class="intervention-history"><strong>发起人现场意见</strong><article v-for="item in activeRun.interventions?.filter((entry: Json) => !entry.task_id || entry.task_id === selectedSceneTask.id) ?? []" :key="item.id"><b>{{ item.kind }}</b><span :data-status="item.status">{{ item.status === 'applied' ? '已送达' : '等待送达' }}</span><p>{{ item.content }}</p></article><div v-if="!activeRun.interventions?.length" class="empty-room">尚未介入这个现场。</div></section>
                  <form v-if="!['completed','failed','cancelled','budget_exhausted','revision_exhausted'].includes(activeRun.status)" @submit.prevent="submitRunIntervention"><label>意见类型<select v-model="interventionForm.kind"><option value="supplement">补充事实或约束</option><option value="correction">纠偏</option><option value="question">向人物提问</option><option value="require_rework">要求本节点返工并重跑下游</option></select></label><label>送达人物<select v-model="interventionForm.agent_id"><option value="">本节点所有相关人物</option><option v-for="person in sceneParticipants(selectedSceneTask)" :key="person.id" :value="person.id">{{ person.name }} · {{ person.role }}</option></select></label><label>公开意见<textarea v-model="interventionForm.content" placeholder="说明新增事实、必须调整的方向、要回答的问题或明确返工要求。此内容会进入节点公共卷宗。"></textarea></label><button class="jh-primary" :disabled="interventionSaving || !interventionForm.content.trim()"><LoaderCircle v-if="interventionSaving" class="spin" />提交到现场</button><small>如需先停住后续动作，请先点击上方“暂停并介入”；当前已发出的模型回合不会被强行截断。</small></form>
                </div>
              </aside>
            </div>
            <footer class="world-broadcast"><strong>📣 江湖播报</strong><div><article v-for="event in worldBroadcasts" :key="event.id"><span>{{ eventAgent(event)?.name ?? (event.payload?.team_id ? teamById[event.payload.team_id]?.name : '平台') }}</span><p>{{ ['task.failed','run.failed','llm.retrying','task.retrying'].includes(String(event.type)) ? eventDetail(event) : uiRuntimeText(event.payload?.contribution_preview ?? event.summary) }}</p><small>{{ eventTypeLabel(event.type) }} · {{ new Date(event.created_at).toLocaleTimeString('zh-CN') }}</small></article></div></footer>
          </section>
          <section class="artifact-board"><header><div><span>正式交付</span><h3>节点产物</h3></div><b>{{ activeRun.artifacts?.length ?? 0 }} 份</b></header><div v-if="!activeRun.artifacts?.length" class="artifact-waiting"><LoaderCircle v-if="activeRun.status === 'running'" class="spin" /><span>{{ activeRun.status === 'running' ? '人物正在行动，首份产物形成后会自动写入本 Run 的隔离工作区。' : '本次事件尚未形成产物。' }}</span></div><details v-for="artifact in activeRun.artifacts" :key="artifact.id" class="artifact-card"><summary><div><strong>{{ artifact.title }}</strong><small>{{ artifact.kind }} · 第 {{ artifact.version }} 版 · {{ artifact.status }}</small><code v-if="artifact.relative_path">{{ artifact.relative_path }} · SHA-256 {{ artifact.sha256?.slice(0, 12) }}</code></div><span>展开查看</span></summary><div class="artifact-actions"><a v-if="artifact.relative_path" :href="api.artifactDownloadUrl(artifact.id, currentOrganizationId)"><Download />下载独立文件</a><small>{{ artifact.size_bytes ?? 0 }} bytes · {{ artifact.media_type ?? 'text/markdown' }}</small></div><pre>{{ artifact.content }}</pre></details></section>
        </section>
      </main>

      <main v-else class="jh-page">
        <section class="page-heading">
          <div><span>模型与执行设置</span><h1>模型、凭据与执行底座</h1><p>可保存多份真实模型配置，并按高、中、低档分别选择当前启用项。</p></div>
        </section>
        <section class="openclaw-runtime-card" :data-ready="openClawStatus.available">
          <Settings2 />
          <div><small>执行底座状态</small><h2>{{ openClawStatus.available ? '运行正常，可开始人物任务' : '暂不可用，将阻断新人物任务' }}</h2><p>{{ openClawStatus.available ? '独立会话、工具和经历空间已准备就绪。' : '请稍后重新检查运行状态。' }}</p></div>
          <button class="jh-secondary" @click="loadAll"><RefreshCw />重新检查</button>
        </section>
        <section class="model-tier-notice"><b>支持多配置并存</b><span>同一档位可以保存多份配置，其中一份处于启用状态；切换配置不会覆盖其他配置的地址、模型或加密凭据。</span></section>
        <section class="model-layout">
          <aside class="model-config-list">
            <header>
              <div><strong>已保存配置</strong><small>{{ modelConfigs.length }} 份</small></div>
              <button class="model-new-button" @click="beginNewModel"><Plus />新建</button>
            </header>
            <p v-if="!modelConfigs.length" class="model-list-empty">还没有配置，请新建并填写真实模型连接信息。</p>
            <button v-for="config in modelConfigs" :key="config.id" :class="{ active: modelForm.id === config.id }" @click="selectModel(config)">
              <span class="model-config-title"><strong>{{ config.name }}</strong><em v-if="config.active">已启用</em></span>
              <small>{{ ({ high: '高档', medium: '中档', low: '低档' } as Json)[config.tier ?? 'medium'] }} · {{ config.provider }}</small>
              <small>{{ config.model }}</small>
            </button>
          </aside>
          <div class="model-form">
            <div class="model-form-heading"><div><small>{{ modelForm.id ? '编辑已保存配置' : '创建新配置' }}</small><strong>{{ modelForm.name || '未命名模型配置' }}</strong></div><span v-if="modelForm.id">{{ modelForm.token_hint || '凭据已加密保存' }}</span></div>
            <label>配置名称<input v-model="modelForm.name" placeholder="例如：主力推理模型" /></label>
            <label>模型档位<select v-model="modelForm.tier"><option value="high">高：复杂判断与裁决</option><option value="medium">中：综合协作与规划</option><option value="low">低：执行、提取与格式化</option></select></label>
            <label>协议<select v-model="modelForm.provider"><option value="openai-responses">OpenAI Responses API</option><option value="anthropic-compatible">Anthropic Messages API</option></select></label>
            <label>Base URL<input v-model="modelForm.base_url" placeholder="https://api.example.com" /></label>
            <label>模型<input v-model="modelForm.model" placeholder="模型标识" /></label>
            <label>Token<input v-model="modelForm.token" type="password" :placeholder="modelForm.id ? '留空保留当前加密凭据' : '请输入真实 Token'" /></label>
            <label class="model-active-toggle"><input v-model="modelForm.active" type="checkbox" /><span><b>保存后启用此配置</b><small>同档位原先启用的配置会保留，但切换为未启用。</small></span></label>
            <div class="model-form-actions">
              <button v-if="modelForm.id" class="model-delete-button" :disabled="modelDeletingId === modelForm.id" @click="deleteModel(modelForm)"><Trash2 />{{ modelDeletingId === modelForm.id ? '删除中' : '删除配置' }}</button>
              <span />
              <button class="jh-secondary" :disabled="busy" @click="testModel"><Zap />测试真实连接</button>
              <button class="jh-primary" :disabled="busy || !modelForm.name || !modelForm.base_url || !modelForm.model || (!modelForm.id && !modelForm.token)" @click="saveModel">安全保存</button>
            </div>
            <p class="model-message">{{ modelMessage }}</p>
          </div>
        </section>
      </main>
    </div>
  </div>
</template>
