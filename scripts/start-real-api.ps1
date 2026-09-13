param(
  [int]$Port = 8003,
  [int]$AgentTimeoutSeconds = 1800,
  [int]$AgentTimeoutMaxSeconds = 14400,
  [int]$AgentTimeoutRetryMultiplier = 2,
  [int]$ClaudeMaxTurns = 100,
  [int]$MaxRunMinutes = 720,
  [string]$LogDirectory = '.data\logs'
)

$ErrorActionPreference = 'Stop'

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $workspaceRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
  throw "Python runtime not found: $pythonPath"
}

$existingListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existingListener) {
  throw "Port $Port is already listening (PID $($existingListener.OwningProcess))."
}

$resolvedLogDirectory = if ([IO.Path]::IsPathRooted($LogDirectory)) {
  $LogDirectory
} else {
  Join-Path $workspaceRoot $LogDirectory
}
New-Item -ItemType Directory -Path $resolvedLogDirectory -Force | Out-Null
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stdoutPath = Join-Path $resolvedLogDirectory "uvicorn-$Port-$timestamp.stdout.log"
$stderrPath = Join-Path $resolvedLogDirectory "uvicorn-$Port-$timestamp.stderr.log"

# Provider URL, model and encrypted token remain in the platform database.
# The launcher only selects the Runtime and bounded execution budgets.
$env:JIANGHU_AGENT_RUNTIME = 'claude_code'
$env:JIANGHU_AGENT_TIMEOUT_SECONDS = [string]$AgentTimeoutSeconds
$env:JIANGHU_AGENT_TIMEOUT_MAX_SECONDS = [string]$AgentTimeoutMaxSeconds
$env:JIANGHU_AGENT_TIMEOUT_RETRY_MULTIPLIER = [string]$AgentTimeoutRetryMultiplier
$env:JIANGHU_CLAUDE_MAX_TURNS = [string]$ClaudeMaxTurns
$env:JIANGHU_MAX_RUN_MINUTES = [string]$MaxRunMinutes
$env:PYTHONUNBUFFERED = '1'

$process = Start-Process -FilePath $pythonPath `
  -ArgumentList @('-m', 'uvicorn', 'server.app.main:app', '--host', '127.0.0.1', '--port', [string]$Port) `
  -WorkingDirectory $workspaceRoot `
  -WindowStyle Hidden `
  -RedirectStandardOutput $stdoutPath `
  -RedirectStandardError $stderrPath `
  -PassThru

[pscustomobject]@{
  ProcessId = $process.Id
  Port = $Port
  Runtime = 'claude_code'
  AgentTimeoutSeconds = $AgentTimeoutSeconds
  AgentTimeoutMaxSeconds = $AgentTimeoutMaxSeconds
  AgentTimeoutRetryMultiplier = $AgentTimeoutRetryMultiplier
  ClaudeMaxTurns = $ClaudeMaxTurns
  MaxRunMinutes = $MaxRunMinutes
  StdoutLog = $stdoutPath
  StderrLog = $stderrPath
}
