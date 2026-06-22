$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-BackendHealth {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3 -UseBasicParsing
        return [int]$response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

try {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    $PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $LogDir = Join-Path $ProjectRoot "data\logs"
    $Stdout = Join-Path $LogDir "backend.stdout.log"
    $Stderr = Join-Path $LogDir "backend.stderr.log"
    $PidFile = Join-Path $LogDir "backend.pid"

    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "Missing project Python: $PythonExe"
    }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

    if (Test-Path -LiteralPath $PidFile) {
        $oldPidText = Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($oldPidText -and (Get-Process -Id ([int]$oldPidText) -ErrorAction SilentlyContinue)) {
            if (Test-BackendHealth) {
                Write-Host "Backend already running. PID=$oldPidText URL=http://127.0.0.1:8000"
                exit 0
            }
            throw "Backend PID file exists but health check failed: $oldPidText"
        }
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    }

    $process = Start-Process -FilePath $PythonExe `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $Stdout `
        -RedirectStandardError $Stderr `
        -PassThru `
        -WindowStyle Hidden

    Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ascii
    Write-Host "Backend started. PID=$($process.Id)"
    Write-Host "Backend URL=http://127.0.0.1:8000"
    Write-Host "Backend stdout=$Stdout"
    Write-Host "Backend stderr=$Stderr"
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
