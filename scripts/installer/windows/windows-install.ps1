[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$UserName = "root",

    [int]$Port = 22,

    [string]$Password,

    [string]$KeyPath,

    [string]$HostKey,

    [string]$AnswersFile = ".\scripts\installer\windows\install-answers.example.txt",

    [string]$RemoteDir = "~/multiserversubgen-remote"
)

$ErrorActionPreference = "Stop"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
$deployScript = Join-Path $PSScriptRoot "invoke-remote-deploy.ps1"
$answersPath = Resolve-Path $AnswersFile

$invokeParams = @{
    HostName    = $HostName
    UserName    = $UserName
    Port        = $Port
    Mode        = "install"
    AnswersFile = $answersPath.Path
    RemoteDir   = $RemoteDir
}

if ($Password) { $invokeParams.Password = $Password }
if ($KeyPath) { $invokeParams.KeyPath = $KeyPath }
if ($HostKey) { $invokeParams.HostKey = $HostKey }

& powershell -NoProfile -ExecutionPolicy Bypass -File $deployScript @invokeParams
