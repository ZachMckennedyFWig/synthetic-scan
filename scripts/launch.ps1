<#
.SYNOPSIS
  Start Scan Lab and open it in the browser.

.DESCRIPTION
  Single process: the Python backend serves the built UI, so there is one port, no Node at
  run time, and no CORS. Rebuilds the UI only when its sources are newer than the build.
  Closing this window stops the server. Modeled on FootprintUi's launcher.

.PARAMETER Dev
  Run Vite's dev server (hot reload, port 5173) alongside the API instead of the static build.
#>
param(
  [int] $Port = 8849,
  [int] $Workers = 0,
  [switch] $Dev,
  [switch] $NoBrowser,
  [switch] $Rebuild
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$ui = Join-Path $root 'ui'
$dist = Join-Path $ui 'dist'
$Host.UI.RawUI.WindowTitle = 'Scan Lab'

function Say($msg, $color = 'Gray') { Write-Host $msg -ForegroundColor $color }
function Fail($msg) { Write-Host "`n  $msg`n" -ForegroundColor Red; Read-Host 'Press Enter to close'; exit 1 }

Say "`n  Scan Lab`n  ========`n" Cyan

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Fail 'uv is not on PATH. Install it: https://docs.astral.sh/uv/getting-started/installation/'
}
Push-Location $root
try {
  if (-not (Test-Path (Join-Path $root '.venv'))) { Say '  First run: creating the Python environment...' Yellow }
  uv sync --quiet
  if ($LASTEXITCODE -ne 0) { Fail 'uv sync failed.' }
} finally { Pop-Location }

function Test-NeedsBuild {
  if ($Rebuild) { return $true }
  $index = Join-Path $dist 'index.html'
  if (-not (Test-Path $index)) { return $true }
  $built = (Get-Item $index).LastWriteTime
  $newest = Get-ChildItem (Join-Path $ui 'src'), (Join-Path $ui 'index.html'), (Join-Path $ui 'package.json') -Recurse -File |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
  return ($newest -and $newest.LastWriteTime -gt $built)
}

if (-not $Dev -and (Test-NeedsBuild)) {
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    if (Test-Path (Join-Path $dist 'index.html')) { Say '  npm not found - using the existing UI build.' Yellow }
    else { Fail 'npm is not on PATH and there is no UI build yet. Install Node.js 22.' }
  } else {
    Say '  Building the UI...' Yellow
    Push-Location $ui
    try {
      if (-not (Test-Path 'node_modules')) { npm ci --no-audit --no-fund }
      npm run build
      if ($LASTEXITCODE -ne 0) { Fail 'UI build failed.' }
    } finally { Pop-Location }
  }
}

$serveArgs = @('run', 'synthscan', 'serve', '--port', $Port)
if ($Workers -gt 0) { $serveArgs += @('--workers', $Workers) }
if ($NoBrowser -or $Dev) { $serveArgs += '--no-browser' }

if ($Dev) {
  Say "  Dev mode: API on :$Port, UI with hot reload on http://localhost:5173" Yellow
  $vite = Start-Process -PassThru -WorkingDirectory $ui -FilePath 'npm.cmd' -ArgumentList 'run', 'dev'
  if (-not $NoBrowser) { Start-Process 'http://localhost:5173' }
  try { Push-Location $root; uv @serveArgs } finally { Pop-Location; if ($vite -and -not $vite.HasExited) { Stop-Process -Id $vite.Id -Force } }
} else {
  Say "  Serving on http://127.0.0.1:$Port  (close this window to stop)" Green
  Push-Location $root
  try { uv @serveArgs } finally { Pop-Location }
}
