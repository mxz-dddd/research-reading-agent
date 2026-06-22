$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

try {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    $PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $LogDir = Join-Path $ProjectRoot "data\logs"

    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "Missing project Python: $PythonExe"
    }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

    Write-Host "ProjectRoot=$ProjectRoot"
    Write-Host "PythonExe=$PythonExe"
    Write-Host "LogDir=$LogDir"

    & $PythonExe --version
    if ($LASTEXITCODE -ne 0) { throw "Python failed" }

    & $PythonExe -c "import struct; print('Bits=' + str(struct.calcsize('P') * 8))"
    if ($LASTEXITCODE -ne 0) { throw "Python bits check failed" }

    & $PythonExe -m pip check
    if ($LASTEXITCODE -ne 0) { throw "pip check failed" }

    & $PythonExe -c "import fastapi, uvicorn, streamlit, requests, httpx, pydantic, certifi, pypdf, pandas; print('CORE_IMPORTS_OK')"
    if ($LASTEXITCODE -ne 0) { throw "core imports failed" }

    Write-Host "DIAGNOSE_OK"
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
