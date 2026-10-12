"""Proof pictures for the Editor: compares the file before and after saving and draws what changed."""
from __future__ import annotations

import difflib
import zipfile
from pathlib import Path

from app import proof


def _para_lists(p: Path, kind: str) -> dict[str, list[str]]:
    from app import editor
    info = editor._open_markup(p, kind) if kind in ("docx", "pptx") else editor._open_odf(p)
    return {pt["label"] + "": [it["text"] for it in pt["items"]] for pt in info["parts"]}


def _paragraphs(P, p: Path, tmp: Path, kind: str, name: str) -> None:
    a, b = _para_lists(p, kind), _para_lists(tmp, kind)
    for label in b:
        if label not in a:
            continue
        sm = difflib.SequenceMatcher(None, a[label], b[label], autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                bt = a[label][i1 + k] if i1 + k < i2 else None
                at = b[label][j1 + k] if j1 + k < j2 else None
                where = f"{label} · paragraph {i1 + k + 1}" if bt is not None else f"{label} · new paragraph"
                if bt is not None and at is not None:
                    proof.text_change(P, "Paragraph changed", where, bt, at)
                elif bt is not None:
                    proof.text_change(P, "Paragraph removed", where, bt, "", [(0, len(bt))], [])
                else:
                    proof.text_change(P, "Paragraph added", where, "", at, [], [(0, len(at))])


def _cells(P, p: Path, tmp: Path, edits: dict) -> None:
    import openpyxl
    wa = openpyxl.load_workbook(p, read_only=False)
    wb = openpyxl.load_workbook(tmp, read_only=False)
    rows_b, rows_a, sb, sa = [], [], [], []
    ob = oa = 0
    def flush():
        nonlocal rows_b, rows_a, sb, sa, ob, oa
        if rows_b:
            proof.text_change(P, "Cells changed", "spreadsheet", "\n".join(rows_b), "\n".join(rows_a), sb, sa)
        rows_b, rows_a, sb, sa, ob, oa = [], [], [], [], 0, 0
    for sheet, cells in edits.items():
        for ref in cells:
            va, vb = wa[sheet][ref].value, wb[sheet][ref].value
            if va == vb:
                continue
            lab = f"{sheet}!{ref}  "
            tb, ta = "" if va is None else str(va), "" if vb is None else str(vb)
            sb.append((ob + len(lab), ob + len(lab) + max(len(tb), 1))); sa.append((oa + len(lab), oa + len(lab) + max(len(ta), 1)))
            rows_b.append(lab + tb); rows_a.append(lab + ta)
            ob += len(rows_b[-1]) + 1; oa += len(rows_a[-1]) + 1
            if len(rows_b) >= 6:
                flush()
    flush()


def _db(P, p: Path, tmp: Path, edits: dict) -> None:
    import sqlite3
    ca, cb = sqlite3.connect(f"file:{p}?mode=ro", uri=True), sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
    try:
        for table, spec in edits.items():
            cols = [r[1] for r in ca.execute(f'pragma table_info("{table}")')]
            for rid in list((spec.get("cells") or {}).keys()) + list(spec.get("delete") or []):
                ra = ca.execute(f'select * from "{table}" where rowid=?', (int(rid),)).fetchone()
                rb = cb.execute(f'select * from "{table}" where rowid=?', (int(rid),)).fetchone()
                if ra == rb:
                    continue
                def fmt(r):
                    if r is None:
                        return "", []
                    lines, spans, off = [], [], 0
                    for c, v in zip(cols, r):
                        txt = "" if v is None else str(v)
                        line = f"{c}  {txt}"
                        lines.append(line)
                        spans.append((off + len(c) + 2, off + len(line)))
                        off += len(line) + 1
                    return "\n".join(lines), spans
                tb, sb = fmt(ra); ta, sa = fmt(rb)
                if ra is not None and rb is not None:
                    sb = [sp for sp, x, y in zip(sb, ra, rb) if x != y]; sa = [sp for sp, x, y in zip(sa, ra, rb) if x != y]
                    proof.text_change(P, f"Row changed in {table}", f"{table} · row {rid}", tb, ta, sb, sa)
                elif ra is not None:
                    proof.text_change(P, f"Row deleted from {table}", f"{table} · row {rid}", tb, "", [(0, len(tb))], [])
    finally:
        ca.close(); cb.close()


def _pdf(P, p: Path, tmp: Path, edits: list[dict]) -> None:
    from app.editor import _fitz
    fitz = _fitz()
    doc = fitz.open(p)
    pages: dict[int, list[tuple]] = {}
    texts: list[tuple] = []
    for e in edits:
        pno = int(e["page"]) - 1
        spans = [sp for b in doc[pno].get_text("dict")["blocks"] for ln in b.get("lines", []) for sp in ln.get("spans", [])]
        i = int(e["i"])
        if i < len(spans) and spans[i]["text"] != str(e["text"]):
            r = fitz.Rect(spans[i]["bbox"])
            pages.setdefault(pno, []).append((r.x0 - 3, r.y0 - 3, r.x1 + 3, r.y1 + 3))
            texts.append((pno + 1, spans[i]["text"], str(e["text"])))
    doc.close()
    if not proof.pdf_page_changes(P, p, tmp, pages, "PDF text changed", "text"):
        for pg, b, a in texts:
            proof.text_change(P, "PDF text changed", f"page {pg}", b, a)


def _image(P, p: Path, tmp: Path) -> None:
    from PIL import Image, ImageOps
    b = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
    a = ImageOps.exif_transpose(Image.open(tmp)).convert("RGB")
    note = "" if b.size == a.size else f"Size changed: {b.width}×{b.height} → {a.width}×{a.height}"
    bx = proof.image_diff_boxes(b, a)
    if b.size != a.size or not bx:
        P.add("Picture edited", p.name, proof.framed(b), proof.framed(a), note or "Picture edited")
    else:
        proof.picture_change(P, "Picture edited", p.name, b, bx, a, bx, "object", note)


def build(p: Path, tmp: Path, kind: str, payload: dict) -> list[dict]:
    """returns proof items (never raises: proof is a bonus, the saved file is what matters)"""
    P = proof.Proofs(proof.new_sid())
    try:
        if kind == "text":
            from app.textedit import decode_text
            proof.text_diff(P, "Text changed", decode_text(p.read_bytes())[0].replace("\r\n", "\n"), decode_text(tmp.read_bytes())[0].replace("\r\n", "\n"))
        elif kind in ("docx", "pptx", "odf"):
            _paragraphs(P, p, tmp, kind, p.name)
        elif kind == "xlsx":
            _cells(P, p, tmp, payload.get("cells", {}))
        elif kind == "sqlite":
            _db(P, p, tmp, payload.get("tables", {}))
        elif kind == "pdf":
            _pdf(P, p, tmp, payload.get("edits", []))
        elif kind == "image":
            _image(P, p, tmp)
    except Exception:
        pass
    return P.result()
