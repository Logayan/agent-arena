param(
  [string]$BaseUrl = 'http://127.0.0.1:8002',
  [string]$Task = '分析一个社区报修系统并输出可执行的产品、架构和交付方案',
  [int]$PollSeconds = 5,
  [int]$MaxPolls = 60
)
$ErrorActionPreference = 'Stop'

$status = Invoke-RestMethod "$BaseUrl/api/platform/llm/status"
if (-not $status.configured -or $status.mock_fallback) {
  throw 'Real LLM is not configured or mock fallback is enabled.'
}
$workflows = @(Invoke-RestMethod "$BaseUrl/api/platform/workflows")
if ($workflows.Count -eq 0) { throw 'No persisted workflow is available.' }
$workflow = $workflows[0]
$payload = @{ workflow_id = $workflow.id; task = $Task; project_id = 'project_jianghu' } | ConvertTo-Json
$created = Invoke-RestMethod "$BaseUrl/api/platform/runs" -Method Post -ContentType 'application/json' -Body $payload
$runId = $created.run.id
Invoke-RestMethod "$BaseUrl/api/platform/runs/$runId/start" -Method Post | Out-Null

for ($i = 0; $i -lt $MaxPolls; $i++) {
  Start-Sleep -Seconds $PollSeconds
  $snapshot = Invoke-RestMethod "$BaseUrl/api/platform/runs/$runId"
  $run = $snapshot.run
  Write-Output "status=$($run.status) progress=$($run.progress)% tasks=$($run.tasks.Count) artifacts=$($run.artifacts.Count) tokens=$($run.token_count)"
  if ($run.status -in @('completed', 'failed', 'cancelled')) { break }
}

if ($run.status -ne 'completed') {
  $failure = @($run.events | Where-Object { $_.type -eq 'run.failed' -or $_.type -eq 'task.failed' } | Select-Object -Last 1)
  if ($failure) { Write-Error "Real platform run failed: $($failure.summary)" }
  throw "Real platform run ended with status '$($run.status)'."
}
if ($run.artifacts.Count -eq 0) { throw 'Completed run has no persisted artifacts.' }
Write-Output "REAL_PLATFORM_OK run=$runId model=$($status.model) artifacts=$($run.artifacts.Count) tokens=$($run.token_count)"
