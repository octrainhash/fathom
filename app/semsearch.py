"""Search by meaning, all on this computer. Files are cut into short passages, each passage is turned into numbers by a small local
embedding model (Ollama, default nomic-embed-text), and the numbers are kept in a SQLite file. A search embeds your question and
returns the closest passages. Only changed files are read again. Nothing leaves the computer."""
from __future__ import annotations

import array
import json
import math
import sqlite3
import subprocess
import threading
import urllib.request
from pathlib import Path
from typing import Callable

from . import ops, paths
from .filetools import expand_sources
from .ops import Ctx, Output, Task

TEXT_EXT = {".txt", ".md", ".csv", ".json", ".log", ".html", ".htm", ".xml", ".rtf", ".srt", ".vtt", ".yaml", ".yml", ".py", ".js", ".tex"}
MODEL = "nomic-embed-text"
CHUNK, MAX_CHUNKS = 900, 10
_LOCK = threading.Lock()


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(str(paths.data_root() / "semantic.db"), timeout=30)
    c.execute("create table if not exists files(path text primary key, mtime real, size integer, model text)")
    c.execute("create table if not exists chunks(path text, n integer, text text, vec blob)")
    c.execute("create index if not exists ci on chunks(path)")
    return c


def read_text(p: Path, limit: int = CHUNK * MAX_CHUNKS) -> str:
    ext = p.suffix.lower()
    try:
        if ext in TEXT_EXT:
            return p.read_bytes()[:limit * 4].decode("utf-8", "replace")[:limit]
        if ext == ".pdf":
            try:
                import fitz                              # PyMuPDF ships with Fathom, so no extra program is needed
                with fitz.open(str(p)) as d:
                    t = " ".join(pg.get_text() for pg in list(d)[:12])
                return t[:limit]
            except ImportError:
                r = subprocess.run(["pdftotext", "-l", "12", "-q", str(p), "-"], capture_output=True, timeout=60)
                return r.stdout.decode("utf-8", "replace")[:limit]
    except Exception:
        pass
    return ""


def chunks(text: str) -> list[str]:
    text = " ".join(text.split())
    return [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)][:MAX_CHUNKS]


def ollama_embed(texts: list[str], cfg: dict | None = None) -> list[list[float]]:
    from .ai import store
    cfg = cfg or store.load()
    base = (cfg["base_urls"].get("ollama") or "http://localhost:11434/v1").rstrip("/")
    root = base[:-3] if base.endswith("/v1") else base
    model = cfg.get("embed_model") or MODEL
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


def index_start(paths_in: list[str], recursive: bool, embed: Callable | None = None) -> dict:
    emb = embed or ollama_embed
    tasks = []
    for p, rel in expand_sources(paths_in, recursive):
        if p.suffix.lower() not in TEXT_EXT and p.suffix.lower() != ".pdf":
            continue

        def fn(ctx: Ctx, task: Task, p=p) -> Output:
            ctx.check()
            st = p.stat()
            with _LOCK:
                c = _db()
                row = c.execute("select mtime,size from files where path=?", (str(p),)).fetchone()
                c.close()
            if row and abs(row[0] - st.st_mtime) < 1e-3 and row[1] == st.st_size:
                return Output(note="Already up to date", skipped=True)
            parts = chunks(read_text(p))
            if not parts:
                return Output(note="No readable text", skipped=True)
            vecs = emb(parts)
            with _LOCK:
                c = _db()
                c.execute("delete from chunks where path=?", (str(p),))
                c.executemany("insert into chunks values(?,?,?,?)", [(str(p), i, t, _pack(v)) for i, (t, v) in enumerate(zip(parts, vecs))])
                c.execute("insert or replace into files values(?,?,?,?)", (str(p), st.st_mtime, st.st_size, MODEL))
                c.commit()
                c.close()
            return Output(note=f"{len(parts)} passage{'s' if len(parts) != 1 else ''}")
        tasks.append(Task(p.name, fn, p, rel=rel))
    if not tasks:
        from .service import UserError
        raise UserError("Add text files, notes or PDFs to index.")
    job = ops.start("semindex", "Learning your files", tasks, workers=1)
    return {"job": job.id, "total": len(tasks)}


def search(query: str, roots: list[str], limit: int = 12, embed: Callable | None = None) -> dict:
    from .service import UserError
    if not query.strip():
        raise UserError("Type what you are looking for.")
    qv = (embed or ollama_embed)([query])[0]
    prefixes = [str(Path(r)) for r in roots]
    with _LOCK:
        c = _db()
        rows = c.execute("select path,n,text,vec from chunks").fetchall()
        c.close()
    best: dict[str, tuple[float, str]] = {}
    for path, _n, text, vec in rows:
        if prefixes and not any(path == r or path.startswith(r.rstrip("/\\") + ("\\" if "\\" in r else "/")) for r in prefixes):
            continue
        s = cosine(qv, _unpack(vec))
        if path not in best or s > best[path][0]:
            best[path] = (s, text)
    out = sorted(best.items(), key=lambda kv: -kv[1][0])[:limit]
    return {"hits": [{"path": k, "name": Path(k).name, "score": round(v[0], 3), "snippet": v[1][:260]} for k, v in out], "indexed": len(rows)}
