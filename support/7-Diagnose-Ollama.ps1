# Collects what is needed to understand an Ollama problem (read-only). Writes Fathom-ollama-diagnosis.txt in Downloads.
. (Join-Path $PSScriptRoot '_common.ps1')
Start-Report 'Fathom-ollama-diagnosis'
$exe = Find-Ollama
L ('ollama.exe: ' + $exe)
if ($exe) { try { L ('version: ' + ((& $exe --version 2>&1) -join ' ')) } catch {} }
L ('server running: ' + (Test-OllamaUp))
foreach ($n in 'OLLAMA_MODELS', 'OLLAMA_CONTEXT_LENGTH', 'OLLAMA_KEEP_ALIVE', 'OLLAMA_HOST') { L ('  ' + $n + ' (user) = ' + [Environment]::GetEnvironmentVariable($n, 'User') + '   (machine) = ' + [Environment]::GetEnvironmentVariable($n, 'Machine')) }
$o = Join-Path $env:USERPROFILE '.ollama'
$i = Get-Item -LiteralPath $o -Force -ErrorAction SilentlyContinue
if ($i) { L ('.ollama: ' + $(if ($i.LinkType) { 'LINK -> ' + ($i.Target | Select-Object -First 1) } else { 'normal folder' })) } else { L '.ollama: missing' }
$mm = [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User')
if (-not $mm) { $mm = Join-Path $o 'models' }
L ('models folder: ' + $mm + '   exists: ' + (Test-Path -LiteralPath $mm))
foreach ($sub in 'manifests', 'manifests-v2', 'blobs') {
  $p = Join-Path $mm $sub
  if (Test-Path -LiteralPath $p) { $c = (Get-ChildItem -LiteralPath $p -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object); L ('  ' + $sub + ': ' + $c.Count + ' files') }
}
Get-ChildItem -LiteralPath $mm -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { $_.LinkType } | Select-Object -First 20 | ForEach-Object { L ('  LINK inside: ' + $_.FullName + ' -> ' + ($_.Target | Select-Object -First 1)) }
if ($exe -and (Test-OllamaUp)) {
  L '---- ollama list'; & $exe list 2>&1 | ForEach-Object { L $_ }
}
L '---- the last lines of Ollama''s own logs'
foreach ($f in @((Join-Path $env:LOCALAPPDATA 'Ollama\server.log'), (Join-Path $DataDir 'ollama-serve.log'), (Join-Path $DataDir 'ollama-report.txt'))) {
  if (Test-Path -LiteralPath $f) { L ('-- ' + $f); Get-Content -LiteralPath $f -Tail 30 -ErrorAction SilentlyContinue | ForEach-Object { L ('   ' + $_) } }
}
Finish-Report
