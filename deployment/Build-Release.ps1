[CmdletBinding()]
param(
    [string]$OutputDirectory = "",
    [string]$PythonVersion = "3.14",
    [string]$WinSWPath = "",
    [switch]$OnlineInstall,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $RepoRoot "release-output"
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)

$UvCommand = Get-Command uv -ErrorAction SilentlyContinue
if (-not $UvCommand) {
    throw "uv was not found. Install uv on the build machine, then run this script again."
}
$UvExe = $UvCommand.Source

$ProjectFile = Join-Path $RepoRoot "pyproject.toml"
$VersionMatch = Select-String -LiteralPath $ProjectFile -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $VersionMatch) {
    throw "Could not read the project version from $ProjectFile."
}
$Version = $VersionMatch.Matches[0].Groups[1].Value
$ReleaseName = "nl2sql-$Version"
$ReleaseRoot = Join-Path $OutputDirectory $ReleaseName
$ZipPath = Join-Path $OutputDirectory "$ReleaseName.zip"

if ((Test-Path -LiteralPath $ReleaseRoot) -or (Test-Path -LiteralPath $ZipPath)) {
    throw "Release $Version already exists in $OutputDirectory. Increase the version in pyproject.toml, or move the existing release first."
}

New-Item -ItemType Directory -Path (Join-Path $ReleaseRoot "app") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ReleaseRoot "tools") -Force | Out-Null

Push-Location $RepoRoot
try {
    if (-not $SkipTests) {
        Write-Host "[1/6] Running tests..." -ForegroundColor Cyan
        Invoke-Checked $UvExe "run" "--python" $PythonVersion "pytest" "-q"
    }
    else {
        Write-Host "[1/6] Tests skipped by request." -ForegroundColor Yellow
    }

    Write-Host "[2/6] Building wheel $Version..." -ForegroundColor Cyan
    Invoke-Checked $UvExe "--quiet" "build" "--wheel" "--no-sources" "--python" $PythonVersion "--out-dir" (Join-Path $ReleaseRoot "app")

    Write-Host "[3/6] Exporting locked dependencies..." -ForegroundColor Cyan
    Invoke-Checked $UvExe "--quiet" "export" "--frozen" "--no-dev" "--no-emit-project" "--format" "requirements.txt" "--output-file" (Join-Path $ReleaseRoot "requirements.txt")

    $Wheels = @(Get-ChildItem -LiteralPath (Join-Path $ReleaseRoot "app") -Filter "*.whl")
    if ($Wheels.Count -ne 1 -or $Wheels[0].Name -notmatch "-$([regex]::Escape($Version))-" ) {
        throw "Expected exactly one wheel for version $Version, but found: $($Wheels.Name -join ', ')"
    }

    Copy-Item -LiteralPath (Join-Path $RepoRoot ".env.oracle.example") -Destination (Join-Path $ReleaseRoot ".env.example")
    Copy-Item -Path (Join-Path $PSScriptRoot "production\*") -Destination $ReleaseRoot -Recurse
    Copy-Item -LiteralPath $UvExe -Destination (Join-Path $ReleaseRoot "tools\uv.exe")

    Write-Host "[4/6] Adding the Windows service wrapper..." -ForegroundColor Cyan
    $WinSWVersion = "2.12.0"
    $WinSWHash = "05B82D46AD331CC16BDC00DE5C6332C1EF818DF8CEEFCD49C726553209B3A0DA"
    if (-not $WinSWPath) {
        $CacheRoot = Join-Path $env:LOCALAPPDATA "nl2sql-build-cache"
        New-Item -ItemType Directory -Path $CacheRoot -Force | Out-Null
        $WinSWPath = Join-Path $CacheRoot "WinSW-x64-$WinSWVersion.exe"
        if (-not (Test-Path -LiteralPath $WinSWPath)) {
            $WinSWUrl = "https://github.com/winsw/winsw/releases/download/v$WinSWVersion/WinSW-x64.exe"
            Write-Host "Downloading WinSW $WinSWVersion from its official GitHub release..."
            Invoke-WebRequest -Uri $WinSWUrl -OutFile $WinSWPath -UseBasicParsing
        }
    }
    $WinSWPath = (Resolve-Path -LiteralPath $WinSWPath).Path
    $ActualWinSWHash = (Get-FileHash -LiteralPath $WinSWPath -Algorithm SHA256).Hash
    if ($ActualWinSWHash -ne $WinSWHash) {
        throw "WinSW checksum verification failed. Expected $WinSWHash, received $ActualWinSWHash."
    }
    Copy-Item -LiteralPath $WinSWPath -Destination (Join-Path $ReleaseRoot "tools\WinSW-x64.exe")

    if (-not $OnlineInstall) {
        Write-Host "[5/6] Downloading offline Python packages..." -ForegroundColor Cyan
        $Wheelhouse = Join-Path $ReleaseRoot "wheelhouse"
        New-Item -ItemType Directory -Path $Wheelhouse -Force | Out-Null
        Invoke-Checked $UvExe "run" "--python" $PythonVersion "--with" "pip" "python" "-m" "pip" "download" "--quiet" "--only-binary=:all:" "--requirement" (Join-Path $ReleaseRoot "requirements.txt") "--dest" $Wheelhouse
    }
    else {
        Write-Host "[5/6] Online installation selected; wheelhouse was not included." -ForegroundColor Yellow
    }

    @(
        "Product: nl-2-sql-vanna-oracle-pc"
        "Version: $Version"
        "Built: $([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))"
        "Python target: $PythonVersion"
        "Offline packages included: $(-not $OnlineInstall)"
    ) | Set-Content -LiteralPath (Join-Path $ReleaseRoot "RELEASE.txt") -Encoding UTF8

    Write-Host "[6/6] Creating release ZIP..." -ForegroundColor Cyan
    Compress-Archive -Path (Join-Path $ReleaseRoot "*") -DestinationPath $ZipPath -CompressionLevel Optimal
    $ZipHash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash
    "$ZipHash  $ReleaseName.zip" | Set-Content -LiteralPath "$ZipPath.sha256" -Encoding ASCII
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Release ready:" -ForegroundColor Green
Write-Host "  $ZipPath"
Write-Host "  $ZipPath.sha256"
Write-Host "Send both files to production. The operator only needs to extract the ZIP and run DEPLOY.cmd."
