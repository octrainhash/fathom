# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Which engine can turn which format into which, and how a conversion is carried out (including two-step routes)."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from app.convert.core import Cancelled, ConvertError, Ctx, Edge, Engine, Opts
from app.convert.eng_data import DataEngine
from app.convert.eng_docs import CalibreEngine, OfficeEngine, PageEngine, PandocEngine, PdfSlidesEngine, PdfTablesEngine, PdfToWordEngine, SlidesToDocEngine, TextPdfEngine
from app.convert.eng_image import ImageEngine, OcrEngine
from app.convert.eng_media import FrameEngine, MediaEngine, SpeechEngine, SubtitleEngine
from app.convert.eng_misc import ArchiveEngine, FontEngine, MeshEngine
from app.convert.formats import FORMATS, category, label

log = logging.getLogger("fathom")

ENGINES: list[Engine] = [
    ImageEngine(), OcrEngine(), PageEngine(), TextPdfEngine(), PandocEngine(), OfficeEngine(), CalibreEngine(), PdfToWordEngine(), PdfTablesEngine(), PdfSlidesEngine(), SlidesToDocEngine(),
    DataEngine(), MediaEngine(), FrameEngine(), SubtitleEngine(), SpeechEngine(), ArchiveEngine(), FontEngine(), MeshEngine(),
]
ANY_SOURCE = {"archive"}
# formats a two-step route may pass through
MIDDLE = {"pdf", "png", "jpg", "txt", "html", "docx", "xlsx", "csv", "epub", "odt", "md", "json", "wav", "mp4"}
NOT_A_TARGET = {"bin"}
HOP_PENALTY = 0.4


@lru_cache(maxsize=1)
def graph() -> dict[str, dict[str, list[Edge]]]:
    ids = list(FORMATS)
    g: dict[str, dict[str, list[Edge]]] = {i: {} for i in ids}
    for eng in ENGINES:
        try:
            if not eng.available():
                continue
            R, W = eng.reads(), eng.writes()
        except Exception:
            log.exception("engine %s failed to start", eng.name)
            continue
        sources = ids if eng.name in ANY_SOURCE else [s for s in ids if s in R]
        targets = [t for t in ids if t in W and t not in NOT_A_TARGET]
        for s in sources:
            for t in targets:
                if s == t and not eng.same_ok:   # "same type" is only offered by engines that can apply adjustments alone
                    continue
                try:
                    e = eng.can(s, t)
                except Exception:
                    log.exception("engine %s can() failed", eng.name)
                    e = None
                if e:
                    g[s].setdefault(t, []).append(e)
    for s in g:
        for t in g[s]:
            g[s][t].sort(key=lambda e: e.cost)
    return g


def reset() -> None:
    graph.cache_clear()
    _paths.cache_clear()


# For a two-step route: which kinds of result make sense from which kinds of source, and which middle format is needed.
PICTURE_FINALS = {"png", "jpg", "tif", "webp", "bmp", "gif"}
EXOTIC_TEXT = {"ipynb", "fb2", "docbook", "asciidoc", "wiki", "org", "textile", "rst", "tex"}
TWO_STEP = {
    "document": {"document", "presentation", "text", "ebook", "image"},
    "presentation": {"document", "text", "ebook", "image", "presentation"},
    "spreadsheet": {"document", "text", "image", "spreadsheet", "data"},
    "data": {"document", "text", "image", "spreadsheet", "data"},
    "text": {"document", "text", "ebook", "image", "presentation"},
    "ebook": {"document", "text", "ebook", "image"},
    "image": {"document", "text", "ebook"},
    "video": {"document", "text"},
    "audio": {"document", "text"},
}


def _two_step_ok(s: str, mid: str, t: str) -> bool:
    allowed = TWO_STEP.get(category(s))
    if not allowed:
        return False
    cat_t = category(t)
    if cat_t not in allowed:
        return False
    if cat_t in ("spreadsheet", "data") and s in ("toml", "ini", "xml", "yaml", "json"):
        return False
    if cat_t == "image":
        return mid == "pdf" and t in PICTURE_FINALS
    if category(s) in ("video", "audio", "image"):
        return mid in ("txt", "pdf") if category(s) == "image" else mid == "txt"
    if cat_t in ("spreadsheet", "data") and category(s) in ("document", "presentation", "ebook", "text"):
        return mid == "html"
    if t in EXOTIC_TEXT or t in ("ini", "toml", "sql", "jsonl") and category(s) != "data":
        return False
    if t in ("ini", "toml"):
        return False
    if t in ("pptx", "odp") and category(s) not in ("text", "document", "presentation"):
        return False
    return True


@lru_cache(maxsize=256)
def _paths(s: str) -> dict[str, list[tuple[float, tuple[Edge, ...]]]]:
    """Every route from format s to each other format: one engine, or two engines through a middle format."""
    g = graph()
    out: dict[str, list[tuple[float, tuple[Edge, ...]]]] = {}
    for t1, edges in g.get(s, {}).items():
        for e in edges:
            out.setdefault(t1, []).append((e.cost, (e,)))
    for t1, edges in g.get(s, {}).items():
        if t1 not in MIDDLE or t1 == s:
            continue
        e1 = edges[0]
        if e1.multi:
            continue
        for t2, edges2 in g.get(t1, {}).items():
            if t2 == s or t2 in NOT_A_TARGET or not _two_step_ok(s, t1, t2):
                continue
            for e2 in edges2[:2]:
                out.setdefault(t2, []).append((e1.cost + e2.cost + HOP_PENALTY, (e1, e2)))
    for t in out:
        out[t].sort(key=lambda x: x[0])
        seen, keep = set(), []   # keep distinct engine combinations only
        for cost, edges in out[t]:
            key = tuple(e.engine.name for e in edges)
            if key not in seen:
                seen.add(key)
                keep.append((cost, edges))
        out[t] = keep[:4]
    return out


def targets_for(s: str) -> list[dict]:
    res = []
    for t, routes in _paths(s).items():
        cost, edges = routes[0]
        notes: list[str] = []
        for e in edges:
            if e.note and e.note not in notes:
                notes.append(e.note)
        via = ""
        if len(edges) == 2:
            via = label(edges[0].dst)
        res.append({"id": t, "label": label(t), "category": category(t), "notes": notes, "via": via, "cost": round(cost, 2),
                    "heavy": any(e.engine.heavy for e in edges)})
    order = {"image": 0, "video": 1, "audio": 2, "document": 3, "presentation": 4, "spreadsheet": 5, "data": 6, "text": 7, "ebook": 8,
             "subtitle": 9, "font": 10, "mesh": 11, "archive": 12, "other": 13}
    res.sort(key=lambda r: (order.get(r["category"], 99), r["cost"], r["label"]))
    return res


def route_heavy(s: str, t: str) -> bool:
    routes = _paths(s).get(t)
    return bool(routes and any(e.engine.heavy for e in routes[0][1]))


def convert_file(src: Path, s: str, t: str, o: Opts, ctx: Ctx) -> tuple[list[Path], str]:
    """Converts one file. Returns the new files (in the scratch folder) and a note about the conversion."""
    routes = _paths(s).get(t)
    if not routes:
        raise ConvertError(f"Fathom cannot turn {label(s)} into {label(t)}.")
    first: Exception | None = None
    for _cost, edges in routes:
        ctx.check()
        try:
            cur = src
            outs: list[Path] = []
            for i, e in enumerate(edges):
                ctx.span = (i / len(edges), (i + 1) / len(edges))
                outs = e.engine.convert(cur, ctx.scratch_dir(), e.src, e.dst, o, ctx)
                if not outs:
                    raise ConvertError("Nothing was produced.")
                if i < len(edges) - 1:
                    cur = outs[0]
            ctx.span = (0.0, 1.0)
            notes = []
            for e in edges:
                if e.note and e.note not in notes:
                    notes.append(e.note)
            return outs, " ".join(notes)
        except Cancelled:
            raise
        except ConvertError as exc:
            first = first or exc
        except Exception as exc:  # an engine bug or an odd file: report it, try the next route
            log.exception("conversion %s -> %s failed", s, t)
            first = first or ConvertError(f"{type(exc).__name__}: {exc}")
    ctx.span = (0.0, 1.0)
    assert first is not None
    raise first


def engine_report() -> list[dict]:
    """For the 'what can Fathom do' panel: each engine, whether it is installed and what it adds."""
    rows = []
    for e in ENGINES:
        try:
            ok = e.available()
            r = sorted(e.reads()) if ok else []
            w = sorted(e.writes()) if ok else []
        except Exception:
            ok, r, w = False, [], []
        rows.append({"name": e.name, "label": e.label, "available": ok, "needs": e.needs, "reads": r, "writes": w})
    return rows


def format_matrix() -> dict:
    g = graph()
    readable = sorted(s for s in g if _paths(s))
    writable = sorted({t for s in g for t in _paths(s)})
    return {"readable": [{"id": i, "label": label(i), "category": category(i)} for i in readable if i not in NOT_A_TARGET],
            "writable": [{"id": i, "label": label(i), "category": category(i)} for i in writable]}
