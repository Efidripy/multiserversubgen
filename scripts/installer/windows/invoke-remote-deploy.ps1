[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$UserName = "root",

    [int]$Port = 22,

    [ValidateSet("install", "update", "smoke")]
    [string]$Mode = "install",

    [string]$RemoteDir = "~/multiserversubgen-remote",

    [string]$Password,

    [string]$HostKey,

    [string]$KeyPath,

    [string]$AnswersFile,

    [ValidateRange(1, 5)]
    [int]$UpdateChoice = 1,

    [switch]$SkipSync
)

$ErrorActionPreference = "Stop"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

function Get-RepoRoot {
    $root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
    return $root.Path
}

function Get-CommandPathOrNull {
    param([string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function New-Archive {
    param(
        [string]$RepoRoot,
        [string]$ArchivePath
    )

    if (Test-Path $ArchivePath) {
        Remove-Item -Force $ArchivePath
    }

    $parent = Split-Path $RepoRoot -Parent
    $leaf = Split-Path $RepoRoot -Leaf
    Push-Location $parent
    try {
        & tar `
            --exclude="$leaf/.git" `
            --exclude="$leaf/.venv" `
            --exclude="$leaf/frontend/node_modules" `
            --exclude="$leaf/.tmp" `
            --exclude="$leaf/.local_snapshots" `
            --exclude="$leaf/.local_project_docs" `
            -czf $ArchivePath $leaf
    }
    finally {
        Pop-Location
    }
}

function Get-Transport {
    param(
        [string]$Password,
        [string]$HostKey,
        [string]$KeyPath
    )

    $plink = Get-CommandPathOrNull "plink.exe"
    $pscp = Get-CommandPathOrNull "pscp.exe"
    $ssh = Get-CommandPathOrNull "ssh.exe"
    $scp = Get-CommandPathOrNull "scp.exe"

    if ($Password) {
        if (-not $plink -or -not $pscp) {
            throw "For password-based deployment install PuTTY tools (plink.exe and pscp.exe), or use key-based OpenSSH."
        }
        return @{
            Type    = "putty"
            Plink   = $plink
            Pscp    = $pscp
            HostKey = $HostKey
            KeyPath = $KeyPath
        }
    }

    if (-not $ssh -or -not $scp) {
        throw "OpenSSH ssh.exe/scp.exe not found."
    }

    return @{
        Type    = "openssh"
        Ssh     = $ssh
        Scp     = $scp
        HostKey = $HostKey
        KeyPath = $KeyPath
    }
}

function Invoke-RemoteCommand {
    param(
        [hashtable]$Transport,
        [string]$UserName,
        [string]$HostName,
        [int]$Port,
        [string]$Password,
        [string]$Command
    )

    if ($Transport.Type -eq "putty") {
        $args = @("-ssh", "-batch", "-P", "$Port")
        if ($Transport.HostKey) { $args += @("-hostkey", $Transport.HostKey) }
        if ($Transport.KeyPath) { $args += @("-i", $Transport.KeyPath) }
        if ($Password) { $args += @("-pw", $Password) }
        $args += "$UserName@$HostName"
        $args += $Command
        & $Transport.Plink @args
        return
    }

    $args = @("-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-p", "$Port")
    if ($Transport.HostKey) { $args += @("-o", "HostKeyAlgorithms=ssh-ed25519,ecdsa-sha2-nistp256,rsa-sha2-512,rsa-sha2-256") }
    if ($Transport.KeyPath) { $args += @("-i", $Transport.KeyPath) }
    $args += "$UserName@$HostName"
    $args += $Command
    & $Transport.Ssh @args
}

function Copy-ToRemote {
    param(
        [hashtable]$Transport,
        [string]$UserName,
        [string]$HostName,
        [int]$Port,
        [string]$Password,
        [string]$LocalPath,
        [string]$RemotePath
    )

    if ($Transport.Type -eq "putty") {
        $args = @("-batch", "-P", "$Port")
        if ($Transport.HostKey) { $args += @("-hostkey", $Transport.HostKey) }
        if ($Transport.KeyPath) { $args += @("-i", $Transport.KeyPath) }
        if ($Password) { $args += @("-pw", $Password) }
        $args += $LocalPath
        $args += "${UserName}@${HostName}:$RemotePath"
        & $Transport.Pscp @args
        return
    }

    $args = @("-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-P", "$Port")
    if ($Transport.KeyPath) { $args += @("-i", $Transport.KeyPath) }
    $args += $LocalPath
    $args += "${UserName}@${HostName}:$RemotePath"
    & $Transport.Scp @args
}

$repoRoot = Get-RepoRoot
$transport = Get-Transport -Password $Password -HostKey $HostKey -KeyPath $KeyPath
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runId = [guid]::NewGuid().ToString("N")
$archivePath = Join-Path ([IO.Path]::GetTempPath()) "multiserversubgen-remote-$timestamp-$runId.tar.gz"
$remoteArchive = "/tmp/multiserversubgen-remote-$timestamp-$runId.tar.gz"
$remoteLog = "/tmp/sub-manager-$Mode-$timestamp.log"
$remoteWorkDir = "$RemoteDir-$runId"

if (-not $SkipSync) {
    Write-Host "Packing current source tree..."
    New-Archive -RepoRoot $repoRoot -ArchivePath $archivePath

    Write-Host "Copying source archive to $UserName@$HostName ..."
    Copy-ToRemote -Transport $transport -UserName $UserName -HostName $HostName -Port $Port -Password $Password -LocalPath $archivePath -RemotePath $remoteArchive

    Write-Host "Extracting source tree on remote host..."
    $extractCmd = "bash -lc 'rm -rf $remoteWorkDir && mkdir -p $remoteWorkDir && tar -xzf $remoteArchive -C $remoteWorkDir --strip-components=1 && rm -f $remoteArchive'"
    Invoke-RemoteCommand -Transport $transport -UserName $UserName -HostName $HostName -Port $Port -Password $Password -Command $extractCmd
}

switch ($Mode) {
    "install" {
        if (-not $AnswersFile) {
            throw "Mode=install requires -AnswersFile."
        }
        $answersResolved = (Resolve-Path $AnswersFile).Path
        $remoteAnswers = "/tmp/sub-manager-install-answers-$timestamp.txt"
        Write-Host "Copying install answers file..."
        Copy-ToRemote -Transport $transport -UserName $UserName -HostName $HostName -Port $Port -Password $Password -LocalPath $answersResolved -RemotePath $remoteAnswers
        $remoteCmd = "bash -lc 'cd $remoteWorkDir && sudo bash -x ./install.sh < $remoteAnswers 2>&1 | tee $remoteLog; rc=`${PIPESTATUS[0]}; rm -f $remoteAnswers; exit `$rc'"
        Write-Host "Running remote install..."
        Invoke-RemoteCommand -Transport $transport -UserName $UserName -HostName $HostName -Port $Port -Password $Password -Command $remoteCmd
    }
    "update" {
        $remoteCmd = "bash -lc 'cd $remoteWorkDir && sudo NONINTERACTIVE=true UPDATE_CHOICE=$UpdateChoice bash -x ./update.sh 2>&1 | tee $remoteLog; exit `${PIPESTATUS[0]}'"
        Write-Host "Running remote update..."
        Invoke-RemoteCommand -Transport $transport -UserName $UserName -HostName $HostName -Port $Port -Password $Password -Command $remoteCmd
    }
    "smoke" {
        $remoteCmd = "bash -lc 'cd $remoteWorkDir && sudo bash scripts/ops/smoke-test.sh 2>&1 | tee $remoteLog; exit `${PIPESTATUS[0]}'"
        Write-Host "Running remote smoke checks..."
        Invoke-RemoteCommand -Transport $transport -UserName $UserName -HostName $HostName -Port $Port -Password $Password -Command $remoteCmd
    }
}

Write-Host ""
Write-Host "Remote workdir: $remoteWorkDir"
Write-Host "Remote log: $remoteLog"
