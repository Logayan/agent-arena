param(
    [switch]$Build,
    [switch]$Postgres
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$envFile = Join-Path $repoRoot '.env.docker'
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $repoRoot '.env.docker.example') -Destination $envFile
    Write-Warning '已创建 .env.docker；如使用 PostgreSQL，请先修改其中的密码。'
}
if ([string]::IsNullOrWhiteSpace($env:DOCKER_CONFIG)) {
    $env:DOCKER_CONFIG = Join-Path $repoRoot '.tmp\docker-config'
    New-Item -ItemType Directory -Path $env:DOCKER_CONFIG -Force | Out-Null
}

$composeArgs = @('compose', '--env-file', $envFile, '-f', (Join-Path $repoRoot 'compose.yaml'))
if ($Postgres) {
    $composeArgs += @('-f', (Join-Path $repoRoot 'compose.postgres.yaml'))
}
$composeArgs += @('up', '-d')
if ($Build) {
    $composeArgs += '--build'
}

& docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    throw "docker compose failed with exit code $LASTEXITCODE"
}
& docker compose --env-file $envFile -f (Join-Path $repoRoot 'compose.yaml') ps
