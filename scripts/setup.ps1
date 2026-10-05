$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
}
Set-Location (Join-Path $root "frontend")
npm install
Write-Host "Setup complete. Start the app with scripts\run.ps1"
