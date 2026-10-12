"""Background jobs for everything that is not a search: converting, resizing, and the file tools.

A job is a list of tasks. Tasks run in a small thread pool (heavy ones - video, Office, OCR - one at a time), progress and results
stream to the window through /api/ops/{id}, and one bad file never stops the others."""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.convert.core import Cancelled, ConvertError, Ctx, file_bytes, unique_path
from app.paths import temp_dir
from app import history

log = logging.getLogger("fathom")
MAX_RESULTS = 200000
HEAVY = threading.Semaphore(1)


def path_bytes(p: Path) -> int:
    if p.is_dir():
        total = 0
        for root, _d, files in os.walk(p):
            for f in files:
                total += file_bytes(Path(root) / f)
        return total
    return file_bytes(p)


@dataclass
class Output:
    paths: list[Path] = field(default_factory=list)
    note: str = ""
    extra: dict = field(default_factory=dict)
    skipped: bool = False            # nothing to do for this file (not an error)


@dataclass
class Task:
    name: str                         # shown in the list
    fn: Callable[["Ctx", "Task"], Output]
    src: Path | None = None
    heavy: bool = False
    rel: Path = Path(".")             # where it sat inside an added folder (kept when the output goes to another folder)


class OpJob:
    def __init__(self, kind: str, title: str = ""):
        self.id = uuid.uuid4().hex
        self.kind, self.title = kind, title
        self.status = "starting"      # starting | running | done | cancelled | failed
        self.message = ""
        self.total = 0
        self.done = 0
        self.frac: dict[int, float] = {}
        self.results: list[dict] = []
        self.data: dict[str, Any] = {}
        self.started = time.time()
        self.finished: float | None = None
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.tmp = temp_dir() / self.id
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.ctxs: set[Ctx] = set()

    def progress(self) -> float:
        with self.lock:
            if not self.total:
                return 0.0
            return min(1.0, (self.done + sum(self.frac.values())) / self.total)

    def add(self, rec: dict) -> None:
        with self.lock:
            if len(self.results) < MAX_RESULTS:
                rec["seq"] = len(self.results)
                self.results.append(rec)

    def snapshot(self, since: int = 0) -> dict:
        with self.lock:
            counts = {"done": 0, "error": 0, "skipped": 0, "cancelled": 0}
            bytes_in = bytes_out = 0
            for r in self.results:
                counts[r["status"]] = counts.get(r["status"], 0) + 1
                bytes_in += r.get("bytes_in", 0)
                bytes_out += r.get("bytes_out", 0)
            return {"id": self.id, "kind": self.kind, "title": self.title, "status": self.status, "message": self.message,
                    "total": self.total, "done": self.done, "progress": 0 if not self.total else min(1.0, (self.done + sum(self.frac.values())) / self.total),
                    "elapsed": round((self.finished or time.time()) - self.started, 1), "counts": counts,
                    "bytes_in": bytes_in, "bytes_out": bytes_out, "results": self.results[since:], "next": len(self.results), "data": self.data}


OPJOBS: dict[str, OpJob] = {}


def _outputs_info(paths: list[Path]) -> list[dict]:
    return [{"path": str(p), "name": p.name, "bytes": path_bytes(p), "dir": p.is_dir()} for p in paths]


def _run_task(job: OpJob, idx: int, task: Task) -> None:
    t0 = time.time()
    rec: dict = {"name": task.name, "src": str(task.src) if task.src else "", "status": "done", "outputs": [], "bytes_in": path_bytes(task.src) if task.src and task.src.exists() else 0,
                 "bytes_out": 0, "note": "", "error": "", "extra": {}}
    ctx = Ctx(job.tmp / uuid.uuid4().hex[:8], job.cancel, lambda f: job.frac.__setitem__(idx, f), lambda s: setattr(job, "message", s))
    ctx.job = job  # type: ignore[attr-defined]
    job.ctxs.add(ctx)
    history.bind(job)
    try:
        if job.cancel.is_set():
            raise Cancelled()
        if task.heavy:
            while not HEAVY.acquire(timeout=0.3):
                ctx.check()
            try:
                out = task.fn(ctx, task)
            finally:
                HEAVY.release()
        else:
            out = task.fn(ctx, task)
        rec["note"], rec["extra"] = out.note, out.extra
        if out.skipped:
            rec["status"] = "skipped"
        rec["outputs"] = _outputs_info(out.paths)
        rec["bytes_out"] = sum(o["bytes"] for o in rec["outputs"])
        if not out.skipped and "proof" not in rec["extra"] and out.paths and task.src is not None and getattr(job, "proof_count", 0) < 40:
            try:                                    # before/after pictures for simple changes (rotate, resize, details ...); the first 40 files of a big batch
                from app import autoproof
                pr = autoproof.for_task(job.kind, task.src, list(out.paths))
                if pr:
                    job.proof_count = getattr(job, "proof_count", 0) + 1
                    rec["extra"] = {**rec["extra"], "proof": pr}
            except Exception:
                pass
    except Cancelled:
        rec["status"] = "cancelled"
    except ConvertError as exc:
        rec["status"], rec["error"] = "error", str(exc)
    except PermissionError as exc:
        rec["status"], rec["error"] = "error", f"Windows did not allow this ({exc.strerror or exc}). Is the file open in another program, or the folder read-only?"
    except OSError as exc:
        rec["status"], rec["error"] = "error", (f"The disk is full ({exc})" if getattr(exc, "errno", 0) == 28 else f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        log.exception("task failed: %s", task.name)
        rec["status"], rec["error"] = "error", f"{type(exc).__name__}: {exc}"
    finally:
        history.unbind()
        ctx.kill_all()
        shutil.rmtree(ctx.tmp, ignore_errors=True)
        job.ctxs.discard(ctx)
        rec["secs"] = round(time.time() - t0, 1)
        job.frac.pop(idx, None)
        with job.lock:
            job.done += 1
        job.add(rec)


def _run(job: OpJob, tasks: list[Task], workers: int, after: Callable[[OpJob], None] | None) -> None:
    try:
        job.total = len(tasks)
        job.status = "running"
        with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="op") as pool:
            futures = [pool.submit(_run_task, job, i, t) for i, t in enumerate(tasks)]
            for f in futures:
                f.result()
        if after and not job.cancel.is_set():
            history.bind(job)
            try:
                after(job)
            finally:
                history.unbind()
        job.status = "cancelled" if job.cancel.is_set() else "done"
        job.message = ""
    except Exception as exc:
        log.exception("job failed")
        job.status, job.message = "failed", str(exc)
    finally:
        job.finished = time.time()
        shutil.rmtree(job.tmp, ignore_errors=True)
        history.from_job(job)


def start(kind: str, title: str, tasks: list[Task], workers: int | None = None, after: Callable[[OpJob], None] | None = None) -> OpJob:
    job = OpJob(kind, title)
    OPJOBS[job.id] = job
    n = workers if workers is not None else max(1, min(4, (os.cpu_count() or 4) // 2))
    threading.Thread(target=_run, args=(job, tasks, n, after), daemon=True, name="op-job").start()
    return job


def cancel(job_id: str) -> None:
    job = OPJOBS.get(job_id)
    if job:
        job.cancel.set()
        for c in list(job.ctxs):
            c.kill_all()


# ---------------------------------------------------------------- where the results go
@dataclass
class OutputPolicy:
    mode: str = "beside"              # beside | folder
    dir: str = ""
    keep_structure: bool = True

    @staticmethod
    def from_dict(d: dict | None) -> "OutputPolicy":
        d = d or {}
        mode = "folder" if d.get("mode") == "folder" and str(d.get("dir", "")).strip() else "beside"
        return OutputPolicy(mode, str(d.get("dir", "")).strip(), bool(d.get("keep_structure", True)))

    def target_dir(self, src: Path, rel: Path) -> Path:
        if self.mode == "folder":
            base = Path(self.dir)
            return base / rel if self.keep_structure and str(rel) not in ("", ".") else base
        return src.parent

    def place(self, outs: list[Path], src: Path, rel: Path, group_name: str = "") -> list[Path]:
        """Moves finished files from the scratch folder to their final home, never overwriting anything."""
        base = self.target_dir(src, rel)
        base.mkdir(parents=True, exist_ok=True)
        if len(outs) > 1 and group_name:
            base = unique_path(base / group_name)
            base.mkdir(parents=True, exist_ok=True)
        placed: list[Path] = []
        for o in outs:
            final = unique_path(base / o.name)
            shutil.move(str(o), str(final))
            placed.append(final)
        return placed
