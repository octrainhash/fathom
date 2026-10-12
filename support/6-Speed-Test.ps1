# Times the assistant with Fathom's real instructions, so a slow answer can be explained. Writes Fathom-speed.txt in Downloads.
. (Join-Path $PSScriptRoot '_common.ps1')
Start-Report 'Fathom-speed'
$exe = Find-Ollama
if (-not $exe -or -not (Start-OllamaServer $exe)) { L 'Ollama is not running. Run Fathom.bat first (or 2-Fix-Ollama).'; Finish-Report; exit }
$code = @'
import os, sys, json, time, urllib.request
sys.path.insert(0, os.environ["FATHOM_APP"])
from app.ai import agent, tools, store
cfg = store.load()
M = (cfg.get("models") or {}).get("ollama") or "qwen3-vl:4b-instruct"
B = "http://127.0.0.1:11434"
print("model:", M)
def post(path, body, timeout=900):
    t = time.time()
    req = urllib.request.Request(B + path, data=json.dumps(body).encode(), headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return time.time() - t, {"error": str(e)}
    return time.time() - t, j
def show(name, el, j):
    if "error" in j and "message" not in j:
        print(name, "| ERROR", j["error"]); return
    m = j.get("message", {})
    print(name, "| total %.1fs" % el, "| answer:", repr((m.get("content") or "")[:80]), "| thinking chars:", len(m.get("thinking") or ""),
          "| prompt tokens:", j.get("prompt_eval_count"), "prefill s: %.1f" % ((j.get("prompt_eval_duration") or 0) / 1e9),
          "| new tokens:", j.get("eval_count"), "gen s: %.1f" % ((j.get("eval_duration") or 0) / 1e9), "| load s: %.1f" % ((j.get("load_duration") or 0) / 1e9))
hi = [{"role": "user", "content": "Say hi in one short sentence."}]
show("1 warm-up (loads the model)  ", *post("/api/chat", {"model": M, "messages": hi, "stream": False, "options": {"num_predict": 40}}))
show("2 simple question            ", *post("/api/chat", {"model": M, "messages": hi, "stream": False, "options": {"num_predict": 40}}))
sp = agent.system_prompt(agent.Session())
tl = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in tools.schemas()]
big = [{"role": "system", "content": sp}, {"role": "user", "content": "hi"}]
print("Fathom's real prompt: %d characters of instructions, %d tools" % (len(sp), len(tl)))
show("3 Fathom prompt              ", *post("/api/chat", {"model": M, "messages": big, "tools": tl, "stream": False, "options": {"num_predict": 60}}))
show("4 same again (cached)        ", *post("/api/chat", {"model": M, "messages": big, "tools": tl, "stream": False, "options": {"num_predict": 60}}))
print("DONE")
'@
Invoke-FathomPython $code 'speed'
Finish-Report
