# Reads the state of Fathom and Ollama (read-only) and asks the assistant a test question. Writes Fathom-check.txt in Downloads.
. (Join-Path $PSScriptRoot '_common.ps1')
Start-Report 'Fathom-check'
L ('Fathom app folder : ' + $AppDir)
L ('Fathom version    : ' + (Get-AppVersion))
L ('Data folder       : ' + $DataDir)
$it = Get-Item -LiteralPath $DataDir -Force -ErrorAction SilentlyContinue
if ($it) { if ($it.LinkType) { L ('  it is a link to  : ' + ($it.Target | Select-Object -First 1)) } else { L '  it is a normal folder' } } else { L '  (it does not exist: Fathom is not set up yet)' }
foreach ($f in 'installed-2.ok', 'build.txt', 'app-dir.txt', 'places.txt') {
  $p = Join-Path $DataDir $f
  if (Test-Path -LiteralPath $p) { L ('  ' + $f + ': ' + ((Get-Content -LiteralPath $p -TotalCount 6) -join ' ; ')) } else { L ('  ' + $f + ': missing') }
}
L ('Fathom Python    : ' + $(if (Find-Python) { 'found' } else { 'missing' }))
L ('Choice file      : ' + $(if (Test-Path -LiteralPath (Join-Path $AppDir 'install-choice.txt')) { ((Get-Content -LiteralPath (Join-Path $AppDir 'install-choice.txt')) -join ' ; ') } else { '(none)' }))
L ''
L '== Windows settings Fathom uses'
foreach ($n in 'OLLAMA_MODELS', 'OLLAMA_CONTEXT_LENGTH', 'OLLAMA_KEEP_ALIVE') { L ('  ' + $n + ' = ' + [Environment]::GetEnvironmentVariable($n, 'User')) }
L ''
L '== Programs'
foreach ($p in @((Join-Path $env:ProgramFiles 'Python312'), (Join-Path $env:ProgramFiles 'LibreOffice'), (Join-Path $env:ProgramFiles 'Calibre2'), (Join-Path $env:ProgramFiles '7-Zip'), (Join-Path $env:LOCALAPPDATA 'Programs\Ollama'), (Join-Path $env:USERPROFILE '.ollama'))) {
  $i2 = Get-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
  if ($i2) { if ($i2.LinkType) { L ('  ' + $p + '  -> ' + ($i2.Target | Select-Object -First 1)) } else { L ('  ' + $p + '  (normal folder)') } } else { L ('  ' + $p + '  : not installed') }
}
L ''
L '== Free space'
foreach ($d in [IO.DriveInfo]::GetDrives()) { if ($d.DriveType -eq 'Fixed' -and $d.IsReady) { L ('  {0}  {1:N1} GB free of {2:N1} GB' -f $d.Name, ($d.AvailableFreeSpace / 1GB), ($d.TotalSize / 1GB)) } }
L ''
L '== Ollama'
$exe = Find-Ollama
if (-not $exe) { L '  Ollama is not installed.' }
else {
  L ('  program: ' + $exe)
  try { L ('  version: ' + ((& $exe --version 2>&1) -join ' ')) } catch {}
  L ('  server running: ' + (Test-OllamaUp))
  if (Test-OllamaUp) {
    try { $tags = (Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 10).models; L ('  models listed: ' + $tags.Count); foreach ($m in $tags) { L ('    ' + $m.name + '  ' + [math]::Round($m.size / 1GB, 2) + ' GB') } } catch { L ('  could not read the model list: ' + $_.Exception.Message) }
  }
}
L ''
L '== Ask the assistant (through Fathom itself)'
$code = @'
import os, sys, time
sys.path.insert(0, os.environ["FATHOM_APP"])
from app.ai import llm, store
cfg = store.load()
print("provider:", cfg.get("provider"), "| model:", (cfg.get("models") or {}).get(cfg.get("provider")))
t = time.time()
try:
    ans = llm.complete("You answer very briefly.", [{"role": "user", "content": "Reply with the single word: pong"}], max_tokens=40)
    print("answer: %r in %.1f s" % (ans, time.time() - t))
except Exception as e:
    print("FAILED after %.1f s: %s" % (time.time() - t, e))
'@
Invoke-FathomPython $code 'check'
Finish-Report
