[CmdletBinding()]
param(
    [string]$Target = 'vm3',
    [switch]$DryRun,
    [switch]$Execute,
    [string]$HostName = 'vm3-host-from-targets.local',
    [string]$UserName = 'root',
    [int]$Port = 22,
    [string]$KeyPath = '',
    [string]$HostKey = '',
    [string]$AnswersFile = '',
    [string]$RemoteDir = '/opt/multiserversubgen-remote',
    [string]$ProjectDir = '/opt/sub-manager'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($Target -ne 'vm3') {
    Write-Error "vm3-scenarios.ps1 accepts only -Target vm3; refusing '$Target'."
    exit 2
}
if ($DryRun -and $Execute) {
    Write-Error 'Choose either -DryRun or -Execute, not both.'
    exit 2
}
if (-not $Execute) {
    $DryRun = $true
}
if ($Execute -and ($HostName -eq 'vm3-host-from-targets.local' -or [string]::IsNullOrWhiteSpace($HostName))) {
    Write-Error 'Pass the real vm3 host with -HostName when using -Execute.'
    exit 2
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$deployScript = Join-Path $repoRoot 'scripts\deploy\deploy.ps1'
$installScript = Join-Path $repoRoot 'scripts\installer\windows\windows-install.ps1'
$updateScript = Join-Path $repoRoot 'scripts\installer\windows\windows-update.ps1'
$smokeScript = Join-Path $repoRoot 'scripts\installer\windows\windows-smoke.ps1'
$answersPath = if ($AnswersFile) { (Resolve-Path $AnswersFile).Path } else { Join-Path $PSScriptRoot 'install-answers.example.txt' }

function Format-Argument {
    param([string]$Value)
    if ($Value -match '[\s''"]') { return "'$($Value.Replace("'", "''"))'" }
    return $Value
}

function Show-Command {
    param([string]$Name, [string]$Command)
    Write-Host "[$Name]"
    if ($DryRun) {
        Write-Host "  DRY-RUN: $Command"
    } else {
        Write-Host "  EXECUTE: $Command"
    }
}

function Invoke-PowerShellScript {
    param([string]$Path, [string[]]$Arguments)
    & pwsh -NoProfile -ExecutionPolicy Bypass -File $Path @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$(Split-Path -Leaf $Path) failed with exit code $LASTEXITCODE."
    }
}

function Invoke-RemoteRemove {
    $ssh = @('-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-p', "$Port")
    if ($KeyPath) { $ssh += @('-i', $KeyPath) }
    $remote = "$UserName@$HostName"
    $command = "sudo REMOVE_MODE=keep-db REMOVE_SCOPE=soft bash $ProjectDir/scripts/installer/remove.sh"
    & ssh @ssh $remote $command
    if ($LASTEXITCODE -ne 0) {
        throw "remove.sh failed with exit code $LASTEXITCODE."
    }
}

$common = @('-HostName', $HostName, '-UserName', $UserName, '-Port', "$Port", '-RemoteDir', $RemoteDir)
if ($KeyPath) { $common += @('-KeyPath', $KeyPath) }
if ($HostKey) { $common += @('-HostKey', $HostKey) }
$installArgs = $common + @('-AnswersFile', $answersPath)
$updateArgs = $common + @('-UpdateChoice', '1')
$smokeArgs = $common

$commands = @(
    @('preflight', "pwsh -NoProfile -File scripts/deploy/deploy.ps1 -Target vm3 -DryRun", 'preflight'),
    @('clean install', "pwsh -NoProfile -File scripts/installer/windows/windows-install.ps1 $(($installArgs | ForEach-Object { Format-Argument $_ }) -join ' ')", $installArgs),
    @('smoke after install', "pwsh -NoProfile -File scripts/installer/windows/windows-smoke.ps1 $(($smokeArgs | ForEach-Object { Format-Argument $_ }) -join ' ')", $smokeArgs),
    @('update over the installation', "pwsh -NoProfile -File scripts/installer/windows/windows-update.ps1 $(($updateArgs | ForEach-Object { Format-Argument $_ }) -join ' ')", $updateArgs),
    @('smoke after update', "pwsh -NoProfile -File scripts/installer/windows/windows-smoke.ps1 $(($smokeArgs | ForEach-Object { Format-Argument $_ }) -join ' ')", $smokeArgs),
    @('remove (soft, keep-db)', "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -p $Port $UserName@$HostName `"sudo REMOVE_MODE=keep-db REMOVE_SCOPE=soft bash $ProjectDir/scripts/installer/remove.sh`"", 'remove'),
    @('reinstall', "pwsh -NoProfile -File scripts/installer/windows/windows-install.ps1 $(($installArgs | ForEach-Object { Format-Argument $_ }) -join ' ')", $installArgs),
    @('final smoke', "pwsh -NoProfile -File scripts/installer/windows/windows-smoke.ps1 $(($smokeArgs | ForEach-Object { Format-Argument $_ }) -join ' ')", $smokeArgs)
)

Write-Host "vm3 scenario runner (target locked to vm3; dry-run=$DryRun)"
foreach ($entry in $commands) {
    Show-Command -Name $entry[0] -Command $entry[1]
    if (-not $Execute) { continue }
    switch ($entry[2]) {
        'preflight' { Invoke-PowerShellScript -Path $deployScript -Arguments @('-Target', 'vm3', '-DryRun') }
        'remove' { Invoke-RemoteRemove }
        default {
            $scriptPath = switch ($entry[0]) {
                'clean install' { $installScript }
                'smoke after install' { $smokeScript }
                'smoke after update' { $smokeScript }
                'reinstall' { $installScript }
                'final smoke' { $smokeScript }
                default { $updateScript }
            }
            Invoke-PowerShellScript -Path $scriptPath -Arguments $entry[2]
        }
    }
}

Write-Host 'Health-failure/auto-rollback remains a manual checkpoint; see docs/INSTALLER-VM3-CHECKLIST.md.'
