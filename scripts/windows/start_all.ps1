$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Wait-HttpStatus {
    param(
        [Parameter(Mandatory=$true)][string]$Url,
        [Parameter(Mandatory=$true)][int]$ExpectedStatus,
        [int]$TimeoutSeconds = 60
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing
            if ([int]$response.StatusCode -eq $ExpectedStatus) {
                return $true
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

try {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    $LogDir = Join-Path $ProjectRoot "data\logs"
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

    & (Join-Path $PSScriptRoot "stop_all.ps1")
    if ($LASTEXITCODE -ne 0) { throw "stop_all failed" }

    & (Join-Path $PSScriptRoot "start_backend.ps1")
    if ($LASTEXITCODE -ne 0) { throw "start_backend failed" }

    if (-not (Wait-HttpStatus -Url "http://127.0.0.1:8000/health" -ExpectedStatus 200 -TimeoutSeconds 90)) {
        throw "Backend health did not return 200"
    }

    & (Join-Path $PSScriptRoot "start_frontend.ps1")
    if ($LASTEXITCODE -ne 0) { throw "start_frontend failed" }

    if (-not (Wait-HttpStatus -Url "http://127.0.0.1:8501" -ExpectedStatus 200 -TimeoutSeconds 90)) {
        throw "Frontend did not return 200"
    }

    $BackendPid = Get-Content -LiteralPath (Join-Path $LogDir "backend.pid") | Select-Object -First 1
    $FrontendPid = Get-Content -LiteralPath (Join-Path $LogDir "frontend.pid") | Select-Object -First 1

    Write-Host "START_ALL_OK"
    Write-Host "Backend PID=$BackendPid URL=http://127.0.0.1:8000"
    Write-Host "Frontend PID=$FrontendPid URL=http://127.0.0.1:8501"
    Write-Host "Logs=$LogDir"
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
