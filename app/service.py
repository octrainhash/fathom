# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""The app's actions as plain functions (main.py only wires them to web routes)."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

from app import extract
from app.jobs import JOBS, start_job
from app.paths import VERSION, models_dir, sessions_dir
from app.query import compile_query
from app.runtime import no_window_flags
from app.search import Options


class UserError(Exception):
    """A problem the user can fix (shown as-is in the UI)."""


def _has(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def create_search(query: str, paths: list[str], options: dict) -> dict:
    opts = Options.from_dict({**options, "query": query})
    if not opts.query:
        raise UserError("Type what to look for first.")
    if not paths:
        raise UserError("Add at least one file, folder or link to search.")
    if opts.mode == "text" or opts.media_text or opts.media_speech:
        try:
            compile_query(opts.query, opts.case_sensitive, opts.use_regex, opts.whole_word)
        except ValueError as exc:
            if opts.mode == "text":
                raise UserError(str(exc))
    if opts.refs:
        missing = [r for r in opts.refs if not Path(r).is_file()]
        if len(missing) == len(opts.refs):
            raise UserError("The reference picture could not be found. Add it again.")
    if (opts.mode == "object" or opts.media_object) and not opts.refs and not (_has("onnxruntime") and _has("tokenizers")):
        raise UserError("Object search is not installed. Run Fathom.bat again to finish setup.")
    if opts.refs and opts.ref_kind == "like" and not (_has("onnxruntime") and _has("tokenizers")):
        raise UserError("Picture matching is not installed. Run Fathom.bat again to finish setup, or choose “This exact item”.")
    job = start_job(opts, list(dict.fromkeys(paths)))
    return {"job": job.id}


def job_status(job_id: str, since: int = 0) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise UserError("That search no longer exists.")
    return job.snapshot(max(0, since))


def cancel_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is not None:
        job.cancel.set()
    return {"ok": True}


def capabilities() -> dict:
    from app.detect import models_ready

    return {
        "version": VERSION,
        "ocr": _has("rapidocr_onnxruntime"),
        "pdf": _has("pymupdf") or _has("fitz"),
        "objects": _has("onnxruntime") and _has("tokenizers") and _has("huggingface_hub"),
        "objects_model_ready": models_ready(),
        "faces": __import__("app.reference", fromlist=["x"]).faces_supported(),
        "faces_model_ready": __import__("app.reference", fromlist=["x"]).face_models_ready(),
        "links": True,
        "links_page": _has("yt_dlp"),
        "speech": _has("faster_whisper"),
        "heic": extract.HEIF,
    }


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def storage() -> dict:
    return {"results_bytes": dir_size(sessions_dir()), "models_bytes": dir_size(models_dir()), "path": str(sessions_dir().parent)}


def clear_results() -> dict:
    busy = {j.id for j in JOBS.values() if j.status in ("starting", "scanning", "searching")}
    freed = 0
    for child in sessions_dir().iterdir():
        if child.name in busy:
            continue
        freed += dir_size(child) if child.is_dir() else 0
        shutil.rmtree(child, ignore_errors=True)
        JOBS.pop(child.name, None)
    return {"freed_bytes": freed}


def reveal(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise UserError("That file is no longer there.")
    if os.name == "nt":
        subprocess.Popen(f'explorer /select,"{p}"', creationflags=no_window_flags())
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p.parent)])
    return {"ok": True}


def open_path(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        raise UserError("That file is no longer there.")
    if os.name == "nt":
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])
    return {"ok": True}
