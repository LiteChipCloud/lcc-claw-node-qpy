$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$baseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = $env:QPY_PYTHON
if (-not $pythonExe) { $pythonExe = 'python' }
$replPort = $env:QPY_REPL_PORT
if (-not $replPort) { $replPort = 'COM6' }
$replBaud = $env:QPY_REPL_BAUD
if (-not $replBaud) { $replBaud = '921600' }
$runMain = $env:QPY_RUN_MAIN
if (-not $runMain) { $runMain = '1' }
$pushConfigMode = $env:QPY_PUSH_CONFIG
if (-not $pushConfigMode) { $pushConfigMode = 'auto' }
$configOverride = $env:QPY_CONFIG_FILE
$runtimeDir = Join-Path $baseDir 'usr_mirror'
$fsCli = Join-Path (Join-Path $baseDir 'host_tools') 'qpy_device_fs_cli.py'

function Test-PlaceholderConfig {
  param([string]$Path)
  if (-not (Test-Path $Path)) { return $false }
  $content = Get-Content -Path $Path -Raw -ErrorAction SilentlyContinue
  if (-not $content) { return $false }
  $markers = @(
    '<openclaw_auth_token>',
    'replace_with_your_token',
    'REMOTE_SIGNER_HTTP_URL = ""',
    'OPENCLAW_AUTH_TOKEN = "replace_with_your_token"',
    'REMOTE_SIGNER_HTTP_AUTH_TOKEN = ""'
  )
  foreach ($marker in $markers) {
    if ($content.Contains($marker)) { return $true }
  }
  return $false
}

function Push-DeviceFile {
  param(
    [string]$LocalPath,
    [string]$RemoteDir,
    [string]$RemoteName = ''
  )
  $args = @('--port', $replPort, '--baud', $replBaud, '--json', 'push', '--local', $LocalPath, '--remote-dir', $RemoteDir)
  if ($RemoteName) {
    $args += @('--remote-name', $RemoteName)
  }
  & $pythonExe $fsCli @args | Out-Host
}

if ($configOverride) {
  $resolved = Resolve-Path -Path $configOverride -ErrorAction SilentlyContinue
  if (-not $resolved) {
    throw "QPY_CONFIG_FILE not found: $configOverride"
  }
  $configOverride = $resolved.Path
}

Write-Host "[1/4] Ensure remote directories on $replPort@$replBaud"
& $pythonExe $fsCli --port $replPort --baud $replBaud --json mkdir --path /usr | Out-Host
& $pythonExe $fsCli --port $replPort --baud $replBaud --json mkdir --path /usr/app | Out-Host
& $pythonExe $fsCli --port $replPort --baud $replBaud --json mkdir --path /usr/app/tools | Out-Host

Write-Host '[2/4] Push runtime files'
Push-DeviceFile -LocalPath (Join-Path $runtimeDir '_main.py') -RemoteDir /usr
Get-ChildItem -Path (Join-Path $runtimeDir 'app') -File | Sort-Object Name | ForEach-Object {
  if ($_.Name -ne 'config.py') {
    Push-DeviceFile -LocalPath $_.FullName -RemoteDir /usr/app
    return
  }

  if ($pushConfigMode -eq 'skip') {
    Write-Host '  Skip /usr/app/config.py because QPY_PUSH_CONFIG=skip'
    return
  }

  if ($configOverride) {
    Write-Host "  Push /usr/app/config.py from QPY_CONFIG_FILE: $configOverride"
    Push-DeviceFile -LocalPath $configOverride -RemoteDir /usr/app -RemoteName 'config.py'
    return
  }

  if ($pushConfigMode -eq 'always') {
    Write-Host '  Push /usr/app/config.py from runtime bundle because QPY_PUSH_CONFIG=always'
    Push-DeviceFile -LocalPath $_.FullName -RemoteDir /usr/app
    return
  }

  if (Test-PlaceholderConfig -Path $_.FullName) {
    Write-Warning 'Skip placeholder /usr/app/config.py in auto mode. Set QPY_CONFIG_FILE=<path> or QPY_PUSH_CONFIG=always to override.'
    return
  }

  Write-Host '  Push /usr/app/config.py from runtime bundle (auto mode, non-placeholder)'
  Push-DeviceFile -LocalPath $_.FullName -RemoteDir /usr/app
}
Get-ChildItem -Path (Join-Path $runtimeDir 'app\tools') -File | Sort-Object Name | ForEach-Object {
  Push-DeviceFile -LocalPath $_.FullName -RemoteDir /usr/app/tools
}

Write-Host '[3/4] Verify /usr/app tree'
& $pythonExe $fsCli --port $replPort --baud $replBaud --json ls --path /usr | Out-Host
& $pythonExe $fsCli --port $replPort --baud $replBaud --json ls --path /usr/app | Out-Host
& $pythonExe $fsCli --port $replPort --baud $replBaud --json ls --path /usr/app/tools | Out-Host

if ($runMain -eq '1') {
  Write-Host '[4/4] Start runtime'
  & $pythonExe $fsCli --port $replPort --baud $replBaud --json run --path /usr/_main.py | Out-Host
} else {
  Write-Host "[4/4] Skip runtime start because QPY_RUN_MAIN=$runMain"
}
