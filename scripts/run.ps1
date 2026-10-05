$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $root "backend"
Start-Process -FilePath (Join-Path $root ".venv\Scripts\python.exe") -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8787" -WorkingDirectory $root
Set-Location (Join-Path $root "frontend")
npm run dev
