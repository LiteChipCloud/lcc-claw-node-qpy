$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoDir = Split-Path -Parent $scriptDir
$pythonExe = $env:QPY_PYTHON
if (-not $pythonExe) { $pythonExe = 'python' }
$replPort = $env:QPY_REPL_PORT
if (-not $replPort) { $replPort = 'COM6' }
$replBaud = $env:QPY_REPL_BAUD
if (-not $replBaud) { $replBaud = '921600' }
$autoPort = $env:QPY_AUTO_PORT
if (-not $autoPort) { $autoPort = '0' }

$args = @(
  (Join-Path $repoDir 'host_tools\qpy_debug_snapshot.py'),
  '--baud', $replBaud
)

if ($autoPort -eq '1') {
  $args += '--auto-port'
} else {
  $args += @('--port', $replPort)
}

Write-Host '[runtime] Capture debug snapshot'
& $pythonExe @args
exit $LASTEXITCODE
