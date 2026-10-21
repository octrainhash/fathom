# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
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


# ------------------------------------------------------------------ "where is it?" (finding a place in the app)
# Things people can use that are not a tool tab of their own. "open" is the tool tab that shows it (None = nothing to open).
PLACES = [
    {"id": "p-quickfind", "label": "Quick find (Ctrl+K)", "open": "home", "where": "the 🔍 Ctrl+K button at the top right of the window (or press Ctrl+K anywhere)", "what": "Jump to any tool by typing what you want to do.", "words": "jump search tools shortcut keyboard"},
    {"id": "p-theme", "label": "Light / dark look", "open": "home", "where": "the Home tab, 'All tools', next to the search box (the 'Look' menu)", "what": "Switch Fathom between light, dark and matching Windows.", "words": "theme dark mode light mode colours appearance look"},
    {"id": "p-saved", "label": "Saved results", "open": None, "where": "the 'Saved results' button at the top right of the window", "what": "See how much room the pictures and clips of your search matches use, and delete them. Your own files are never touched.", "words": "storage cache disk space proof pictures clear delete saved"},
    {"id": "p-undo", "label": "Undo", "open": "history", "where": "the Undo button at the top right (it appears after Fathom changes your files); the full list is in Tidy > Activity & Undo", "what": "Take back the last renaming or tidy-up.", "words": "undo revert restore back rename mistake"},
    {"id": "p-key", "label": "AI key and model", "open": "aisettings", "where": "the Assistant tab, then Settings", "what": "Choose the AI, paste your key, pick the model and decide when the assistant must ask you first.", "words": "api key claude openai ollama model provider ai brain approval"},
    {"id": "p-voice", "label": "Voice and microphone", "open": "aisettings", "where": "the Assistant tab, then Settings, in the Voice card", "what": "Pick the voice that reads answers aloud, the speech engine for the microphone and test the speaker.", "words": "voice speak read aloud microphone speech tts talk listen"},
    {"id": "p-pictures", "label": "Picture-making service", "open": "aisettings", "where": "the Assistant tab, then Settings, in the Pictures card", "what": "Connect a service so the assistant can paint pictures (posters and diagrams work without one).", "words": "image generate draw painting dall-e stable diffusion pictures"},
    {"id": "p-newtool", "label": "Build a new tool", "open": "aisettings", "where": "the Assistant tab, then Settings, at the bottom ('Build a new tool'); finished tools appear in the My tools tab", "what": "Describe a feature and the assistant adds it to Fathom as a tool of your own.", "words": "plugin custom create make add feature mytools extension"},
    {"id": "p-watch", "label": "Watch my screen", "open": "aichat", "where": "the Assistant tab, the 👁 'Watch my screen' button next to the message box", "what": "Lets the assistant see your screen so it can guide you.", "words": "screen share look see guide help"},
    {"id": "p-findopts", "label": "Search options (case, whole word, OCR, handwriting, objects, speech)", "open": "find", "where": "the Search tab, then Find: the kind-of-search buttons and the options under them", "what": "Words, words seen in pictures, spoken words, objects and scenes, matching a picture, and every option for each.", "words": "case regex whole word ocr handwriting objects speech spoken video clips strictness"},
]

# words people use for things, mapped to what the screens call them
ALIASES = {
    "compress": "smaller pack resize shrink", "shrink": "smaller resize compress", "reduce": "smaller resize", "zip": "pack archive", "unzip": "pack archive extract",
    "watermark": "stamp", "signature": "sign stamp", "sign": "signature stamp", "autograph": "sign",
    "ocr": "find scan handwriting pictures text", "scan": "scan scanner pages", "scanner": "scanner scan import",
    "delete": "shred empty duplicates junk", "wipe": "shred", "clean": "junk duplicates empty organise", "cleanup": "junk duplicates organise",
    "password": "lock pdflock", "encrypt": "lock pdflock", "protect": "lock redact", "secure": "lock shred redact",
    "blur": "redact", "censor": "redact", "hide": "redact hidden steg", "private": "redact meta exif",
    "convert": "convert encodings", "change format": "convert", "transform": "convert",
    "edit": "editor visual replace", "drag": "visual", "move objects": "visual", "arrows": "visual", "shapes": "visual", "layers": "visual", "slide": "visual", "powerpoint": "visual editor", "svg": "visual", "vector": "visual",
    "duplicate": "dups duplicates", "same": "dups duplicates compare", "diff": "compare", "difference": "compare",
    "name": "rename smartrename", "rename": "rename smartrename", "ai rename": "smartrename",
    "meaning": "semsearch search", "semantic": "semsearch", "notes": "semsearch", "concept": "semsearch",
    "photo": "exif touchup meta", "location": "exif meta", "gps": "exif meta", "date": "times", "dates": "times",
    "download": "downloads torrent links", "magnet": "downloads torrent", "torrent": "downloads mktorrent torinfo", "url": "links",
    "recover": "carve repair", "deleted": "carve", "restore": "carve history", "corrupt": "repair", "broken": "repair", "damaged": "repair damage",
    "disk": "drives space", "drive": "drives space compat", "format": "drives fsguide fsother compat", "usb": "drives compat", "storage": "drives space",
    "print": "print copy", "photocopy": "copy", "xerox": "copy",
    "merge": "merge join", "combine": "merge join", "split": "split cut", "cut": "cut split", "trim": "cut", "crop": "touchup cut",
    "rotate": "rotate", "flip": "rotate", "mirror": "rotate", "pages": "pages nup extract rotate", "reorder": "pages", "booklet": "nup",
    "bookmark": "pdfprops", "title": "pdfprops", "author": "pdfprops", "form": "pdfform", "fill": "pdfform",
    "qr": "qr", "barcode": "qr", "hash": "hash", "checksum": "hash", "fingerprint": "hash",
    "text": "find editor replace", "search": "find semsearch scrape", "find": "find semsearch dups",
    "backup": "sync", "cloud": "sync", "ftp": "sync links", "mirror folder": "sync",
    "permissions": "perms", "attributes": "attrs", "hidden": "attrs streams meta steg",
    "handwriting": "hand", "handwritten": "hand",
    "chat": "aichat", "assistant": "aichat", "settings": "aisettings",
}
STOP = {"the", "a", "an", "to", "of", "in", "on", "is", "it", "where", "what", "how", "do", "does", "can", "i", "you", "me", "my", "for", "with", "and", "or", "that", "this", "there", "have", "has", "find", "feature", "option", "button", "tool", "tab", "section", "page", "fathom", "app", "files", "file", "document", "documents", "want", "need", "use", "get", "go", "take", "show", "open", "something"}


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _bag(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())}


def _score(words: list[str], hay_id: str, hay_label: str, hay_what: str, hay_extra: str) -> int:
    lab, what, ext = _bag(hay_label), _bag(hay_what), _bag(hay_extra)
    sc = 0
    for w in words:
        s = _stem(w)
        if w == hay_id or w == hay_label:
            sc += 12
        elif s in lab or w in hay_id.split("-") or (len(w) >= 4 and w in hay_id):
            sc += 8
        elif s in ext:
            sc += 4
        elif s in what:
            sc += 2
    return sc


def find(query: str, tools: list[dict] | None = None, groups: dict[str, str] | None = None, limit: int = 6) -> dict:
    """Where is it in the app? tools = what the window says it has (preferred, always up to date); falls back to the source scan."""
    groups = groups or {}
    if not tools:
        tools = [{"id": s["id"], "group": s["group"], "label": s["label"], "what": s["what"]} for s in screens()]
        have = {t["id"] for t in tools}
        for tid, lab, what in (("stamp", "Stamp", "Put a stamp, text or picture on PDFs and pictures."), ("sign", "Sign", "Draw, type or place your signature on a PDF or picture.")):
            if tid not in have:
                tools.append({"id": tid, "group": "edit", "label": lab, "what": what})
    q = re.sub(r"[^\w\s-]", " ", (query or "").lower())
    words = [w for w in q.split() if w not in STOP and len(w) > 1]
    phrase = " ".join(words)
    extra: list[str] = []
    for k, v in ALIASES.items():
        if (" " in k and k in q) or k in words or (k.endswith("s") and k[:-1] in words):
            extra += v.split()
    seen_w = set(words)
    all_words = words + [w for w in extra if w not in seen_w]
    hits = []
    for t in tools:
        hid, hl, hw = t["id"].lower(), t["label"].lower(), (t.get("what") or t.get("blurb") or "").lower()
        gl = (groups.get(t["group"]) or t["group"]).lower()
        sc = _score(words, hid, hl, hw, gl) * 2 + _score([w for w in extra if w not in seen_w], hid, hl, hw, gl)
        if phrase and phrase in hl:
            sc += 10
        if sc > 0:
            hits.append((sc, {"id": t["id"], "label": t["label"], "tab": groups.get(t["group"], t["group"]), "what": _tidy(hw, 160),
                              "where": f"the {groups.get(t['group'], t['group'])} tab at the top, then {t['label']} in the row under it", "open_with": t["id"]}))
    for p in PLACES:
        sc = _score(words, p["id"], p["label"].lower(), p["what"].lower(), p["words"]) * 2 + _score([w for w in extra if w not in seen_w], p["id"], p["label"].lower(), p["what"].lower(), p["words"])
        if sc > 0:
            hits.append((sc, {"id": p["id"], "label": p["label"], "what": p["what"], "where": p["where"], "open_with": p["open"]}))
    hits.sort(key=lambda x: -x[0])
    out = [h for _, h in hits[:limit]]
    res: dict = {"query": query, "found": bool(out), "matches": out}
    if out and hits[0][0] >= 8:
        res["best"] = out[0]["label"]
    if not out:
        res["note"] = ("Nothing in Fathom's screens matches that. Do NOT say it exists. Say Fathom has no screen for it; if the assistant itself can do it (code, a custom tool), offer that instead. "
                       "You may call fathom_tools with one or two plain words to double-check the web routes.")
    else:
        res["note"] = ("Tell the user plainly whether it exists and exactly where (tab, then tool), then ask if they want to be taken there (ask_user with choices 'Yes, take me there' / 'No thanks'). "
                       "Only call open_in_fathom after a yes, unless they already asked to be taken or opened there.")
    return res
