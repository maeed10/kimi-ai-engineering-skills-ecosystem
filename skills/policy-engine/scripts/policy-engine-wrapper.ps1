#!/usr/bin/env pwsh
# policy-engine-wrapper.ps1 — External integrity verifier for policy-engine-server.py
# Kimi AI Engineering Skills Ecosystem v4.2.1
#
# This wrapper runs OUTSIDE the Python process to verify the policy engine script's
# SHA-256 hash before execution. It addresses the self-integrity paradox: the code
# that checks the hash must not be inside the file being checked.
#
# Usage:
#   .\policy-engine-wrapper.ps1 [arguments forwarded to policy-engine-server.py]
#
# Exit codes:
#   0 — Hash verified, daemon started normally
#   1 — Hash mismatch or manifest missing (daemon blocked)
#   2 — Python not found

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForwardArgs
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ManifestPath = Join-Path $ScriptDir "..\policy\manifest.json"
$ScriptPath = Join-Path $ScriptDir "policy-engine-server.py"

# --- Validate prerequisites ---
if (-not (Test-Path $ScriptPath)) {
    Write-Error "FATAL: policy-engine-server.py not found at $ScriptPath"
    exit 1
}

if (-not (Test-Path $ManifestPath)) {
    Write-Error "FATAL: manifest.json not found at $ManifestPath"
    exit 1
}

# --- Compute SHA-256 of the script ---
$ActualHash = (Get-FileHash -Path $ScriptPath -Algorithm SHA256).Hash.ToLower()

# --- Read expected hash from manifest ---
try {
    $Manifest = Get-Content -Path $ManifestPath -Raw | ConvertFrom-Json
} catch {
    Write-Error "FATAL: manifest.json is not valid JSON"
    exit 1
}

$ExpectedHash = $Manifest.self_integrity.sha256
if (-not $ExpectedHash) {
    Write-Warning "No self_integrity hash in manifest. Custodian check disabled."
} elseif ($ExpectedHash -ne $ActualHash) {
    Write-Error "=" * 70
    Write-Error "SELF-INTEGRITY CHECK FAILED"
    Write-Error "=" * 70
    Write-Error "Expected: $ExpectedHash"
    Write-Error "Actual:   $ActualHash"
    Write-Error ""
    Write-Error "The policy engine script may have been tampered with."
    Write-Error "Reinstall from a trusted source."
    Write-Error "=" * 70
    exit 1
} else {
    Write-Host "Self-integrity check passed ($($ActualHash.Substring(0,16))...)." -ForegroundColor Green
}

# --- Start the daemon ---
$Python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $Python) {
    Write-Error "FATAL: Python not found in PATH"
    exit 2
}

& $Python.Source $ScriptPath @ForwardArgs
