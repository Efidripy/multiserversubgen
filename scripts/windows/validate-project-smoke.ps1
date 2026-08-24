[CmdletBinding()]
param(
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $RepoRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
}

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
            continue
        }

        $key, $value = $trimmed -split "=", 2
        $key = $key.Trim()
        if (-not $key -or (Test-Path "Env:\$key")) {
            continue
        }

        $value = $value.Trim().Trim('"').Trim("'")
        Set-Item -Path "Env:\$key" -Value $value
    }
}

function Normalize-BasePath {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value -eq "/") {
        return "/"
    }

    $path = $Value.Trim()
    if ($path -match '^https?://') {
        $path = ([Uri]$path).AbsolutePath
    }

    $path = $path.Trim("/")
    if (-not $path) {
        return "/"
    }

    return "/$path/"
}

function Get-BasePathFromConfig {
    if (-not [string]::IsNullOrWhiteSpace($env:PLAYWRIGHT_BASE_URL)) {
        return Normalize-BasePath ([Uri]$env:PLAYWRIGHT_BASE_URL).AbsolutePath
    }

    if (-not [string]::IsNullOrWhiteSpace($env:VITE_BASE)) {
        return Normalize-BasePath $env:VITE_BASE
    }

    if (-not [string]::IsNullOrWhiteSpace($env:WEB_PATH)) {
        return Normalize-BasePath $env:WEB_PATH
    }

    return "/mssg/"
}

Import-DotEnv -Path (Join-Path $RepoRoot ".env")
Import-DotEnv -Path (Join-Path $RepoRoot "frontend\.env")
Import-DotEnv -Path (Join-Path $RepoRoot "backend\.env")

$basePath = Get-BasePathFromConfig
$env:VITE_BASE = $basePath

Write-Host "Project smoke: building frontend with VITE_BASE=$basePath"
Push-Location (Join-Path $RepoRoot "frontend")
try {
    & npm run build
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}

$indexPath = Join-Path $RepoRoot "backend\build\index.html"
if (-not (Test-Path -LiteralPath $indexPath)) {
    throw "Frontend build did not produce backend\build\index.html"
}

$indexHtml = Get-Content -LiteralPath $indexPath -Raw
$expectedAssetPrefix = if ($basePath -eq "/") { "/assets/" } else { "${basePath}assets/" }
if ($indexHtml -notmatch [regex]::Escape($expectedAssetPrefix)) {
    throw "Built index.html does not reference expected asset prefix: $expectedAssetPrefix"
}

if (-not [string]::IsNullOrWhiteSpace($env:PLAYWRIGHT_BASE_URL)) {
    $target = $env:PLAYWRIGHT_BASE_URL.TrimEnd("/") + "/"
    Write-Host "Project smoke: checking configured panel URL"
    $httpCode = & curl.exe -k -L --max-time 10 -o NUL -s -w "%{http_code}" $target
    if ($LASTEXITCODE -ne 0 -and [string]::IsNullOrWhiteSpace($httpCode)) {
        throw "curl.exe failed for $target"
    }
    if ($httpCode -notin @("200", "301", "302", "401")) {
        throw "Unexpected HTTP $httpCode"
    }
}

Write-Host "Project smoke: ok"
