# Shared helpers for the Fathom help scripts in this folder. Plain text: open it in Notepad to read it.
# Nothing here runs by itself; the numbered scripts load it. None of the scripts deletes anything.
$ErrorActionPreference = 'Continue'
$Support = $PSScriptRoot
$AppDir = Split-Path -Parent $Support
$DataDir = Join-Path $env:LOCALAPPDATA 'Fathom'
$Downloads = Join-Path $env:USERPROFILE 'Downloads'
$script:ReportPath = $null

function Start-Report([string]$name) {
  if (-not (Test-Path -LiteralPath $Downloads)) { $script:ReportPath = Join-Path $env:TEMP ($name + '.txt') } else { $script:ReportPath = Join-Path $Downloads ($name + '.txt') }
  Set-Content -LiteralPath $script:ReportPath -Value ($name + '   ' + (Get-Date)) -Encoding UTF8
}
function L([string]$s) {
  Write-Host $s
  if ($script:ReportPath) { try { Add-Content -LiteralPath $script:ReportPath -Value $s -Encoding UTF8 } catch {} }
}
function Finish-Report {
  L ''
  if ($script:ReportPath) { L ('The result was saved in: ' + $script:ReportPath) }
  Read-Host 'Press Enter to close this window'
}
function Test-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
# runs the calling script again with administrator rights (Windows asks once), then ends this copy
function Require-Admin([string]$self) {
  if (Test-Admin) { return }
  Write-Host 'Windows will ask for permission (administrator). Please click Yes.'
  try { Start-Process -FilePath 'powershell.exe' -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File "' + $self + '"') -Verb RunAs } catch { Write-Host 'Permission was not given.'; Read-Host 'Press Enter to close' }
  exit
}
function Find-Ollama {
  foreach ($c in @((Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'), (Join-Path $env:ProgramFiles 'Ollama\ollama.exe'))) { if (Test-Path -LiteralPath $c) { return $c } }
  $cmd = Get-Command ollama.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}
function Test-OllamaUp {
  try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 3 | Out-Null; return $true } catch { return $false }
}
function Start-OllamaServer([string]$exe) {
  if (Test-OllamaUp) { return $true }
  $env:OLLAMA_MODELS = [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User')
  Start-Process -FilePath $exe -ArgumentList 'serve' -WindowStyle Hidden
  for ($i = 0; $i -lt 40; $i++) { Start-Sleep -Seconds 1; if (Test-OllamaUp) { return $true } }
  return $false
}
function Find-Python {
  $p = Join-Path $DataDir 'venv\Scripts\python.exe'
  if (Test-Path -LiteralPath $p) { return $p }
  return $null
}
function Get-AppVersion {
  try { return (Select-String -LiteralPath (Join-Path $AppDir 'app\paths.py') -Pattern '^VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1).Matches[0].Groups[1].Value } catch { return '(unknown)' }
}
# run a little Python with Fathom's own Python and show every line it prints
function Invoke-FathomPython([string]$code, [string]$name) {
  $py = Find-Python
  if (-not $py) { L '  (Fathom''s Python was not found: Fathom is not set up yet. Run Fathom.bat first.)'; return }
  $tmp = Join-Path $env:TEMP ('fathom_' + $name + '.py')
  Set-Content -LiteralPath $tmp -Value $code -Encoding UTF8
  $env:PYTHONIOENCODING = 'utf-8'
  $env:FATHOM_APP = $AppDir
  & $py -u $tmp 2>&1 | ForEach-Object { L ([string]$_) }
}
