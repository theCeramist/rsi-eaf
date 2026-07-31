#Requires -Version 5.1
<#
.SYNOPSIS
  Best-effort durable host for RSI-EAF factory ops on Windows.

.DESCRIPTION
  Registers two Scheduled Tasks (user context, no password store):

  1) RSI-EAF-OpsEnsure
     - At user logon
     - Every 5 minutes indefinitely
     - Runs: python -u scripts/factory_ops_keeper.py --once
     - Idempotent: if supervisor/monitor already up, no-op
     - Multiple instances: IgnoreNew (no thrash)

  2) RSI-EAF-OpsKeeperLoop (optional belt)
     - At user logon only
     - Runs: python -u scripts/launch_ops_keeper_detached.py
     - Detached long-loop; periodic Ensure is the source of truth

  Design rationale:
  - Long-lived Python processes die under Job Objects / max_runtime / logoff.
  - A short --once every 5 minutes is the most reliable Windows "host".
  - Does not require SYSTEM / stored credentials (runs as current user).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_ops_scheduled_tasks.ps1
#>

param(
    [string]$RepoRoot = "",
    [int]$EnsureMinutes = 5,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    if ($RepoRoot -and (Test-Path $RepoRoot)) { return (Resolve-Path $RepoRoot).Path }
    if ($PSScriptRoot) {
        $parent = Split-Path -Parent $PSScriptRoot
        if (Test-Path (Join-Path $parent "scripts\factory_ops_keeper.py")) { return $parent }
    }
    $cwd = (Get-Location).Path
    if (Test-Path (Join-Path $cwd "scripts\factory_ops_keeper.py")) { return $cwd }
    throw "Cannot find repo root (scripts\factory_ops_keeper.py). Pass -RepoRoot."
}

function Get-PythonExe {
    $candidates = @(
        (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "C:\Python313\python.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }
    if (-not $candidates) { throw "python.exe not found on PATH" }
    return $candidates[0]
}

$root = Get-RepoRoot
$py = Get-PythonExe
$taskEnsure = "RSI-EAF-OpsEnsure"
$taskLoop = "RSI-EAF-OpsKeeperLoop"
$logDir = Join-Path $root "runtime"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if ($Uninstall) {
    foreach ($n in @($taskEnsure, $taskLoop)) {
        if (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $n -Confirm:$false
            Write-Host "Removed task $n"
        } else {
            Write-Host "Task $n not found"
        }
    }
    exit 0
}

# --- Ensure task: the durable host ---
$ensureArgs = "-u `"$root\scripts\factory_ops_keeper.py`" --once --cooldown 60"
$actionEnsure = New-ScheduledTaskAction `
    -Execute $py `
    -Argument $ensureArgs `
    -WorkingDirectory $root

$triggerLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# Repeat every N minutes for 10 years (indefinite-ish)
$triggerRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $EnsureMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -WakeToRun:$false

# Prefer InteractiveToken so user env/network/X creds paths work
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskEnsure `
    -Action $actionEnsure `
    -Trigger @($triggerLogon, $triggerRepeat) `
    -Settings $settings `
    -Principal $principal `
    -Description "RSI-EAF durable host: ensure supervisor+monitor every ${EnsureMinutes}m + at logon. Idempotent." `
    -Force | Out-Null

Write-Host "Registered $taskEnsure (logon + every ${EnsureMinutes}m)"

# --- Optional loop at logon ---
$loopArgs = "-u `"$root\scripts\launch_ops_keeper_detached.py`""
$actionLoop = New-ScheduledTaskAction `
    -Execute $py `
    -Argument $loopArgs `
    -WorkingDirectory $root

Register-ScheduledTask `
    -TaskName $taskLoop `
    -Action $actionLoop `
    -Trigger $triggerLogon `
    -Settings $settings `
    -Principal $principal `
    -Description "RSI-EAF ops keeper detached loop at logon (secondary). Ensure task is primary." `
    -Force | Out-Null

Write-Host "Registered $taskLoop (at logon)"

# Kick immediately so we don't wait for next interval
try {
    Start-ScheduledTask -TaskName $taskEnsure
    Write-Host "Started $taskEnsure once now"
} catch {
    Write-Host "Could not start task immediately: $_"
}

# Verify
Get-ScheduledTask -TaskName $taskEnsure, $taskLoop | Format-Table TaskName, State -AutoSize
Write-Host ""
Write-Host "Python: $py"
Write-Host "Repo:   $root"
Write-Host "Done. Primary durability = $taskEnsure every ${EnsureMinutes} minutes."
Write-Host "Uninstall: powershell -File scripts\install_ops_scheduled_tasks.ps1 -Uninstall"
