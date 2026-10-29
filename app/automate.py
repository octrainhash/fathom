# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Automation: workflows (a chain of steps run one after another) and watch folders (run a step or a workflow on every new file)."""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from app import ops, opsvc, toolbox
from app.convert import formats
from app.paths import data_root
from app.service import UserError

log = logging.getLogger("fathom")


def _convert(paths, rec, o, out):
    to = (o.get("to") or "").strip().lower().lstrip(".")
    if not to:
        raise UserError("Choose what to convert to.")
    from app.convert import engines
    mapping = {}
    from app.opsvc import expand_sources
    for src, _rel in expand_sources(paths, rec):
        s = formats.detect(src)
        if s not in mapping and to in {x["id"] for x in engines.targets_for(s)}:
            mapping[s] = to
    if not mapping:
        raise UserError(f"None of these files can be turned into {to.upper()}.")
    return opsvc.convert_start(paths, rec, mapping, {k: v for k, v in o.items() if k != "to"}, out)


ACTIONS = {
    "convert": ("Convert to another type", _convert),
    "ocrpdf": ("Make PDF searchable (OCR)", lambda p, r, o, out: toolbox.ocrpdf_start(p, r, o, out)),
    "watermark": ("Remove PDF watermark", lambda p, r, o, out: toolbox.wm_start(p, r, o, out)),
    "nobg": ("Remove picture background", lambda p, r, o, out: toolbox.bg_start(p, r, o, out)),
    "translate": ("Translate subtitles", lambda p, r, o, out: toolbox.translate_start(p, r, o, out)),
    "subs": ("Fix subtitles", lambda p, r, o, out: toolbox.subs_start(p, r, o, out)),
}


def actions() -> list[dict]:
    return [{"id": k, "label": v[0]} for k, v in ACTIONS.items()]


def _wait(job_id: str, stop: threading.Event | None = None) -> ops.OpJob:
    job = ops.OPJOBS[job_id]
    while job.status in ("starting", "running"):
        if stop is not None and stop.is_set():
            ops.cancel(job_id)
        time.sleep(0.4)
    return job


def run_flow_blocking(steps: list[dict], paths: list[str], output: dict, stop: threading.Event | None = None, on_job=None) -> dict:
    if not steps:
        raise UserError("Add at least one step.")
    for s in steps:
        if s.get("action") not in ACTIONS:
            raise UserError("Unknown step: " + str(s.get("action")))
    work = data_root() / "flows" / uuid.uuid4().hex[:8]
    work.mkdir(parents=True, exist_ok=True)
    cur = [str(p) for p in paths]
    first = Path(cur[0]) if cur else None
    notes = []
    try:
        for i, st in enumerate(steps):
            last = i == len(steps) - 1
            if last:
                out = output if (output or {}).get("mode") == "folder" else {"mode": "folder", "dir": str((first.parent if first and first.is_file() else first) or work)}
            else:
                out = {"mode": "folder", "dir": str(work / f"step{i + 1}")}
            r = ACTIONS[st["action"]][1](cur, True, st.get("options") or {}, out)
            if on_job:
                on_job(r["job"], i, len(steps))
            job = _wait(r["job"], stop)
            produced = [o["path"] for rec in job.results if rec["status"] == "done" for o in rec["outputs"]]
            errs = [rec["error"] for rec in job.results if rec["status"] == "error"]
            notes.append(f"Step {i + 1} ({ACTIONS[st['action']][0]}): {len(produced)} made" + (f", {len(errs)} failed" if errs else ""))
            if not produced:
                raise UserError("Step %d produced nothing. %s" % (i + 1, errs[0] if errs else ""))
            cur = produced
        return {"outputs": cur, "notes": notes}
    finally:
        shutil.rmtree(work, ignore_errors=True)


FLOWS: dict[str, dict] = {}


def flow_start(steps, paths, output) -> dict:
    fid = uuid.uuid4().hex
    st = FLOWS[fid] = {"id": fid, "status": "running", "step": 0, "of": len(steps), "job": "", "notes": [], "outputs": [], "error": ""}
    stop = threading.Event()
    st["stop"] = stop

    def run():
        try:
            def onjob(j, i, n):
                st["job"], st["step"] = j, i + 1
            res = run_flow_blocking(steps, paths, output, stop, onjob)
            st.update(status="done", outputs=res["outputs"], notes=res["notes"])
        except Exception as e:
            st.update(status="failed", error=str(e))
    threading.Thread(target=run, daemon=True, name="flow").start()
    return {"flow": fid}


def flow_status(fid: str) -> dict:
    st = FLOWS.get(fid)
    if not st:
        raise UserError("That workflow run is not known any more.")
    return {k: v for k, v in st.items() if k != "stop"}


def flow_cancel(fid: str):
    st = FLOWS.get(fid)
    if st:
        st["stop"].set()


# ---------------------------------------------------------------- watch folders
_LOCK = threading.Lock()
LOG: list[dict] = []
_started = False


def _cfg_path() -> Path:
    return data_root() / "watch.json"


def _state_path() -> Path:
    return data_root() / "watch_seen.json"


def get_rules() -> list[dict]:
    try:
        v = json.loads(_cfg_path().read_text(encoding="utf-8"))
        return v if isinstance(v, list) else []
    except Exception:
        return []


def set_rules(rules: list[dict]) -> list[dict]:
    clean = []
    for r in rules[:30]:
        folder = str(r.get("folder") or "").strip()
        if not folder:
            continue
        clean.append({"id": r.get("id") or uuid.uuid4().hex[:8], "name": str(r.get("name") or Path(folder).name)[:60], "folder": folder, "enabled": bool(r.get("enabled", True)),
                      "exts": str(r.get("exts") or "").lower(), "subfolders": bool(r.get("subfolders")), "existing": bool(r.get("existing")),
                      "steps": [s for s in (r.get("steps") or []) if s.get("action") in ACTIONS][:8], "outdir": str(r.get("outdir") or "").strip()})
    _cfg_path().parent.mkdir(parents=True, exist_ok=True)
    tmp = _cfg_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=1), encoding="utf-8")
    os.replace(tmp, _cfg_path())
    _prime(clean)
    ensure_running()
    return clean


def _seen() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_seen(s: dict):
    tmp = _state_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(s), encoding="utf-8")
    os.replace(tmp, _state_path())


def _list(rule: dict):
    root = Path(rule["folder"])
    if not root.is_dir():
        return
    exts = {e.strip().lstrip(".") for e in rule.get("exts", "").replace(";", ",").split(",") if e.strip()}
    outdir = rule.get("outdir") or str(root / "Fathom output")
    it = root.rglob("*") if rule.get("subfolders") else root.iterdir()
    for p in it:
        try:
            if not p.is_file() or p.name.startswith((".", "~$")) or p.suffix.lower() in (".tmp", ".part", ".crdownload", ".download"):
                continue
            if str(p).startswith(outdir):
                continue
            if exts and p.suffix.lower().lstrip(".") not in exts:
                continue
            yield p
        except OSError:
            continue


def _prime(rules):
    """New rules ignore the files already in the folder, unless the rule says to include them."""
    seen = _seen()
    changed = False
    for r in rules:
        if r.get("existing"):
            continue
        for p in _list(r):
            k = f"{r['id']}|{p}"
            if k not in seen:
                try:
                    st = p.stat(); seen[k] = [st.st_mtime, st.st_size]; changed = True
                except OSError:
                    pass
    if changed:
        _save_seen(seen)


_pending: dict = {}


def _tick():
    rules = [r for r in get_rules() if r.get("enabled") and r.get("steps")]
    if not rules:
        return
    seen = _seen()
    changed = False
    for r in rules:
        for p in _list(r):
            k = f"{r['id']}|{p}"
            try:
                st = p.stat()
            except OSError:
                continue
            sig = [st.st_mtime, st.st_size]
            if seen.get(k) == sig:
                continue
            prev = _pending.get(k)
            if prev != sig or time.time() - st.st_mtime < 3:      # still being written
                _pending[k] = sig
                continue
            _pending.pop(k, None)
            seen[k] = sig; changed = True
            out = {"mode": "folder", "dir": r.get("outdir") or str(Path(r["folder"]) / "Fathom output")}
            ent = {"time": time.time(), "rule": r["name"], "file": str(p), "status": "working", "note": ""}
            LOG.insert(0, ent); del LOG[100:]

            def go(ent=ent, r=r, p=p, out=out):
                try:
                    res = run_flow_blocking(r["steps"], [str(p)], out)
                    ent.update(status="done", note="; ".join(res["notes"]), outputs=res["outputs"])
                except Exception as e:
                    ent.update(status="failed", note=str(e))
            threading.Thread(target=go, daemon=True, name="watch-run").start()
    if changed:
        _save_seen(seen)


def _loop():
    while True:
        try:
            _tick()
        except Exception:
            log.exception("watch tick")
        time.sleep(4)


def ensure_running():
    global _started
    with _LOCK:
        if not _started:
            _started = True
            threading.Thread(target=_loop, daemon=True, name="watch").start()


def get_log() -> list[dict]:
    return LOG[:60]
