# Downloads the fast assistant model (qwen3-vl:4b-instruct, about 3.3 GB), makes Fathom use it and times a first answer. Writes Fathom-model.txt in Downloads.
. (Join-Path $PSScriptRoot '_common.ps1')
Start-Report 'Fathom-model'
$exe = Find-Ollama
if (-not $exe) { L 'Ollama is not installed. Run Fathom.bat (or Fathom-Setup.vbs) first.'; Finish-Report; exit }
if (-not (Start-OllamaServer $exe)) { L 'Ollama did not start. Run 2-Fix-Ollama first.'; Finish-Report; exit }
L 'Downloading qwen3-vl:4b-instruct (3.3 GB). Keep this window open; a part that is already downloaded is kept if it stops.'
& $exe pull qwen3-vl:4b-instruct
L ('download finished, exit code ' + $LASTEXITCODE)
& $exe list 2>&1 | ForEach-Object { L $_ }
$code = @'
import os, sys, time
sys.path.insert(0, os.environ["FATHOM_APP"])
from app.ai import llm, store
store.save({"provider": "ollama", "models": {"ollama": "qwen3-vl:4b-instruct"}})
print("Fathom now uses qwen3-vl:4b-instruct for the Assistant.")
t = time.time()
try:
    ans = llm.complete("You answer very briefly.", [{"role": "user", "content": "Say hi in one short sentence."}], max_tokens=60)
    print("first answer: %r in %.1f s (the first one loads the model, later ones are faster)" % (ans, time.time() - t))
except Exception as e:
    print("the test question failed: %s" % e)
'@
Invoke-FathomPython $code 'model'
Finish-Report
