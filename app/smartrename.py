"""Smart rename: the local AI reads each file (text, PDF first page, or a small copy of a picture) and suggests a clear name.
Nothing is renamed here. The suggestions come back as rows in the same shape as the normal Rename preview, so the person edits
them and applies with the existing rename/apply (which keeps the undo journal)."""
from __future__ import annotations

import base64
import io
import json
import re
import subprocess
from pathlib import Path
from typing import Callable

from . import ops
from .filetools import expand_sources
from .ops import Ctx, Output, Task

TEXT_EXT = {".txt", ".md", ".csv", ".json", ".log", ".html", ".htm", ".xml", ".py", ".js", ".rtf", ".srt", ".vtt", ".yaml", ".yml"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

SYSTEM = ("You name files. Given a file's current name and a sample of its content, reply with ONE short, clear, descriptive file name "
          "WITHOUT the extension, in the same language as the content. No quotes, no explanation, no path. Use at most {words} words. "
          "{style}")
STYLES = {"words": "Use normal words separated by spaces.", "dash": "Use lowercase words joined with dashes.",
          "snake": "Use lowercase words joined with underscores."}


def clean_name(s: str, style: str = "words", limit: int = 80) -> str:
    """turn whatever the model said into a safe file stem ('' if nothing usable)"""
    s = (s or "").strip().splitlines()[0] if (s or "").strip() else ""
    s = re.sub(r"^(file ?name|name)\s*[:=-]\s*", "", s, flags=re.I).strip().strip("`'\" ")
    s = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", s) if re.search(r"\.[A-Za-z]{2,4}$", s) else s
    s = BAD.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    if style == "dash":
        s = re.sub(r"[\s_]+", "-", s.lower())
    elif style == "snake":
        s = re.sub(r"[\s-]+", "_", s.lower())
    return s[:limit].rstrip(" .-_")


def sample(p: Path, limit: int = 1800) -> tuple[str, bytes | None]:
    """(text sample, small jpeg bytes for pictures)"""
    ext = p.suffix.lower()
    try:
        if ext in TEXT_EXT:
            return p.read_bytes()[:limit * 4].decode("utf-8", "replace")[:limit], None
        if ext == ".pdf":
            r = subprocess.run(["pdftotext", "-l", "2", "-q", str(p), "-"], capture_output=True, timeout=30)
            return r.stdout.decode("utf-8", "replace")[:limit], None
        if ext in IMG_EXT:
            from PIL import Image
            with Image.open(p) as im:
                im = im.convert("RGB")
                im.thumbnail((768, 768))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=80)
                return "", buf.getvalue()
    except Exception:
        pass
    return "", None


def suggest_one(p: Path, ask: Callable[..., str], words: int, style: str, use_pictures: bool) -> str:
    text, img = sample(p)
    if img is not None and not use_pictures:
        img = None
    if not text.strip() and img is None:
        return ""                                    # nothing to read, so we do not guess
    content: list | str
    head = f"Current name: {p.stem}\n" + (f"Content sample:\n{text}" if text.strip() else "The picture is attached.")
    if img is not None:
        content = [{"type": "text", "text": head},
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(img).decode()}}]
    else:
        content = head
    system = SYSTEM.format(words=words, style=STYLES.get(style, STYLES["words"]))
    return clean_name(ask(system, [{"role": "user", "content": content}]), style)


def _default_ask(cancel):
    from .ai import llm
    return lambda system, messages: llm.complete(system, messages, cancel, 60)


def start(paths: list[str], recursive: bool, options: dict, ask: Callable[..., str] | None = None) -> dict:
    words = max(2, min(12, int(options.get("words") or 6)))
    style = options.get("style") or "words"
    pics = bool(options.get("pictures", True))
    tasks = []
    for p, rel in expand_sources(paths, recursive):
        def fn(ctx: Ctx, task: Task, p=p) -> Output:
            ctx.check()
            a = ask or _default_ask(ctx.cancel)
            try:
                stem = suggest_one(p, a, words, style, pics)
            except Exception as e:                   # model off, not installed, ... : one clear message per file
                raise RuntimeError(f"The AI could not answer ({str(e)[:160]}). Check that your local AI is running in AI settings.")
            if not stem:
                return Output(note="Nothing readable to base a name on", skipped=True, extra={"old": p.name, "path": str(p)})
            new = stem + p.suffix
            return Output(note=new, extra={"old": p.name, "new": new, "path": str(p), "folder": str(p.parent)})
        tasks.append(Task(p.name, fn, p, rel=rel))
    if not tasks:
        from .service import UserError
        raise UserError("Add some files first.")
    job = ops.start("smartrename", "Suggesting names", tasks, workers=1)
    return {"job": job.id, "total": len(tasks)}


def rows_from_results(results: list[dict]) -> dict:
    """job results -> the same rows the Rename preview gives (so apply, undo and clash handling are shared)"""
    rows, taken = [], {}
    for r in results:
        x = r.get("extra") or {}
        if r["status"] != "done" or not x.get("new"):
            continue
        p = Path(x["path"])
        new, n = x["new"], 2
        used = taken.setdefault(str(p.parent).lower(), set())
        while new.lower() in used or (new != p.name and (p.parent / new).exists()):
            new = f"{Path(x['new']).stem} ({n}){p.suffix}"
            n += 1
        used.add(new.lower())
        rows.append({"path": x["path"], "old": p.name, "new": new, "folder": str(p.parent), "status": "same" if new == p.name else "ok"})
    return {"rows": rows, "changes": sum(1 for r in rows if r["status"] == "ok")}
