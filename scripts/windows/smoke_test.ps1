$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Check {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][scriptblock]$Action
    )
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $result = & $Action
        $sw.Stop()
        Write-Host "CHECK $Name PASS $($sw.ElapsedMilliseconds)ms $result"
        return $true
    }
    catch {
        $sw.Stop()
        Write-Host "CHECK $Name FAIL $($sw.ElapsedMilliseconds)ms $($_.Exception.Message)"
        return $false
    }
}

try {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    $PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $LogDir = Join-Path $ProjectRoot "data\logs"
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "Missing project Python: $PythonExe"
    }
    $Base = "http://127.0.0.1:8000"
    $ok = $true

    $ok = (Invoke-Check "backend_health" {
        $r = Invoke-WebRequest -Uri "$Base/health" -TimeoutSec 10 -UseBasicParsing
        if ([int]$r.StatusCode -ne 200) { throw "HTTP $($r.StatusCode)" }
        "status=200"
    }) -and $ok

    $ok = (Invoke-Check "openapi" {
        $r = Invoke-WebRequest -Uri "$Base/openapi.json" -TimeoutSec 20 -UseBasicParsing
        if ([int]$r.StatusCode -ne 200) { throw "HTTP $($r.StatusCode)" }
        "status=200"
    }) -and $ok

    $ok = (Invoke-Check "docs" {
        $r = Invoke-WebRequest -Uri "$Base/docs" -TimeoutSec 20 -UseBasicParsing
        if ([int]$r.StatusCode -ne 200) { throw "HTTP $($r.StatusCode)" }
        "status=200"
    }) -and $ok

    $ok = (Invoke-Check "accepted_papers" {
        $r = Invoke-WebRequest -Uri "$Base/api/papers/accepted" -TimeoutSec 30 -UseBasicParsing
        if ([int]$r.StatusCode -ne 200) { throw "HTTP $($r.StatusCode)" }
        $items = $r.Content | ConvertFrom-Json
        "status=200 count=$(@($items).Count)"
    }) -and $ok

    $ok = (Invoke-Check "workflow_dry_run" {
        $body = @{
            topic = "smoke test"
            max_results = 1
            accept_top_k = 1
            dry_run = $true
            index_rag = $true
            generate_knowledge = $true
            generate_innovation = $true
        } | ConvertTo-Json -Depth 8
        $r = Invoke-WebRequest -Method Post -Uri "$Base/api/workflow/run" -Body $body -ContentType "application/json" -TimeoutSec 120 -UseBasicParsing
        if ([int]$r.StatusCode -ne 200) { throw "HTTP $($r.StatusCode)" }
        $data = $r.Content | ConvertFrom-Json
        if (-not $data.success) { throw "workflow success=false" }
        if (-not $data.dry_run) { throw "workflow dry_run=false" }
        "status=200 run_id=$($data.run_id)"
    }) -and $ok

    $ok = (Invoke-Check "frontend_8501" {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8501" -TimeoutSec 20 -UseBasicParsing
        if ([int]$r.StatusCode -ne 200) { throw "HTTP $($r.StatusCode)" }
        "status=200"
    }) -and $ok

    $ok = (Invoke-Check "frontend_log_no_traceback" {
        $text = ""
        foreach ($file in @("frontend.stdout.log", "frontend.stderr.log")) {
            $path = Join-Path $LogDir $file
            if (Test-Path -LiteralPath $path) { $text += Get-Content -LiteralPath $path -Raw }
        }
        if ($text -match "Traceback|Exception|Error|Stack \(most recent call last\)") {
            throw "frontend log contains traceback/error text"
        }
        "logs_clean=true"
    }) -and $ok

    if (-not $ok) { throw "one or more smoke checks failed" }
    Write-Host "SMOKE_TEST_OK"
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
