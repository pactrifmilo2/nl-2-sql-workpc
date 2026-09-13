[CmdletBinding()]
param(
    [string]$AppRoot = "C:\Apps\nl2sql",
    [ValidateRange(1, 65535)][int]$Port = 8000
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-IsAdministrator {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
    return $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $Command $($Arguments -join ' ')"
    }
}

function Find-Uv {
    $BundledUv = Join-Path $PSScriptRoot "tools\uv.exe"
    if (Test-Path -LiteralPath $BundledUv) { return $BundledUv }

    $Command = Get-Command uv -ErrorAction SilentlyContinue
    if ($Command) { return $Command.Source }

    $Candidates = @(
        "C:\Program Files\Python314\Scripts\uv.exe",
        "C:\Program Files\Python313\Scripts\uv.exe",
        "C:\Program Files\Python312\Scripts\uv.exe",
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe")
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate) { return $Candidate }
    }
    throw "uv was not found. Ask technical support to install uv for this machine."
}

function Wait-ForApplication {
    param([int]$ApplicationPort)

    $Url = "http://127.0.0.1:$ApplicationPort/"
    for ($Attempt = 1; $Attempt -le 20; $Attempt++) {
        try {
            $Request = [Net.HttpWebRequest]::Create($Url)
            $Request.Timeout = 2000
            $Request.AllowAutoRedirect = $false
            $Response = $Request.GetResponse()
            $StatusCode = [int]$Response.StatusCode
            $Response.Close()
            if ($StatusCode -ge 200 -and $StatusCode -lt 500) { return $StatusCode }
        }
        catch [Net.WebException] {
            if ($_.Exception.Response) {
                $StatusCode = [int]$_.Exception.Response.StatusCode
                $_.Exception.Response.Close()
                if ($StatusCode -eq 401) { return $StatusCode }
            }
        }
        Start-Sleep -Seconds 2
    }
    throw "The service started, but the application did not answer at $Url within 40 seconds."
}

if (-not (Test-IsAdministrator)) {
    Write-Host "Requesting Administrator permission..." -ForegroundColor Yellow
    $ArgumentString = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -AppRoot `"$AppRoot`" -Port $Port"
    $Process = Start-Process powershell.exe -Verb RunAs -ArgumentList $ArgumentString -Wait -PassThru
    exit $Process.ExitCode
}

$ReleaseRoot = $PSScriptRoot
$Wheels = @(Get-ChildItem -LiteralPath (Join-Path $ReleaseRoot "app") -Filter "*.whl")
if ($Wheels.Count -ne 1) {
    throw "The release must contain exactly one wheel in the app folder. Found $($Wheels.Count)."
}
if ($Wheels[0].Name -notmatch '-([0-9]+\.[0-9]+\.[0-9]+(?:[^-]*))-' ) {
    throw "Could not read the release version from $($Wheels[0].Name)."
}
$Version = $Matches[1]
$RequirementsFile = Join-Path $ReleaseRoot "requirements.txt"
$EnvExample = Join-Path $ReleaseRoot ".env.example"
$WinSWSource = Join-Path $ReleaseRoot "tools\WinSW-x64.exe"
$UvSource = Join-Path $ReleaseRoot "tools\uv.exe"
$ServiceTemplate = Join-Path $ReleaseRoot "nl2sql-service.xml"
foreach ($RequiredFile in @($RequirementsFile, $EnvExample, $WinSWSource, $UvSource, $ServiceTemplate)) {
    if (-not (Test-Path -LiteralPath $RequiredFile)) {
        throw "Release file is missing: $RequiredFile"
    }
}

$UvExe = Find-Uv
$PythonExe = Join-Path $AppRoot ".venv\Scripts\python.exe"
$ServiceExe = Join-Path $AppRoot "nl2sql-service.exe"
$ServiceXml = Join-Path $AppRoot "nl2sql-service.xml"
$EnvFile = Join-Path $AppRoot ".env"
$ServiceName = "Nl2SqlVannaOracle"
$ExistingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
$IsFirstInstall = -not (Test-Path -LiteralPath $PythonExe)

Write-Host ""
Write-Host "NL2SQL deployment $Version" -ForegroundColor Cyan
Write-Host "Target: $AppRoot"
Write-Host "Mode: $(if ($IsFirstInstall) { 'first installation' } else { 'upgrade' })"

New-Item -ItemType Directory -Path $AppRoot -Force | Out-Null
foreach ($Folder in @("app", "data", "logs", "service-logs", "releases")) {
    New-Item -ItemType Directory -Path (Join-Path $AppRoot $Folder) -Force | Out-Null
}

if ($ExistingService -and $ExistingService.Status -ne "Stopped") {
    Write-Host "[1/7] Stopping the existing service..." -ForegroundColor Cyan
    Invoke-Checked $ServiceExe "stop"
}
else {
    Write-Host "[1/7] Service is already stopped." -ForegroundColor DarkGray
}

if (-not $ExistingService -and (Test-Path -LiteralPath $PythonExe)) {
    $ExpectedPython = [IO.Path]::GetFullPath($PythonExe)
    $ManualServers = @(
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
            Where-Object {
                $_.ExecutablePath -and
                [IO.Path]::GetFullPath($_.ExecutablePath) -eq $ExpectedPython -and
                $_.CommandLine -like "*nl_2_sql_vanna_oracle_pc.asgi:app*"
            }
    )
    foreach ($ManualServer in $ManualServers) {
        Write-Host "Stopping the old console server (PID $($ManualServer.ProcessId)) before installing the service..." -ForegroundColor Yellow
        Stop-Process -Id $ManualServer.ProcessId -Force
    }
}

Write-Host "[2/7] Saving release files..." -ForegroundColor Cyan
$InstalledRelease = Join-Path $AppRoot "releases\$Version"
New-Item -ItemType Directory -Path (Join-Path $InstalledRelease "app") -Force | Out-Null
Copy-Item -LiteralPath $Wheels[0].FullName -Destination (Join-Path $InstalledRelease "app\$($Wheels[0].Name)") -Force
Copy-Item -LiteralPath $RequirementsFile -Destination (Join-Path $InstalledRelease "requirements.txt") -Force
Copy-Item -LiteralPath $Wheels[0].FullName -Destination (Join-Path $AppRoot "app\$($Wheels[0].Name)") -Force
Copy-Item -LiteralPath $RequirementsFile -Destination (Join-Path $AppRoot "requirements.txt") -Force
Copy-Item -LiteralPath $EnvExample -Destination (Join-Path $AppRoot ".env.example.latest") -Force

if (-not (Test-Path -LiteralPath $EnvFile)) {
    Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
    Write-Host ""
    Write-Host "A new production configuration file was created:" -ForegroundColor Yellow
    Write-Host "  $EnvFile"
    Write-Host "Technical setup is required once. Fill in Oracle, Ollama, Chroma and ADMIN values, save the file, then run DEPLOY.cmd again."
    Start-Process notepad.exe -ArgumentList $EnvFile -Wait
    Write-Host "Run DEPLOY.cmd again after the configuration has been checked." -ForegroundColor Yellow
    exit 2
}

Write-Host "[3/7] Preparing Python..." -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath $PythonExe)) {
    Invoke-Checked $UvExe "venv" "--python" "3.14" (Join-Path $AppRoot ".venv")
}

$Wheelhouse = Join-Path $ReleaseRoot "wheelhouse"
if (Test-Path -LiteralPath $Wheelhouse) {
    Invoke-Checked $UvExe "pip" "install" "--python" $PythonExe "--upgrade" "--no-index" "--find-links" $Wheelhouse "--requirement" $RequirementsFile
}
else {
    Write-Host "This release uses an online package installation." -ForegroundColor Yellow
    Invoke-Checked $UvExe "pip" "install" "--python" $PythonExe "--upgrade" "--requirement" $RequirementsFile
}
Invoke-Checked $UvExe "pip" "install" "--python" $PythonExe "--upgrade" "--force-reinstall" "--no-deps" $Wheels[0].FullName

Write-Host "[4/7] Verifying package and configuration..." -ForegroundColor Cyan
$VersionCode = "import importlib.metadata as m; print(m.version('nl-2-sql-vanna-oracle-pc'))"
$InstalledVersion = (& $PythonExe -c $VersionCode).Trim()
if ($LASTEXITCODE -ne 0 -or $InstalledVersion -ne $Version) {
    throw "Installed package version is $InstalledVersion; expected $Version."
}

$ConfigCheck = @'
from nl_2_sql_vanna_oracle_pc.settings import settings

required = {
    "OLLAMA_MODEL": settings.ollama_model,
    "OLLAMA_HOST": settings.ollama_host,
    "ORACLE_USER": settings.oracle_user,
    "ORACLE_PASSWORD": settings.oracle_password,
    "ORACLE_DSN": settings.oracle_dsn,
    "CHROMA_COLLECTION_NAME": settings.chroma_collection_name,
    "CHROMA_PERSIST_DIRECTORY": settings.chroma_persist_directory,
}
placeholders = ("your_", "replace-", "change-me")
missing = [
    name for name, value in required.items()
    if not str(value or "").strip() or str(value).strip().lower().startswith(placeholders)
]
if not settings.allowed_tables:
    missing.append("ALLOWED_TABLES")
if settings.query_jobs_enabled and not settings.query_job_api_key:
    missing.append("QUERY_JOB_API_KEY")
admin_values = (
    settings.admin_auth_user,
    settings.admin_auth_password,
    settings.admin_session_secret,
)
if any(admin_values) and not settings.admin_auth_enabled:
    missing.append("ADMIN_AUTH_USER / ADMIN_AUTH_PASSWORD / ADMIN_SESSION_SECRET (secret must be at least 32 characters)")
if missing:
    print("Configuration needs attention: " + ", ".join(missing))
    raise SystemExit(2)
print("Configuration OK (secret values were not displayed).")
'@
Push-Location $AppRoot
try {
    $ConfigCheck | & $PythonExe -
    if ($LASTEXITCODE -ne 0) {
        throw "Production configuration is incomplete. Edit $EnvFile, then run DEPLOY.cmd again."
    }

    Write-Host "[5/7] Synchronizing baseline memory..." -ForegroundColor Cyan
    Invoke-Checked $PythonExe "-m" "nl_2_sql_vanna_oracle_pc.training"
}
finally {
    Pop-Location
}

Write-Host "[6/7] Installing or updating the Windows service..." -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath $ServiceExe)) {
    Copy-Item -LiteralPath $WinSWSource -Destination $ServiceExe
}
$Xml = (Get-Content -LiteralPath $ServiceTemplate -Raw).Replace("{{PORT}}", [string]$Port)
$Xml | Set-Content -LiteralPath $ServiceXml -Encoding UTF8

$ExistingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $ExistingService) {
    Invoke-Checked $ServiceExe "install"
}
Invoke-Checked $ServiceExe "start"

Write-Host "[7/7] Checking the running application..." -ForegroundColor Cyan
$StatusCode = Wait-ForApplication -ApplicationPort $Port
$Version | Set-Content -LiteralPath (Join-Path $AppRoot "current-version.txt") -Encoding ASCII

Write-Host ""
Write-Host "DEPLOYMENT SUCCESSFUL" -ForegroundColor Green
Write-Host "Version: $Version"
Write-Host "Service: Running"
Write-Host "Local URL: http://127.0.0.1:$Port/ (HTTP $StatusCode)"
Write-Host "Production data and .env were preserved."
