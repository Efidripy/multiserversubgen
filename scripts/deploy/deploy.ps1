<#
.SYNOPSIS
    Безопасный деплой на прод или тестовую машину одной командой.

.DESCRIPTION
    Выполняет полный цикл: preflight-проверки, pre-check на сервере,
    вызов invoke-remote-deploy.ps1 и post-check после деплоя.
    Производственный сервер: dev.kleva.ru (алиас prod).
    Тестовая машина: vm3.kleva.ru/192.168.48.130 (алиас vm3, НЕ прод).

.PARAMETER Target
    Цель деплоя: prod или vm3.

.PARAMETER DryRun
    Только preflight и read-only pre-check по SSH; деплой не запускается.

.PARAMETER Yes
    Пропустить интерактивное подтверждение (только для prod).

.PARAMETER KeyPath
    Путь к SSH-ключу. Если не указан — берётся из targets.psd1.

.EXAMPLE
    pwsh scripts/deploy/deploy.ps1 -Target prod
    pwsh scripts/deploy/deploy.ps1 -Target prod -DryRun
    pwsh scripts/deploy/deploy.ps1 -Target vm3 -Yes
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('prod', 'vm3')]
    [string]$Target,

    [switch]$DryRun,
    [switch]$Yes,

    [string]$KeyPath = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------
# Вспомогательные функции вывода
# ---------------------------------------------------------------------------
function Write-Step  { param([string]$Msg) Write-Host "[STEP]  $Msg" -ForegroundColor Cyan }
function Write-Ok    { param([string]$Msg) Write-Host "[ OK ]  $Msg" -ForegroundColor Green }
function Write-Warn  { param([string]$Msg) Write-Host "[WARN]  $Msg" -ForegroundColor Yellow }
function Write-Fail  { param([string]$Msg) Write-Host "[FAIL]  $Msg" -ForegroundColor Red }
function Write-Info  { param([string]$Msg) Write-Host "        $Msg" }

function Fail {
    param([string]$Msg)
    Write-Fail $Msg
    exit 1
}

# ---------------------------------------------------------------------------
# Загрузка таблицы целей
# ---------------------------------------------------------------------------
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = (Resolve-Path (Join-Path $ScriptDir '..\..')).Path
$TargetsFile = Join-Path $ScriptDir 'targets.psd1'

if (-not (Test-Path $TargetsFile)) {
    Fail "targets.psd1 not found at $TargetsFile"
}
$Targets = Import-PowerShellDataFile $TargetsFile
if (-not $Targets.ContainsKey($Target)) {
    Fail "Unknown target '$Target'. Available: $($Targets.Keys -join ', ')"
}
$T = $Targets[$Target]

# Разворачиваем KeyPath из targets: подставляем $env:USERPROFILE
$ResolvedKeyPath = if ($KeyPath) {
    $KeyPath
} elseif ($T.KeyPath) {
    # targets.psd1 хранит строку с $env:USERPROFILE — раскрываем её
    $T.KeyPath -replace '\$env:USERPROFILE', $env:USERPROFILE
} else {
    ''
}

$IsProd    = ($Target -eq 'prod')
$IsLocalTest = [bool]$T.LocalTest

Write-Host ''
Write-Host "========================================" -ForegroundColor Magenta
Write-Host " deploy.ps1  ->  target: $Target" -ForegroundColor Magenta
if ($IsLocalTest) {
    Write-Host " (ТЕСТОВАЯ МАШИНА — не прод)" -ForegroundColor Yellow
} else {
    Write-Host " (PRODUCTION: $($T.HostName))" -ForegroundColor Red
}
if ($DryRun) {
    Write-Host " *** DRY-RUN: только проверки, деплой не выполняется ***" -ForegroundColor Yellow
}
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ''

# ---------------------------------------------------------------------------
# Исправление PATH: ssh/scp из Git bin в КОНЕЦ PATH
# (GNU tar из E:\Git\usr\bin ломает Windows tar.exe — добавляем в конец)
# ---------------------------------------------------------------------------
$GitBin = 'E:\Git\usr\bin'
if (Test-Path $GitBin) {
    $currentPath = $env:PATH
    if ($currentPath -notlike "*$GitBin*") {
        $env:PATH = "$currentPath;$GitBin"
        Write-Info "PATH: добавлен $GitBin (в конец, чтобы не переопределить Windows tar.exe)"
    } else {
        Write-Info "PATH: $GitBin уже присутствует"
    }
} else {
    Write-Warn "Git bin не найден по пути $GitBin — ssh/scp должны быть в PATH"
}

# ---------------------------------------------------------------------------
# Preflight: git fetch + проверки ветки/состояния/CI
# ---------------------------------------------------------------------------
Write-Step 'Preflight: git fetch'
& git -C $RepoRoot fetch --quiet origin
if ($LASTEXITCODE -ne 0) { Fail 'git fetch не выполнен' }

$HeadCommit  = (& git -C $RepoRoot rev-parse HEAD).Trim()
$HeadBranch  = (& git -C $RepoRoot rev-parse --abbrev-ref HEAD).Trim()
$OriginMain  = (& git -C $RepoRoot rev-parse 'origin/main' 2>$null).Trim()

# invoke-remote-deploy.ps1 always archives HEAD, so HEAD is the only deployable ref.
$DeployRef = $HeadCommit
$DeploySubject = (& git -C $RepoRoot log -1 --pretty='%s' $DeployRef 2>$null).Trim()

Write-Info "Ветка:  $HeadBranch"
Write-Info "HEAD:   $HeadCommit"
Write-Info "Ref:    $DeployRef"
Write-Info "Тема:   $DeploySubject"

# Проверка чистого дерева — обязательна для всех целей
Write-Step 'Preflight: чистота рабочего дерева'
$DirtyFiles = @(& git -C $RepoRoot status --porcelain=v1 --untracked-files=no)
if ($LASTEXITCODE -ne 0) { Fail 'git status failed' }
if ($DirtyFiles.Count -gt 0) {
    Write-Fail 'Рабочее дерево содержит изменения:'
    $DirtyFiles | ForEach-Object { Write-Info "  $_" }
    Fail 'Закоммитьте или откатите изменения перед деплоем.'
}
Write-Ok 'Рабочее дерево чистое'

# Для prod: требуем ветку main и соответствие origin/main
if ($IsProd) {
    Write-Step 'Preflight: проверка ветки и CI (prod)'
    if ($HeadBranch -ne 'main') {
        Fail "Деплой на prod разрешён только из ветки main (текущая: $HeadBranch)"
    }
    Write-Ok "Ветка: main"

    if (-not $OriginMain) {
        Fail 'Не удалось определить origin/main'
    }
    if ($HeadCommit -ne $OriginMain) {
        Fail "HEAD ($HeadCommit) != origin/main ($OriginMain). Сделайте git pull или git push."
    }
    Write-Ok "HEAD == origin/main"

    # Проверка CI через gh
    Write-Step "Preflight: CI checks для $DeployRef"
    $ghAvailable = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $ghAvailable) {
        Fail "gh (GitHub CLI) не найден в PATH. Установите его или убедитесь в доступности: https://cli.github.com`nДля prod деплоя CI checks обязательны."
    }

    # Every check run of the commit must be completed with success/skipped/neutral.
    $jq = '{total: (.check_runs | length), bad: [.check_runs[] | select(.status != "completed" or ((.conclusion // "") | IN("success","skipped","neutral") | not)) | .name]}'
    $apiOutput = (& gh api "repos/Efidripy/multiserversubgen/commits/$DeployRef/check-runs" --jq $jq 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0) {
        Fail "Не удалось получить CI check-runs через gh api.`nВывод: $apiOutput`nДля prod деплоя gh должен быть авторизован."
    }
    $ci = $apiOutput | ConvertFrom-Json
    if ($ci.total -eq 0) {
        Fail "Для $DeployRef нет CI check-runs. Деплой на prod запрещён."
    }
    if (@($ci.bad).Count -gt 0) {
        Fail "CI для $DeployRef не зелёный (упали или не завершены): $(@($ci.bad) -join ', ')"
    }
    Write-Ok "CI зелёный для ${DeployRef}: $($ci.total) проверок"
} else {
    Write-Info "vm3: строгие git-проверки пропущены (любая ветка разрешена, дерево чистое — уже проверено)"
}

# ---------------------------------------------------------------------------
# Информация о текущей версии на сервере
# ---------------------------------------------------------------------------
Write-Info ''
Write-Info "  Хост:       $($T.HostName):$($T.Port)"
Write-Info "  User:       $($T.User)"
Write-Info "  RemoteDir:  $($T.RemoteDir)"
Write-Info "  HealthUrl:  $($T.HealthUrl)"
Write-Info "  Деплой ref: $DeployRef"
Write-Info "  Тема:       $DeploySubject"

# ---------------------------------------------------------------------------
# Подтверждение для prod (если не -Yes и не -DryRun)
# ---------------------------------------------------------------------------
if ($IsProd -and -not $Yes -and -not $DryRun) {
    Write-Host ''
    Write-Host '  ┌─────────────────────────────────────────────────────┐' -ForegroundColor Red
    Write-Host '  │  ВНИМАНИЕ: деплой на PRODUCTION (dev.kleva.ru)      │' -ForegroundColor Red
    Write-Host '  │  Введите  yes  для подтверждения                    │' -ForegroundColor Red
    Write-Host '  └─────────────────────────────────────────────────────┘' -ForegroundColor Red
    Write-Host ''
    $Confirm = Read-Host 'Подтверждение'
    if ($Confirm -ne 'yes') {
        Fail "Деплой отменён (введено: '$Confirm', ожидалось 'yes')"
    }
}

# ---------------------------------------------------------------------------
# SSH helper: выполнение read-only команды на сервере
# ---------------------------------------------------------------------------
function Invoke-RemoteSsh {
    param(
        [string]$Command,
        [switch]$PassThru
    )
    $sshArgs = @()
    $sshArgs += '-o', 'BatchMode=yes'
    $sshArgs += '-o', 'ConnectTimeout=10'
    $sshArgs += '-p', "$($T.Port)"
    if ($ResolvedKeyPath) {
        $sshArgs += '-i', $ResolvedKeyPath
    }
    $sshArgs += "$($T.User)@$($T.HostName)"
    $sshArgs += $Command

    if ($PassThru) {
        $result = & ssh @sshArgs 2>&1
        return $result
    } else {
        & ssh @sshArgs 2>&1
        return $LASTEXITCODE
    }
}

# ---------------------------------------------------------------------------
# Pre-check: read-only состояние сервера
# ---------------------------------------------------------------------------
function Invoke-PreCheck {
    Write-Step 'Pre-check: sub-manager active'
    $statusOut = Invoke-RemoteSsh -Command 'systemctl is-active sub-manager' -PassThru
    if ([string]$statusOut -ne 'active') {
        Write-Warn "sub-manager не active (статус: $statusOut)"
        # Не прерываем — сервис мог быть временно недоступен
    } else {
        Write-Ok "sub-manager: $statusOut"
    }

    Write-Step 'Pre-check: health 200'
    $healthOut = Invoke-RemoteSsh -Command "curl -sf -o /dev/null -w '%{http_code}' $($T.HealthUrl)" -PassThru
    if ($healthOut -notmatch '200') {
        Fail "Health endpoint вернул '$healthOut' вместо 200. Сервис нездоров, деплой прерван."
    }
    Write-Ok "Health: $healthOut"

    Write-Step 'Pre-check: свободное место на / >= 3 GB'
    $dfOut = Invoke-RemoteSsh -Command "df --output=avail -BG / | tail -1 | tr -d 'G '" -PassThru
    $dfGB = [int]($dfOut -replace '[^0-9]', '')
    if ($dfGB -lt 3) {
        Fail "Недостаточно места: ${dfGB}GB < 3GB. Освободите место перед деплоем."
    }
    Write-Ok "Свободно: ${dfGB} GB"

    Write-Step 'Pre-check: последний бэкап в /var/backups/sub-manager_deploy'
    $backupOut = Invoke-RemoteSsh -Command 'ls -1t /var/backups/sub-manager_deploy/*.tgz 2>/dev/null | head -1' -PassThru
    if (-not $backupOut -or $backupOut -notmatch '\.tgz$') {
        Write-Warn "Бэкапы в /var/backups/sub-manager_deploy не найдены (это нормально при первом деплое)"
    } else {
        Write-Ok "Последний бэкап: $backupOut"
    }
}

Write-Step 'Pre-check (read-only SSH на сервер)'
try {
    Invoke-PreCheck
} catch {
    Fail "Pre-check не пройден: $_"
}
if ($DryRun) {
    Write-Host ''
    Write-Ok 'DRY-RUN завершён успешно: деплой не запускался.'
    exit 0
}

# ---------------------------------------------------------------------------
# Деплой: вызов invoke-remote-deploy.ps1
# ---------------------------------------------------------------------------
$InvokeScript = Join-Path $RepoRoot 'scripts\installer\windows\invoke-remote-deploy.ps1'
if (-not (Test-Path $InvokeScript)) {
    Fail "Не найден invoke-remote-deploy.ps1: $InvokeScript"
}

Write-Step 'Запуск invoke-remote-deploy.ps1 -Mode update'

$InvokeArgs = @(
    '-HostName', $T.HostName
    '-Port',     "$($T.Port)"
    '-UserName', $T.User
    '-Mode',     'update'
    '-RemoteDir', $T.RemoteDir
)
if ($ResolvedKeyPath) {
    $InvokeArgs += '-KeyPath', $ResolvedKeyPath
}

& pwsh -NoProfile -ExecutionPolicy Bypass -File $InvokeScript @InvokeArgs
$DeployExit = $LASTEXITCODE

if ($DeployExit -ne 0) {
    Write-Fail "invoke-remote-deploy.ps1 завершился с кодом $DeployExit"
    Write-Host ''
    Write-Host '  ROLLBACK: server-deploy.sh автоматически откатывает при ROLLBACK_ON_FAIL=1.' -ForegroundColor Yellow
    Write-Host '  Для ручного отката найдите последний бэкап:' -ForegroundColor Yellow
    Write-Host "    ssh $($T.User)@$($T.HostName) -p $($T.Port) ls -lt /var/backups/sub-manager_deploy/*.tgz" -ForegroundColor Yellow
    Write-Host '  Для проверки здоровья:' -ForegroundColor Yellow
    Write-Host "    ssh $($T.User)@$($T.HostName) -p $($T.Port) systemctl is-active sub-manager" -ForegroundColor Yellow
    Write-Host "    ssh $($T.User)@$($T.HostName) -p $($T.Port) curl -sf $($T.HealthUrl)" -ForegroundColor Yellow
    exit $DeployExit
}
Write-Ok 'invoke-remote-deploy.ps1 завершён успешно'

# ---------------------------------------------------------------------------
# Post-check: health x3, journalctl на ошибки
# ---------------------------------------------------------------------------
Write-Step 'Post-check: health x3 с паузой'
$HealthOk = 0
for ($i = 1; $i -le 3; $i++) {
    if ($i -gt 1) { Start-Sleep -Seconds 5 }
    $h = Invoke-RemoteSsh -Command "curl -sf -o /dev/null -w '%{http_code}' $($T.HealthUrl)" -PassThru
    if ($h -match '200') {
        $HealthOk++
        Write-Info "  Попытка ${i}: OK ($h)"
    } else {
        Write-Warn "  Попытка ${i}: $h"
    }
}
if ($HealthOk -lt 3) {
    Write-Fail "Health не прошёл $HealthOk/3 раз(а)"
    Write-Host ''
    Write-Host '  server-deploy.sh мог уже откатить изменения (ROLLBACK_ON_FAIL=1).' -ForegroundColor Yellow
    Write-Host '  Для ручного отката:' -ForegroundColor Yellow
    Write-Host "    ssh $($T.User)@$($T.HostName) -p $($T.Port) 'ls -lt /var/backups/sub-manager_deploy/*.tgz | head -5'" -ForegroundColor Yellow
    Write-Host '  Восстановление из бэкапа — вручную по docs/DEPLOY.md (не распаковывать архив поверх / без проверки).' -ForegroundColor Yellow
    Write-Host '  Для диагностики:' -ForegroundColor Yellow
    Write-Host "    ssh $($T.User)@$($T.HostName) -p $($T.Port) 'journalctl -u sub-manager -n 50 --no-pager'" -ForegroundColor Yellow
    exit 1
}
Write-Ok 'Health: 3/3 OK'

Write-Step 'Post-check: journalctl — ошибки за последние 3 минуты'
$JournalCmd = 'journalctl -u sub-manager --since "-3 minutes" --no-pager -q 2>/dev/null | grep -E "ERROR|Traceback|Exception" | head -20'
$JournalOut = Invoke-RemoteSsh -Command $JournalCmd -PassThru
if ($JournalOut -match 'ERROR|Traceback|Exception') {
    Write-Warn "Обнаружены ошибки в journalctl за последние 3 минуты:"
    $JournalOut | ForEach-Object { Write-Info "  $_" }
    Write-Warn "Проверьте логи вручную. Деплой формально завершён, но могут быть проблемы."
} else {
    Write-Ok 'journalctl: ошибок не обнаружено'
}

# ---------------------------------------------------------------------------
# Итог
# ---------------------------------------------------------------------------
Write-Host ''
Write-Host '========================================' -ForegroundColor Green
Write-Host " ДЕПЛОЙ УСПЕШЕН: $Target ($($T.HostName))" -ForegroundColor Green
Write-Host '========================================' -ForegroundColor Green
Write-Info "  Ref:     $DeployRef"
Write-Info "  Тема:    $DeploySubject"
Write-Info "  Health:  $($T.HealthUrl) -> 200"
Write-Info "  UI:      https://$($T.HostName)$($T.UiUrlPath)"
Write-Host ''