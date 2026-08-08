param(
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$packageRoot = Join-Path $repoRoot "dist\jianghu-online-docker-$stamp"
$envFile = Join-Path $repoRoot '.env.docker'
if (-not (Test-Path -LiteralPath $envFile)) {
    $envFile = Join-Path $repoRoot '.env.docker.example'
}
if ([string]::IsNullOrWhiteSpace($env:DOCKER_CONFIG)) {
    $env:DOCKER_CONFIG = Join-Path $repoRoot '.tmp\docker-config'
    New-Item -ItemType Directory -Path $env:DOCKER_CONFIG -Force | Out-Null
}

# Fail closed before creating an uploadable archive. The scanner reports only
# file paths and line numbers; it never prints a matched credential value.
& (Join-Path $PSScriptRoot 'check-no-secrets.ps1') -Root $repoRoot

New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $repoRoot 'compose.yaml') -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $repoRoot 'compose.postgres.yaml') -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $repoRoot '.env.docker.example') -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $repoRoot 'Dockerfile') -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $repoRoot 'docker\PACKAGE-README.md') -Destination (Join-Path $packageRoot 'README.md')

Push-Location $repoRoot
try {
    docker compose --env-file $envFile config --quiet
    if (-not $SkipBuild) {
        docker compose --env-file $envFile build
        docker image save --output (Join-Path $packageRoot 'jianghu-online-image.tar') 'jianghu-online:local'
    }
    # Do not pass the whole server/client directory to bsdtar. On Windows,
    # bsdtar may stat an ACL-protected cache directory before applying its
    # exclude rules. Enumerating only the wanted top-level entries avoids that
    # failure while still packaging uncommitted source changes.
    $serverEntries = Get-ChildItem -LiteralPath (Join-Path $repoRoot 'server') -Force |
        Where-Object { $_.Name -notin @('.pytest_cache', '__pycache__') } |
        ForEach-Object { "server/$($_.Name)" }
    $clientEntries = Get-ChildItem -LiteralPath (Join-Path $repoRoot 'client') -Force |
        Where-Object { $_.Name -notin @('node_modules', 'dist') } |
        ForEach-Object { "client/$($_.Name)" }
    $sourceEntries = @(
        'Dockerfile', '.dockerignore', '.gitignore', 'compose.yaml', 'compose.postgres.yaml',
        '.env.docker.example', 'package.json', 'package-lock.json', 'README.md',
        'scripts', 'docker', 'docs'
    ) + $serverEntries + $clientEntries

    tar.exe -czf (Join-Path $packageRoot 'jianghu-online-source.tar.gz') `
        --exclude='__pycache__' `
        --exclude='*.pyc' `
        -C $repoRoot `
        $sourceEntries
    if ($LASTEXITCODE -ne 0) {
        throw "Source archive failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

$files = Get-ChildItem -LiteralPath $packageRoot -File
$checksums = foreach ($file in $files) {
    $hash = Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256
    "{0}  {1}" -f $hash.Hash.ToLowerInvariant(), $file.Name
}
Set-Content -LiteralPath (Join-Path $packageRoot 'SHA256SUMS.txt') -Value $checksums -Encoding utf8

Write-Output $packageRoot
