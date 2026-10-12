"""My tools: features the assistant (or you) add to Fathom after it was built.

A tool is a small folder  <data>/ai/plugins/<id>/  with
    tool.json   {"id","label","icon","blurb","title","sub","run":"Start","mode":"all|each","accepts":"any|pdf|image|video|audio|text|office","fields":[...form fields...]}
    run.py      def run(ctx): ...   (see HARNESS below for what ctx offers)
It shows up in the app under "My tools", with the same file list, "where to save" chooser, progress and results as the built-in tools.
Each run is a separate Python process (so a mistake in a tool can never crash Fathom, and Stop really stops it)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from app import ops
from app.ai import store
from app.convert.core import Cancelled, ConvertError
from app.ops import Output, Task
from app.runtime import no_window_flags
from app.service import UserError
from app.opsvc import expand_sources

KINDS = {
    "pdf": {".pdf"}, "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".avif", ".ico"},
    "video": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".flv", ".m4v", ".mpg", ".mpeg"}, "audio": {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".opus", ".wma"},
    "text": {".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".html", ".htm", ".log", ".py", ".js", ".yml", ".yaml", ".ini", ".sql"}, "office": {".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt", ".odt", ".ods", ".odp", ".rtf"},
}

HARNESS_HELP = '''Write run.py like this:

    def run(ctx):
        # ctx.files      list of pathlib.Path  (mode "each": ctx.file is the single file; mode "all": ctx.files is every added file)
        # ctx.inputs     dict with what the user typed/chose in the form (keys are the field ids)
        # ctx.out_dir    pathlib.Path folder to save new files in (already exists)
        # ctx.log("text")            shows a line of progress to the user
        # ctx.progress(0.0 .. 1.0)   moves the progress bar
        # ctx.save(path)             mark a file as a result (also: just return paths)
        # ctx.new_path("name.ext")   a free file name inside out_dir (never overwrites)
        # ctx.table(rows)            show a small table in the results (list of dicts)
        # ctx.note("text")           the short sentence shown under the result
        # return a path, a list of paths, or None
    Everything installed with Fathom can be imported (Pillow, numpy, pypdf, reportlab, python-docx, openpyxl, cv2, requests ...).
    Raise an Exception with a plain-words message when something is wrong; the user will read it.'''

_HARNESS = r'''
import importlib.util, json, sys, traceback, pathlib, os
spec = json.load(open(sys.argv[1], encoding="utf-8"))
sys.path.insert(0, spec["dir"])
class Ctx:
    def __init__(self):
        self.files = [pathlib.Path(p) for p in spec["files"]]
        self.file = self.files[0] if self.files else None
        self.inputs = spec["inputs"]
        self.out_dir = pathlib.Path(spec["out_dir"]); self.out_dir.mkdir(parents=True, exist_ok=True)
        self.saved = []; self.notes = []; self.tables = []
    def log(self, *a):
        print("FXLOG " + " ".join(str(x) for x in a), flush=True)
    def progress(self, f):
        print("FXPROG %.4f" % max(0.0, min(1.0, float(f))), flush=True)
    def save(self, p):
        self.saved.append(str(p)); return p
    def note(self, t):
        self.notes.append(str(t))
    def table(self, rows):
        self.tables.append(list(rows)[:500])
    def new_path(self, name):
        p = self.out_dir / name; stem, suf, i = p.stem, p.suffix, 2
        while p.exists():
            p = self.out_dir / f"{stem} ({i}){suf}"; i += 1
        return p
try:
    s = importlib.util.spec_from_file_location("fx_plugin", os.path.join(spec["dir"], "run.py"))
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    ctx = Ctx()
    r = m.run(ctx)
    outs = list(ctx.saved)
    if r is not None:
        for x in (r if isinstance(r, (list, tuple)) else [r]):
            if x: outs.append(str(x))
    outs = list(dict.fromkeys(outs))
    json.dump({"ok": True, "outputs": outs, "notes": ctx.notes, "tables": ctx.tables}, open(spec["result"], "w", encoding="utf-8"))
except BaseException as e:
    tb = traceback.format_exc()
    json.dump({"ok": False, "error": f"{type(e).__name__}: {e}", "trace": tb[-1800:]}, open(spec["result"], "w", encoding="utf-8"))
    sys.exit(1)
'''


def root() -> Path:
    p = store.root() / "plugins"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:40] or "tool"


def _clean_fields(fields: list) -> list[dict]:
    allowed = {"text", "number", "textarea", "select", "check", "range", "password", "choice", "multi", "note", "pages", "datetime"}
    out = []
    for f in fields or []:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        t = f.get("type", "text")
        if t not in allowed:
            t = "text"
        d = {"id": re.sub(r"[^A-Za-z0-9_]", "_", str(f["id"])), "type": t, "label": str(f.get("label") or f["id"]), "tip": str(f.get("tip") or f.get("label") or "")}
        for k in ("value", "placeholder", "min", "max", "step"):
            if k in f:
                d[k] = f[k]
        if t in ("select", "choice", "multi"):
            opts = []
            for o in f.get("options") or []:
                if isinstance(o, dict):
                    opts.append({"v": str(o.get("v", o.get("l", ""))), "l": str(o.get("l", o.get("v", ""))), "tip": str(o.get("tip") or "")})
                else:
                    opts.append({"v": str(o), "l": str(o), "tip": ""})
            d["options"] = opts
        out.append(d)
    return out


def save(spec: dict, code: str) -> dict:
    tid = _slug(spec.get("id") or spec.get("label"))
    if not code or "def run" not in code:
        raise UserError("The tool needs a run.py with a function  def run(ctx):\n" + HARNESS_HELP)
    compile(code, "run.py", "exec")                      # syntax errors come back to the assistant right away
    meta = {
        "id": tid, "label": str(spec.get("label") or tid)[:40], "icon": str(spec.get("icon") or "🧰")[:4], "blurb": str(spec.get("blurb") or spec.get("label") or "A tool added to Fathom."),
        "title": str(spec.get("title") or spec.get("label") or tid), "sub": str(spec.get("sub") or spec.get("blurb") or ""), "run": str(spec.get("run") or "Start"),
        "mode": "each" if spec.get("mode") == "each" else "all", "accepts": spec.get("accepts") if spec.get("accepts") in KINDS else "any",
        "needs_files": spec.get("needs_files", True) is not False, "fields": _clean_fields(spec.get("fields")), "created": spec.get("created") or time.time(), "updated": time.time(),
    }
    d = root() / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.py").write_text(code, encoding="utf-8")
    (d / "tool.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def listing() -> list[dict]:
    out = []
    for d in sorted(root().iterdir()):
        try:
            m = json.loads((d / "tool.json").read_text(encoding="utf-8"))
            if (d / "run.py").exists():
                out.append(m)
        except Exception:
            continue
    return out


def get(tid: str) -> dict:
    if not re.fullmatch(r"[a-z0-9-]+", tid or ""):
        raise UserError("Unknown tool.")
    p = root() / tid
    if not (p / "tool.json").exists():
        raise UserError("That tool does not exist (any more).")
    m = json.loads((p / "tool.json").read_text(encoding="utf-8"))
    m["code"] = (p / "run.py").read_text(encoding="utf-8")
    return m


def delete(tid: str) -> None:
    get(tid)
    shutil.rmtree(root() / tid, ignore_errors=True)


def _accepts(kind: str, p: Path) -> bool:
    return kind == "any" or p.suffix.lower() in KINDS.get(kind, set())


def _exec(meta: dict, files: list[Path], inputs: dict, out_dir: Path, ctx, timeout: float | None = None) -> dict:
    tid = meta["id"]
    work = ctx.tmp
    work.mkdir(parents=True, exist_ok=True)
    spec = {"dir": str(root() / tid), "files": [str(f) for f in files], "inputs": inputs, "out_dir": str(out_dir), "result": str(work / "result.json")}
    (work / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    (work / "harness.py").write_text(_HARNESS, encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONPATH=os.environ.get("PYTHONPATH", ""))
    proc = subprocess.Popen([sys.executable, str(work / "harness.py"), str(work / "spec.json")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            cwd=str(out_dir), env=env, creationflags=no_window_flags())
    tail: list[str] = []

    def pump():
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip("\n")
            if line.startswith("FXLOG "):
                ctx.status(line[6:])
                tail.append(line[6:])
            elif line.startswith("FXPROG "):
                try:
                    ctx.progress(float(line[7:]))
                except ValueError:
                    pass
            else:
                tail.append(line)
            del tail[:-60]

    th = threading.Thread(target=pump, daemon=True)
    th.start()
    t0 = time.time()
    try:
        while proc.poll() is None:
            ctx.check()
            if timeout and time.time() - t0 > timeout:
                proc.kill()
                raise ConvertError(f"The tool ran for more than {int(timeout)} seconds and was stopped.")
            time.sleep(0.15)
    except Cancelled:
        proc.kill()
        raise
    finally:
        if proc.poll() is None:
            proc.kill()
    th.join(timeout=3)
    try:
        res = json.loads((work / "result.json").read_text(encoding="utf-8"))
    except Exception:
        res = {"ok": False, "error": "The tool stopped without an answer.", "trace": "\n".join(tail[-12:])}
    if not res.get("ok"):
        e = ConvertError(res.get("error") or "The tool failed.")
        e.trace = res.get("trace", "")  # type: ignore[attr-defined]
        raise e
    res["log"] = tail[-12:]
    return res


def run_start(tid: str, paths: list[str], recursive: bool, output: dict, inputs: dict) -> dict:
    meta = get(tid)
    files: list[tuple[Path, Path]] = []
    if meta.get("needs_files", True):
        for src, rel in expand_sources(paths, recursive):
            if _accepts(meta.get("accepts", "any"), src):
                files.append((src, rel))
        if not files:
            raise UserError("There are no files this tool can use. " + (f"It works on {meta['accepts']} files." if meta.get("accepts") != "any" else "Add some files first."))

    def out_folder(src: Path | None) -> Path:
        o = output or {}
        if o.get("mode") == "folder" and o.get("dir"):
            p = Path(o["dir"])
        elif src is not None:
            p = src.parent / (meta["label"] + " results")
        else:
            p = store.output_dir() / meta["label"]
        p.mkdir(parents=True, exist_ok=True)
        return p

    def make(srcs: list[Path], name: str) -> Task:
        def fn(ctx, task):
            res = _exec(meta, srcs, inputs, out_folder(srcs[0] if srcs else None), ctx)
            outs = [Path(p) for p in res["outputs"] if Path(p).exists()]
            note = " ".join(res.get("notes") or []) or (f"{len(outs)} file{'s' if len(outs) != 1 else ''} made." if outs else "Done.")
            extra = {}
            if res.get("tables"):
                extra["table"] = res["tables"][0]
            return Output(outs, note, extra=extra, skipped=False)
        return Task(name, fn, srcs[0] if srcs and len(srcs) == 1 else None)

    if not meta.get("needs_files", True):
        tasks = [make([], meta["label"])]
    elif meta["mode"] == "each":
        tasks = [make([s], s.name) for s, _r in files]
    else:
        tasks = [make([s for s, _r in files], f"{meta['label']} ({len(files)} files)")]
    return {"job": ops.start("plugin-" + tid, meta["label"], tasks, workers=1 if meta["mode"] == "all" else None).id}


def test_run(tid: str, files: list[str], inputs: dict, timeout: float = 600) -> dict:
    """run a tool once, right now, and report what happened (for the assistant to check its own work)"""
    meta = get(tid)

    class C:
        tmp = ops.temp_dir() / ("plugtest-" + tid)

        def status(self, s):
            pass

        def progress(self, f):
            pass

        def check(self):
            pass

    c = C()
    out = store.output_dir() / "tool tests" / tid
    out.mkdir(parents=True, exist_ok=True)
    try:
        res = _exec(meta, [Path(f) for f in files], inputs, out, c, timeout)
        return {"ok": True, "outputs": res["outputs"], "notes": res.get("notes"), "log": res.get("log"), "tables": res.get("tables")}
    except Exception as e:
        return {"ok": False, "error": str(e), "trace": getattr(e, "trace", "")}
    finally:
        shutil.rmtree(c.tmp, ignore_errors=True)
