# Fixes "the model was not found" / "bad manifest" in the Assistant. Needs administrator rights (it asks once). Writes Fathom-fix-ollama.txt in Downloads.
# What it does, in order (no model or file of yours is deleted):
#  1. stops Ollama;
#  2. if Ollama's folder (.ollama in your user folder) is a LINK to another folder (Ollama 0.40 cannot read models through a link),
#     it removes ONLY the link (a few KB; the folder it points to and every model in it stay untouched), makes a normal small .ollama
#     folder and points Ollama straight at the real models folder with the OLLAMA_MODELS setting. Nothing is left behind on C: for the models.
#     (To undo: in a Command Prompt run   mklink /J "%USERPROFILE%\.ollama" "<the folder named in the report>"  after removing the new .ollama folder.)
#  3. starts Ollama again, lists the models, and asks a model a question to prove it works.
. (Join-Path $PSScriptRoot '_common.ps1')
Require-Admin $MyInvocation.MyCommand.Path
Start-Report 'Fathom-fix-ollama'
$exe = Find-Ollama
if (-not $exe) { L 'Ollama is not installed. Run Fathom.bat (or Fathom-Setup.vbs) first.'; Finish-Report; exit }
foreach ($n in 'ollama app', 'ollama', 'ollama_llama_server') { Get-Process $n -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3
$o = Join-Path $env:USERPROFILE '.ollama'
$it = Get-Item -LiteralPath $o -Force -ErrorAction SilentlyContinue
$models = [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User')
if ($it -and $it.LinkType) {
  $t = $it.Target | Select-Object -First 1
  L ('The folder ' + $o + ' is a link to ' + $t)
  if (-not (Test-Path -LiteralPath $t)) { L 'The folder it points to is missing, so nothing was changed.'; Finish-Report; exit }
  & cmd.exe /c rmdir "$o" | Out-Null
  if (Test-Path -LiteralPath $o) { L 'Could not remove the link (a program is using it). Close Fathom and Ollama and run this again.'; Finish-Report; exit }
  New-Item -ItemType Directory -Path $o -Force | Out-Null
  Get-ChildItem -LiteralPath $t -File -Force -ErrorAction SilentlyContinue | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $o -Force }
  $models = Join-Path $t 'models'
  [Environment]::SetEnvironmentVariable('OLLAMA_MODELS', $models, 'User')
  L ('The link was removed (only the link; the models are untouched in ' + $t + '). Ollama now reads its models straight from ' + $models)
}
else { L ('The folder ' + $o + ' is not a link, so no link fix was needed.') }
if ($models) { $env:OLLAMA_MODELS = $models }
L ('OLLAMA_MODELS = ' + $models)
if (-not (Start-OllamaServer $exe)) { L 'Ollama did not start. Restart the PC and run this again.'; Finish-Report; exit }
L 'Ollama is running.'
L '---- models Ollama can see'
$tags = $null
try { $tags = (Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 10).models } catch {}
if ($tags) { foreach ($m in $tags) { L ('  ' + $m.name) } }
if (-not $tags -or $tags.Count -eq 0) {
  L 'Still empty. Downloading a tiny test model (400 MB) to see whether Ollama can store and read models at all ...'
  & $exe pull qwen2.5:0.5b 2>&1 | Select-Object -Last 2 | ForEach-Object { L $_ }
  try { $tags = (Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 10).models; foreach ($m in $tags) { L ('  ' + $m.name) } } catch {}
}
if ($tags -and $tags.Count -gt 0) {
  $name = $tags[0].name
  foreach ($m in $tags) { if ($m.name -like 'qwen3-vl*instruct*') { $name = $m.name } }
  L ('---- asking ' + $name + ' a question')
  try {
    $body = ('{"model":"' + $name + '","prompt":"Say hi","stream":false,"options":{"num_predict":12}}')
    $r = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/generate' -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 300
    L ('answer: ' + $r.response)
    L 'It works. Open Fathom and try the Assistant.'
  } catch { L ('The question failed: ' + $_.Exception.Message) }
}
else { L 'Ollama still shows no models. Run 7-Diagnose-Ollama and send me the file it saves.' }
Finish-Report
