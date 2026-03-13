[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]]$RemainingArgs
)

$target = Join-Path (Join-Path $PSScriptRoot "..\installer\windows") "windows-install.ps1"
& powershell -NoProfile -ExecutionPolicy Bypass -File $target @RemainingArgs
