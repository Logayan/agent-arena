param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$excludedDirectories = @(
    '.git', '.data', '.tmp', '.venv', '.pytest_cache', 'node_modules',
    'dist', '__pycache__', 'coverage', 'playwright-report', 'test-results'
)
$textExtensions = @(
    '.cfg', '.conf', '.css', '.env', '.example', '.html', '.ini', '.js',
    '.json', '.md', '.mjs', '.ps1', '.py', '.sh', '.toml', '.ts', '.tsx',
    '.txt', '.vue', '.yaml', '.yml'
)
$rootFiles = @(
    '.dockerignore', '.env.docker.example', '.gitignore',
    'compose.yaml', 'compose.postgres.yaml', 'Dockerfile',
    'package.json', 'package-lock.json', 'README.md'
)
$sourceDirectories = @('client', 'docker', 'docs', 'examples', 'scripts', 'server')

function Get-ScannableFiles([string]$directory) {
    try {
        foreach ($file in [IO.Directory]::EnumerateFiles($directory)) {
            if ($textExtensions -contains [IO.Path]::GetExtension($file).ToLowerInvariant() -or [IO.Path]::GetFileName($file) -eq 'Dockerfile') {
                $file
            }
        }
        foreach ($child in [IO.Directory]::EnumerateDirectories($directory)) {
            if ($excludedDirectories -contains [IO.Path]::GetFileName($child)) {
                continue
            }
            Get-ScannableFiles $child
        }
    } catch [UnauthorizedAccessException] {
        return
    }
}

$files = @()
foreach ($name in $rootFiles) {
    $path = Join-Path $rootPath $name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $files += $path
    }
}
foreach ($name in $sourceDirectories) {
    $path = Join-Path $rootPath $name
    if (Test-Path -LiteralPath $path -PathType Container) {
        $files += @(Get-ScannableFiles $path)
    }
}

$credentialAssignment = [regex]::new(
    '(?i)\b(ANTHROPIC_AUTH_TOKEN|OPENAI_API_KEY|OPENAPI_API_KEY|AZURE_OPENAI_API_KEY)\b\s*[:=]\s*["'']?([^"''\s,}]+)'
)
$secretPatterns = @(
    @{ Name = 'OpenAI-style key'; Regex = [regex]::new('(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}') },
    @{ Name = 'vLLM credential'; Regex = [regex]::new('(?<![A-Za-z0-9])vllm-[A-Za-z0-9-]{24,}') },
    @{ Name = 'Bearer credential'; Regex = [regex]::new('(?i)\bBearer\s+[A-Za-z0-9._-]{24,}') }
)
$violations = [Collections.Generic.List[object]]::new()

foreach ($file in ($files | Sort-Object -Unique)) {
    $lineNumber = 0
    foreach ($line in [IO.File]::ReadLines($file)) {
        $lineNumber++
        foreach ($pattern in $secretPatterns) {
            if ($pattern.Regex.IsMatch($line)) {
                $violations.Add([pscustomobject]@{ File = $file; Line = $lineNumber; Reason = $pattern.Name })
            }
        }
        foreach ($match in $credentialAssignment.Matches($line)) {
            $value = $match.Groups[2].Value.Trim()
            $isPlaceholder = [string]::IsNullOrWhiteSpace($value) -or $value -match '^(?i)(your-|replace-|example|sample|test-|unit-test-|dummy|<|\$\{)'
            if (-not $isPlaceholder) {
                $violations.Add([pscustomobject]@{ File = $file; Line = $lineNumber; Reason = 'configured API credential' })
            }
        }
    }
}

if ($violations.Count) {
    Write-Error 'Secret scan failed. Credential-like values were found; values are intentionally not displayed.'
    $violations | Sort-Object File, Line, Reason -Unique | ForEach-Object {
        $relative = [IO.Path]::GetRelativePath($rootPath, $_.File)
        Write-Error ("{0}:{1} [{2}]" -f $relative, $_.Line, $_.Reason)
    }
    exit 1
}

Write-Output 'secret_scan=passed'
