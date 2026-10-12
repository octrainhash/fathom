"""File tools, part 2: merge, split, cut, rotate, extract, encrypt, password-protect PDFs, pack into archives, join split parts."""
from __future__ import annotations

import io
import os
import re
import shutil
import struct
import zipfile
from pathlib import Path

from app import ops
from app.convert import formats
from app.convert.core import ConvertError, Ctx, Opts, ffmpeg_exe, file_bytes, parse_pages, safe_stem, unique_path
from app.ops import Output, OutputPolicy, Task
from app.opsvc import expand_sources
from app.service import UserError


def _files(paths: list[str], recursive: bool) -> list[tuple[Path, Path]]:
    return expand_sources(paths, recursive)


def _one_output_dir(paths: list[str], policy: OutputPolicy, first: Path) -> Path:
    return policy.target_dir(first, Path("."))


def _unique_name(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    return unique_path(folder / name)


def _mmss(text: str) -> float:
    text = (text or "").strip()
    if not text:
        return 0.0
    try:
        parts = [float(x) for x in text.split(":")]
    except ValueError:
        raise UserError(f"'{text}' is not a time. Use seconds (90) or minutes:seconds (1:30).")
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


# ---------------------------------------------------------------- merge
def merge_start(paths: list[str], recursive: bool, kind: str, output: dict, options: dict) -> dict:
    items = [p for p, _ in _files(paths, recursive)]
    if len(items) < 2:
        raise UserError("Add at least two files to merge (drag them into the order you want in the list).")
    policy = OutputPolicy.from_dict(output)
    fmts = [formats.detect(p) for p in items]
    cats = [formats.category(f) for f in fmts]
    if kind in ("", "auto"):
        if all(c in ("image", "document") or f == "pdf" for c, f in zip(cats, fmts)):
            kind = "pdf"
        elif any(c == "video" for c in cats):
            kind = "video"
        elif all(c == "audio" for c in cats):
            kind = "audio"
        elif all(f in ("csv", "tsv") for f in fmts):
            kind = "table"
        else:
            kind = "text"
    o = Opts.from_dict(options)

    def fn(ctx: Ctx, task: Task) -> Output:
        d = ctx.scratch_dir()
        if kind == "pdf":
            dst = _merge_pdf(items, fmts, d, ctx, dict(options.get("file_pages") or {}))
        elif kind in ("video", "audio"):
            dst = _merge_media(items, fmts, d, kind, o, ctx)
        elif kind == "table":
            dst = _merge_tables(items, fmts, d, ctx)
        else:
            dst = _merge_text(items, d, ctx)
        placed = policy.place([dst], items[0], Path("."))
        return Output(placed, f"{len(items)} files joined in the order shown.")

    job = ops.start("merge", "Merging", [Task("Merged file", fn, items[0], heavy=kind in ("video", "audio"))], workers=1)
    return {"job": job.id}


def _merge_pdf(items: list[Path], fmts: list[str], d: Path, ctx: Ctx, file_pages: dict | None = None) -> Path:
    from app.convert.eng_docs import get_fitz, open_doc
    from app.convert.eng_image import load_frames, rw

    fitz = get_fitz()
    if fitz is None:
        raise ConvertError("PDF tools are not installed.")
    out = fitz.open()
    for n, (p, f) in enumerate(zip(items, fmts), 1):
        ctx.check()
        if f == "pdf":
            src = open_doc(p, Opts())
            spec = str((file_pages or {}).get(str(p)) or (file_pages or {}).get("*") or "")
            if spec.strip():                                    # only some pages of this PDF
                from app import pagesel
                for pg in pagesel.need(spec, src.page_count):
                    out.insert_pdf(src, from_page=pg, to_page=pg)
            else:
                out.insert_pdf(src)
            src.close()
        elif f in ("xps", "epub", "mobi", "fb2", "cbz", "svg"):
            src = fitz.open(str(p))
            out.insert_pdf(fitz.open("pdf", src.convert_to_pdf()))
        elif f in rw()[0]:
            frames, _d, _first = load_frames(p, f, all_frames=False)
            buf = io.BytesIO()
            im = frames[0].convert("RGB")
            im.save(buf, "PNG")
            img = fitz.open("png", buf.getvalue())
            out.insert_pdf(fitz.open("pdf", img.convert_to_pdf()))
        else:
            raise ConvertError(f"{p.name} cannot be added to a PDF (convert it to PDF first).")
        ctx.progress(n / len(items))
    dst = d / "Merged.pdf"
    out.save(str(dst), garbage=3, deflate=True)
    out.close()
    return dst


def _merge_media(items: list[Path], fmts: list[str], d: Path, kind: str, o: Opts, ctx: Ctx) -> Path:
    from app.convert.eng_media import AUDIO_OUT, VIDEO_OUT, _ok, audio_args, probe, run_ffmpeg, video_args

    infos = [probe(ctx, p) for p in items]
    ext = fmts[0] if (fmts[0] in VIDEO_OUT or fmts[0] in AUDIO_OUT) and fmts[0] != "gif" else ("mp4" if kind == "video" else "mp3")
    if kind == "video":
        ref = next((i for i in infos if i["video"]), None)
        if not ref:
            raise ConvertError("None of these files has a picture.")
        w, h = (ref["w"] // 2) * 2, (ref["h"] // 2) * 2
        fps = int(round(ref["fps"] or 30)) or 30
    cmd: list = []
    filters: list[str] = []
    labels: list[str] = []
    extra_inputs = 0
    for i, (p, inf) in enumerate(zip(items, infos)):
        cmd += ["-i", p]
    idx_next = len(items)
    for i, inf in enumerate(infos):
        if kind == "video":
            if inf["video"]:
                filters.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{i}]")
            else:
                cmd += ["-f", "lavfi", "-t", f"{max(0.1, inf['duration']):.2f}", "-i", f"color=c=black:s={w}x{h}:r={fps}"]
                filters.append(f"[{idx_next}:v]setsar=1,format=yuv420p[v{i}]")
                idx_next += 1
            labels.append(f"[v{i}]")
        if inf["audio"]:
            filters.append(f"[{i}:a:0]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]")
        else:
            cmd += ["-f", "lavfi", "-t", f"{max(0.1, inf['duration']):.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
            filters.append(f"[{idx_next}:a]aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]")
            idx_next += 1
        labels.append(f"[a{i}]")
    n = len(items)
    concat = "".join(labels) + f"concat=n={n}:v={1 if kind == 'video' else 0}:a=1" + ("[v][a]" if kind == "video" else "[a]")
    dst = d / f"Merged.{ext}"
    graph = ";".join(filters + [concat])
    if kind == "video":
        args = video_args(ext, Opts(video_quality="balanced", audio_kbps=192), True)
        # the scaling is already in the filter graph
        if "-vf" in args:
            i = args.index("-vf")
            del args[i:i + 2]
        run_ffmpeg(ctx, [*cmd, "-filter_complex", graph, "-map", "[v]", "-map", "[a]", *args, dst], sum(i["duration"] for i in infos), "join")
    else:
        run_ffmpeg(ctx, [*cmd, "-filter_complex", graph, "-map", "[a]", *audio_args(ext, Opts(audio_kbps=256)), dst], sum(i["duration"] for i in infos), "join")
    return dst


def _merge_text(items: list[Path], d: Path, ctx: Ctx) -> Path:
    from app.extract import detect_encoding

    ext = items[0].suffix or ".txt"
    dst = d / f"Merged{ext}"
    with open(dst, "w", encoding="utf-8", newline="") as out:
        for n, p in enumerate(items, 1):
            ctx.check()
            text = p.read_text(encoding=detect_encoding(p), errors="replace")
            out.write(text if text.endswith("\n") or not text else text + "\n")
            ctx.progress(n / len(items))
    return dst


def _merge_tables(items: list[Path], fmts: list[str], d: Path, ctx: Ctx) -> Path:
    import csv

    from app.convert.eng_data import read_csv

    dst = d / f"Merged.{fmts[0]}"
    delim = "\t" if fmts[0] == "tsv" else ","
    header = None
    with open(dst, "w", encoding="utf-8-sig" if fmts[0] == "csv" else "utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=delim)
        for p, f in zip(items, fmts):
            tab = read_csv(p, "\t" if f == "tsv" else None)
            if header is None:
                header = tab.header
                w.writerow(header)
            elif tab.header != header:
                w.writerow(tab.header)   # a different header is kept as a row so nothing is lost
            for r in tab.rows:
                ctx.check()
                w.writerow(r)
    return dst


# ---------------------------------------------------------------- split
def split_start(paths: list[str], recursive: bool, mode: str, value: str, output: dict, options: dict) -> dict:
    policy = OutputPolicy.from_dict(output)
    tasks = []
    for src, rel in _files(paths, recursive):
        fmt = formats.detect(src)

        def fn(ctx: Ctx, task: Task, src=src, fmt=fmt, rel=rel) -> Output:
            d = ctx.scratch_dir()
            if mode == "size":
                outs = _split_size(src, d, value, ctx)
            elif fmt == "pdf":
                outs = _split_pdf(src, d, mode, value, ctx)
            elif formats.category(fmt) in ("video", "audio") and mode == "seconds":
                outs = _split_media(src, fmt, d, value, bool(options.get("exact")), ctx)
            else:
                raise ConvertError("Pick a way to split that fits this kind of file (pages for PDFs, seconds for video/audio, size for anything).")
            placed = policy.place(outs, src, rel, group_name=safe_stem(src) + " (split)")
            return Output(placed, f"{len(placed)} files created.")

        tasks.append(Task(src.name, fn, src, heavy=formats.category(fmt) in ("video", "audio"), rel=rel))
    if not tasks:
        raise UserError("There are no files to split.")
    return {"job": ops.start("split", "Splitting", tasks).id, "count": len(tasks)}


def _split_size(src: Path, d: Path, value: str, ctx: Ctx) -> list[Path]:
    try:
        mb = float(value)
    except ValueError:
        raise UserError("Enter the size of each part in MB.")
    if mb <= 0:
        raise UserError("The part size must be above zero.")
    part = int(mb * 1024 * 1024)
    total = max(1, file_bytes(src))
    outs, n, done = [], 1, 0
    with open(src, "rb") as fh:
        while True:
            ctx.check()
            chunk_left = part
            path = d / f"{src.name}.part{n:03d}"
            wrote = 0
            with open(path, "wb") as out:
                while chunk_left > 0:
                    block = fh.read(min(8 << 20, chunk_left))
                    if not block:
                        break
                    out.write(block)
                    chunk_left -= len(block)
                    wrote += len(block)
                    done += len(block)
                    ctx.progress(done / total)
            if wrote == 0:
                path.unlink()
                break
            outs.append(path)
            n += 1
    return outs


def join_parts_start(paths: list[str], output: dict) -> dict:
    policy = OutputPolicy.from_dict(output)
    groups: dict[tuple[str, str], list[Path]] = {}
    for p, _ in _files(paths, True):
        m = re.fullmatch(r"(.+)\.part(\d{3,})", p.name)
        if m:
            groups.setdefault((str(p.parent), m.group(1)), []).append(p)
    if not groups:
        raise UserError("No split parts found (files named like movie.mp4.part001, .part002 ...).")
    tasks = []
    for (folder, base), parts in groups.items():
        parts.sort(key=lambda p: int(p.name.rsplit("part", 1)[1]))

        def fn(ctx: Ctx, task: Task, parts=parts, base=base) -> Output:
            dst = ctx.scratch_dir() / base
            total = max(1, sum(file_bytes(p) for p in parts))
            done = 0
            with open(dst, "wb") as out:
                for p in parts:
                    with open(p, "rb") as fh:
                        while True:
                            ctx.check()
                            block = fh.read(8 << 20)
                            if not block:
                                break
                            out.write(block)
                            done += len(block)
                            ctx.progress(done / total)
            return Output(policy.place([dst], parts[0], Path(".")), f"{len(parts)} parts joined.")

        tasks.append(Task(base, fn, parts[0]))
    return {"job": ops.start("join", "Joining parts", tasks).id, "count": len(tasks)}


def _split_pdf(src: Path, d: Path, mode: str, value: str, ctx: Ctx) -> list[Path]:
    from app.convert.eng_docs import get_fitz, open_doc

    fitz = get_fitz()
    doc = open_doc(src, Opts())
    n = doc.page_count
    stem = safe_stem(src)
    chunks: list[list[int]] = []
    names: list[str] = []
    if mode == "each":
        chunks = [[i] for i in range(n)]
        names = [f"{stem}_page{i + 1:03d}" for i in range(n)]
    elif mode == "every":
        try:
            k = max(1, int(float(value)))
        except ValueError:
            raise UserError("Enter how many pages each part should have.")
        for a in range(0, n, k):
            chunks.append(list(range(a, min(n, a + k))))
            names.append(f"{stem}_pages{a + 1}-{min(n, a + k)}")
    elif mode == "ranges":
        for part in re.split(r"[;,]+", value):
            part = part.strip()
            if part:
                pages = parse_pages(part, n)
                chunks.append(pages)
                names.append(f"{stem}_pages{part.replace(' ', '')}")
    else:
        raise UserError("Choose how to split the PDF.")
    outs = []
    for i, (pages, name) in enumerate(zip(chunks, names), 1):
        ctx.check()
        out = fitz.open()
        for pg in pages:
            out.insert_pdf(doc, from_page=pg, to_page=pg)
        dst = d / f"{name}.pdf"
        out.save(str(dst), garbage=3, deflate=True)
        out.close()
        outs.append(dst)
        ctx.progress(i / len(chunks))
    doc.close()
    return outs


def _split_media(src: Path, fmt: str, d: Path, value: str, exact: bool, ctx: Ctx) -> list[Path]:
    from app.convert.eng_media import AUDIO_OUT, VIDEO_OUT, audio_args, probe, run_ffmpeg, video_args

    try:
        sec = float(value)
    except ValueError:
        raise UserError("Enter the length of each piece in seconds.")
    if sec < 0.5:
        raise UserError("Each piece must be at least half a second long.")
    info = probe(ctx, src)
    pattern = d / f"{safe_stem(src)}_part%03d.{fmt}"
    if exact and fmt in VIDEO_OUT and info["video"]:
        args = video_args(fmt, Opts(video_quality="balanced"), info["audio"]) + ["-force_key_frames", f"expr:gte(t,n_forced*{sec:g})"]
    elif exact and fmt in AUDIO_OUT:
        args = audio_args(fmt, Opts(audio_kbps=256))
    else:
        args = ["-c", "copy", "-map", "0"]
    run_ffmpeg(ctx, ["-i", src, *args, "-f", "segment", "-segment_time", f"{sec:g}", "-reset_timestamps", "1", pattern], info["duration"], "split")
    return sorted(d.glob(f"*_part*.{fmt}"))


def trim_start(paths: list[str], recursive: bool, start: str, end: str, exact: bool, output: dict) -> dict:
    a, b = _mmss(start), _mmss(end)
    if end.strip() and b <= a:
        raise UserError("The end time must be after the start time.")
    policy = OutputPolicy.from_dict(output)
    tasks = []
    for src, rel in _files(paths, recursive):
        fmt = formats.detect(src)
        if formats.category(fmt) not in ("video", "audio"):
            continue

        def fn(ctx: Ctx, task: Task, src=src, fmt=fmt, rel=rel) -> Output:
            from app.convert.eng_media import AUDIO_OUT, VIDEO_OUT, audio_args, probe, run_ffmpeg, video_args

            info = probe(ctx, src)
            dst = ctx.scratch_dir() / f"{src.stem} (cut){src.suffix}"
            pre = ["-ss", f"{a:g}"] if a else []
            length = ["-t", f"{(b - a):g}"] if end.strip() else []
            if exact:
                args = video_args(fmt, Opts(video_quality="high"), info["audio"]) if info["video"] and fmt in VIDEO_OUT else audio_args(fmt, Opts(audio_kbps=256))
            else:
                args = ["-c", "copy"]
            run_ffmpeg(ctx, [*pre, "-i", src, *length, *args, dst], (b - a) if end.strip() else info["duration"] - a, "cut")
            return Output(policy.place([dst], src, rel), "Cut with exact timing." if exact else "Cut without re-encoding (fast; starts at the nearest keyframe).")

        tasks.append(Task(src.name, fn, src, heavy=True, rel=rel))
    if not tasks:
        raise UserError("Add a video or audio file to cut.")
    return {"job": ops.start("trim", "Cutting", tasks).id, "count": len(tasks)}


# ---------------------------------------------------------------- rotate and flip
def rotate_start(paths: list[str], recursive: bool, angle: int, flip: str, output: dict, pages: str = "", orient: str = "any") -> dict:
    angle = angle % 360
    if angle not in (0, 90, 180, 270):
        raise UserError("Choose 90, 180 or 270 degrees.")
    policy = OutputPolicy.from_dict(output)
    tasks = []
    for src, rel in _files(paths, recursive):
        fmt = formats.detect(src)
        cat = formats.category(fmt)

        def fn(ctx: Ctx, task: Task, src=src, fmt=fmt, cat=cat, rel=rel) -> Output:
            d = ctx.scratch_dir()
            dst = d / f"{src.stem} (rotated){src.suffix}"
            if cat == "image":
                from PIL import Image, ImageOps

                from app.convert.eng_image import SAVE_NAME, load_frames, rw, save_pil

                if fmt not in rw()[1]:
                    raise ConvertError("Fathom cannot save this picture format.")
                frames, durs, first = load_frames(src, fmt, all_frames=True)
                out = []
                from app import pagesel
                chosen_fr = set(pagesel.need(pages, len(frames))) if (len(frames) > 1 and pages.strip()) else set(range(len(frames)))
                for fi, fr in enumerate(frames):
                    if fi not in chosen_fr:
                        out.append(fr)
                        continue
                    if flip in ("h", "both"):
                        fr = ImageOps.mirror(fr)
                    if flip in ("v", "both"):
                        fr = ImageOps.flip(fr)
                    if angle:
                        fr = fr.rotate(-angle, expand=True)
                    out.append(fr)
                save_pil(out, durs, dst, fmt, Opts(image_quality=95), first)
            elif fmt == "pdf":
                from pypdf import PdfReader, PdfWriter

                from app import pagesel
                reader = PdfReader(str(src))
                if reader.is_encrypted:
                    try:
                        reader.decrypt("")
                    except Exception:
                        pass
                    if reader.is_encrypted:
                        raise ConvertError("This PDF is locked with a password. Remove the password first (Protect → PDF password).")
                sizes = []
                for pg in reader.pages:
                    wd, ht = float(pg.mediabox.width), float(pg.mediabox.height)
                    if (pg.get("/Rotate") or 0) % 180:
                        wd, ht = ht, wd
                    sizes.append((wd, ht))
                chosen = set(pagesel.need(pages, len(reader.pages), sizes, orient))
                w = PdfWriter()
                for i, pg in enumerate(reader.pages):
                    page = w.add_page(pg)
                    if i in chosen and angle:
                        page.rotate(angle)
                with open(dst, "wb") as fh:
                    w.write(fh)
            elif cat == "video":
                from app.convert.eng_media import VIDEO_OUT, probe, run_ffmpeg, video_args

                if fmt not in VIDEO_OUT or fmt == "gif":
                    raise ConvertError("Fathom cannot re-encode this video format.")
                info = probe(ctx, src)
                chain = []
                if flip in ("h", "both"):
                    chain.append("hflip")
                if flip in ("v", "both"):
                    chain.append("vflip")
                chain += {90: ["transpose=1"], 180: ["hflip", "vflip"], 270: ["transpose=2"], 0: []}[angle]
                args = video_args(fmt, Opts(video_quality="high"), info["audio"])
                vf = ",".join(chain) or "null"
                if "-vf" in args:
                    i = args.index("-vf")
                    args[i + 1] = vf + "," + args[i + 1]
                else:
                    args = ["-vf", vf] + args
                run_ffmpeg(ctx, ["-i", src, *args, dst], info["duration"], "rotate")
            else:
                raise ConvertError("Only pictures, PDFs and videos can be rotated.")
            return Output(policy.place([dst], src, rel), "")

        tasks.append(Task(src.name, fn, src, heavy=cat == "video", rel=rel))
    if not tasks:
        raise UserError("There are no files to rotate.")
    return {"job": ops.start("rotate", "Rotating", tasks).id, "count": len(tasks)}


# ---------------------------------------------------------------- extract pictures / frames
def extract_start(paths: list[str], recursive: bool, what: str, every: float, fmt_out: str, output: dict, pages: str = "") -> dict:
    policy = OutputPolicy.from_dict(output)
    tasks = []
    for src, rel in _files(paths, recursive):
        fmt = formats.detect(src)
        cat = formats.category(fmt)
        if what == "frames" and cat != "video":
            continue
        if what == "images" and not (fmt == "pdf" or fmt in ("docx", "pptx", "xlsx", "odt", "ods", "odp", "epub", "zip", "cbz", "xlsm")):
            continue

        def fn(ctx: Ctx, task: Task, src=src, fmt=fmt, rel=rel) -> Output:
            d = ctx.scratch_dir()
            if what == "frames":
                from app.convert.eng_media import probe, run_ffmpeg

                step = max(0.1, float(every or 1))
                ext = "png" if fmt_out == "png" else "jpg"
                info = probe(ctx, src)
                q = ["-q:v", "2"] if ext == "jpg" else []
                run_ffmpeg(ctx, ["-i", src, "-vf", f"fps=1/{step:g}", *q, d / f"frame_%05d.{ext}"], info["duration"], "pull frames from")
            else:
                _extract_images(src, fmt, d, ctx, pages)
            files = sorted(p for p in d.iterdir() if p.is_file())
            if not files:
                return Output([], "No pictures found inside.", skipped=True)
            placed = policy.place(files, src, rel, group_name=f"{safe_stem(src)} " + ("frames" if what == "frames" else "pictures"))
            return Output(placed, f"{len(placed)} pictures saved.")

        tasks.append(Task(src.name, fn, src, heavy=cat == "video", rel=rel))
    if not tasks:
        raise UserError("There is nothing to extract from these files.")
    return {"job": ops.start("extract", "Extracting", tasks).id, "count": len(tasks)}


def _extract_images(src: Path, fmt: str, d: Path, ctx: Ctx, pages: str = "") -> None:
    if fmt == "pdf":
        from app.convert.eng_docs import get_fitz, open_doc

        doc = open_doc(src, Opts())
        seen = set()
        from app import pagesel
        chosen = set(pagesel.need(pages, doc.page_count))
        for pn, page in enumerate(doc, 1):
            ctx.check()
            if pn - 1 not in chosen:
                continue
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen:
                    continue
                seen.add(xref)
                try:
                    info = doc.extract_image(xref)
                except Exception:
                    continue
                (d / f"page{pn:03d}_{xref}.{info['ext']}").write_bytes(info["image"])
            ctx.progress(pn / doc.page_count)
        doc.close()
        return
    with zipfile.ZipFile(src) as z:
        for info in z.infolist():
            ctx.check()
            if re.search(r"\.(png|jpe?g|gif|bmp|tiff?|webp|svg|emf|wmf)$", info.filename, re.I) and not info.is_dir():
                name = re.sub(r"[\\/]+", "_", info.filename)
                (d / name).write_bytes(z.read(info))


# ---------------------------------------------------------------- encryption
MAGIC = b"FTHM1\x00"        # AES-256-GCM
MAGIC2 = b"FTHM2\x00"       # ChaCha20-Poly1305


def _kdf(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password.encode("utf-8"))


def encrypt_start(paths: list[str], recursive: bool, password: str, decrypt: bool, output: dict, algo: str = "aes") -> dict:
    if len(password) < 4:
        raise UserError("Use a password of at least 4 characters (longer is much safer).")
    policy = OutputPolicy.from_dict(output)
    tasks = []
    for src, rel in _files(paths, recursive):
        if decrypt != src.name.lower().endswith(".locked"):
            continue

        def fn(ctx: Ctx, task: Task, src=src, rel=rel) -> Output:
            d = ctx.scratch_dir()
            if decrypt:
                dst = d / (src.name[:-7] or "decrypted")
                _decrypt_file(src, dst, password, ctx)
                return Output(policy.place([dst], src, rel), "Unlocked.")
            dst = d / (src.name + ".locked")
            _encrypt_file(src, dst, password, ctx, algo)
            return Output(policy.place([dst], src, rel), ("Locked with ChaCha20-Poly1305. " if algo == "chacha" else "Locked with AES-256. ") + "Keep the password safe: without it the file cannot be recovered.")

        tasks.append(Task(src.name, fn, src, rel=rel))
    if not tasks:
        raise UserError("There are no " + ("locked (.locked) files" if decrypt else "files") + " to " + ("unlock" if decrypt else "lock") + ".")
    return {"job": ops.start("decrypt" if decrypt else "encrypt", "Unlocking" if decrypt else "Locking", tasks).id, "count": len(tasks)}


CHUNK = 1 << 20


def _cipher(chacha: bool):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

    return ChaCha20Poly1305 if chacha else AESGCM


def _encrypt_file(src: Path, dst: Path, password: str, ctx: Ctx, algo: str = "aes") -> None:

    salt, prefix = os.urandom(16), os.urandom(4)
    aes = _cipher(algo == "chacha")(_kdf(password, salt))
    total = max(1, file_bytes(src))
    done, idx = 0, 0
    name = src.name.encode("utf-8")
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        fout.write((MAGIC2 if algo == "chacha" else MAGIC) + salt + prefix + struct.pack(">H", len(name)))
        fout.write(aes.encrypt(prefix + b"\xff" * 8, name, b"name"))
        block = fin.read(CHUNK)
        while True:
            ctx.check()
            nxt = fin.read(CHUNK)
            last = not nxt
            nonce = prefix + struct.pack(">Q", idx)
            ct = aes.encrypt(nonce, block, b"last" if last else b"more")
            fout.write(struct.pack(">I", len(ct)) + ct)
            done += len(block)
            ctx.progress(done / total)
            idx += 1
            if last:
                break
            block = nxt


def _decrypt_file(src: Path, dst: Path, password: str, ctx: Ctx) -> None:
    from cryptography.exceptions import InvalidTag

    total = max(1, file_bytes(src))
    with open(src, "rb") as fin:
        head = fin.read(len(MAGIC) + 16 + 4 + 2)
        if head[:len(MAGIC)] not in (MAGIC, MAGIC2):
            raise ConvertError("This is not a file locked by this app.")
        salt, prefix = head[len(MAGIC):len(MAGIC) + 16], head[len(MAGIC) + 16:len(MAGIC) + 20]
        nlen = struct.unpack(">H", head[-2:])[0]
        aes = _cipher(head[:len(MAGIC)] == MAGIC2)(_kdf(password, salt))
        try:
            aes.decrypt(prefix + b"\xff" * 8, fin.read(nlen + 16), b"name")
        except InvalidTag:
            raise ConvertError("Wrong password.")
        idx = 0
        with open(dst, "wb") as fout:
            while True:
                ctx.check()
                raw = fin.read(4)
                if not raw:
                    raise ConvertError("The file is cut short (damaged or incomplete).")
                ln = struct.unpack(">I", raw)[0]
                ct = fin.read(ln)
                is_last = fin.peek(1)[:1] == b"" if hasattr(fin, "peek") else False
                nonce = prefix + struct.pack(">Q", idx)
                try:
                    fout.write(aes.decrypt(nonce, ct, b"last" if is_last else b"more"))
                except InvalidTag:
                    raise ConvertError("The file is damaged or was changed after it was locked.")
                ctx.progress(fin.tell() / total)
                idx += 1
                if is_last:
                    break


def pdf_lock_start(paths: list[str], recursive: bool, password: str, unlock: bool, output: dict) -> dict:
    if not password:
        raise UserError("Enter a password.")
    policy = OutputPolicy.from_dict(output)
    tasks = []
    for src, rel in _files(paths, recursive):
        if formats.detect(src) != "pdf":
            continue

        def fn(ctx: Ctx, task: Task, src=src, rel=rel) -> Output:
            from app.convert.eng_docs import get_fitz

            fitz = get_fitz()
            doc = fitz.open(str(src))
            dst = ctx.scratch_dir() / f"{src.stem} ({'unlocked' if unlock else 'protected'}).pdf"
            if unlock:
                if doc.needs_pass and not doc.authenticate(password):
                    raise ConvertError("Wrong password.")
                doc.save(str(dst), encryption=fitz.PDF_ENCRYPT_NONE, garbage=3, deflate=True)
            else:
                doc.save(str(dst), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password + "-owner", garbage=3, deflate=True)
            doc.close()
            return Output(policy.place([dst], src, rel), "Opens with the password in any PDF reader." if not unlock else "The password was removed.")

        tasks.append(Task(src.name, fn, src, rel=rel))
    if not tasks:
        raise UserError("Add a PDF first.")
    return {"job": ops.start("pdflock", "Working on PDFs", tasks).id, "count": len(tasks)}


# ---------------------------------------------------------------- pack into an archive
def pack_start(paths: list[str], fmt: str, name: str, password: str, level: int, output: dict, extra: dict | None = None) -> dict:
    from app.convert.eng_misc import PACK_OUT

    extra = extra or {}
    if fmt not in PACK_OUT and fmt != "sfx" or fmt in ("gz", "bz2", "xz"):
        fmt = "zip"
    roots = [Path(p) for p in paths if Path(p).exists()]
    if not roots:
        raise UserError("Add files or folders to pack.")
    policy = OutputPolicy.from_dict(output)
    o = Opts(password=password, level=int(level or 9))

    def fn(ctx: Ctx, task: Task) -> Output:
        d = ctx.scratch_dir()
        stem = re.sub(r'[<>:"/\\|?*]', "_", name.strip()) or (roots[0].stem if len(roots) == 1 else "Archive")
        dst = d / f"{stem}.{fmt}"
        if fmt == "sfx" or float(extra.get("volume_mb") or 0) > 0:
            _pack_with_7z(roots, d, stem, fmt, o, ctx, float(extra.get("volume_mb") or 0))
            dst = sorted(d.glob(f"{stem}.*"))[0]
            outs = sorted(d.glob(f"{stem}.*"))
            return Output(policy.place(outs, roots[0], Path("."), group_name=stem), f"{len(roots)} item(s) packed" + (f" into {len(outs)} parts." if len(outs) > 1 else "."))
        _pack_paths(roots, dst, fmt, o, ctx)
        return Output(policy.place([dst], roots[0], Path(".")), f"{len(roots)} item(s) packed.")

    return {"job": ops.start("pack", "Packing", [Task("Archive", fn, roots[0])], workers=1).id}


def _pack_paths(roots: list[Path], dst: Path, fmt: str, o: Opts, ctx: Ctx) -> None:
    import tarfile

    entries: list[tuple[Path, str]] = []
    for r in roots:
        if r.is_dir():
            for f in sorted(r.rglob("*")):
                if f.is_file():
                    entries.append((f, (Path(r.name) / f.relative_to(r)).as_posix()))
        else:
            entries.append((r, r.name))
    if not entries:
        raise ConvertError("There is nothing to pack.")
    total = max(1, sum(file_bytes(f) for f, _ in entries))
    done = 0
    level = max(1, min(9, o.level))
    if fmt == "zip":
        if o.password:
            try:
                import pyzipper  # type: ignore
            except ImportError:
                raise ConvertError("Password-protected ZIP files need the 'pyzipper' package (run repair with internet).")
            zf = pyzipper.AESZipFile(dst, "w", compression=pyzipper.ZIP_DEFLATED, compresslevel=level, encryption=pyzipper.WZ_AES)
            zf.setpassword(o.password.encode())
        else:
            zf = zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=level, allowZip64=True)
        with zf:
            for f, arc in entries:
                ctx.check()
                zf.write(f, arc)
                done += file_bytes(f)
                ctx.progress(done / total)
    elif fmt.startswith("tar"):
        mode = {"tar": "w:", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}[fmt]
        kw = {"compresslevel": level} if fmt in ("tar.gz", "tar.bz2") else ({"preset": level} if fmt == "tar.xz" else {})
        with tarfile.open(dst, mode, **kw) as tf:
            for f, arc in entries:
                ctx.check()
                tf.add(f, arc, recursive=False)
                done += file_bytes(f)
                ctx.progress(done / total)
    elif fmt == "7z":
        try:
            import py7zr
        except ImportError:
            raise ConvertError("Making 7z files needs the 'py7zr' package (run repair with internet).")
        with py7zr.SevenZipFile(dst, "w", filters=[{"id": py7zr.FILTER_LZMA2, "preset": level}], password=o.password or None) as z:
            for f, arc in entries:
                ctx.check()
                z.write(f, arc)
                done += file_bytes(f)
                ctx.progress(done / total)


def _pack_with_7z(roots: list[Path], d: Path, stem: str, fmt: str, o: Opts, ctx: Ctx, volume_mb: float) -> None:
    """Self-extracting .exe files and multi-part archives need the real 7-Zip program."""
    from app.convert.eng_misc import sevenzip_exe

    exe = sevenzip_exe()
    if not exe:
        raise ConvertError("Self-extracting and multi-part archives need 7-Zip (Fathom.bat repair installs it).")
    ext = "exe" if fmt == "sfx" else ("zip" if fmt == "zip" else "7z")
    dst = d / f"{stem}.{ext}"
    cmd = [exe, "a", f"-mx={max(1, min(9, o.level))}", "-bsp1", str(dst)]
    if fmt == "sfx":
        sfx = Path(exe).with_name("7z.sfx")
        if not sfx.exists():
            raise ConvertError("This 7-Zip install has no self-extracting module (7z.sfx).")
        cmd.insert(2, f"-sfx{sfx.name}")
    elif fmt == "zip":
        cmd.insert(2, "-tzip")
    if volume_mb > 0:
        cmd.insert(2, f"-v{int(volume_mb)}m")
    if o.password:
        cmd.insert(2, f"-p{o.password}")
        if fmt != "zip":
            cmd.insert(2, "-mhe=on")
    cmd += [str(r) for r in roots]

    def on_line(line: str) -> None:
        m = re.search(r"(\d{1,3})%", line)
        if m:
            ctx.progress(int(m.group(1)) / 100)

    rc, text = ctx.run(cmd, on_line)
    if rc not in (0, 1) or not any(d.glob(f"{stem}.*")):
        raise ConvertError("7-Zip could not make the archive. " + " ".join(text.split())[-200:])
