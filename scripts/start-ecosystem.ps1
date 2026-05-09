#!/usr/bin/env pwsh
# start-ecosystem.ps1 — Unified daemon launcher for Kimi AI Engineering Skills Ecosystem v4.2.1
# Launches Policy Engine, Phase Controller, and Tool Execution Gateway with health monitoring.

param(
    [int]$PolicyPort = 9100,
    [int]$PhasePort = 9101,
    [int]$GatewayPort = 9102,
    [string]$HostAddr = "127.0.0.1",
    [string]$PolicyDir = "$env:USERPROFILE\.kimi\policy",
    [string]$Manifest = "$env:USERPROFILE\.kimi\policy\manifest.json",
    [string]$StateDir = "$env:USERPROFILE\.kimi\state",
    [switch]$NoGateway,
    [switch]$NoPolicy,
    [switch]$NoPhase,
    [switch]$Detach
)

$ErrorActionPreference = "Stop"
$KimiHome = "$env:USERPROFILE\.kimi"
$LogDir = "$KimiHome\logs"
New-Item -ItemType Directory -Path "$LogDir\policy-engine" -Force | Out-Null
New-Item -ItemType Directory -Path "$LogDir\phase-controller" -Force | Out-Null
New-Item -ItemType Directory -Path "$LogDir\gateway" -Force | Out-Null
New-Item -ItemType Directory -Path "$StateDir" -Force | Out-Null

$Processes = @()
$StartTime = Get-Date

function Write-Status($msg) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $msg" -ForegroundColor Cyan
}

function Wait-ForHealth($url, $name, $maxSeconds = 30) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $maxSeconds) {
        try {
            $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) {
                Write-Status "$name health check passed ($($resp.Content))"
                return $true
            }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    Write-Status "WARNING: $name health check timed out after ${maxSeconds}s"
    return $false
}

# ---------------------------------------------------------------------------
# Policy Engine
# ---------------------------------------------------------------------------
if (-not $NoPolicy) {
    Write-Status "Starting Policy Engine on http://$HostAddr`:$PolicyPort ..."
    $peLogOut = "$LogDir\policy-engine\server.out.log"
    $peLogErr = "$LogDir\policy-engine\server.err.log"
    $peProc = Start-Process -FilePath "python" -ArgumentList @(
        "$KimiHome\skills\policy-engine\scripts\policy-engine-server.py",
        "--policy-dir", $PolicyDir,
        "--manifest", $Manifest,
        "--port", $PolicyPort,
        "--host", $HostAddr
    ) -PassThru -WindowStyle Hidden -RedirectStandardOutput $peLogOut -RedirectStandardError $peLogErr
    $Processes += [PSCustomObject]@{ Name = "policy-engine"; Proc = $peProc; LogOut = $peLogOut; LogErr = $peLogErr }
    Start-Sleep -Seconds 2
    if ($peProc.HasExited) {
        Write-Status "ERROR: Policy Engine crashed. Logs:"
        if (Test-Path $peLogErr) { Get-Content $peLogErr -Tail 20 }
        exit 1
    }
    Wait-ForHealth "http://$HostAddr`:$PolicyPort/health" "Policy Engine" | Out-Null
}

# ---------------------------------------------------------------------------
# Phase Controller
# ---------------------------------------------------------------------------
if (-not $NoPhase) {
    Write-Status "Starting Phase Controller on http://$HostAddr`:$PhasePort ..."
    $pcLogOut = "$LogDir\phase-controller\server.out.log"
    $pcLogErr = "$LogDir\phase-controller\server.err.log"
    $pcProc = Start-Process -FilePath "python" -ArgumentList @(
        "$KimiHome\skills\phase-controller\scripts\phase-controller-server.py",
        "--state-dir", $StateDir,
        "--port", $PhasePort,
        "--host", $HostAddr
    ) -PassThru -WindowStyle Hidden -RedirectStandardOutput $pcLogOut -RedirectStandardError $pcLogErr
    $Processes += [PSCustomObject]@{ Name = "phase-controller"; Proc = $pcProc; LogOut = $pcLogOut; LogErr = $pcLogErr }
    Start-Sleep -Seconds 2
    if ($pcProc.HasExited) {
        Write-Status "ERROR: Phase Controller crashed. Logs:"
        if (Test-Path $pcLogErr) { Get-Content $pcLogErr -Tail 20 }
        exit 1
    }
    Wait-ForHealth "http://$HostAddr`:$PhasePort/health" "Phase Controller" | Out-Null
}

# ---------------------------------------------------------------------------
# Tool Execution Gateway
# ---------------------------------------------------------------------------
if (-not $NoGateway) {
    $policyEndpoint = "http://$HostAddr`:$PolicyPort"
    Write-Status "Starting Tool Execution Gateway on http://$HostAddr`:$GatewayPort ..."
    Write-Status "Gateway -> Policy Engine at $policyEndpoint"
    $gwLogOut = "$LogDir\gateway\server.out.log"
    $gwLogErr = "$LogDir\gateway\server.err.log"
    $gwProc = Start-Process -FilePath "python" -ArgumentList @(
        "$KimiHome\skills\tool-execution-gateway\scripts\gateway-server.py",
        "--port", $GatewayPort,
        "--host", $HostAddr,
        "--policy-endpoint", $policyEndpoint
    ) -PassThru -WindowStyle Hidden -RedirectStandardOutput $gwLogOut -RedirectStandardError $gwLogErr
    $Processes += [PSCustomObject]@{ Name = "gateway"; Proc = $gwProc; LogOut = $gwLogOut; LogErr = $gwLogErr }
    Start-Sleep -Seconds 2
    if ($gwProc.HasExited) {
        Write-Status "ERROR: Gateway crashed. Logs:"
        if (Test-Path $gwLogErr) { Get-Content $gwLogErr -Tail 20 }
        exit 1
    }
    Wait-ForHealth "http://$HostAddr`:$GatewayPort/health" "Gateway" | Out-Null
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
$elapsed = ([DateTime]::Now - $StartTime).TotalSeconds
Write-Status "All daemons started in $([math]::Round($elapsed,1))s"
Write-Status ""
Write-Status "Services:"
if (-not $NoPolicy) { Write-Status "  Policy Engine    http://$HostAddr`:$PolicyPort/health" }
if (-not $NoPhase)  { Write-Status "  Phase Controller http://$HostAddr`:$PhasePort/health" }
if (-not $NoGateway){ Write-Status "  Gateway          http://$HostAddr`:$GatewayPort/health" }
Write-Status ""
Write-Status "Logs: $LogDir"
Write-Status "State: $StateDir"
Write-Status ""

if ($Detach) {
    Write-Status "Running detached. PIDs:"
    foreach ($p in $Processes) {
        Write-Status "  $($p.Name): PID $($p.Proc.Id)"
    }
    exit 0
}

Write-Status "Press Ctrl+C to shut down all daemons gracefully..."
Write-Status ""

try {
    while ($true) {
        Start-Sleep -Seconds 5
        foreach ($p in $Processes) {
            if ($p.Proc.HasExited) {
                Write-Status "WARNING: $($p.Name) exited with code $($p.Proc.ExitCode). Check logs in $LogDir\$($p.Name)\"
            }
        }
    }
} finally {
    Write-Status "Shutting down daemons..."
    foreach ($p in $Processes) {
        if (-not $p.Proc.HasExited) {
            Stop-Process -Id $p.Proc.Id -Force -ErrorAction SilentlyContinue
            Write-Status "  Stopped $($p.Name) (PID $($p.Proc.Id))"
        }
    }
}
