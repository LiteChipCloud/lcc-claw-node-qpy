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
$pushConfigMode = $env:QPY_PUSH_CONFIG
if (-not $pushConfigMode) { $pushConfigMode = 'auto' }
$configOverride = $env:QPY_CONFIG_FILE
$filesCsv = $env:QPY_FILES
$startRuntime = $env:QPY_START_RUNTIME
if (-not $startRuntime) { $startRuntime = '0' }
$autoPort = $env:QPY_AUTO_PORT
if (-not $autoPort) { $autoPort = '0' }
$jsonMode = $env:QPY_JSON
if (-not $jsonMode) { $jsonMode = '1' }

$args = @(
  (Join-Path $repoDir 'host_tools\qpy_incremental_deploy.py'),
  '--runtime-root', (Join-Path $repoDir 'usr_mirror'),
  '--manifest', (Join-Path $repoDir 'host_tools\runtime_manifest.json'),
  '--baud', $replBaud,
  '--config-mode', $pushConfigMode
)

if ($autoPort -eq '1') {
  $args += '--auto-port'
} else {
  $args += @('--port', $replPort)
}

if ($configOverride) {
  $args += @('--config-file', $configOverride)
}

if ($filesCsv) {
  foreach ($item in ($filesCsv -split ',')) {
    $value = $item.Trim()
    if ($value) {
      $args += @('--file', $value)
    }
  }
}

if ($startRuntime -eq '1') {
  $args += '--start-runtime'
  $args += '--snapshot'
}

if ($jsonMode -eq '1') {
  $args += '--json'
}

Write-Host '[deploy] Running manifest-driven deploy'
Write-Host "  repoDir=$repoDir"
Write-Host "  configMode=$pushConfigMode"
if ($filesCsv) {
  Write-Host "  selectedFiles=$filesCsv"
} else {
  Write-Host '  selectedFiles=<full manifest>'
}

& $pythonExe @args
exit $LASTEXITCODE
