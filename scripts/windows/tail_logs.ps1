$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

try {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    $LogDir = Join-Path $ProjectRoot "data\logs"
    $Files = @(
        "backend.stdout.log",
        "backend.stderr.log",
        "frontend.stdout.log",
        "frontend.stderr.log"
    )

    foreach ($file in $Files) {
        $path = Join-Path $LogDir $file
        Write-Host "===== $path ====="
        if (Test-Path -LiteralPath $path) {
            Get-Content -LiteralPath $path -Tail 80
        }
        else {
            Write-Host "missing"
        }
    }
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
