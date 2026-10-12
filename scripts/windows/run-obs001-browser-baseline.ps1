[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
if ($Port -lt 1024 -or $Port -gt 65535) { throw "OBS-001 fixture port must be between 1024 and 65535" }
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }
$fixture = Join-Path $RepoRoot "scripts\observability_browser_fixture.py"
if (-not (Test-Path -LiteralPath $fixture)) { throw "OBS-001 fixture is missing" }
$baseUrl = "http://127.0.0.1:$Port"
$baseUri = [Uri]$baseUrl
if (-not $baseUri.IsLoopback -or $baseUri.Host -ne "127.0.0.1") { throw "OBS-001 target must be IPv4 loopback" }

$env:OBSERVABILITY_ATTRIBUTION_ENABLED = "true"
$playwrightCli = "C:/Users/xman/.codex/skills/playwright/scripts/playwright_cli.sh"
$gitBash = "E:\Git\bin\bash.exe"
$artifactRoot = Join-Path ([IO.Path]::GetTempPath()) ("mssg-obs001-browser-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
$fixtureProcess = $null
$browserStarted = $false
$artifactLocationPushed = $false

function Invoke-PlaywrightStep {
    param([Parameter(Mandatory)][string]$Arguments, [Parameter(Mandatory)][string]$Step)
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & $gitBash --noprofile --norc -lc "$playwrightCli --session mssg-obs001 $Arguments" 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorAction
    if ($exitCode -ne 0) { throw "OBS-001 Playwright step '$Step' failed with exit code $exitCode" }
    return $output
}

function Assert-Snapshot {
    param([string]$Snapshot, [string]$Scenario, [string]$ExpectedSource)
    if ($Snapshot -notmatch "OBS-001 local baseline") { throw "OBS-001 $Scenario headed snapshot missing fixture heading" }
    if ($Snapshot -notmatch "fixture_snapshot") { throw "OBS-001 $Scenario snapshot missing dashboard response" }
    if ($Snapshot -notmatch $ExpectedSource) { throw "OBS-001 $Scenario snapshot missing expected policy source $ExpectedSource" }
}

try {
    Push-Location $artifactRoot
    $artifactLocationPushed = $true
    $fixtureProcess = Start-Process -FilePath python -ArgumentList @($fixture, "--port", "$Port") -WorkingDirectory $RepoRoot -WindowStyle Hidden -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    $ready = $null
    do {
        try { $ready = Invoke-RestMethod -Uri "$baseUrl/baseline-report" -TimeoutSec 1; break }
        catch { Start-Sleep -Milliseconds 250 }
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($null -eq $ready) { throw "OBS-001 loopback fixture did not become ready" }

    $cold = Invoke-PlaywrightStep -Arguments "open $baseUrl/?scenario=cold --headed" -Step "open cold"
    $browserStarted = $true
    Start-Sleep -Milliseconds 500
    $coldSnapshot = Invoke-PlaywrightStep -Arguments "snapshot" -Step "snapshot cold"
    Assert-Snapshot -Snapshot $coldSnapshot -Scenario "cold" -ExpectedSource "memory_miss"

    $warm = Invoke-PlaywrightStep -Arguments "open $baseUrl/?scenario=warm --headed" -Step "open warm"
    Start-Sleep -Milliseconds 500
    $warmSnapshot = Invoke-PlaywrightStep -Arguments "snapshot" -Step "snapshot warm"
    Assert-Snapshot -Snapshot $warmSnapshot -Scenario "warm" -ExpectedSource "memory_fresh"

    $requests = Invoke-PlaywrightStep -Arguments "requests" -Step "request capture"
    if ($requests -match "https?://(?!127\.0\.0\.1|localhost)") { throw "OBS-001 browser observed non-loopback network URL" }

    $report = Invoke-RestMethod -Uri "$baseUrl/baseline-report" -TimeoutSec 5
    if ($report.fake_node_calls -ne 0) { throw "OBS-001 fake-node invariant failed" }
    if (@($report.unexpected_fixture_requests).Count -ne 0) { throw "OBS-001 unexpected fixture request observed" }
    $coldReads = @($report.policy_reads | Where-Object { $_.scenario -eq "cold" })
    $warmReads = @($report.policy_reads | Where-Object { $_.scenario -eq "warm" })
    if ($coldReads.Count -ne 1 -or $coldReads[0].cache_source -ne "memory_miss") { throw "OBS-001 cold policy evidence invalid" }
    if ($warmReads.Count -ne 1 -or $warmReads[0].cache_source -ne "memory_fresh") { throw "OBS-001 warm policy evidence invalid" }
    Write-Output "OBS-001 local headed browser baseline passed"
}
finally {
    if ($browserStarted) {
        try { Invoke-PlaywrightStep -Arguments "close" -Step "close browser" | Out-Null } catch { Write-Warning $_ }
    if ($artifactLocationPushed) { Pop-Location; $artifactLocationPushed = $false }
    }
    if ($null -ne $fixtureProcess -and -not $fixtureProcess.HasExited) { Stop-Process -Id $fixtureProcess.Id -Force }
    if (Test-Path -LiteralPath $artifactRoot) { Remove-Item -LiteralPath $artifactRoot -Recurse -Force }
    if (Test-Path -LiteralPath $artifactRoot) { throw "OBS-001 temporary artifact cleanup failed" }
}