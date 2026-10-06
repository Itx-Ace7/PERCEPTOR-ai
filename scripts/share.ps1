# Publish the analysis service so the hosted site works from any device.
# Starts the API and a public tunnel, points the Vercel site at the tunnel, and redeploys it.
# Run it again after a restart: a free tunnel gets a new address each time it starts.
param(
  [string]$Alias = "perceptor-ai-release.vercel.app",
  [int]$Port = 8787,
  [string]$Cloudflared = $(if ($env:CLOUDFLARED) { $env:CLOUDFLARED } else { "cloudflared" })
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

function Start-Detached([string]$file, [string]$arguments, [string]$stdout, [string]$stderr, [string]$setup = "") {
  # cmd /c redirects the output; WMI starts it outside this shell's job so it outlives the window.
  # That process does not inherit this shell's variables, so $setup carries them (e.g. "set A=1 &").
  $line = "cmd /c `"$setup `"$file`" $arguments > `"$stdout`" 2> `"$stderr`"`""
  $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $line; CurrentDirectory = $root }
  if ($result.ReturnValue -ne 0) { throw "Could not start $file (code $($result.ReturnValue))" }
}

function Wait-Until([scriptblock]$check, [int]$seconds, [string]$what) {
  $deadline = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $deadline) {
    $value = & $check
    if ($value) { return $value }
    Start-Sleep -Milliseconds 500
  }
  throw "Timed out waiting for $what"
}

# 1. The API. A public service must not read folders on this machine.
$health = "http://127.0.0.1:$Port/api/health"
$up = try { (Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $false }
if (-not $up) {
  $python = Join-Path $root ".venv\Scripts\python.exe"
  $setup = "set `"PYTHONPATH=$(Join-Path $root 'backend')`"& set PERCEPTOR_ALLOW_LOCAL_PATHS=0&"
  Start-Detached $python "-m uvicorn app.main:app --host 127.0.0.1 --port $Port" (Join-Path $logs "api.out.log") (Join-Path $logs "api.err.log") $setup
  Wait-Until { try { (Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { $false } } 40 "the API" | Out-Null
}
Write-Host "API is up on port $Port"

# 2. A public tunnel to it. Keep one that is already answering, otherwise start a new one.
$tunnelLog = Join-Path $logs "tunnel.err.log"
function Get-TunnelUrl {
  if (-not (Test-Path $tunnelLog)) { return $null }
  $m = [regex]::Match((Get-Content $tunnelLog -Raw), "https://[a-z0-9-]+\.trycloudflare\.com")
  if ($m.Success) { $m.Value } else { $null }
}
function Test-Tunnel([string]$url) {
  if (-not $url -or -not (Get-Process cloudflared -ErrorAction SilentlyContinue)) { return $false }
  try { (Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 8).StatusCode -eq 200 } catch { $false }
}
$tunnel = Get-TunnelUrl
if (-not (Test-Tunnel $tunnel)) {
  Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Remove-Item $tunnelLog -ErrorAction SilentlyContinue
  Start-Detached $Cloudflared "tunnel --url http://127.0.0.1:$Port --no-autoupdate" (Join-Path $logs "tunnel.out.log") $tunnelLog
  $tunnel = Wait-Until { Get-TunnelUrl } 40 "the tunnel address"
  Wait-Until { Test-Tunnel $tunnel } 90 "the tunnel to answer" | Out-Null
}
Write-Host "Tunnel is up at $tunnel"

# 3. Point the hosted site at it and publish. Use the installed Vercel CLI; npx would download one.
$vercel = (Get-Command vercel -ErrorAction SilentlyContinue).Source
if (-not $vercel) { throw "Install the Vercel CLI first: npm install -g vercel, then vercel login" }
function Invoke-Vercel {
  # Its progress goes to stderr, which PowerShell would otherwise report as a failure.
  $previous = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try { $text = & $vercel @args 2>&1 | Out-String } finally { $ErrorActionPreference = $previous }
  if ($LASTEXITCODE -ne 0) { Write-Host $text; throw "vercel $($args[0]) failed" }
  $text
}
Set-Location (Join-Path $root "frontend")
Invoke-Vercel env add API_UPSTREAM production --value $tunnel --yes --force --no-sensitive | Out-Null
$deploy = Invoke-Vercel --prod --yes
$match = [regex]::Match($deploy, '"url":\s*"https://([^"]+)"')
if (-not $match.Success) { Write-Host $deploy; throw "Vercel did not report a deployment" }
Invoke-Vercel alias set $match.Groups[1].Value $Alias | Out-Null

$answer = try { (Invoke-WebRequest -Uri "https://$Alias/api/health" -UseBasicParsing -TimeoutSec 40).StatusCode } catch { "failed" }
Write-Host "Live site /api/health: $answer"
Write-Host "Keep this computer awake while people use https://$Alias"
