$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Read-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)
    $map = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $map }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) { continue }
        $parts = $trimmed.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if ($key.StartsWith("export ")) { $key = $key.Substring(7).Trim() }
        if ($value.Length -ge 2 -and $value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if ($key) { $map[$key] = $value }
    }
    return $map
}

function Has-Value {
    param([hashtable]$Map, [string]$Key)
    return $Map.ContainsKey($Key) -and -not [string]::IsNullOrWhiteSpace([string]$Map[$Key])
}

function Write-Result {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host $Message
    Add-Content -LiteralPath $PreflightLog -Value $Message -Encoding UTF8
}

try {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    $PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "Missing project Python: $PythonExe"
    }
    $LogDir = Join-Path $ProjectRoot "data\logs"
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $script:PreflightLog = Join-Path $LogDir "feishu_preflight.log"
    Set-Content -LiteralPath $PreflightLog -Value "feishu_preflight_start" -Encoding UTF8
    $EnvMap = Read-DotEnv -Path (Join-Path $ProjectRoot ".env")

    $HasAppId = Has-Value $EnvMap "FEISHU_APP_ID"
    $HasAppSecret = Has-Value $EnvMap "FEISHU_APP_SECRET"
    $HasVerificationToken = Has-Value $EnvMap "FEISHU_VERIFICATION_TOKEN"
    $HasEncryptKey = Has-Value $EnvMap "FEISHU_ENCRYPT_KEY"
    $HasPublicBaseUrl = Has-Value $EnvMap "PUBLIC_BASE_URL"

    Write-Result ("FEISHU_APP_ID configured={0}" -f $HasAppId)
    Write-Result ("FEISHU_APP_SECRET configured={0}" -f $HasAppSecret)
    Write-Result ("FEISHU_VERIFICATION_TOKEN configured={0}" -f $HasVerificationToken)
    Write-Result ("FEISHU_ENCRYPT_KEY configured={0}" -f $HasEncryptKey)
    Write-Result ("PUBLIC_BASE_URL configured={0}" -f $HasPublicBaseUrl)

    $health = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 10 -UseBasicParsing
    Write-Result ("backend_health_status={0}" -f [int]$health.StatusCode)
    if ([int]$health.StatusCode -ne 200) { throw "backend health failed" }

    $challengeBody = @{ type = "url_verification"; challenge = "local-preflight" }
    if ($HasVerificationToken) {
        $challengeBody["token"] = [string]$EnvMap["FEISHU_VERIFICATION_TOKEN"]
    }
    $challengeJson = $challengeBody | ConvertTo-Json -Depth 5
    $challenge = Invoke-WebRequest -Method Post -Uri "http://127.0.0.1:8000/api/feishu/webhook" -Body $challengeJson -ContentType "application/json" -TimeoutSec 20 -UseBasicParsing
    Write-Result ("local_challenge_status={0}" -f [int]$challenge.StatusCode)
    if ([int]$challenge.StatusCode -ne 200) { throw "local challenge failed" }

    if ($HasAppId -and $HasAppSecret) {
        $tokenBody = @{
            app_id = [string]$EnvMap["FEISHU_APP_ID"]
            app_secret = [string]$EnvMap["FEISHU_APP_SECRET"]
        } | ConvertTo-Json -Depth 5
        $tokenResponse = Invoke-WebRequest -Method Post -Uri "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal" -Body $tokenBody -ContentType "application/json" -TimeoutSec 30 -UseBasicParsing
        $tokenData = $tokenResponse.Content | ConvertFrom-Json
        $tokenOk = ($tokenData.code -eq 0) -and -not [string]::IsNullOrWhiteSpace([string]$tokenData.tenant_access_token)
        Write-Result ("tenant_access_token_test_success={0}" -f $tokenOk)
        if (-not $tokenOk) { throw ("tenant_access_token test failed with code={0}" -f $tokenData.code) }
    }
    else {
        $missingCredentialMessage = -join ([int[]](
            39134,20070,32,108,105,118,101,32,112,114,101,102,108,105,103,104,116,65306,
            32570,23569,20973,35777,65292,26410,25191,34892,32,
            116,101,110,97,110,116,95,97,99,99,101,115,115,95,116,111,107,101,110,32,
            27979,35797,12290
        ) | ForEach-Object { [char]$_ })
        Write-Result $missingCredentialMessage
    }

    $publicHttps = $false
    $publicReachable = $false
    if ($HasPublicBaseUrl) {
        $publicBase = ([string]$EnvMap["PUBLIC_BASE_URL"]).TrimEnd("/")
        $publicHttps = $publicBase.StartsWith("https://")
        if ($publicHttps) {
            try {
                $public = Invoke-WebRequest -Uri ($publicBase + "/api/feishu/webhook") -Method Options -TimeoutSec 20 -UseBasicParsing
                $publicReachable = [int]$public.StatusCode -lt 500
            }
            catch {
                $publicReachable = $false
            }
        }
    }
    Write-Result ("PUBLIC_BASE_URL_https={0}" -f $publicHttps)
    Write-Result ("public_webhook_reachable={0}" -f $publicReachable)
    Write-Result "callback_path=/api/feishu/webhook"
    Write-Result "FEISHU_PREFLIGHT_DONE"
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
