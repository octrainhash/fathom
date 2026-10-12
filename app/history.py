"""Activity & Undo: a list of everything Fathom changed on disk, and a way to take each change back.

Every finished job that made, replaced or moved files is written here. For each one we remember
  * made:    files Fathom created (with size and time, so a file you edited later is never removed by undo)
  * removed: originals that went to the Recycle Bin, plus a private copy to put back (a hard link when
             possible, so it costs no extra space; otherwise a real copy)
  * moves:   renames and moves (bulk rename, organise, fix extension)
Undo puts originals back, moves renamed files back, and sends files Fathom made to the Recycle Bin.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from app.paths import data_root

_lock = threading.Lock()
_tl = threading.local()
KEEP_DAYS_DEFAULT = 30
KEEP_COPY_MAX = 2 * 1024 ** 3        # bytes: bigger files are only kept via a hard link (free) or not at all


def _dir() -> Path:
    d = data_root() / "history"
    (d / "copies").mkdir(parents=True, exist_ok=True)
    return d


def _file() -> Path:
    return _dir() / "history.jsonl"


def _settings_path() -> Path:
    return _dir() / "settings.json"


def settings() -> dict:
    try:
        s = json.loads(_settings_path().read_text(encoding="utf-8"))
    except Exception:
        s = {}
    return {"keep_days": int(s.get("keep_days", KEEP_DAYS_DEFAULT)), "enabled": bool(s.get("enabled", True))}


def set_settings(keep_days: int | None = None, enabled: bool | None = None) -> dict:
    s = settings()
    if keep_days is not None:
        s["keep_days"] = max(0, int(keep_days))
    if enabled is not None:
        s["enabled"] = bool(enabled)
    _settings_path().write_text(json.dumps(s), encoding="utf-8")
    return s


# ---------------------------------------------------------------- recording
def bind(job) -> None:
    """Called by the job runner on each worker thread so removals land on the right job."""
    _tl.job = job


def unbind() -> None:
    _tl.job = None


def _stat(p: Path) -> dict:
    try:
        st = p.stat()
        return {"size": st.st_size if p.is_file() else -1, "mtime": round(st.st_mtime, 3)}
    except OSError:
        return {"size": -1, "mtime": 0}


def keep_copy(path: Path) -> str:
    """Keeps a private copy of a file that is about to go to the Recycle Bin. Returns where it went ('' if not possible)."""
    if getattr(_tl, "quiet", False) or not settings()["enabled"]:
        return ""
    path = Path(path)
    if not path.is_file():
        return ""
    dest = _dir() / "copies" / uuid.uuid4().hex[:12] / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(path, dest)                     # same drive: instant and takes no extra room
    except OSError:
        try:
            if path.stat().st_size > KEEP_COPY_MAX:      # a very big file on another drive: copying it would take as long as the job itself; it stays in the Recycle Bin
                shutil.rmtree(dest.parent, ignore_errors=True)
                return ""
            shutil.copy2(path, dest)
        except OSError:
            shutil.rmtree(dest.parent, ignore_errors=True)
            return ""
    return str(dest)


def note_removed(path: Path, copy: str) -> None:
    rec = {"orig": str(path), "copy": copy}
    job = getattr(_tl, "job", None)
    if job is not None:
        with job.lock:
            job.data.setdefault("_removed", []).append(rec)
    else:
        add({"kind": "remove", "title": f"Moved {Path(path).name} to the Recycle Bin", "removed": [rec]})


def note_made(paths: list[Path], title: str, kind: str = "file") -> None:
    """For changes made outside the job system (Editor save, the assistant writing a file)."""
    job = getattr(_tl, "job", None)
    made = [{"path": str(p), **_stat(Path(p))} for p in paths]
    if job is not None:
        with job.lock:
            job.data.setdefault("_made", []).extend(made)
    else:
        add({"kind": kind, "title": title, "made": made})


def note_moves(kind: str, moves: list[dict], title: str = "") -> None:
    add({"kind": kind, "title": title or {"rename": "Renamed files", "organise": "Organised files", "fix-extension": "Fixed file extensions", "compat-fix": "Fixed names for another system"}.get(kind, "Moved files"), "moves": moves})


def add(entry: dict) -> dict | None:
    if not settings()["enabled"]:
        return None
    if not (entry.get("made") or entry.get("removed") or entry.get("moves")):
        return None
    entry = {"id": uuid.uuid4().hex[:12], "time": time.time(), "undone": False, **entry}
    with _lock:
        with _file().open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def from_job(job) -> None:
    """Writes one entry for a finished job."""
    try:
        made: list[dict] = []
        sources = set()
        for r in job.results:
            if r.get("src"):
                sources.add(r["src"])
            for o in r.get("outputs", []):
                p = Path(o["path"])
                if p.exists():
                    made.append({"path": str(p), **_stat(p)})
        made.extend(job.data.get("_made", []))
        removed = job.data.pop("_removed", [])
        removed_paths = {r["orig"] for r in removed}
        for m in made:                              # a file written where an original used to be is a replacement
            if m["path"] in removed_paths:
                m["replaces"] = True
        made = [m for m in made if m["path"] not in sources or m.get("replaces")]
        counts = {}
        for r in job.results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        add({"kind": job.kind, "title": job.title or job.kind, "job": job.id, "made": made, "removed": removed,
             "counts": counts, "secs": round((job.finished or time.time()) - job.started, 1)})
    except Exception:
        import logging
        logging.getLogger("fathom").exception("history: could not record job")


# ---------------------------------------------------------------- reading
def _read_all() -> list[dict]:
    try:
        lines = _file().read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out


def _write_all(entries: list[dict]) -> None:
    tmp = _file().with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    tmp.replace(_file())


def listing(limit: int = 300, query: str = "") -> dict:
    with _lock:
        entries = _read_all()
    q = query.lower().strip()
    rows = []
    for e in reversed(entries):
        if q and q not in json.dumps(e, ensure_ascii=False).lower():
            continue
        rows.append(summary(e))
        if len(rows) >= limit:
            break
    return {"items": rows, "total": len(entries), "settings": settings(), "copies_bytes": copies_bytes()}


def summary(e: dict) -> dict:
    made, removed, moves = e.get("made", []), e.get("removed", []), e.get("moves", [])
    bits = []
    new = [m for m in made if not m.get("replaces")]
    if new:
        bits.append(f"{len(new)} new file{'s' if len(new) != 1 else ''}")
    if removed:
        bits.append(f"{len(removed)} original{'s' if len(removed) != 1 else ''} replaced (kept for undo)" if any(r.get("copy") for r in removed)
                    else f"{len(removed)} sent to the Recycle Bin")
    if moves:
        bits.append(f"{len(moves)} renamed or moved")
    return {"id": e["id"], "time": e["time"], "kind": e.get("kind", ""), "title": e.get("title", ""), "undone": e.get("undone", False),
            "what": ", ".join(bits), "made": made[:200], "removed": removed[:200], "moves": moves[:200],
            "more": max(0, len(made) - 200) + max(0, len(removed) - 200) + max(0, len(moves) - 200),
            "can_undo": not e.get("undone") and bool(made or any(r.get("copy") for r in removed) or moves)}


# ---------------------------------------------------------------- undo
def _trash(p: Path) -> None:
    from app.recycle import to_recycle_bin
    _tl.quiet = True
    try:
        to_recycle_bin(p)
    finally:
        _tl.quiet = False


def _same(p: Path, rec: dict) -> bool:
    if rec.get("size", -1) == -1:              # folders: only check that it is still there
        return p.exists()
    s = _stat(p)
    return s["size"] == rec.get("size") and abs(s["mtime"] - rec.get("mtime", 0)) < 2


def undo(entry_id: str, force: bool = False) -> dict:
    with _lock:
        entries = _read_all()
    e = next((x for x in entries if x["id"] == entry_id), None)
    if e is None:
        raise ValueError("That change is no longer in the list.")
    if e.get("undone"):
        raise ValueError("That change was already undone.")
    done, kept, failed = [], [], []
    from app.convert.core import unique_path
    # 1. files Fathom made -> Recycle Bin (unless you changed them since)
    for m in e.get("made", []):
        p = Path(m["path"])
        if not p.exists():
            continue
        if not force and not _same(p, m):
            kept.append({"path": str(p), "why": "You changed this file after Fathom made it, so it was left alone."})
            continue
        try:
            _trash(p)
            done.append({"path": str(p), "what": "sent to the Recycle Bin"})
        except Exception as exc:
            failed.append({"path": str(p), "error": str(exc)})
    # 2. originals back where they were
    for r in e.get("removed", []):
        orig, copy = Path(r["orig"]), Path(r.get("copy") or "")
        if not r.get("copy") or not copy.exists():
            kept.append({"path": str(orig), "why": "No private copy was kept; it is in the Recycle Bin, where you can restore it."})
            continue
        try:
            target = orig
            if target.exists():
                target = unique_path(orig)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(copy, target)
            done.append({"path": str(target), "what": "original put back" + ("" if target == orig else " (beside a file with the same name)")})
        except Exception as exc:
            failed.append({"path": str(orig), "error": str(exc)})
    # 3. renames and moves backwards
    for mv in reversed(e.get("moves", [])):
        src, dst = Path(mv["to"]), Path(mv["from"])
        try:
            if mv.get("copied"):
                if src.exists():
                    _trash(src)
            else:
                if not src.exists():
                    raise FileNotFoundError("the renamed file is not there any more")
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(unique_path(dst) if dst.exists() else dst))
            done.append({"path": str(dst), "what": "moved back"})
        except Exception as exc:
            failed.append({"path": str(src), "error": str(exc)})
    with _lock:
        entries = _read_all()
        for x in entries:
            if x["id"] == entry_id:
                x["undone"] = True
                x["undone_at"] = time.time()
        _write_all(entries)
    if e.get("journal"):                        # keep the old one-step Undo button in step
        j = data_root() / "undo" / e["journal"]
        if j.exists():
            j.rename(j.with_suffix(".done"))
    return {"done": done, "kept": kept, "failed": failed, "title": e.get("title", "")}


def mark_journal_undone(name: str) -> None:
    with _lock:
        entries = _read_all()
        for x in entries:
            if x.get("journal") == name:
                x["undone"] = True
        _write_all(entries)


def last_undoable() -> dict | None:
    with _lock:
        entries = _read_all()
    for e in reversed(entries):
        s = summary(e)
        if s["can_undo"]:
            return s
    return None


# ---------------------------------------------------------------- housekeeping
def copies_bytes() -> int:
    total = 0
    for root, _d, files in os.walk(_dir() / "copies"):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def prune(keep_days: int | None = None, everything: bool = False) -> dict:
    """Drops entries (and their private copies) older than keep_days. keep_days=0 keeps forever."""
    days = settings()["keep_days"] if keep_days is None else keep_days
    if not everything and days <= 0:
        return {"removed": 0}
    cutoff = time.time() - days * 86400
    with _lock:
        entries = _read_all()
        keep, drop = [], []
        for e in entries:
            (drop if everything or e["time"] < cutoff else keep).append(e)
        for e in drop:
            for r in e.get("removed", []):
                if r.get("copy"):
                    shutil.rmtree(Path(r["copy"]).parent, ignore_errors=True)
        _write_all(keep)
    return {"removed": len(drop)}
