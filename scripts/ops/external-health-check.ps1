[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Run this from a Windows external observer, not from the deployed VM. This
# script intentionally relies on the operating system DNS resolver and the
# default Windows certificate validation policy.
function Get-RequiredEnvironmentInteger {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [int]$DefaultValue,
        [Parameter(Mandatory = $true)]
        [bool]$AllowZero
    )

    $rawValue = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($rawValue)) {
        return $DefaultValue
    }

    if ($rawValue -notmatch '^[0-9]+$') {
        throw "$Name must be a $(if ($AllowZero) { 'non-negative' } else { 'positive' }) integer"
    }

    $parsedValue = 0
    if (-not [int]::TryParse($rawValue, [ref]$parsedValue) -or ($AllowZero -and $parsedValue -lt 0) -or (-not $AllowZero -and $parsedValue -lt 1)) {
        throw "$Name must be a $(if ($AllowZero) { 'non-negative' } else { 'positive' }) integer"
    }

    return $parsedValue
}

function ConvertTo-CanonicalPublicBaseUri {
    param(
        [AllowEmptyString()]
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "PUBLIC_BASE_URL is required"
    }

    try {
        $uri = [System.Uri]$Value
    }
    catch {
        throw "PUBLIC_BASE_URL must be an HTTPS FQDN without credentials, query or fragment"
    }

    if (
        -not $uri.IsAbsoluteUri -or
        $uri.Scheme -ne "https" -or
        [string]::IsNullOrEmpty($uri.DnsSafeHost) -or
        -not [string]::IsNullOrEmpty($uri.UserInfo) -or
        -not [string]::IsNullOrEmpty($uri.Query) -or
        -not [string]::IsNullOrEmpty($uri.Fragment)
    ) {
        throw "PUBLIC_BASE_URL must be an HTTPS FQDN without credentials, query or fragment"
    }

    $fqdn = $uri.DnsSafeHost.TrimEnd('.')
    $ipAddress = $null
    if ([System.Net.IPAddress]::TryParse($fqdn, [ref]$ipAddress)) {
        throw "PUBLIC_BASE_URL must be an HTTPS FQDN without credentials, query or fragment"
    }

    $labels = $fqdn.Split('.')
    $labelPattern = '^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$'
    if (
        $fqdn.Length -gt 253 -or
        $labels.Count -lt 2 -or
        @($labels | Where-Object { $_.Length -eq 0 -or $_ -notmatch $labelPattern }).Count -gt 0
    ) {
        throw "PUBLIC_BASE_URL must be an HTTPS FQDN without credentials, query or fragment"
    }

    return $uri
}

$publicBaseUrl = [Environment]::GetEnvironmentVariable("PUBLIC_BASE_URL")

try {
    $uri = ConvertTo-CanonicalPublicBaseUri -Value $publicBaseUrl
    $maxAttempts = Get-RequiredEnvironmentInteger -Name "MAX_ATTEMPTS" -DefaultValue 5 -AllowZero $false
    $retrySeconds = Get-RequiredEnvironmentInteger -Name "RETRY_SECONDS" -DefaultValue 2 -AllowZero $true
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 2
}

$healthUrl = $uri.AbsoluteUri.TrimEnd('/') + "/health"
for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    try {
        # Resolve with the same normal Windows name-resolution path used by the
        # HTTPS client. This script never changes hosts, DNS settings, or the
        # request URL to bypass name resolution.
        Resolve-DnsName -Name $uri.DnsSafeHost -ErrorAction Stop | Out-Null
        $response = Invoke-WebRequest -Uri $healthUrl -Method Get -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            Write-Output "external canonical health: ok"
            exit 0
        }
    }
    catch {
        # The final result remains intentionally redacted: do not print server
        # headers, DNS answers, routes, certificates, or response bodies.
    }

    if ($attempt -lt $maxAttempts -and $retrySeconds -gt 0) {
        Start-Sleep -Seconds $retrySeconds
    }
}

[Console]::Error.WriteLine("external canonical health: failed (expected HTTPS /health -> 200)")
exit 1
