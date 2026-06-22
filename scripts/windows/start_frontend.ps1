$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-Frontend {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8501" -TimeoutSec 3 -UseBasicParsing
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
    $Stdout = Join-Path $LogDir "frontend.stdout.log"
    $Stderr = Join-Path $LogDir "frontend.stderr.log"
    $PidFile = Join-Path $LogDir "frontend.pid"

    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "Missing project Python: $PythonExe"
    }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

    if (Test-Path -LiteralPath $PidFile) {
        $oldPidText = Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($oldPidText -and (Get-Process -Id ([int]$oldPidText) -ErrorAction SilentlyContinue)) {
            if (Test-Frontend) {
                Write-Host "Frontend already running. PID=$oldPidText URL=http://127.0.0.1:8501"
                exit 0
            }
            throw "Frontend PID file exists but port check failed: $oldPidText"
        }
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    }

    $process = Start-Process -FilePath $PythonExe `
        -ArgumentList @("-m", "streamlit", "run", "frontend\streamlit_app.py", "--server.address", "127.0.0.1", "--server.port", "8501") `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $Stdout `
        -RedirectStandardError $Stderr `
        -PassThru `
        -WindowStyle Hidden

    Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ascii
    Write-Host "Frontend started. PID=$($process.Id)"
    Write-Host "Frontend URL=http://127.0.0.1:8501"
    Write-Host "Frontend stdout=$Stdout"
    Write-Host "Frontend stderr=$Stderr"
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
