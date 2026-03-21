param(
  [Parameter(Mandatory = $true, Position = 0)]
  [ValidateSet('deploy', 'start', 'snapshot', 'fs', 'cleanup-tmp')]
  [string]$Command,

  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$toolkitDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = $env:QPY_PYTHON
if (-not $pythonExe) { $pythonExe = 'py' }

$pythonArgs = @()
if ($env:QPY_PYTHON_ARGS) {
  foreach ($item in ($env:QPY_PYTHON_ARGS -split ' ')) {
    $value = $item.Trim()
    if ($value) {
      $pythonArgs += $value
    }
  }
}
if ($pythonArgs.Count -eq 0) {
  $pythonArgs += '-3'
}

switch ($Command) {
  'deploy' {
    $scriptPath = Join-Path $toolkitDir 'qpy_incremental_deploy.py'
  }
  'start' {
    $scriptPath = Join-Path $toolkitDir 'qpy_runtime_start.py'
  }
  'snapshot' {
    $scriptPath = Join-Path $toolkitDir 'qpy_debug_snapshot.py'
  }
  'fs' {
    $scriptPath = Join-Path $toolkitDir 'qpy_device_fs_cli.py'
  }
  'cleanup-tmp' {
    $scriptPath = Join-Path $toolkitDir 'qpy_tmp_cleanup.py'
  }
  default {
    throw "Unsupported command: $Command"
  }
}

& $pythonExe @pythonArgs $scriptPath @Rest
exit $LASTEXITCODE
