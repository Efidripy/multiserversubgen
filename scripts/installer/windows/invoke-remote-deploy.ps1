[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$UserName = "root",

    [int]$Port = 22,

    [ValidateSet("install", "update", "smoke")]
    [string]$Mode = "install",

    [ValidatePattern('^/[A-Za-z0-9._/-]{1,200}$')]
    [string]$RemoteDir = "/opt/multiserversubgen-remote",

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

function Assert-SafeRemotePath {
    param([Parameter(Mandatory = $true)][string]$Path)
    if ($Path -notmatch '^/[A-Za-z0-9._/-]{1,200}$' -or $Path -match '(^|/)\.\.(/|$)' -or $Path -match '//') {
        throw "RemoteDir must be an absolute POSIX path without shell metacharacters or parent traversal."
    }
}

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)][string]$Action,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter()][string[]]$ArgumentList = @()
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE."
    }
}

function New-Archive {
    param(
        [string]$RepoRoot,
        [string]$ArchivePath
    )

    $commit = (& git -C $RepoRoot rev-parse --verify HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $commit) {
        throw "Unable to resolve the immutable source commit."
    }
    $changes = @(& git -C $RepoRoot status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to verify the source worktree state."
    }
    if ($changes.Count -gt 0) {
        throw "Refusing to deploy a dirty source worktree; commit or remove local changes first."
    }

    $leaf = Split-Path $RepoRoot -Leaf
    & git -C $RepoRoot archive --format=tar.gz "--prefix=$leaf/" "--output=$ArchivePath" $commit
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ArchivePath)) {
        throw "Unable to create the source archive from commit $commit."
    }
    return $commit
}

function Get-Transport {
    param(
        [string]$Password,
        [string]$PasswordFile,
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
        if (-not $HostKey) { throw "Password-based PuTTY deployment requires a pinned -HostKey." }
        return @{
            Type         = "putty"
            Plink        = $plink
            Pscp         = $pscp
            HostKey      = $HostKey
            KeyPath      = $KeyPath
            PasswordFile = $PasswordFile
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
        if ($Transport.PasswordFile) { $args += @("-pwfile", $Transport.PasswordFile) }
        $args += "$UserName@$HostName"
        $args += $Command
        Invoke-NativeChecked -Action "PuTTY remote command" -FilePath $Transport.Plink -ArgumentList $args
        return
    }

    $knownHosts = Join-Path $env:USERPROFILE ".ssh\known_hosts"
    if (-not (Test-Path -LiteralPath $knownHosts)) { throw "Pinned OpenSSH known_hosts file is required: $knownHosts" }
    $args = @("-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=$knownHosts", "-p", "$Port")
    if ($Transport.HostKey) { $args += @("-o", "HostKeyAlgorithms=ssh-ed25519,ecdsa-sha2-nistp256,rsa-sha2-512,rsa-sha2-256") }
    if ($Transport.KeyPath) { $args += @("-i", $Transport.KeyPath) }
    $args += "$UserName@$HostName"
    $args += $Command
    Invoke-NativeChecked -Action "OpenSSH remote command" -FilePath $Transport.Ssh -ArgumentList $args
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
        if ($Transport.PasswordFile) { $args += @("-pwfile", $Transport.PasswordFile) }
        $args += $LocalPath
        $args += "${UserName}@${HostName}:$RemotePath"
        Invoke-NativeChecked -Action "PuTTY remote copy" -FilePath $Transport.Pscp -ArgumentList $args
        return
    }

    $knownHosts = Join-Path $env:USERPROFILE ".ssh\known_hosts"
    if (-not (Test-Path -LiteralPath $knownHosts)) { throw "Pinned OpenSSH known_hosts file is required: $knownHosts" }
    $args = @("-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=$knownHosts", "-P", "$Port")
    if ($Transport.KeyPath) { $args += @("-i", $Transport.KeyPath) }
    $args += $LocalPath
    $args += "${UserName}@${HostName}:$RemotePath"
    Invoke-NativeChecked -Action "OpenSSH remote copy" -FilePath $Transport.Scp -ArgumentList $args
}

$repoRoot = Get-RepoRoot
$null = Assert-SafeRemotePath -Path $RemoteDir
$passwordFile = $null
$passwordDirectory = $null
if ($Password) {
    $passwordBase = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { $env:TEMP }
    $passwordDirectory = Join-Path $passwordBase "mssg-secure"
    New-Item -ItemType Directory -Path $passwordDirectory -Force | Out-Null
    $passwordFile = Join-Path $passwordDirectory ("mssg-putty-password-{0}.txt" -f ([guid]::NewGuid().ToString("N")))
    [IO.File]::WriteAllText($passwordFile, $Password, [Text.UTF8Encoding]::new($false))
    $acl = Get-Acl -LiteralPath $passwordFile
    $acl.SetAccessRuleProtection($true, $false)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($identity, "Read", "Allow")
    $acl.SetAccessRule($rule)
    Set-Acl -LiteralPath $passwordFile -AclObject $acl
}
$transport = Get-Transport -Password $Password -PasswordFile $passwordFile -HostKey $HostKey -KeyPath $KeyPath
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runId = [guid]::NewGuid().ToString("N")
$archivePath = Join-Path ([IO.Path]::GetTempPath()) "multiserversubgen-remote-$timestamp-$runId.tar.gz"
$remoteArchive = "/tmp/multiserversubgen-remote-$timestamp-$runId.tar.gz"
$remoteLog = "/tmp/sub-manager-$Mode-$timestamp.log"
$remoteWorkDir = "$RemoteDir-$runId"

try {
    if (-not $SkipSync) {
        Write-Host "Packing committed source archive..."
        $deployCommit = New-Archive -RepoRoot $repoRoot -ArchivePath $archivePath

        Write-Host "Copying source archive to $UserName@$HostName ..."
        Copy-ToRemote -Transport $transport -UserName $UserName -HostName $HostName -Port $Port -Password $Password -LocalPath $archivePath -RemotePath $remoteArchive

        Write-Host "Extracting source tree on remote host..."
        $extractCmd = "bash -lc 'rm -rf -- $remoteWorkDir && mkdir -p -- $remoteWorkDir && tar -xzf -- $remoteArchive -C $remoteWorkDir --strip-components=1 && printf %s\\n $deployCommit > $remoteWorkDir/.deploy-source-commit && chmod 0600 $remoteWorkDir/.deploy-source-commit && rm -f -- $remoteArchive'"
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
            $remoteCmd = "bash -lc 'cd $remoteWorkDir && sudo bash ./install.sh < $remoteAnswers 2>&1 | tee $remoteLog; rc=`${PIPESTATUS[0]}; rm -f $remoteAnswers; exit `$rc'"
            Write-Host "Running remote install..."
            Invoke-RemoteCommand -Transport $transport -UserName $UserName -HostName $HostName -Port $Port -Password $Password -Command $remoteCmd
        }
        "update" {
            $remoteCmd = "bash -lc 'cd $remoteWorkDir && sudo NONINTERACTIVE=true UPDATE_CHOICE=$UpdateChoice bash ./update.sh 2>&1 | tee $remoteLog; exit `${PIPESTATUS[0]}'"
            Write-Host "Running remote update..."
            Invoke-RemoteCommand -Transport $transport -UserName $UserName -HostName $HostName -Port $Port -Password $Password -Command $remoteCmd
        }
        "smoke" {
            $remoteCmd = "bash -lc 'cd $remoteWorkDir && sudo bash scripts/ops/smoke-test.sh 2>&1 | tee $remoteLog; exit `${PIPESTATUS[0]}'"
            Write-Host "Running remote smoke checks..."
            Invoke-RemoteCommand -Transport $transport -UserName $UserName -HostName $HostName -Port $Port -Password $Password -Command $remoteCmd
        }
    }
}
finally {
    if ($passwordFile -and (Test-Path -LiteralPath $passwordFile)) {
        Remove-Item -LiteralPath $passwordFile -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "Remote workdir: $remoteWorkDir"
Write-Host "Remote log: $remoteLog"
