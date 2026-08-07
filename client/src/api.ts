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
  platformOverview: () => request<Record<string, unknown>>('/api/platform/overview'),
  organizations: () => request<Record<string, unknown>[]>('/api/platform/organizations'),
  platformProjects: () => request<Record<string, unknown>[]>('/api/platform/projects'),
  platformRuns: () => request<Record<string, unknown>[]>('/api/platform/runs'),
  platformAgents: () => request<Record<string, unknown>[]>('/api/platform/agents'),
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
  assessCommission: (title: string, description: string, organizationId = 'org_jianghu', commissionId?: string) =>
    request<Record<string, unknown>>('/api/platform/commissions/assess', {
      method: 'POST',
      body: JSON.stringify({ title, description, organization_id: organizationId, commission_id: commissionId }),
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
  platformWorkflows: () => request<Record<string, unknown>[]>('/api/platform/workflows'),
  reviseWorkflow: (workflowId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/platform/workflows/${workflowId}/revisions`, { method: 'POST', body: JSON.stringify(payload) }),
  deleteWorkflow: (workflowId: string) =>
    request<Record<string, unknown>>(`/api/platform/workflows/${encodeURIComponent(workflowId)}`, { method: 'DELETE' }),
  knowledgeSources: () => request<Record<string, unknown>[]>('/api/platform/knowledge-sources'),
  knowledgeSourcesPage: (scopeType: 'organization' | 'team', scopeId: string, offset = 0, limit = 20) =>
    request<Record<string, unknown>>(`/api/platform/knowledge-sources/page?scope_type=${encodeURIComponent(scopeType)}&scope_id=${encodeURIComponent(scopeId)}&offset=${offset}&limit=${limit}`),
  knowledgeSourceDetail: (sourceId: string, offset = 0, limit = 50) =>
    request<Record<string, unknown>>(`/api/platform/knowledge-sources/${encodeURIComponent(sourceId)}?offset=${offset}&limit=${limit}`),
  createKnowledgeSource: (source: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/knowledge-sources', {
      method: 'POST',
      body: JSON.stringify(source),
    }),
  knowledgeDownloadUrl: (sourceId: string) =>
    `${API_BASE}/api/platform/knowledge-sources/${encodeURIComponent(sourceId)}/download`,
  marketplace: () => request<Record<string, unknown>>('/api/platform/marketplace'),
  modelConfigs: () => request<Record<string, unknown>[]>('/api/platform/model-configs'),
  openClawStatus: () => request<Record<string, unknown>>('/api/platform/openclaw/status'),
  saveModelConfig: (config: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/model-configs', {
      method: 'POST',
      body: JSON.stringify(config),
    }),
  testModelConfig: (config: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/platform/model-configs/test', {
      method: 'POST',
      body: JSON.stringify(config),
    }),
  buildWorkflow: (requirement: string, name?: string) =>
    request<Record<string, unknown>>('/api/platform/workflows/build', {
      method: 'POST',
      body: JSON.stringify({ requirement, name }),
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
  createPlatformRun: (workflowId: string, task: string, clarificationId?: string, projectId = 'project_jianghu', commissionId?: string) =>
    request<Record<string, unknown>>('/api/platform/runs', {
      method: 'POST',
      body: JSON.stringify({ workflow_id: workflowId, task, project_id: projectId, clarification_id: clarificationId, commission_id: commissionId }),
    }),
  getPlatformRun: (runId: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}`),
  artifactDownloadUrl: (artifactId: string) =>
    `${API_BASE}/api/platform/artifacts/${encodeURIComponent(artifactId)}/download`,
  startPlatformRun: (runId: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/start`, { method: 'POST' }),
  retryPlatformRun: (runId: string, fromTaskId?: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/retry`, {
      method: 'POST', body: JSON.stringify(fromTaskId ? { from_task_id: fromTaskId } : {}),
    }),
  cancelPlatformRun: (runId: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/cancel`, { method: 'POST' }),
  pausePlatformRun: (runId: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/pause`, { method: 'POST' }),
  resumePlatformRun: (runId: string) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/resume`, { method: 'POST' }),
  intervenePlatformRun: (runId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/platform/runs/${runId}/interventions`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  runCodeDownloadUrl: (runId: string) =>
    `${API_BASE}/api/platform/runs/${encodeURIComponent(runId)}/code/download`,
}
