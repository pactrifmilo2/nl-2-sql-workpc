[CmdletBinding()]
param(
    [string]$AppRoot = "C:\Apps\nl2sql",
    [ValidateRange(1, 65535)][int]$Port = 8000
)

$ErrorActionPreference = "Continue"
$Service = Get-Service -Name "Nl2SqlVannaOracle" -ErrorAction SilentlyContinue
$VersionFile = Join-Path $AppRoot "current-version.txt"
$Version = if (Test-Path -LiteralPath $VersionFile) { (Get-Content -LiteralPath $VersionFile -Raw).Trim() } else { "unknown" }
$PortTest = Test-NetConnection -ComputerName "127.0.0.1" -Port $Port -WarningAction SilentlyContinue

Write-Host "NL2SQL PRODUCTION STATUS" -ForegroundColor Cyan
Write-Host "Version : $Version"
Write-Host "Service : $(if ($Service) { $Service.Status } else { 'Not installed' })"
Write-Host "Port $Port : $(if ($PortTest.TcpTestSucceeded) { 'Open' } else { 'Closed' })"
Write-Host "URL     : http://$($env:COMPUTERNAME):$Port/"

if ($Service -and $Service.Status -eq "Running" -and $PortTest.TcpTestSucceeded) {
    Write-Host "RESULT  : OK" -ForegroundColor Green
    exit 0
}

Write-Host "RESULT  : NEEDS TECHNICAL SUPPORT" -ForegroundColor Red
$AppLog = Join-Path $AppRoot "logs\app.log"
if (Test-Path -LiteralPath $AppLog) {
    Write-Host ""
    Write-Host "Last application log lines:"
    Get-Content -LiteralPath $AppLog -Tail 30
}
exit 1

