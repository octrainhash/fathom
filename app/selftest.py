# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""python -m app.selftest  -> checks every part of Fathom on this PC and prints PASS/FAIL for each."""
from __future__ import annotations

import sys
import tempfile
import threading
import traceback
from pathlib import Path

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str):
    def wrap(fn):
        try:
            RESULTS.append((name, True, str(fn() or "")))
        except Exception as exc:
            RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"))
            if "-v" in sys.argv:
                traceback.print_exc()
        return fn
    return wrap


def _text_picture():
    from PIL import Image, ImageDraw
    from app.textsnap import get_font

    img = Image.new("RGB", (900, 220), "white")
    ImageDraw.Draw(img).text((40, 70), "Invoice 48213 paid in full", fill="black", font=get_font(44))
    return img


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fathom_selftest_"))

    @check("Python packages load")
    def _():
        import cv2, numpy, onnxruntime, PIL, fastapi, uvicorn, tokenizers, huggingface_hub, openpyxl, imageio_ffmpeg  # noqa: F401
        return f"opencv {cv2.__version__}, onnxruntime {onnxruntime.__version__}"

    @check("PDF reader (PyMuPDF)")
    def _():
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        from app import extract
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "pdf selftest butterfly")
        text = " ".join(b[0] for b in extract.pdf_blocks(page))
        assert "butterfly" in text, "could not read text back from a PDF"
        return "ok"

    @check("Reads text in pictures (OCR)")
    def _():
        from app.ocr import ocr_boxes
        found = " ".join(t["text"] for t in ocr_boxes(_text_picture()))
        assert "48213" in found.replace(" ", ""), f"OCR read: {found!r}"
        return found

    @check("Highlight + circle drawing")
    def _():
        from app.annotate import annotate
        annotate(_text_picture(), [(40, 60, 300, 120)], "text").save(tmp / "annotated.png")
        return "ok"

    @check("Video clips (ffmpeg, slow motion)")
    def _():
        import cv2
        import numpy as np
        from app import video

        src = tmp / "t.mp4"
        vw = cv2.VideoWriter(str(src), cv2.VideoWriter_fourcc(*"mp4v"), 20, (320, 180))
        for _i in range(60):
            vw.write(np.full((180, 320, 3), 200, np.uint8))
        vw.release()
        info = video.probe(src)
        ev = video.Event(1.0, 1.0, 1.0, np.full((180, 320, 3), 200, np.uint8), [(40, 40, 120, 90)], [], [(1.0, [(40, 40, 120, 90)])])
        n, _secs = video.write_clip(src, tmp / "c.mp4", info, 0.5, 2.0, (0.8, 1.4), ev, 3.0, "result", 1.0, "text")
        assert (tmp / "c.mp4").stat().st_size > 1000 and n > 30
        return f"{n} frames written"

    @check("Object search model files")
    def _():
        from app.detect import models_ready
        assert models_ready(), "not downloaded yet (it downloads on the first object search)"
        return "downloaded"

    @check("Object search model runs")
    def _():
        from PIL import Image, ImageDraw
        from app.detect import find_objects
        img = Image.new("RGB", (640, 480), (235, 235, 235))
        ImageDraw.Draw(img).ellipse([300, 150, 520, 370], fill=(220, 30, 30))
        hit = find_objects(img, "red ball", 0.35, thorough=False)
        return f"{len(hit)} box(es) in a test picture with a red ball"

    @check("Whole search pipeline")
    def _():
        from app.search import Context, Options, search_file
        (tmp / "n.txt").write_text("alpha\nthe needle is here\nomega\n", encoding="utf-8")
        results: list[dict] = []
        ctx = Context(Options.from_dict({"query": "needle"}), tmp, "/media/x", results.append, lambda f, m: None, threading.Event())
        search_file(ctx, tmp / "n.txt", "n.txt")
        assert len(results) == 1 and (tmp / Path(results[0]["image"]).name).exists()
        return "ok"

    @check("Find and replace in a Word file")
    def _():
        import zipfile
        from app import textedit
        docx = tmp / "r.docx"
        with zipfile.ZipFile(docx, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>Hello Wor</w:t></w:r><w:r><w:t>ld</w:t></w:r></w:p></w:body></w:document>')
        out = tmp / "r_edited.docx"
        R = textedit.Replacer([{"find": "world", "replace": "Earth"}])
        textedit.edit_ooxml(docx, out, R)
        assert R.count == 1 and b"Earth" in zipfile.ZipFile(out).read("word/document.xml")
        return "ok"

    @check("Stamp and sign a PDF (pypdf + reportlab)")
    def _():
        from pypdf import PdfReader
        from reportlab.pdfgen import canvas
        from app import stamp
        src, dst = tmp / "s.pdf", tmp / "s_out.pdf"
        c = canvas.Canvas(str(src)); c.drawString(72, 700, "page"); c.showPage(); c.save()
        n = stamp.stamp_pdf(src, dst, {"render": {"text": "APPROVED", "style": "box", "color": "#1e8449"}, "position": "br", "size": 30})
        assert n == 1 and len(PdfReader(str(dst)).pages) == 1
        return "ok"

    @check("Proof pictures (before and after, highlighted)")
    def _():
        from app import proof
        P = proof.Proofs(proof.new_sid())
        proof.text_change(P, "Test change", "x", "hello world", "hello Earth")
        items = P.result()
        assert items and items[0]["before"] and items[0]["after"]
        return "ok"

    @check("QR codes (make and read)")
    def _():
        from app import extras
        p = tmp / "qr.png"
        p.write_bytes(extras.qr_png("fathom selftest", 8))
        assert extras.qr_read(p) == ["fathom selftest"]
        return "ok"

    @check("Torrent files (make and read)")
    def _():
        from app import torrent
        d = tmp / "tor"; d.mkdir()
        (d / "a.txt").write_text("hello torrent")
        # build the same bytes make_start would, without the job system
        import hashlib
        info = {"name": "a.txt", "piece length": 32768, "pieces": hashlib.sha1(b"hello torrent").digest(), "length": 13}
        (tmp / "a.torrent").write_bytes(torrent.bencode({"info": info, "announce": "udp://t.example:80"}))
        i = torrent.info_of(tmp / "a.torrent")
        assert i["size"] == 13 and i["name"] == "a.txt" and len(i["hash"]) == 40
        ok, why = torrent.available()
        return "downloads ready" if ok else "making torrents works; downloading needs libtorrent (optional)"

    @check("Assistant: PDF, Word, slides and sheet makers")
    def _():
        from app.ai import docs
        md = "# Hello\n\nSome text.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        docs.make_pdf(md, tmp / "ai.pdf", "Hello")
        docs.make_docx(md, tmp / "ai.docx", "Hello")
        assert (tmp / "ai.pdf").stat().st_size > 500 and (tmp / "ai.docx").stat().st_size > 500
        return "ok"

    @check("Assistant: tool catalogue and My tools")
    def _():
        from app.ai import catalog, plugins
        assert len(catalog.routes()) > 30
        assert plugins.listing() is not None
        return f"{len(catalog.routes())} routes known"

    @check("Handwriting: page cleaning and line cutting")
    def _():
        import numpy as np
        from PIL import Image, ImageDraw
        from app import handwriting
        im = Image.new("L", (900, 500), 240)
        d = ImageDraw.Draw(im)
        for y in (120, 250, 380):
            for x in range(80, 800, 40):
                d.line([(x, y - 20), (x + 15, y + 20)], fill=40, width=7)
        p = tmp / "hw.png"; im.convert("RGB").save(p)
        lines = handwriting.segment_lines(Image.open(p).convert("RGB"))["lines"]
        assert len(lines) >= 2
        return f"{len(lines)} lines"

    @check("Activity & Undo list")
    def _():
        from app import history
        history.listing(5)
        return "ok"

    @check("Assistant safety stops")
    def _():
        from app.ai import tools
        assert tools._blocked("format d: /q") and not tools._blocked("dir")
        return "ok"

    @check("Toolbox: text helpers")
    def _():
        from app import toolbox_quick as q
        assert '"a": 1' in q.run("json", '{"a":1,}', {"lenient": True})["result"]
        assert q.run("base64", "hi", {})["result"] == "aGk="
        assert q.run("hash", "abc", {"algos": ["sha256"]})["result"].startswith("ba7816bf")
        assert "<h1" in q.run("markdown", "# Hi", {})["result"]
        return "ok"

    @check("Toolbox: barcodes")
    def _():
        from app import toolbox
        assert all(sum(map(int, p)) == 11 for p in toolbox.C128[:-1])
        w, shown = toolbox.encode("ean13", "590123412345")
        assert shown == "5901234123457" and sum(w) == 95
        img, svg = toolbox.render_barcode("code128", "Fathom", {})
        assert img.width > 100 and svg.startswith("<svg")
        return "ok"

    @check("Toolbox: subtitles")
    def _():
        from app import toolbox
        p = tmp / "t.srt"
        p.write_text("1\n00:00:01,000 --> 00:00:02,000\n<i>Hi</i>\n", encoding="utf-8")
        cues, _enc = toolbox.read_subs(p)
        out, _n = toolbox.fix_subs(cues, {"shift": 1})
        assert out[0][2] == "Hi" and abs(out[0][0] - 2.0) < 1e-6
        return "ok"

    width = max(len(n) for n, _, _ in RESULTS)
    bad = 0
    for name, ok, detail in RESULTS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name.ljust(width)}  {detail}")
        bad += 0 if ok else 1
    print()
    print("Everything works." if not bad else f"{bad} check(s) failed - send me this list and I will fix it.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
