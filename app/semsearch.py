# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Search by meaning, all on this computer. Files are cut into short passages, each passage is turned into numbers by a small local
embedding model (Ollama, default nomic-embed-text), and the numbers are kept in a SQLite file. A search embeds your question and
returns the closest passages, with a proof picture: the best-matching sentence highlighted, circled and pointed at with an arrow.
Only changed files are read again. Nothing leaves the computer."""
from __future__ import annotations

import array
import contextlib
import json
import math
import re
import sqlite3
import subprocess
import threading
import urllib.request
from pathlib import Path
from typing import Callable

from . import annotate, ops, paths, proof, textsnap
from .filetools import expand_sources
from .ops import Ctx, Output, Task

GROUPS = {
    "notes": {".txt", ".md", ".rtf", ".tex"},
    "data": {".csv", ".json", ".xml", ".yaml", ".yml", ".log", ".srt", ".vtt"},
    "web": {".html", ".htm"},
    "code": {".py", ".js"},
    "pdf": {".pdf"},
}
MODEL = "nomic-embed-text"
CHUNK_SIZES = {"small": 500, "medium": 900, "large": 1500}
_LOCK = threading.Lock()
_COLOR_LOCK = threading.Lock()


def _int(v, default, lo, hi):
    try:
        return max(lo, min(hi, int(float(v))))
    except (TypeError, ValueError):
        return default


def index_opts(o: dict | None) -> dict:
    o = o or {}
    groups = [g for g in (o.get("groups") or list(GROUPS)) if g in GROUPS] or list(GROUPS)
    return {"groups": groups, "chunk": CHUNK_SIZES.get(o.get("size") or "medium", 900), "max_chunks": _int(o.get("max_chunks"), 10, 1, 60),
            "pdf_pages": _int(o.get("pdf_pages"), 12, 1, 300), "model": (o.get("model") or "").strip() or MODEL}


def _sig(io: dict) -> str:
    return f"{io['chunk']}|{io['max_chunks']}|{io['pdf_pages']}|{io['model']}"


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(str(paths.data_root() / "semantic.db"), timeout=30)
    c.execute("create table if not exists files2(path text primary key, mtime real, size integer, sig text)")
    c.execute("create table if not exists chunks2(path text, n integer, page integer, text text, vec blob)")
    c.execute("create index if not exists ci2 on chunks2(path)")
    return c


def _fitz():
    try:
        import pymupdf as fitz  # type: ignore
        return fitz
    except ImportError:
        try:
            import fitz  # type: ignore
            return fitz
        except ImportError:
            return None


def read_units(p: Path, pdf_pages: int, cap: int) -> list[tuple[int, str]]:
    """[(page number (0 for non-PDF), text)]"""
    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            f = _fitz()
            if f is not None:
                with f.open(str(p)) as d:
                    return [(i + 1, pg.get_text()) for i, pg in enumerate(list(d)[:pdf_pages])]
            r = subprocess.run(["pdftotext", "-l", str(pdf_pages), "-q", str(p), "-"], capture_output=True, timeout=90)
            return [(i + 1, t) for i, t in enumerate(r.stdout.decode("utf-8", "replace").split("\f")) if t.strip()]
        raw = p.read_bytes()[:cap * 4].decode("utf-8", "replace")
        if ext in (".html", ".htm"):
            raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
            raw = re.sub(r"<[^>]+>", " ", raw)
        return [(0, raw)]
    except Exception:
        return []


def chunks(units: list[tuple[int, str]], size: int, max_chunks: int) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for page, text in units:
        text = " ".join(text.split())
        for i in range(0, len(text), size):
            out.append((page, text[i:i + size]))
            if len(out) >= max_chunks:
                return out
    return out


def ollama_embed(texts: list[str], cfg: dict | None = None, model: str = "") -> list[list[float]]:
    from .ai import store
    cfg = cfg or store.load()
    base = (cfg["base_urls"].get("ollama") or "http://localhost:11434/v1").rstrip("/")
    root = base[:-3] if base.endswith("/v1") else base
    model = model or cfg.get("embed_model") or MODEL
    req = urllib.request.Request(root + "/api/embed", data=json.dumps({"model": model, "input": texts}).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())["embeddings"]
    except Exception as e:
        raise RuntimeError(f"The embedding model is not available ({str(e)[:120]}). In a terminal run: ollama pull {model}")


def _pack(v: list[float]) -> bytes:
    return array.array("f", v).tobytes()


def _unpack(b: bytes) -> list[float]:
    a = array.array("f")
    a.frombytes(b)
    return list(a)


def cosine(a: list[float], b: list[float]) -> float:
    d = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return d / (na * nb) if na and nb else 0.0


def _under(path: str, roots: list[str]) -> bool:
    if not roots:
        return True
    for r in roots:
        r = str(Path(r))
        sep = "\\" if "\\" in r else "/"
        if path == r or path.startswith(r.rstrip("/\\") + sep):
            return True
    return False


# ---------------------------------------------------------------- learning the files
def index_start(paths_in: list[str], recursive: bool, opts: dict | None = None, embed: Callable | None = None) -> dict:
    io = index_opts(opts)
    allowed = set().union(*(GROUPS[g] for g in io["groups"]))
    sig = _sig(io)
    emb = embed or (lambda t: ollama_embed(t, model=io["model"]))
    tasks = []
    for p, rel in expand_sources(paths_in, recursive):
        if p.suffix.lower() not in allowed:
            continue

        def fn(ctx: Ctx, task: Task, p=p) -> Output:
            ctx.check()
            st = p.stat()
            with _LOCK:
                c = _db()
                row = c.execute("select mtime,size,sig from files2 where path=?", (str(p),)).fetchone()
                c.close()
            if row and abs(row[0] - st.st_mtime) < 1e-3 and row[1] == st.st_size and row[2] == sig:
                return Output(note="Already up to date", skipped=True)
            parts = chunks(read_units(p, io["pdf_pages"], io["chunk"] * io["max_chunks"]), io["chunk"], io["max_chunks"])
            if not parts:
                return Output(note="No readable text (a scanned PDF needs OCR first)", skipped=True)
            vecs = emb([t for _, t in parts])
            with _LOCK:
                c = _db()
                c.execute("delete from chunks2 where path=?", (str(p),))
                c.executemany("insert into chunks2 values(?,?,?,?,?)", [(str(p), i, pg, t, _pack(v)) for i, ((pg, t), v) in enumerate(zip(parts, vecs))])
                c.execute("insert or replace into files2 values(?,?,?,?)", (str(p), st.st_mtime, st.st_size, sig))
                c.commit()
                c.close()
            return Output(note=f"{len(parts)} passage{'s' if len(parts) != 1 else ''}")
        tasks.append(Task(p.name, fn, p, rel=rel))
    if not tasks:
        from .service import UserError
        raise UserError("None of the added files are of a type you chose to learn. Add text files, notes or PDFs, or tick more file types.")
    job = ops.start("semindex", "Learning your files", tasks, workers=1)
    return {"job": job.id, "total": len(tasks)}


def status(roots: list[str] | None = None) -> dict:
    with _LOCK:
        c = _db()
        files = [r[0] for r in c.execute("select path from files2")]
        n = c.execute("select count(*) from chunks2").fetchone()[0]
        c.close()
    mine = [f for f in files if _under(f, roots or [])]
    db = paths.data_root() / "semantic.db"
    return {"files": len(files), "passages": n, "here": len(mine), "bytes": db.stat().st_size if db.exists() else 0}


def forget(roots: list[str] | None, everything: bool = False) -> dict:
    with _LOCK:
        c = _db()
        files = [r[0] for r in c.execute("select path from files2")]
        gone = files if everything else [f for f in files if _under(f, roots or [])]
        for f in gone:
            c.execute("delete from chunks2 where path=?", (f,))
            c.execute("delete from files2 where path=?", (f,))
        c.commit()
        c.close()
    return {"forgotten": len(gone)}


# ---------------------------------------------------------------- proof pictures
@contextlib.contextmanager
def _colors(hl: str, circle: str):
    def rgb(h, d):
        h = (h or "").lstrip("#")
        try:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else d
        except ValueError:
            return d
    with _COLOR_LOCK:
        old = annotate.YELLOW, annotate.RED
        annotate.YELLOW, annotate.RED = rgb(hl, old[0]), rgb(circle, old[1])
        try:
            yield
        finally:
            annotate.YELLOW, annotate.RED = old


def _sentences(text: str) -> list[tuple[int, int]]:
    spans = [(m.start(), m.end()) for m in re.finditer(r"[^.!?\n]+[.!?]?", text) if len(m.group().strip()) > 3]
    return spans or [(0, len(text))]


def best_span(text: str, qv: list[float], embed: Callable) -> tuple[int, int]:
    """the sentence of the passage closest to the question (falls back to the first sentence if the model cannot be asked again)"""
    spans = _sentences(text)
    if len(spans) == 1:
        return spans[0]
    spans = spans[:24]
    try:
        vs = embed([text[a:b] for a, b in spans])
        k = max(range(len(spans)), key=lambda i: cosine(qv, vs[i]))
        return spans[k]
    except Exception:
        return spans[0]


def _text_card(passage: str, span: tuple[int, int], title: str, arrows: bool):
    text, spans = proof._window(passage, [span], 260)
    img, boxes = textsnap.render_snapshot([("", text)], [(0, spans[0][0], spans[0][1])], title=title)
    flat = [b for bs in boxes for b in bs]
    return annotate.annotate(img, flat, "text", arrows=arrows) if flat else img


def _pdf_card(path: str, page: int, sentence: str, arrows: bool):
    f = _fitz()
    if f is None or not page:
        return None
    words = sentence.split()
    with f.open(path) as d:
        pg = d[page - 1]
        rects = []
        for n in (len(words), 12, 8, 5):
            if n and words:
                rects = pg.search_for(" ".join(words[:n]))
                if rects:
                    break
        if not rects:
            return None
        got = proof.render_pdf_page(Path(path), page - 1, 110)
    if not got:
        return None
    im, scale = got
    boxes = [(r.x0 * scale, r.y0 * scale, r.x1 * scale, r.y1 * scale) for r in rects]
    bi, bb = proof._fit(annotate.to_rgb(im), boxes)
    return annotate.annotate(bi, bb, "text", arrows=arrows)


# ---------------------------------------------------------------- searching
def search(query: str, roots: list[str], opts: dict | None = None, embed: Callable | None = None, limit: int | None = None) -> dict:
    from .service import UserError
    o = opts or {}
    if limit is not None:
        o = {**o, "limit": limit}
    if not query.strip():
        raise UserError("Type what you are looking for.")
    io = index_opts(o.get("index") or {})
    emb = embed or (lambda t: ollama_embed(t, model=io["model"]))
    qv = emb([query])[0]
    n_show = _int(o.get("limit"), 12, 1, 100)
    floor = max(0.0, min(1.0, float(o.get("min_score") or 0)))
    groups = [g for g in (o.get("groups") or list(GROUPS)) if g in GROUPS]
    allowed = set().union(*(GROUPS[g] for g in groups)) if groups else set()
    contains = (o.get("name_contains") or "").lower().strip()
    per_file = 3 if o.get("per_file") == "top3" else 1
    with _LOCK:
        c = _db()
        rows = c.execute("select path,n,page,text,vec from chunks2").fetchall()
        c.close()
    cand: dict[str, list[tuple[float, int, str]]] = {}
    for path, _n, page, text, vec in rows:
        if not _under(path, roots) or (allowed and Path(path).suffix.lower() not in allowed):
            continue
        if contains and contains not in Path(path).name.lower():
            continue
        s = cosine(qv, _unpack(vec))
        if s >= floor:
            cand.setdefault(path, []).append((s, page, text))
    flat = []
    for path, lst in cand.items():
        lst.sort(key=lambda x: -x[0])
        for s, page, text in lst[:per_file]:
            flat.append((s, path, page, text))
    flat.sort(key=lambda x: -x[0])
    flat = flat[:n_show]
    hits = [{"path": p, "name": Path(p).name, "folder": str(Path(p).parent), "page": pg or None, "score": round(s, 3), "percent": round(max(0.0, s) * 100),
             "snippet": t[:300], "proof": None} for s, p, pg, t in flat]
    n_proof = _int(o.get("proofs"), 6, 0, 30)
    if n_proof and hits:
        P = proof.Proofs(proof.new_sid(), limit=n_proof)
        with _colors(o.get("highlight") or "", o.get("circle") or ""):
            for h, (s, p, pg, text) in zip(hits[:n_proof], flat):
                try:
                    a, b = best_span(text, qv, emb)
                    img = _pdf_card(p, pg, text[a:b].strip(), bool(o.get("arrows", True))) if p.lower().endswith(".pdf") else None
                    if img is None:
                        img = _text_card(text, (a, b), Path(p).name + (f" · page {pg}" if pg else ""), bool(o.get("arrows", True)))
                    n0 = len(P.items)
                    P.add(Path(p).name, f"page {pg}" if pg else "", None, img, f"{h['percent']}% match")
                    if len(P.items) > n0:
                        h["proof"] = P.items[-1]
                        h["best"] = text[a:b].strip()[:200]
                except Exception:
                    continue
    return {"hits": hits, "indexed": len(rows), "files_searched": len(cand)}
