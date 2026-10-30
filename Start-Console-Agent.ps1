$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Run Setup-Project.ps1 first.' }
& $python scripts/sites_connection_agent.py
if ($LASTEXITCODE -ne 0) { throw 'The connection agent stopped. See the message above.' }
