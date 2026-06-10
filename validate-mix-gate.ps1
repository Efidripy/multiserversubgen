[CmdletBinding()]
param(
    [switch]$NoRun
)

$ErrorActionPreference = "Stop"
$script = "E:\GitHub\workspace\control\scripts\shared\validate-mix-gate.ps1"

$argsList = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $script,
    "-ProjectName", "multiserversubgen"
)

if ($NoRun) {
    $argsList += "-NoRun"
}

& powershell @argsList
exit $LASTEXITCODE
