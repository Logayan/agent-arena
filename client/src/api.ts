// 默认走同源 /api，由开发服务器或生产网关代理到平台后端。
// 独立部署时仍可通过 VITE_API_URL 指定完整 API 地址。
const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    const detail = body.detail
    const message = typeof detail === 'string'
      ? detail
      : (detail?.message ? String(detail.message) : JSON.stringify(detail ?? body))
    throw new Error(message || '请求失败')
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<Record<string, unknown>>('/api/health'),
  platformOverview: () => request<Record<string, unknown>>('/api/platform/overview'),
  organizations: () => request<Record<string, unknown>[]>('/api/platform/organizations'),
  updateOrganization: (organizationId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/platform/organizations/${encodeURIComponent(organizationId)}`, { method: 'PUT', body: JSON.stringify(payload) }),
  generateOrganization: (payload: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/organizations/generate', { method: 'POST', body: JSON.stringify(payload) }),
  platformProjects: () => request<Record<string, unknown>[]>('/api/platform/projects'),
  platformRuns: (organizationId?: string) => request<Record<string, unknown>[]>(`/api/platform/runs${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`),
  productionFlowShowcase: () =>
    request<Record<string, unknown>>('/api/platform/showcases/production-flow-comparison'),
  installProductionFlowShowcase: () =>
    request<Record<string, unknown>>('/api/platform/showcases/production-flow-comparison/install', { method: 'POST' }),
  createProductionFlowComparison: () =>
    request<Record<string, unknown>>('/api/platform/showcases/production-flow-comparison/comparisons', { method: 'POST' }),
  getProductionFlowComparison: (comparisonId: string) =>
    request<Record<string, unknown>>(`/api/platform/showcases/production-flow-comparison/comparisons/${encodeURIComponent(comparisonId)}`),
  startProductionFlowComparison: (comparisonId: string) =>
    request<Record<string, unknown>>(`/api/platform/showcases/production-flow-comparison/comparisons/${encodeURIComponent(comparisonId)}/start`, { method: 'POST' }),
  platformAgents: (organizationId?: string) => request<Record<string, unknown>[]>(`/api/platform/agents${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`),
  createAgent: (agent: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/agents', { method: 'POST', body: JSON.stringify(agent) }),
  reviseAgent: (agentId: string, agent: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/platform/agents/${encodeURIComponent(agentId)}`, { method: 'PUT', body: JSON.stringify(agent) }),
  agentVersions: (agentId: string) => request<Record<string, unknown>[]>(`/api/platform/agents/${encodeURIComponent(agentId)}/versions`),
  agentMemories: (agentId: string) => request<Record<string, unknown>[]>(`/api/platform/agents/${encodeURIComponent(agentId)}/memories`),
  addAgentMemory: (agentId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/platform/agents/${encodeURIComponent(agentId)}/memories`, { method: 'POST', body: JSON.stringify(payload) }),
  generateAgent: (requirement: string, organizationId = 'org_jianghu', preferredRole?: string, requiredCapabilities: string[] = []) =>
    request<Record<string, unknown>>('/api/platform/agents/generate', { method: 'POST', body: JSON.stringify({ requirement, organization_id: organizationId, preferred_role: preferredRole, required_capabilities: requiredCapabilities }) }),
  teams: (organizationId = 'org_jianghu') => request<Record<string, unknown>[]>(`/api/platform/teams?organization_id=${encodeURIComponent(organizationId)}`),
  createTeam: (team: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/teams', { method: 'POST', body: JSON.stringify(team) }),
  updateTeam: (teamId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/platform/teams/${encodeURIComponent(teamId)}`, { method: 'PUT', body: JSON.stringify(payload) }),
  addTeamMember: (teamId: string, agentId: string, responsibility = '') =>
    request<Record<string, unknown>>(`/api/platform/teams/${teamId}/members`, {
      method: 'POST',
      body: JSON.stringify({ agent_id: agentId, responsibility }),
    }),
  uploadTeamKnowledge: (teamId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/platform/teams/${teamId}/knowledge`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  uploadTeamKnowledgeFolder: (teamId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/platform/teams/${teamId}/knowledge/folders`, { method: 'POST', body: JSON.stringify(payload) }),
  uploadOrganizationKnowledgeFolder: (organizationId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/platform/organizations/${organizationId}/knowledge/folders`, { method: 'POST', body: JSON.stringify(payload) }),
  addOrganizationKnowledgeNote: (organizationId: string, title: string, content: string) =>
    request<Record<string, unknown>>(`/api/platform/organizations/${organizationId}/knowledge/notes`, {
      method: 'POST', body: JSON.stringify({ title, content }),
    }),
  knowledgeGraph: (organizationId: string) =>
    request<Record<string, unknown>>(`/api/platform/organizations/${organizationId}/knowledge-graph`),
  addTeamKnowledgeNote: (teamId: string, title: string, content: string) =>
    request<Record<string, unknown>>(`/api/platform/teams/${teamId}/knowledge/notes`, {
      method: 'POST',
      body: JSON.stringify({ title, content }),
    }),
  searchTeamKnowledge: (teamId: string, query: string, limit = 8) =>
    request<Record<string, unknown>>(`/api/platform/teams/${teamId}/knowledge/search?q=${encodeURIComponent(query)}&limit=${limit}`),
  disbandTeam: (teamId: string) =>
    request<Record<string, unknown>>(`/api/platform/teams/${teamId}`, { method: 'DELETE' }),
  commissions: (organizationId = 'org_jianghu') =>
    request<Record<string, unknown>[]>(`/api/platform/commissions?organization_id=${encodeURIComponent(organizationId)}`),
  assessCommission: (title: string, description: string, organizationId = 'org_jianghu', commissionId?: string, gitDelivery?: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/commissions/assess', {
      method: 'POST',
      body: JSON.stringify({ title, description, organization_id: organizationId, commission_id: commissionId, git_delivery: gitDelivery }),
    }),
  resolveCommissionTeam: (commissionId: string, forceCreate = false) =>
    request<Record<string, unknown>>(`/api/platform/commissions/${encodeURIComponent(commissionId)}/resolve-team`, {
      method: 'POST', body: JSON.stringify({ force_create: forceCreate }),
    }),
  confirmCommissionTeamProposal: (commissionId: string, proposalId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/platform/commissions/${encodeURIComponent(commissionId)}/team-proposals/${encodeURIComponent(proposalId)}/confirm`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  rejectCommissionTeamProposal: (commissionId: string, proposalId: string) =>
    request<Record<string, unknown>>(`/api/platform/commissions/${encodeURIComponent(commissionId)}/team-proposals/${encodeURIComponent(proposalId)}`, {
      method: 'DELETE',
    }),
  generateTeamWorkflow: (companyTaskId: string, teamIds: string[]) =>
    request<Record<string, unknown>>('/api/platform/team-workflows/generate', { method: 'POST', body: JSON.stringify({ company_task_id: companyTaskId, team_ids: teamIds }) }),
  platformWorkflows: (organizationId?: string) => request<Record<string, unknown>[]>(`/api/platform/workflows${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`),
  reviseWorkflow: (workflowId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/platform/workflows/${workflowId}/revisions`, { method: 'POST', body: JSON.stringify(payload) }),
  deleteWorkflow: (workflowId: string) =>
    request<Record<string, unknown>>(`/api/platform/workflows/${encodeURIComponent(workflowId)}`, { method: 'DELETE' }),
  knowledgeSources: () => request<Record<string, unknown>[]>('/api/platform/knowledge-sources'),
  knowledgeSourcesPage: (scopeType: 'organization' | 'team', scopeId: string, offset = 0, limit = 20) =>
    request<Record<string, unknown>>(`/api/platform/knowledge-sources/page?scope_type=${encodeURIComponent(scopeType)}&scope_id=${encodeURIComponent(scopeId)}&offset=${offset}&limit=${limit}`),
  knowledgeSourceDetail: (sourceId: string, offset = 0, limit = 50) =>
    request<Record<string, unknown>>(`/api/platform/knowledge-sources/${encodeURIComponent(sourceId)}?offset=${offset}&limit=${limit}`),
  deleteKnowledgeSource: (sourceId: string) =>
    request<Record<string, unknown>>(`/api/platform/knowledge-sources/${encodeURIComponent(sourceId)}`, { method: 'DELETE' }),
  createKnowledgeSource: (source: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/knowledge-sources', {
      method: 'POST',
      body: JSON.stringify(source),
    }),
  knowledgeDownloadUrl: (sourceId: string) =>
    `${API_BASE}/api/platform/knowledge-sources/${encodeURIComponent(sourceId)}/download`,
  marketplace: () => request<Record<string, unknown>>('/api/platform/marketplace'),
  modelConfigs: () => request<Record<string, unknown>[]>('/api/platform/model-configs'),
  projects: () => request<Record<string, unknown>[]>('/api/platform/projects'),
  runtimeStatus: () => request<Record<string, unknown>>('/api/platform/runtime/status'),
  saveModelConfig: (config: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/model-configs', {
      method: 'POST',
      body: JSON.stringify(config),
    }),
  deleteModelConfig: (configId: string) =>
    request<Record<string, unknown>>(`/api/platform/model-configs/${encodeURIComponent(configId)}`, { method: 'DELETE' }),
  testModelConfig: (config: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/model-configs/test', {
      method: 'POST',
      body: JSON.stringify(config),
    }),
  gitCredentials: () => request<Record<string, unknown>[]>('/api/platform/git-credentials'),
  saveGitCredential: (credential: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/git-credentials', {
      method: 'POST', body: JSON.stringify(credential),
    }),
  projectGitRepositories: (projectId?: string) =>
    request<Record<string, unknown>[]>(`/api/platform/project-git-repositories${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`),
  saveProjectGitRepository: (repository: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/project-git-repositories', {
      method: 'POST', body: JSON.stringify(repository),
    }),
  testProjectGitRepository: (repositoryId: string) =>
    request<Record<string, unknown>>('/api/platform/project-git-repositories/test', {
      method: 'POST', body: JSON.stringify({ repository_id: repositoryId }),
    }),
  gitDeliveryConfigs: () => request<Record<string, unknown>[]>('/api/platform/git-delivery-configs'),
  saveGitDeliveryConfig: (config: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/git-delivery-configs', {
      method: 'POST',
      body: JSON.stringify(config),
    }),
  testGitDeliveryConfig: (config: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/git-delivery-configs/test', {
      method: 'POST',
      body: JSON.stringify(config),
    }),
  buildWorkflow: (requirement: string, name?: string, organizationId = 'org_jianghu') =>
    request<Record<string, unknown>>('/api/platform/workflows/build', {
      method: 'POST',
      body: JSON.stringify({ requirement, name, organization_id: organizationId }),
    }),
  createClarification: (workflowId: string, requirement: string) =>
    request<Record<string, unknown>>('/api/platform/clarifications', {
      method: 'POST',
      body: JSON.stringify({ workflow_id: workflowId, requirement }),
    }),
  finalizeClarification: (clarificationId: string, answers: Record<string, string>[]) =>
    request<Record<string, unknown>>(`/api/platform/clarifications/${clarificationId}/finalize`, {
      method: 'POST',
      body: JSON.stringify({ answers }),
    }),
  createPlatformRun: (workflowId: string, task: string, clarificationId?: string, projectId = 'project_jianghu', commissionId?: string, gitDelivery?: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/runs', {
      method: 'POST',
      body: JSON.stringify({
        workflow_id: workflowId, task, project_id: projectId, clarification_id: clarificationId, commission_id: commissionId,
        git_repository_id: gitDelivery?.repository_id, git_target_branch: gitDelivery?.target_branch,
        git_delivery_mode: gitDelivery?.delivery_mode,
      }),
    }),
  bindRunGitDelivery: (runId: string, delivery: Record<string, unknown>, organizationId?: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${encodeURIComponent(runId)}/git-delivery${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`, {
      method: 'POST', body: JSON.stringify(delivery),
    }),
  retryRunGitDelivery: (runId: string, organizationId?: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${encodeURIComponent(runId)}/git-delivery/retry${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`, { method: 'POST' }),
  getPlatformRun: (runId: string, organizationId?: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}?event_limit=300${organizationId ? `&organization_id=${encodeURIComponent(organizationId)}` : ''}`),
  getPlatformRunState: (runId: string, organizationId?: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/state?event_limit=100${organizationId ? `&organization_id=${encodeURIComponent(organizationId)}` : ''}`),
  artifactDownloadUrl: (artifactId: string, organizationId?: string) =>
    `${API_BASE}/api/platform/artifacts/${encodeURIComponent(artifactId)}/download${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`,
  artifactPreviewUrl: (artifactId: string, organizationId?: string) =>
    `${API_BASE}/api/platform/artifacts/${encodeURIComponent(artifactId)}/download?inline=true${organizationId ? `&organization_id=${encodeURIComponent(organizationId)}` : ''}`,
  artifactThumbnailUrl: (artifactId: string, organizationId?: string) =>
    `${API_BASE}/api/platform/artifacts/${encodeURIComponent(artifactId)}/thumbnail${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`,
  artifactContentUrl: (artifactId: string, organizationId?: string) =>
    `${API_BASE}/api/platform/artifacts/${encodeURIComponent(artifactId)}/content${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`,
  artifactDetail: (artifactId: string, organizationId?: string) =>
    request<Record<string, unknown>>(`/api/platform/artifacts/${encodeURIComponent(artifactId)}${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`),
  artifactTextPreview: async (artifactId: string, organizationId?: string, previewBytes = 512_000, resolveContent = false) => {
    const endpoint = resolveContent
      ? `${API_BASE}/api/platform/artifacts/${encodeURIComponent(artifactId)}/content${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`
      : `${API_BASE}/api/platform/artifacts/${encodeURIComponent(artifactId)}/download?inline=true${organizationId ? `&organization_id=${encodeURIComponent(organizationId)}` : ''}`
    const response = await fetch(endpoint, {
      headers: { Range: `bytes=0-${Math.max(1, previewBytes) - 1}` },
    })
    if (!response.ok) throw new Error(response.status === 404 ? '原文件未进入 Artifact 存储，无法预览正文' : `证据正文读取失败（HTTP ${response.status}）`)
    const body = await response.text()
    const contentRange = response.headers.get('content-range')
    return contentRange ? `${body}\n\n—— 页面仅展示 ${contentRange}；可下载原文件查看全部内容。——` : body
  },
  artifactBlobPreview: async (artifactId: string, organizationId?: string, resolveContent = false) => {
    const endpoint = resolveContent
      ? `${API_BASE}/api/platform/artifacts/${encodeURIComponent(artifactId)}/content${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`
      : `${API_BASE}/api/platform/artifacts/${encodeURIComponent(artifactId)}/download?inline=true${organizationId ? `&organization_id=${encodeURIComponent(organizationId)}` : ''}`
    const response = await fetch(endpoint)
    if (!response.ok) throw new Error(response.status === 404 ? '原文件未进入 Artifact 存储，无法在应用内打开' : `文件预览失败（HTTP ${response.status}）`)
    return response.blob()
  },
  startPlatformRun: (runId: string, organizationId?: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/start${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`, { method: 'POST' }),
  retryPlatformRun: (runId: string, fromTaskId?: string, organizationId?: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/retry${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`, {
      method: 'POST', body: JSON.stringify(fromTaskId ? { from_task_id: fromTaskId } : {}),
    }),
  recoverPlatformRun: (runId: string, fromTaskId?: string, organizationId?: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/recover${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`, {
      method: 'POST', body: JSON.stringify(fromTaskId ? { from_task_id: fromTaskId } : {}),
    }),
  cancelPlatformRun: (runId: string, organizationId?: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/cancel${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`, { method: 'POST' }),
  pausePlatformRun: (runId: string, organizationId?: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/pause${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`, { method: 'POST' }),
  resumePlatformRun: (runId: string, organizationId?: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/resume${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`, { method: 'POST' }),
  extendPlatformRun: (runId: string, minutes: number, organizationId?: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/extend${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`, {
      method: 'POST', body: JSON.stringify({ minutes }),
    }),
  intervenePlatformRun: (runId: string, payload: Record<string, unknown>, organizationId?: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/interventions${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  runCodeDownloadUrl: (runId: string, organizationId?: string) =>
    `${API_BASE}/api/platform/runs/${encodeURIComponent(runId)}/code/download${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`,
  gitCommitPatchUrl: (runId: string, commitSha: string, organizationId?: string) =>
    `${API_BASE}/api/platform/runs/${encodeURIComponent(runId)}/git/commits/${encodeURIComponent(commitSha)}/patch${organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''}`,
}
