"""Runs searches in the background: finds the files, searches them in parallel, streams results to the UI."""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from app.paths import data_root, sessions_dir
from app.search import Context, Options, search_file
from app.walk import discover

log = logging.getLogger("fathom")
MAX_STORED_ERRORS = 2000


class Job:
    def __init__(self, opts: Options, sources: list[str]):
        self.id = uuid.uuid4().hex
        self.opts, self.sources = opts, sources
        self.status = "starting"        # starting | scanning | searching | done | cancelled | failed
        self.message = ""
        self.files_found = self.files_total = self.files_done = 0
        self.current = ""
        self.results: list[dict] = []
        self.errors: list[dict] = []
        self.skipped: list[str] = []
        self.started = time.time()
        self.finished: float | None = None
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.out_dir = sessions_dir() / self.id
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def add_result(self, result: dict) -> None:
        with self.lock:
            result["seq"] = len(self.results)
            self.results.append(result)

    def add_error(self, file: str, message: str) -> None:
        with self.lock:
            if len(self.errors) < MAX_STORED_ERRORS:
                self.errors.append({"file": file, "error": message})

    def add_skip(self, note: str) -> None:
        with self.lock:
            self.skipped.append(note)

    def set_message(self, message: str) -> None:
        self.message = message

    def snapshot(self, since: int = 0) -> dict:
        with self.lock:
            return {
                "id": self.id, "status": self.status, "message": self.message,
                "files_found": self.files_found, "files_total": self.files_total, "files_done": self.files_done,
                "current": self.current, "elapsed": round((self.finished or time.time()) - self.started, 1),
                "results": self.results[since:], "next": len(self.results),
                "errors": self.errors[-300:], "error_count": len(self.errors),
                "skipped_count": len(self.skipped), "skipped": self.skipped[:30],
            }


JOBS: dict[str, Job] = {}


def _one(job: Job, ctx: Context, path: Path, display: str) -> None:
    job.current = display
    try:
        search_file(ctx, path, display)
    except Exception as exc:  # one broken file must never stop the whole search
        log.exception("search failed for %s", path)
        job.add_error(display, f"{type(exc).__name__}: {exc}")
    finally:
        with job.lock:
            job.files_done += 1


def _run(job: Job) -> None:
    ctx = None
    try:
        ctx = Context(job.opts, job.out_dir, f"/media/{job.id}", job.add_result, job.add_error, job.cancel, status=job.set_message)
        job.status = "scanning"
        if job.opts.mode == "object":
            from app.detect import model_paths, models_ready

            if not models_ready():
                job.message = "Downloading the object-search model (about 600 MB, one time only)…"
                model_paths(download=True)
                job.message = ""
        files: list[tuple[Path, str]] = []
        for item in discover(job.sources, job.opts.recursive, job.opts.skip_junk, job.opts.include_cloud, [data_root()], job.add_skip, job.cancel.is_set):
            files.append(item)
            job.files_found = len(files)
        job.files_total = len(files)
        job.status = "searching"
        workers = max(2, min(4, (os.cpu_count() or 4) // 2))
        todo = iter(files)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fathom") as pool:
            pending: set = set()

            def submit() -> bool:
                try:
                    path, display = next(todo)
                except StopIteration:
                    return False
                pending.add(pool.submit(_one, job, ctx, path, display))
                return True

            for _ in range(workers * 2):
                if not submit():
                    break
            while pending:
                done, _ = wait(pending, timeout=0.4, return_when=FIRST_COMPLETED)
                pending -= done
                if job.cancel.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                for _ in done:
                    submit()
        job.status = "cancelled" if job.cancel.is_set() else "done"
        job.message = ""
    except Exception as exc:
        log.exception("job failed")
        job.status = "failed"
        job.message = str(exc)
    finally:
        job.current = ""
        job.finished = time.time()
        if ctx is not None:
            shutil.rmtree(ctx.tmp_dir, ignore_errors=True)


def start_job(opts: Options, sources: list[str]) -> Job:
    job = Job(opts, sources)
    JOBS[job.id] = job
    threading.Thread(target=_run, args=(job,), daemon=True, name="fathom-job").start()
    return job
