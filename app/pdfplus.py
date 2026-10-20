# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""More PDF tools: several pages per sheet (and booklets), document properties + bookmarks, and filling in form fields."""
from __future__ import annotations

import re

from app import ops
from app.convert import formats
from app.convert.core import ConvertError, Ctx
from app.ops import Output, OutputPolicy, Task
from app.opsvc import expand_sources
from app.service import UserError

_GRIDS = {2: (2, 1), 4: (2, 2), 6: (2, 3), 9: (3, 3)}     # per sheet -> (columns, rows)
_SHEET = {"a4": (595.28, 841.89), "letter": (612.0, 792.0)}


def _open(src):
    from pypdf import PdfReader
    r = PdfReader(str(src))
    if r.is_encrypted:
        try:
            r.decrypt("")
        except Exception:
            pass
        if r.is_encrypted:
            raise ConvertError("This PDF is locked with a password. Remove the password first (Protect → PDF password).")
    return r


def _pdfs(paths):
    out = [(s, rel) for s, rel in expand_sources(paths, True) if formats.detect(s) == "pdf"]
    if not out:
        raise UserError("Add a PDF first.")
    return out


# ------------------------------------------------------------------ several pages per sheet / booklet
def booklet_order(n: int) -> list[int | None]:
    """Page order for a folded booklet printed double-sided (2 pages per side): [left, right] pairs, None = blank."""
    total = ((n + 3) // 4) * 4
    pages = list(range(n)) + [None] * (total - n)
    out: list[int | None] = []
    for i in range(total // 4):
        out += [pages[total - 1 - 2 * i], pages[2 * i], pages[2 * i + 1], pages[total - 2 - 2 * i]]
    return out


def nup_start(paths: list[str], per: int, booklet: bool, sheet: str, border: bool, output: dict) -> dict:
    policy = OutputPolicy.from_dict(output)
    if not booklet and per not in _GRIDS:
        raise UserError("Choose 2, 4, 6 or 9 pages per sheet.")
    tasks = []
    for src, rel in _pdfs(paths):
        def fn(ctx: Ctx, task: Task, src=src, rel=rel) -> Output:
            from pypdf import PdfWriter, Transformation
            from pypdf.generic import RectangleObject

            r = _open(src)
            n = len(r.pages)
            if booklet:
                cols, rows, seq = 2, 1, booklet_order(n)
            else:
                cols, rows = _GRIDS[per]
                seq = list(range(n))
            per_sheet = cols * rows
            first = r.pages[0]
            pw, ph = float(first.mediabox.width), float(first.mediabox.height)
            if sheet in _SHEET:
                sw, sh = _SHEET[sheet]
                if cols > rows or (cols == rows and pw > ph):
                    sw, sh = max(sw, sh), min(sw, sh)
            else:                                              # same paper as the source page, turned if the grid is wider than tall
                sw, sh = (max(pw, ph), min(pw, ph)) if cols > rows else (pw, ph)
            w = PdfWriter()
            cw, chh = sw / cols, sh / rows
            for base in range(0, len(seq), per_sheet):
                ctx.check()
                page = w.add_blank_page(width=sw, height=sh)
                for k, idx in enumerate(seq[base:base + per_sheet]):
                    if idx is None:
                        continue
                    src_page = r.pages[idx]
                    w_, h_ = float(src_page.mediabox.width), float(src_page.mediabox.height)
                    rot = int(src_page.get("/Rotate", 0) or 0) % 360
                    if rot in (90, 270):
                        w_, h_ = h_, w_
                    scale = min(cw / w_, chh / h_) * 0.96
                    col, row = k % cols, k // cols
                    x = col * cw + (cw - w_ * scale) / 2
                    y = sh - (row + 1) * chh + (chh - h_ * scale) / 2
                    page.merge_transformed_page(src_page, Transformation().scale(scale).translate(x, y))
                if border:
                    pass                                       # (reserved: cut lines are drawn by the viewer's own page borders)
            dst = ctx.scratch_dir() / f"{src.stem} ({'booklet' if booklet else str(per) + ' per sheet'}).pdf"
            with open(dst, "wb") as fh:
                w.write(fh)
            return Output(policy.place([dst], src, rel), f"{len(w.pages)} sheets from {n} pages.")

        tasks.append(Task(src.name, fn, src, rel=rel))
    return {"job": ops.start("nup", "Putting pages on sheets", tasks).id, "count": len(tasks)}


# ------------------------------------------------------------------ properties and bookmarks
def parse_bookmarks(text: str, n: int) -> list[tuple[int, int, str]]:
    """Lines like `1 Introduction`, `3 Chapter 2`, or indented with spaces/dashes for a sub-item: `  5 Details`. -> [(level, page index, title)]"""
    out = []
    for ln in (text or "").splitlines():
        if not ln.strip():
            continue
        m = re.match(r"^(\s*)(-*)\s*(\d+)\s+(.+?)\s*$", ln)
        if not m:
            raise UserError(f"“{ln.strip()[:40]}” should look like: 3 Chapter title (page number first). Indent a line to make it a sub-item.")
        level = len(m[1].replace("\t", "    ")) // 2 + len(m[2])
        page = int(m[3])
        if not 1 <= page <= n:
            raise UserError(f"Bookmark “{m[4][:30]}” points to page {page}, but this PDF has {n} pages.")
        out.append((level, page - 1, m[4]))
    return out


def props_start(paths: list[str], fields: dict, bookmarks: str, clear_bookmarks: bool, output: dict) -> dict:
    policy = OutputPolicy.from_dict(output)
    tasks = []
    for src, rel in _pdfs(paths):
        def fn(ctx: Ctx, task: Task, src=src, rel=rel) -> Output:
            from pypdf import PdfWriter

            r = _open(src)
            w = PdfWriter(clone_from=r)
            md = {f"/{k}": str(v) for k, v in fields.items() if str(v).strip() and k in ("Title", "Author", "Subject", "Keywords")}
            if md:
                w.add_metadata(md)
            if clear_bookmarks or bookmarks.strip():
                try:
                    w._root_object.pop("/Outlines", None)
                except Exception:
                    pass
            if bookmarks.strip():
                stack: list[tuple[int, object]] = []
                for level, page, title in parse_bookmarks(bookmarks, len(r.pages)):
                    while stack and stack[-1][0] >= level:
                        stack.pop()
                    item = w.add_outline_item(title, page, parent=stack[-1][1] if stack else None)
                    stack.append((level, item))
            dst = ctx.scratch_dir() / f"{src.stem} (updated).pdf"
            with open(dst, "wb") as fh:
                w.write(fh)
            return Output(policy.place([dst], src, rel), "Saved.")

        tasks.append(Task(src.name, fn, src, rel=rel))
    return {"job": ops.start("pdfprops", "Updating the PDF", tasks).id, "count": len(tasks)}


def props_view(paths: list[str]) -> dict:
    src, _ = _pdfs(paths)[0]
    r = _open(src)
    md = r.metadata or {}
    marks: list[str] = []

    def walk(items, level=0):
        for it in items:
            if isinstance(it, list):
                walk(it, level + 1)
            else:
                try:
                    marks.append("  " * level + f"{r.get_destination_page_number(it) + 1} {it.title}")
                except Exception:
                    pass
    try:
        walk(r.outline)
    except Exception:
        pass
    return {"name": src.name, "pages": len(r.pages), "Title": str(md.get("/Title", "") or ""), "Author": str(md.get("/Author", "") or ""),
            "Subject": str(md.get("/Subject", "") or ""), "Keywords": str(md.get("/Keywords", "") or ""), "bookmarks": "\n".join(marks)}


# ------------------------------------------------------------------ form fields
def form_fields(paths: list[str]) -> dict:
    src, _ = _pdfs(paths)[0]
    r = _open(src)
    fields = r.get_fields() or {}
    out = []
    for name, f in fields.items():
        kind = {"/Tx": "text", "/Btn": "tick box or button", "/Ch": "choice", "/Sig": "signature"}.get(str(f.get("/FT", "")), "other")
        val = f.get("/V")
        out.append({"name": name, "kind": kind, "value": "" if val is None else str(val), "options": [str(o) for o in (f.get("/Opt") or [])][:50]})
    return {"name": src.name, "fields": out}


def parse_values(text: str) -> dict[str, str]:
    vals: dict[str, str] = {}
    for ln in (text or "").splitlines():
        if not ln.strip():
            continue
        if "=" not in ln:
            raise UserError(f"“{ln.strip()[:40]}” should look like: Field name = value")
        k, v = ln.split("=", 1)
        vals[k.strip()] = v.strip()
    if not vals:
        raise UserError("Type at least one line like: Full name = Ada Lovelace")
    return vals


def form_fill_start(paths: list[str], values: str, flatten: bool, output: dict) -> dict:
    policy = OutputPolicy.from_dict(output)
    vals = parse_values(values)
    tasks = []
    for src, rel in _pdfs(paths):
        def fn(ctx: Ctx, task: Task, src=src, rel=rel) -> Output:
            from pypdf import PdfWriter

            r = _open(src)
            fields = r.get_fields() or {}
            if not fields:
                raise ConvertError("This PDF has no form fields to fill in.")
            unknown = [k for k in vals if k not in fields]
            if unknown:
                raise ConvertError("No field called: " + ", ".join(unknown[:5]) + ". Use “Show the fields” to see the exact names.")
            w = PdfWriter(clone_from=r)
            for page in w.pages:
                if not page.get("/Annots"):
                    continue
                w.update_page_form_field_values(page, {k: v for k, v in vals.items()}, auto_regenerate=False)
            w.set_need_appearances_writer(True)
            if flatten:
                try:
                    w.flatten = True
                    for page in w.pages:
                        for a in list(page.get("/Annots", []) or []):
                            o = a.get_object()
                            if o.get("/Subtype") == "/Widget":
                                o[__import__("pypdf").generic.NameObject("/F")] = __import__("pypdf").generic.NumberObject(4 | 64)  # print + read-only
                except Exception:
                    pass
            dst = ctx.scratch_dir() / f"{src.stem} (filled).pdf"
            with open(dst, "wb") as fh:
                w.write(fh)
            return Output(policy.place([dst], src, rel), f"{len(vals)} field(s) filled.")

        tasks.append(Task(src.name, fn, src, rel=rel))
    return {"job": ops.start("pdfform", "Filling in the form", tasks).id, "count": len(tasks)}
