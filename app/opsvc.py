"""Conversion, resizing and file-tool actions as plain functions (main.py wires them to web routes)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from app import ops
from app.convert import engines, formats
from app.convert.core import ConvertError, Opts, ffmpeg_exe, safe_stem
from app.convert.shrink import SizeSpec, resize_file
from app.ops import Output, OutputPolicy, Task
from app.service import UserError
from app.walk import discover


def expand_sources(paths: list[str], recursive: bool = True, skip_junk: bool = True) -> list[tuple[Path, Path]]:
    """[(file, folder it sat in inside an added folder)] for every file under the added files and folders."""
    out: list[tuple[Path, Path]] = []
    from app.paths import data_root

    for path, display in discover(list(dict.fromkeys(paths)), recursive, skip_junk, True, [data_root()]):
        rel = Path(display).parent
        out.append((path, rel))
    return out


# ---------------------------------------------------------------- convert
def convert_plan(paths: list[str], recursive: bool = True) -> dict:
    if not paths:
        raise UserError("Add at least one file or folder first.")
    groups: dict[str, dict] = {}
    total_bytes = 0
    for p, _rel in expand_sources(paths, recursive):
        fmt = formats.detect(p)
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        total_bytes += size
        g = groups.setdefault(fmt, {"fmt": fmt, "label": formats.label(fmt), "category": formats.category(fmt), "count": 0, "bytes": 0, "names": [], "exts": []})
        g["count"] += 1
        g["bytes"] += size
        if len(g["names"]) < 3:
            g["names"].append(p.name)
        e = formats.ext_of(p)
        if e and e not in g["exts"] and len(g["exts"]) < 8:
            g["exts"].append(e)
    out = []
    for fmt, g in sorted(groups.items(), key=lambda kv: (-kv[1]["count"], kv[0])):
        if fmt == "txt":
            g["label"] = "Text, code and settings files"
        elif fmt == "bin":
            g["label"] = "Other files"
        g["targets"] = engines.targets_for(fmt)
        out.append(g)
    return {"groups": out, "files": sum(g["count"] for g in out), "bytes": total_bytes}


def convert_start(paths: list[str], recursive: bool, mapping: dict, options: dict, output: dict) -> dict:
    mapping = {k: v for k, v in (mapping or {}).items() if v}
    if not mapping:
        raise UserError("Choose what to convert to (on the right of each file type) first.")
    o = Opts.from_dict(options)
    policy = OutputPolicy.from_dict(output)
    tasks: list[Task] = []
    skipped = 0
    for src, rel in expand_sources(paths, recursive):
        s = formats.detect(src)
        t = mapping.get(s)
        if not t:
            skipped += 1
            continue
        if t not in {x["id"] for x in engines.targets_for(s)}:
            skipped += 1
            continue

        def fn(ctx, task, s=s, t=t, src=src, rel=rel):
            outs, note = engines.convert_file(src, s, t, o, ctx)
            placed = policy.place(outs, src, rel, group_name=safe_stem(src))
            return Output(placed, note)

        tasks.append(Task(name=src.name, fn=fn, src=src, heavy=engines.route_heavy(s, t), rel=rel))
    if not tasks:
        raise UserError("None of the added files match the conversions you chose.")
    job = ops.start("convert", "Converting", tasks)
    job.data["skipped"] = skipped
    return {"job": job.id, "count": len(tasks)}


# ---------------------------------------------------------------- make smaller / bigger
def size_start(paths: list[str], recursive: bool, spec: dict, output: dict, replace: bool = False) -> dict:
    sp = SizeSpec.from_dict(spec)
    if sp.mode == "bigger" and not sp.target_bytes and False:
        raise UserError("Enter the size you want.")
    policy = OutputPolicy.from_dict(output)
    suffix = " (smaller)" if sp.mode == "smaller" else " (bigger)"
    tasks: list[Task] = []
    for src, rel in expand_sources(paths, recursive):
        fmt = formats.detect(src)

        def fn(ctx, task, src=src, rel=rel, fmt=fmt):
            res = resize_file(src, fmt, sp, ctx)
            if res.path is None:
                return Output([], res.note, skipped=True)
            new = res.path
            if not new.name.lower().endswith(".zip") or src.suffix.lower() == ".zip":
                renamed = new.with_name(f"{src.stem}{suffix}{src.suffix}") if not replace else new.with_name(src.name)
                if renamed != new:
                    new.replace(renamed)
                    new = renamed
            if replace and policy.mode == "beside":
                from app.recycle import to_recycle_bin

                final = src.parent / new.name
                to_recycle_bin(src)
                shutil.move(str(new), str(final))
                return Output([final], res.note + " The original is in the Recycle Bin.")
            placed = policy.place([new], src, rel)
            return Output(placed, res.note, extra={"before": ops.file_bytes(src), "after": ops.file_bytes(placed[0])})

        fmt_heavy = formats.category(fmt) in ("video", "audio") or fmt in ("pdf",)
        tasks.append(Task(name=src.name, fn=fn, src=src, heavy=fmt_heavy, rel=rel))
    if not tasks:
        raise UserError("There are no files to resize.")
    job = ops.start("size", "Making files " + sp.mode, tasks)
    return {"job": job.id, "count": len(tasks)}


# ---------------------------------------------------------------- job status
def op_status(job_id: str, since: int = 0) -> dict:
    job = ops.OPJOBS.get(job_id)
    if job is None:
        raise UserError("That job no longer exists.")
    return job.snapshot(max(0, since))


def op_cancel(job_id: str) -> dict:
    ops.cancel(job_id)
    return {"ok": True}


def formats_info() -> dict:
    return {"engines": engines.engine_report(), "matrix": engines.format_matrix()}


def source_kinds(paths: list[str], recursive: bool = True, skip_junk: bool = True, limit: int = 40000) -> dict:
    """What kinds of files are in the added files and folders (counted by category), so screens can show only the options that matter."""
    counts: dict[str, int] = {}
    total = 0
    for p, _rel in expand_sources(paths, recursive, skip_junk):
        total += 1
        cat = formats.category(formats.detect(p)) if total <= 4000 else formats.category(formats.known_fmt(formats.ext_of(p)) or "bin")
        counts[cat] = counts.get(cat, 0) + 1
        if total >= limit:
            break
    return {"counts": counts, "total": total, "truncated": total >= limit}
