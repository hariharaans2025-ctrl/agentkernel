$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$dashboardUrl = 'http://127.0.0.1:8766'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Install the project in .venv first. See README.md.'
}
$alreadyRunning = $false
try {
    $config = Invoke-RestMethod -Uri "$dashboardUrl/api/config" -TimeoutSec 2
    $alreadyRunning = $config.execution_backend -eq 'Nebius Sandbox'
} catch { }
if (-not $alreadyRunning) {
    $logDirectory = Join-Path $projectRoot 'reports\dashboard'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $server = Start-Process -FilePath $pythonPath -ArgumentList '-m agentkernel.dashboard.server --port 8766' `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDirectory "$stamp-server.log") `
        -RedirectStandardError (Join-Path $logDirectory "$stamp-error.log")
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try {
            $config = Invoke-RestMethod -Uri "$dashboardUrl/api/config" -TimeoutSec 2
            if ($config.execution_backend -eq 'Nebius Sandbox') { $alreadyRunning = $true; break }
        } catch { }
        if ($server.HasExited) { break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $alreadyRunning) { throw "Dashboard did not start. Check $logDirectory." }
}
Write-Output "Dashboard ready: $dashboardUrl"
