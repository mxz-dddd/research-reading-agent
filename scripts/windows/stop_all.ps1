$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

try {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    $LogDir = Join-Path $ProjectRoot "data\logs"
    $PidFiles = @(
        Join-Path $LogDir "frontend.pid"
        Join-Path $LogDir "backend.pid"
    )

    foreach ($PidFile in $PidFiles) {
        if (-not (Test-Path -LiteralPath $PidFile)) {
            Write-Host "No PID file: $PidFile"
            continue
        }

        $pidText = Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $pidText) {
            Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
            continue
        }

        $processId = [int]$pidText
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process) {
            $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
            $commandLine = if ($processInfo) { [string]$processInfo.CommandLine } else { "" }
            if ($commandLine -and $commandLine.StartsWith("`"")) {
                $commandLineForMatch = $commandLine
            }
            else {
                $commandLineForMatch = $commandLine
            }
            if ($commandLineForMatch -like "*$ProjectRoot*") {
                Stop-Process -Id $processId -Force
                Write-Host "Stopped project PID=$processId from $PidFile"
            }
            else {
                Write-Host "PID=$processId from $PidFile is not a project process; removing stale PID file"
            }
        }
        else {
            Write-Host "Stale PID=$processId from $PidFile"
        }
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    }

    Write-Host "STOP_ALL_OK"
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
