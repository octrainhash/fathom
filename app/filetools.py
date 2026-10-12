"""File tools, part 1: checksums, duplicates, file info, metadata (view and clean), bulk rename and organise (with undo)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import time
import uuid
import zlib
from pathlib import Path

from app import ops
from app.convert import formats
from app.convert.core import ConvertError, Ctx, ffmpeg_exe, file_bytes, unique_path
from app.ops import Output, Task
from app.opsvc import expand_sources
from app.paths import data_root
from app.service import UserError

ALGOS = ("md5", "sha1", "sha224", "sha256", "sha384", "sha512", "sha3_256", "sha3_512", "blake2b", "blake2s", "crc32", "adler32")


# ---------------------------------------------------------------- checksums
def hash_start(paths: list[str], recursive: bool, algos: list[str], expect: str = "") -> dict:
    algos = [a for a in algos if a in ALGOS] or ["sha256"]
    expect = re.sub(r"\s+", "", (expect or "")).lower()
    tasks = []
    for src, rel in expand_sources(paths, recursive):
        def fn(ctx, task, src=src):
            hs = {a: hashlib.new(a) for a in algos if a not in ("crc32", "adler32")}
            crc, adl = 0, 1
            size = max(1, file_bytes(src))
            done = 0
            with open(src, "rb") as fh:
                while True:
                    ctx.check()
                    block = fh.read(4 << 20)
                    if not block:
                        break
                    for h in hs.values():
                        h.update(block)
                    if "crc32" in algos:
                        crc = zlib.crc32(block, crc)
                    if "adler32" in algos:
                        adl = zlib.adler32(block, adl)
                    done += len(block)
                    ctx.progress(done / size)
            vals = {a: h.hexdigest() for a, h in hs.items()}
            if "crc32" in algos:
                vals["crc32"] = f"{crc & 0xffffffff:08x}"
            if "adler32" in algos:
                vals["adler32"] = f"{adl & 0xffffffff:08x}"
            note = ""
            if expect:
                hit = [a for a, v in vals.items() if v == expect or v == expect.lstrip("0")]
                note = f"MATCHES the {hit[0].upper()} you entered." if hit else "Does NOT match the value you entered."
                vals["match"] = bool(hit)
            return Output([], note, extra=vals)

        tasks.append(Task(src.name, fn, src, rel=rel))
    if not tasks:
        raise UserError("There are no files to check.")
    job = ops.start("hash", "Checksums", tasks)
    job.data["algos"] = algos
    return {"job": job.id, "count": len(tasks)}


# ---------------------------------------------------------------- duplicates
def dups_start(paths: list[str], recursive: bool, min_bytes: int = 1) -> dict:
    def fn(ctx: Ctx, task: Task) -> Output:
        ctx.status("Listing files…")
        files = expand_sources(paths, recursive)
        by_size: dict[int, list[Path]] = {}
        for p, _rel in files:
            ctx.check()
            sz = file_bytes(p)
            if sz >= max(1, min_bytes):
                by_size.setdefault(sz, []).append(p)
        cand = {s: v for s, v in by_size.items() if len(v) > 1}
        total = sum(len(v) for v in cand.values()) or 1
        done = 0
        groups = []
        ctx.status("Comparing files…")
        for size, same in cand.items():
            ctx.check()
            quick: dict[bytes, list[Path]] = {}
            for p in same:
                try:
                    with open(p, "rb") as fh:
                        head = fh.read(65536)
                        tail = b""
                        if size > 131072:
                            fh.seek(-65536, 2)
                            tail = fh.read(65536)
                    quick.setdefault(hashlib.sha1(head + tail).digest(), []).append(p)
                except OSError:
                    pass
                done += 1
                ctx.progress(done / total * 0.4)
            for bucket in quick.values():
                if len(bucket) < 2:
                    continue
                full: dict[str, list[Path]] = {}
                for p in bucket:
                    h = hashlib.sha256()
                    try:
                        with open(p, "rb") as fh:
                            while True:
                                ctx.check()
                                b = fh.read(4 << 20)
                                if not b:
                                    break
                                h.update(b)
                    except OSError:
                        continue
                    full.setdefault(h.hexdigest(), []).append(p)
                for same_files in full.values():
                    if len(same_files) > 1:
                        groups.append({"size": size, "files": [{"path": str(p), "mtime": int(p.stat().st_mtime)} for p in sorted(same_files, key=lambda x: x.stat().st_mtime)]})
            ctx.progress(0.4 + 0.6 * done / total)
        groups.sort(key=lambda g: -g["size"] * (len(g["files"]) - 1))
        wasted = sum(g["size"] * (len(g["files"]) - 1) for g in groups)
        ctx.job.data["groups"] = groups  # type: ignore[attr-defined]
        ctx.job.data["wasted"] = wasted  # type: ignore[attr-defined]
        return Output([], f"{len(groups)} sets of identical files; {wasted // (1024 * 1024)} MB could be freed.")

    job = ops.start("dups", "Looking for duplicates", [Task("Looking for duplicates", fn)], workers=1)
    return {"job": job.id}


def dups_apply(job_id: str, action: str, remove: list[str], dest: str = "") -> dict:
    job = ops.OPJOBS.get(job_id)
    if not job or "groups" not in job.data:
        raise UserError("Run the duplicate search first.")
    remove_set = {os.path.normcase(os.path.abspath(p)) for p in remove}
    valid = {}
    for g in job.data["groups"]:
        keep = [f for f in g["files"] if os.path.normcase(os.path.abspath(f["path"])) not in remove_set]
        for f in g["files"]:
            if os.path.normcase(os.path.abspath(f["path"])) in remove_set:
                valid[os.path.normcase(os.path.abspath(f["path"]))] = f["path"]
        if not keep and any(os.path.normcase(os.path.abspath(f["path"])) in remove_set for f in g["files"]):
            raise UserError("For safety, at least one copy of every file must stay. Untick one copy in each set.")
    if action == "move" and not dest:
        raise UserError("Choose a folder to move the copies into.")
    done, failed, freed = 0, [], 0
    for key, path in valid.items():
        p = Path(path)
        try:
            sz = file_bytes(p)
            if action == "move":
                d = Path(dest)
                d.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(unique_path(d / p.name)))
            else:
                from app.recycle import to_recycle_bin

                to_recycle_bin(p)
            done += 1
            freed += sz
        except Exception as exc:
            failed.append({"path": path, "error": str(exc)})
    return {"done": done, "failed": failed, "freed": freed}


# ---------------------------------------------------------------- info
def file_info(paths: list[str]) -> list[dict]:
    rows = []
    for p in (Path(x) for x in paths):
        if not p.exists():
            rows.append({"path": str(p), "name": p.name, "error": "Not found"})
            continue
        if p.is_dir():
            n = sum(1 for _ in p.rglob("*") if _.is_file())
            rows.append({"path": str(p), "name": p.name, "folder": True, "files": n, "bytes": ops.path_bytes(p)})
            continue
        st = p.stat()
        ext = formats.ext_of(p)
        real = formats.sniff(p)
        claimed = formats.known_fmt(ext) or ""
        mismatch = bool(real and claimed and real != claimed and formats.category(real) != "text" and not (real in ("zip",) and claimed in ("docx", "xlsx", "pptx", "odt", "ods", "odp", "epub", "jar", "cbz", "xlsm", "dotx")))
        fmt = formats.detect(p)
        rows.append({"path": str(p), "name": p.name, "bytes": st.st_size, "modified": int(st.st_mtime), "created": int(getattr(st, "st_ctime", st.st_mtime)),
                     "ext": ext, "claimed": claimed, "real": real, "type": formats.label(real or fmt), "category": formats.category(real or fmt),
                     "mismatch": mismatch, "should_be": real if mismatch else ""})
    return rows


def fix_extensions(paths: list[str]) -> dict:
    fixed = []
    journal = []
    for r in file_info(paths):
        if r.get("mismatch") and r.get("should_be"):
            p = Path(r["path"])
            new = unique_path(p.with_name(f"{p.stem}.{r['should_be'].replace('tar.', 'tar.')}"))
            p.rename(new)
            journal.append({"from": str(p), "to": str(new)})
            fixed.append({"from": p.name, "to": new.name})
    if journal:
        _write_journal("fix-extension", journal)
    return {"fixed": fixed}


# ---------------------------------------------------------------- metadata
def _gps_from_exif(exif) -> dict | None:
    try:
        gps = exif.get_ifd(0x8825)
        if not gps:
            return None

        def deg(v, ref):
            d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
            return -d if ref in ("S", "W") else d

        return {"lat": round(deg(gps[2], gps.get(1, "N")), 6), "lon": round(deg(gps[4], gps.get(3, "E")), 6)}
    except Exception:
        return None


def meta_view(paths: list[str]) -> list[dict]:
    out = []
    for p in (Path(x) for x in paths):
        if p.is_dir() or not p.exists():
            continue
        fmt = formats.detect(p)
        cat = formats.category(fmt)
        fields: list[list[str]] = []
        private: list[str] = []
        gps = None
        try:
            if cat == "image":
                from PIL import ExifTags, Image

                with Image.open(p) as im:
                    fields += [["Size", f"{im.width} × {im.height} px"], ["Mode", im.mode]]
                    exif = im.getexif()
                    for k, v in exif.items():
                        name = ExifTags.TAGS.get(k, str(k))
                        if name in ("MakerNote", "UserComment") or isinstance(v, bytes) and len(v) > 80:
                            continue
                        fields.append([name, str(v)[:200]])
                        if name in ("BodySerialNumber", "CameraOwnerName", "LensSerialNumber", "Artist", "HostComputer"):
                            private.append(name)
                    for k, v in exif.get_ifd(0x8769).items():
                        name = ExifTags.TAGS.get(k, str(k))
                        if name in ("MakerNote", "UserComment") or isinstance(v, bytes):
                            continue
                        fields.append([name, str(v)[:200]])
                    gps = _gps_from_exif(exif)
                    if gps:
                        private.append("GPS location")
                    for k, v in im.info.items():
                        if k in ("icc_profile", "exif", "xmp", "dpi") or isinstance(v, (bytes, tuple)):
                            continue
                        fields.append([str(k), str(v)[:200]])
            elif fmt == "pdf":
                from app.convert.eng_docs import get_fitz

                fitz = get_fitz()
                doc = fitz.open(str(p))
                fields += [["Pages", str(doc.page_count)]] + [[k, str(v)] for k, v in (doc.metadata or {}).items() if v]
                for k in ("author", "creator", "producer"):
                    if (doc.metadata or {}).get(k):
                        private.append(k.capitalize())
                doc.close()
            elif fmt in ("docx", "pptx", "xlsx", "odt", "ods", "odp"):
                import zipfile

                with zipfile.ZipFile(p) as z:
                    for name in ("docProps/core.xml", "docProps/app.xml", "meta.xml"):
                        if name in z.namelist():
                            xml = z.read(name).decode("utf8", "replace")
                            for tag, val in re.findall(r"<(?:\w+:)?([A-Za-z]+)[^>]*>([^<]{1,200})</", xml):
                                fields.append([tag, val])
                                if tag.lower() in ("creator", "lastmodifiedby", "company", "manager", "initial-creator", "creator"):
                                    private.append(tag)
            elif cat in ("video", "audio"):
                from app.convert.core import Ctx
                from app.convert.eng_media import probe

                ctx = Ctx(Path(data_root()) / "tmp" / "metaview")
                info = probe(ctx, p)
                if info["duration"]:
                    fields.append(["Duration", f"{info['duration']:.1f} s"])
                if info["w"]:
                    fields.append(["Picture", f"{info['w']} × {info['h']}"])
                block = False
                for line in info["text"].splitlines():
                    s = line.strip()
                    if s.startswith("Metadata:"):
                        block = True
                        continue
                    if block and ":" in s and not s.startswith(("Stream", "Duration", "Input")):
                        k, v = s.split(":", 1)
                        fields.append([k.strip(), v.strip()[:200]])
                        if k.strip().lower() in ("location", "com.apple.quicktime.location.iso6709", "artist", "encoder"):
                            private.append(k.strip())
                    elif s.startswith(("Stream", "Duration")):
                        block = False
        except Exception as exc:
            fields.append(["Could not read", str(exc)])
        st = p.stat()
        fields.insert(0, ["Last changed", dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")])
        out.append({"path": str(p), "name": p.name, "type": formats.label(fmt), "fields": fields, "gps": gps, "private": sorted(set(private))})
    return out


def _strip_jpeg(src: Path, dst: Path) -> bool:
    data = src.read_bytes()
    if data[:2] != b"\xff\xd8":
        return False
    out = bytearray(b"\xff\xd8")
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return False
        marker = data[i + 1]
        if marker == 0xDA:
            out += data[i:]
            break
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            out += data[i:i + 2]
            i += 2
            continue
        ln = int.from_bytes(data[i + 2:i + 4], "big")
        seg = data[i:i + 2 + ln]
        keep = True
        if marker == 0xE1 or marker == 0xFE or marker in (0xEC, 0xED):
            keep = False                 # EXIF / XMP, comments, Ducky / Photoshop blocks
        if marker == 0xE2 and not seg[4:16].startswith(b"ICC_PROFILE"):
            keep = False
        if keep:
            out += seg
        i += 2 + ln
    dst.write_bytes(bytes(out))
    return True


def _strip_png(src: Path, dst: Path) -> bool:
    data = src.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    out = bytearray(data[:8])
    i = 8
    while i + 8 <= len(data):
        ln = int.from_bytes(data[i:i + 4], "big")
        typ = data[i + 4:i + 8]
        chunk = data[i:i + 12 + ln]
        if typ not in (b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"):
            out += chunk
        i += 12 + ln
    dst.write_bytes(bytes(out))
    return True


def meta_strip_start(paths: list[str], recursive: bool, output: dict) -> dict:
    policy = ops.OutputPolicy.from_dict(output)
    tasks = []
    for src, rel in expand_sources(paths, recursive):
        fmt = formats.detect(src)

        def fn(ctx, task, src=src, rel=rel, fmt=fmt):
            d = ctx.scratch_dir()
            dst = d / f"{src.stem} (clean){src.suffix}"
            cat = formats.category(fmt)
            if fmt == "jpg":
                from PIL import Image

                with Image.open(src) as im:
                    orient = im.getexif().get(0x0112, 1)
                if orient in (None, 1):
                    ok = _strip_jpeg(src, dst)
                else:
                    from PIL import ImageOps

                    with Image.open(src) as im:
                        ImageOps.exif_transpose(im).save(dst, "JPEG", quality=95, optimize=True)
                    ok = True
            elif fmt == "png":
                ok = _strip_png(src, dst)
            elif cat == "image":
                from app.convert.eng_image import load_frames, rw, save_pil
                from app.convert.core import Opts

                if fmt not in rw()[1]:
                    return Output([], "Fathom cannot rewrite this picture format without its data.", skipped=True)
                frames, durs, first = load_frames(src, fmt, all_frames=True)
                save_pil(frames, durs, dst, fmt, Opts(strip_metadata=True, image_quality=95), None)
                ok = True
            elif fmt == "pdf":
                from app.convert.eng_docs import get_fitz

                fitz = get_fitz()
                doc = fitz.open(str(src))
                doc.set_metadata({})
                try:
                    doc.del_xml_metadata()
                except Exception:
                    pass
                doc.save(str(dst), garbage=3, deflate=True)
                doc.close()
                ok = True
            elif fmt in ("docx", "pptx", "xlsx", "odt", "ods", "odp"):
                ok = _strip_office(src, dst)
            elif cat in ("video", "audio"):
                from app.convert.eng_media import run_ffmpeg

                run_ffmpeg(ctx, ["-i", src, "-map", "0", "-map_metadata", "-1", "-map_chapters", "-1", "-c", "copy", dst], 0, "clean")
                ok = True
            else:
                return Output([], "This kind of file has no metadata Fathom can clean.", skipped=True)
            if not ok:
                raise ConvertError("This file is not a valid picture, so it could not be cleaned.")
            placed = policy.place([dst], src, rel)
            return Output(placed, "Personal details removed (location, camera, author, comments).")

        tasks.append(Task(src.name, fn, src, heavy=formats.category(fmt) in ("video", "audio"), rel=rel))
    if not tasks:
        raise UserError("There are no files to clean.")
    return {"job": ops.start("meta", "Removing hidden details", tasks).id, "count": len(tasks)}


def _strip_office(src: Path, dst: Path) -> bool:
    import zipfile

    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zout:
        for info in zin.infolist():
            data = zin.read(info)
            n = info.filename
            if n == "docProps/core.xml":
                data = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                        b'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"></cp:coreProperties>')
            elif n == "docProps/app.xml":
                data = re.sub(rb"<(Company|Manager|Application|AppVersion)>[^<]*</\1>", b"", data)
            elif n == "docProps/custom.xml":
                continue
            elif n == "meta.xml":
                data = (b'<?xml version="1.0" encoding="UTF-8"?><office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" office:version="1.2"><office:meta/></office:document-meta>')
            zi = zipfile.ZipInfo(n, info.date_time)
            zi.compress_type = zipfile.ZIP_STORED if n == "mimetype" else zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)
    return True


# ---------------------------------------------------------------- undo journal (rename / organise / fix extension)
def _journal_dir() -> Path:
    d = data_root() / "undo"
    d.mkdir(exist_ok=True)
    return d


def _write_journal(kind: str, moves: list[dict]) -> None:
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}-{kind}.json"
    (_journal_dir() / name).write_text(json.dumps({"kind": kind, "moves": moves, "time": time.time()}), encoding="utf-8")
    try:
        from app import history
        history.add({"kind": kind, "title": {"rename": "Renamed files", "organise": "Organised files", "fix-extension": "Fixed file extensions", "compat-fix": "Fixed names for another system"}.get(kind, "Moved files"), "moves": moves, "journal": name})
    except Exception:
        pass


def undo_last() -> dict:
    files = sorted(_journal_dir().glob("*.json"))
    if not files:
        raise UserError("There is nothing to undo.")
    last = files[-1]
    data = json.loads(last.read_text(encoding="utf-8"))
    restored, failed = 0, []
    for mv in reversed(data["moves"]):
        src, dst = Path(mv["to"]), Path(mv["from"])
        try:
            if mv.get("copied"):
                if src.exists():
                    src.unlink()
            else:
                if not src.exists():
                    raise FileNotFoundError("the renamed file is gone")
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(unique_path(dst) if dst.exists() else dst))
            restored += 1
        except Exception as exc:
            failed.append({"path": str(src), "error": str(exc)})
    last.rename(last.with_suffix(".done"))
    try:
        from app import history
        history.mark_journal_undone(last.name)
    except Exception:
        pass
    return {"restored": restored, "failed": failed, "kind": data["kind"]}


def undo_available() -> dict:
    files = sorted(_journal_dir().glob("*.json"))
    if not files:
        return {"available": False}
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    return {"available": True, "kind": data["kind"], "count": len(data["moves"]), "when": data["time"]}


# ---------------------------------------------------------------- bulk rename
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _apply_rules(stem: str, ext: str, index: int, p: Path, r: dict) -> tuple[str, str]:
    name = stem
    find = r.get("find", "")
    if find:
        if r.get("regex"):
            try:
                name = re.sub(find, r.get("replace", ""), name, flags=0 if r.get("case_sensitive") else re.I)
            except re.error as exc:
                raise UserError(f"The pattern is not valid: {exc}")
        else:
            name = re.sub(re.escape(find), (r.get("replace", "")).replace("\\", "\\\\"), name, flags=0 if r.get("case_sensitive") else re.I)
    if r.get("remove_chars"):
        name = re.sub("[" + re.escape(r["remove_chars"]) + "]", "", name)
    sp = r.get("spaces", "keep")
    if sp != "keep":
        name = re.sub(r"\s+", {"underscore": "_", "dash": "-", "dot": ".", "none": ""}.get(sp, " "), name)
    case = r.get("case", "keep")
    if case == "lower":
        name = name.lower()
    elif case == "upper":
        name = name.upper()
    elif case == "title":
        name = name.title()
    elif case == "sentence":
        name = name[:1].upper() + name[1:].lower()
    if r.get("trim", True):
        name = name.strip()
    pattern = r.get("pattern") or "{name}"
    st = p.stat()
    try:
        name = pattern.format(name=name, ext=ext, n=index + int(r.get("start", 1)) - 1 + (index * (int(r.get("step", 1)) - 1)),
                              date=dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"), time=dt.datetime.fromtimestamp(st.st_mtime).strftime("%H-%M-%S"),
                              year=dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y"), parent=p.parent.name)
    except (KeyError, IndexError, ValueError) as exc:
        raise UserError(f"The name pattern has a problem ({exc}). Use tokens like {{name}}, {{n:03}}, {{date}}, {{parent}}.")
    e = ext
    ec = r.get("ext_case", "keep")
    if ec == "lower":
        e = e.lower()
    elif ec == "upper":
        e = e.upper()
    if r.get("new_ext"):
        e = r["new_ext"].lstrip(".")
    return _INVALID.sub("_", name).rstrip(" ."), e


def rename_preview(paths: list[str], recursive: bool, rules: dict) -> dict:
    files = [p for p, _ in expand_sources(paths, recursive)]
    if rules.get("sort") == "date":
        files.sort(key=lambda p: p.stat().st_mtime)
    elif rules.get("sort") == "size":
        files.sort(key=lambda p: p.stat().st_size)
    else:
        files.sort(key=lambda p: (str(p.parent).lower(), p.name.lower()))
    rows = []
    taken: dict[str, set[str]] = {}
    for i, p in enumerate(files):
        raw = p.name
        suffix = p.suffix
        stem = p.stem if suffix else p.name
        ext = suffix.lstrip(".")
        new_stem, new_ext = _apply_rules(stem, ext, i + 1, p, rules)
        new = new_stem + ("." + new_ext if new_ext else "")
        key = os.path.normcase(str(p.parent))
        used = taken.setdefault(key, set())
        status = "ok"
        if not new_stem:
            status = "invalid"
        elif new == raw:
            status = "same"
        else:
            cand, n = new, 2
            while os.path.normcase(cand) in used or (os.path.normcase(cand) != os.path.normcase(raw) and (p.parent / cand).exists()):
                base, dot, e = new.rpartition(".") if "." in new else (new, "", "")
                cand = f"{base} ({n}){dot}{e}" if dot else f"{new} ({n})"
                n += 1
            if cand != new:
                status = "renumbered"
            new = cand
        used.add(os.path.normcase(new))
        rows.append({"path": str(p), "old": raw, "new": new, "status": status, "folder": str(p.parent)})
    return {"rows": rows, "changes": sum(1 for r in rows if r["status"] in ("ok", "renumbered"))}


def rename_apply(rows: list[dict]) -> dict:
    todo = [r for r in rows if r["status"] in ("ok", "renumbered") and r["old"] != r["new"]]
    journal = []
    failed = []
    # two phases so names can swap or shift without clashing
    staged = []
    for r in todo:
        p = Path(r["path"])
        tmp = p.with_name(f".fathom-{os.urandom(4).hex()}-{p.name}")
        try:
            p.rename(tmp)
            staged.append((p, tmp, r["new"]))
        except OSError as exc:
            failed.append({"path": str(p), "error": str(exc)})
    for p, tmp, new in staged:
        final = p.with_name(new)
        try:
            if final.exists():
                final = unique_path(final)
            tmp.rename(final)
            journal.append({"from": str(p), "to": str(final)})
        except OSError as exc:
            try:
                tmp.rename(p)
            except OSError:
                pass
            failed.append({"path": str(p), "error": str(exc)})
    if journal:
        _write_journal("rename", journal)
    return {"renamed": len(journal), "failed": failed}


# ---------------------------------------------------------------- organise
CATEGORY_FOLDERS = {"image": "Pictures", "video": "Videos", "audio": "Music", "document": "Documents", "presentation": "Presentations",
                    "spreadsheet": "Spreadsheets", "data": "Data", "text": "Text and code", "ebook": "Books", "archive": "Archives",
                    "font": "Fonts", "subtitle": "Subtitles", "mesh": "3D models", "other": "Other"}


def organize_preview(paths: list[str], recursive: bool, how: str, dest: str, copy: bool) -> dict:
    files = [(p, rel) for p, rel in expand_sources(paths, recursive)]
    if not files:
        raise UserError("There are no files to organise.")
    roots = [Path(p) for p in paths]
    base = Path(dest) if dest else (roots[0] if roots[0].is_dir() else roots[0].parent)
    rows = []
    taken: set[str] = set()
    for p, _rel in files:
        st = p.stat()
        when = dt.datetime.fromtimestamp(st.st_mtime)
        if how == "type":
            sub = CATEGORY_FOLDERS.get(formats.category(formats.detect(p)), "Other")
        elif how == "extension":
            sub = (formats.ext_of(p) or "no extension").upper()
        elif how == "year":
            sub = f"{when:%Y}"
        elif how == "month":
            sub = f"{when:%Y}/{when:%Y-%m}"
        elif how == "size":
            mb = st.st_size / (1024 * 1024)
            sub = "Tiny (under 1 MB)" if mb < 1 else "Small (1-100 MB)" if mb < 100 else "Large (100 MB-1 GB)" if mb < 1024 else "Huge (over 1 GB)"
        elif how == "initial":
            sub = (p.name[:1].upper() if p.name[:1].isalnum() else "#")
        else:
            raise UserError("Choose how to organise.")
        target = base / sub / p.name
        if os.path.normcase(str(target)) == os.path.normcase(str(p)):
            continue
        n = 2
        final = target
        while os.path.normcase(str(final)) in taken or final.exists():
            final = target.with_name(f"{target.stem} ({n}){target.suffix}")
            n += 1
        taken.add(os.path.normcase(str(final)))
        rows.append({"path": str(p), "to": str(final), "folder": sub})
    return {"rows": rows, "count": len(rows), "copy": copy}


def organize_apply(rows: list[dict], copy: bool) -> dict:
    journal, failed = [], []
    for r in rows:
        src, dst = Path(r["path"]), Path(r["to"])
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if copy:
                shutil.copy2(src, dst)
            else:
                shutil.move(str(src), str(dst))
            journal.append({"from": str(src), "to": str(dst), "copied": copy})
        except Exception as exc:
            failed.append({"path": str(src), "error": str(exc)})
    if journal:
        _write_journal("organise", journal)
    return {"done": len(journal), "failed": failed}


# ---------------------------------------------------------------- empty folders
def empty_folders(paths: list[str]) -> list[str]:
    found = []
    for root in (Path(p) for p in paths):
        if not root.is_dir():
            continue
        for dirpath, dirs, files in os.walk(root, topdown=False):
            try:
                if not os.listdir(dirpath) and Path(dirpath) != root:
                    found.append(dirpath)
            except OSError:
                pass
    return found


def remove_folders(folders: list[str]) -> dict:
    n, failed = 0, []
    for f in sorted(folders, key=len, reverse=True):
        try:
            os.rmdir(f)
            n += 1
        except OSError as exc:
            failed.append({"path": f, "error": str(exc)})
    return {"removed": n, "failed": failed}
