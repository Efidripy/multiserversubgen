[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$UserName = "root",

    [int]$Port = 22,

    [string]$Password,

    [string]$KeyPath,

    [string]$HostKey,

    [ValidateRange(1, 5)]
    [int]$UpdateChoice = 1,

    [string]$RemoteDir = "~/multiserversubgen-remote"
)

$ErrorActionPreference = "Stop"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
$deployScript = Join-Path $PSScriptRoot "invoke-remote-deploy.ps1"

$invokeParams = @{
    HostName     = $HostName
    UserName     = $UserName
    Port         = $Port
    Mode         = "update"
    UpdateChoice = $UpdateChoice
    RemoteDir    = $RemoteDir
}

if ($Password) { $invokeParams.Password = $Password }
if ($KeyPath) { $invokeParams.KeyPath = $KeyPath }
if ($HostKey) { $invokeParams.HostKey = $HostKey }

& powershell -NoProfile -ExecutionPolicy Bypass -File $deployScript @invokeParams
