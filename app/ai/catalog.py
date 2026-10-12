"""A live catalogue of everything Fathom can do, read from the app's own source so it never goes out of date: the screens (names and plain
descriptions) and the web routes behind them (with how each route reads the request). The assistant uses it to run any tool in the app."""
from __future__ import annotations

import ast
import importlib
import inspect
import re
from functools import lru_cache
from pathlib import Path

from app.paths import ROOT

BODY_FIELDS = {
    "paths": "list of file/folder paths to work on", "recursive": "bool, go into folders (default true)", "mapping": "dict (convert: source format -> target)",
    "options": "dict of tool-specific options", "output": "dict, where results go (see 'output' below)", "spec": "dict, tool-specific settings", "replace": "bool, replace originals",
    "kind": "string", "mode": "string", "value": "string", "text": "string", "text2": "string", "password": "string", "number": "number", "flag": "bool",
    "rows": "list of dicts", "rules": "dict", "algos": "list of strings", "job": "job id string", "remove": "list of strings",
}
OUTPUT_HELP = ("output = {\"mode\": \"folder\"|\"beside\"|\"replace\", \"folder\": \"<path>\", \"name\": \"<optional name>\", \"policy\": \"rename\"|\"overwrite\"|\"skip\"} . "
               "If you leave output empty the files are saved beside the originals with a new name. Always prefer a folder under the assistant output folder for new work.")


def _main_source() -> str:
    return (ROOT / "app" / "main.py").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def routes() -> list[dict]:
    tree = ast.parse(_main_source())
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for dec in fn.decorator_list:
            path = method = None
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "_post" and dec.args and isinstance(dec.args[0], ast.Constant):
                path, method = dec.args[0].value, "POST"
            elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in ("get", "post") and isinstance(dec.func.value, ast.Name) and dec.func.value.id == "app" and dec.args and isinstance(dec.args[0], ast.Constant):
                path, method = dec.args[0].value, dec.func.attr.upper()
            if not path or not path.startswith("/api/") or path.startswith(("/api/ai", "/api/quit", "/api/pick", "/api/health")):
                continue
            body = "\n".join(ast.unparse(s) for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(getattr(s, "value", None), ast.Constant)))
            doc = ast.get_docstring(fn) or ""
            out.append({"path": path, "method": method, "name": fn.name, "doc": doc, "code": body, "args": [a.arg for a in fn.args.args]})
    return sorted(out, key=lambda r: r["path"])


@lru_cache(maxsize=1)
def screens() -> list[dict]:
    """tool screens declared in the interface files: id, group, label, blurb"""
    res = []
    for f in sorted((ROOT / "static").glob("*.js")):
        src = f.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'\bid:\s*"([\w-]+)"\s*,\s*group:\s*"([\w-]+)"[^{}]*?label:\s*"([^"]+)"\s*,\s*blurb:\s*"((?:[^"\\]|\\.)*)"', src):
            res.append({"id": m.group(1), "group": m.group(2), "label": m.group(3), "what": m.group(4).replace('\\"', '"'), "file": f.name})
    return res


def _tidy(s: str, n: int = 140) -> str:
    return re.sub(r"\s+", " ", s).strip()[:n]


def listing(query: str = "") -> dict:
    q = (query or "").lower().split()
    scr = [s for s in screens() if not q or all(w in (s["id"] + " " + s["label"] + " " + s["what"] + " " + s["group"]).lower() for w in q)]
    rts = [r for r in routes() if not q or all(w in (r["path"] + " " + r["doc"]).lower() for w in q)]
    return {
        "screens": [{"id": s["id"], "group": s["group"], "label": s["label"], "what": _tidy(s["what"], 200)} for s in scr[:80]],
        "routes": [{"path": r["path"], "method": r["method"], "calls": _tidy(r["code"].replace("return ", ""), 150)} for r in rts[:120]],
        "note": "Call fathom_tool_info with a route path for exact details. Most routes that change files return {\"job\": id}; fathom_run waits for them.",
    }


def _target(code: str):
    """find the python function a route calls, e.g. filetools2.rotate_start"""
    m = re.search(r"\b(\w+)\.(\w+)\(", code)
    if not m:
        return None
    mod, fn = m.groups()
    for pkg in ("app." + mod, "app.ai." + mod):
        try:
            return getattr(importlib.import_module(pkg), fn)
        except Exception:
            continue
    return None


def info(path: str) -> dict:
    for r in routes():
        if r["path"] == path:
            t = _target(r["code"])
            tdoc = signature = ""
            if t:
                try:
                    signature = f"{t.__module__.split('.')[-1]}.{t.__name__}{inspect.signature(t)}"
                    tdoc = inspect.getdoc(t) or ""
                except Exception:
                    pass
            src = ""
            if t:
                try:
                    src = inspect.getsource(t)
                    src = src[:5200]
                except Exception:
                    pass
            return {"path": path, "method": r["method"], "how_the_route_reads_the_request": r["code"][:1500], "body_fields": BODY_FIELDS, "output": OUTPUT_HELP,
                    "function": signature, "function_doc": tdoc[:1500], "function_source_start": src,
                    "hint": "Body keys are the 'b.xxx' names used in the route code. Put tool-specific settings inside options. Read the function source to see which option keys exist."}
    raise KeyError(path)


def hint_prompt() -> str:
    by_group: dict[str, list[str]] = {}
    for s in screens():
        by_group.setdefault(s["group"], []).append(f'{s["label"]} ({s["id"]})')
    return "; ".join(f"{g}: {', '.join(v)}" for g, v in by_group.items())
