$ErrorActionPreference = 'Stop'
if (-not $env:ANTHROPIC_BASE_URL) { $env:ANTHROPIC_BASE_URL = 'http://104.194.90.248:58317' }
if (-not $env:ANTHROPIC_DEFAULT_SONNET_MODEL) { $env:ANTHROPIC_DEFAULT_SONNET_MODEL = 'claude-sonnet-4-6' }
if (-not $env:ANTHROPIC_DEFAULT_OPUS_MODEL) { $env:ANTHROPIC_DEFAULT_OPUS_MODEL = $env:ANTHROPIC_DEFAULT_SONNET_MODEL }
if (-not $env:ANTHROPIC_AUTH_TOKEN) {
  throw 'ANTHROPIC_AUTH_TOKEN is not configured in the current environment'
}
$port = if ($args.Count -gt 0) { [int]$args[0] } else { 8000 }
Start-Process -FilePath (Join-Path (Get-Location) '.venv\Scripts\python.exe') `
  -ArgumentList @('-m', 'uvicorn', 'server.app.main:app', '--port', "$port") `
  -WorkingDirectory (Get-Location) -WindowStyle Hidden
Write-Output "Started Jianghu API on port $port with real LLM configuration and no mock fallback."
