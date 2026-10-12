"""System junk purger: temp files, crash reports, thumbnail caches and leftovers of programs that are no longer installed.

Scanning only measures. Clearing sends things to the Recycle Bin by default (or deletes for good if asked). Locked files are skipped."""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from app import ops, recycle
from app.convert.core import Ctx
from app.ops import Output, Task
from app.service import UserError

WIN, MAC = sys.platform == "win32", sys.platform == "darwin"
HOME = Path.home()


def _env(n: str, d: str = "") -> Path:
    return Path(os.environ.get(n) or d)


def categories() -> dict[str, dict]:
    """id -> {label, tip, roots:[Path], globs, safe, min_age_days}. 'safe' ones are pre-ticked."""
    c: dict[str, dict] = {}
    if WIN:
        la, ra, win = _env("LOCALAPPDATA"), _env("APPDATA"), _env("SystemRoot", r"C:\Windows")
        c["temp"] = dict(label="Temporary files", tip="Scratch files programs left behind. Files used in the last 2 days are kept.", roots=[Path(os.environ.get("TEMP", la / "Temp")), win / "Temp"], safe=True, age=2)
        c["thumbs"] = dict(label="Picture and icon caches", tip="Windows rebuilds these by itself the next time you open a folder.", roots=[la / "Microsoft/Windows/Explorer"], pat=("thumbcache_*.db", "iconcache_*.db"), safe=True)
        c["crash"] = dict(label="Crash reports and memory dumps", tip="Error reports and memory dumps from programs that crashed. Only useful to developers.", roots=[la / "CrashDumps", win / "Minidump", _env("ProgramData") / "Microsoft/Windows/WER/ReportArchive", _env("ProgramData") / "Microsoft/Windows/WER/ReportQueue", la / "Microsoft/Windows/WER"], safe=True)
        c["logs"] = dict(label="Old log files", tip="Windows and setup logs older than 30 days.", roots=[win / "Logs", win / "Panther", win / "Temp"], pat=("*.log", "*.etl", "*.old"), safe=True, age=30)
        c["browser"] = dict(label="Browser caches", tip="Saved web pages and pictures. Sites load a bit slower once, then it fills again. Your passwords and history are not touched.", roots=[la / "Google/Chrome/User Data/Default/Cache", la / "Google/Chrome/User Data/Default/Code Cache", la / "Microsoft/Edge/User Data/Default/Cache", la / "Microsoft/Edge/User Data/Default/Code Cache", ra / "Mozilla/Firefox/Profiles"], safe=False, only="cache")
    elif MAC:
        L = HOME / "Library"
        c["temp"] = dict(label="Temporary files", tip="Scratch files programs left behind.", roots=[Path("/private/var/tmp"), Path(os.environ.get("TMPDIR", "/tmp"))], safe=True, age=3)
        c["caches"] = dict(label="App caches", tip="Saved data apps rebuild when needed.", roots=[L / "Caches"], safe=True, age=7)
        c["thumbs"] = dict(label="Preview and thumbnail caches", tip="macOS rebuilds these by itself.", roots=[L / "Caches/com.apple.QuickLook.thumbnailcache", L / "Application Support/Quick Look"], safe=True)
        c["crash"] = dict(label="Crash reports", tip="Reports of programs that crashed.", roots=[L / "Logs/DiagnosticReports", L / "Logs/CrashReporter"], safe=True)
        c["logs"] = dict(label="Old log files", tip="App logs older than 30 days.", roots=[L / "Logs"], safe=True, age=30)
    else:
        cache = _env("XDG_CACHE_HOME", str(HOME / ".cache"))
        c["temp"] = dict(label="Temporary files", tip="Scratch files programs left behind. Files used in the last 3 days are kept.", roots=[Path("/var/tmp"), Path("/tmp")], safe=True, age=3, own=True)
        c["thumbs"] = dict(label="Thumbnail cache", tip="Small preview pictures your file manager makes again as needed.", roots=[cache / "thumbnails", HOME / ".thumbnails"], safe=True)
        c["caches"] = dict(label="App caches", tip="Saved data apps rebuild when needed.", roots=[cache], safe=False, age=14)
        c["crash"] = dict(label="Crash reports", tip="Reports of programs that crashed.", roots=[Path("/var/crash"), HOME / ".local/share/apport", HOME / ".local/share/abrt"], safe=True)
        c["logs"] = dict(label="Old log files", tip="Your own app logs older than 30 days.", roots=[HOME / ".local/state"], pat=("*.log", "*.log.*"), safe=True, age=30)
    c["leftovers"] = dict(label="Leftovers of uninstalled programs", tip="Settings folders of programs that no longer seem to be installed, not touched for 90 days. Look before you clear: not every folder here is certain.", roots=[], safe=False, special="leftovers")
    return c


def installed_names() -> set[str]:
    out: set[str] = set()
    if WIN:
        try:
            import winreg
            for hive, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"), (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"), (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        for i in range(winreg.QueryInfoKey(k)[0]):
                            try:
                                with winreg.OpenKey(k, winreg.EnumKey(k, i)) as s:
                                    for val in ("DisplayName", "Publisher"):
                                        try:
                                            out.add(str(winreg.QueryValueEx(s, val)[0]).lower())
                                        except OSError:
                                            pass
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
    elif MAC:
        for d in (Path("/Applications"), HOME / "Applications"):
            if d.is_dir():
                out |= {p.stem.lower() for p in d.glob("*.app")}
    else:
        for d in (Path("/usr/share/applications"), HOME / ".local/share/applications", Path("/opt")):
            if d.is_dir():
                out |= {p.stem.lower() for p in d.iterdir()}
        out |= {p.name.lower() for p in Path("/usr/bin").glob("*")} if Path("/usr/bin").is_dir() else set()
    return out


PROTECTED = {"microsoft", "windows", "packages", "temp", "programs", "google", "mozilla", "apple", "nvidia", "intel", "amd", "adobe", "comms", "connecteddevicesplatform", "d3dscache", "publishers", "virtualstore", "history", "fathom", "fathom",
             "systemd", "dconf", "gtk-3.0", "gtk-4.0", "fontconfig", "mesa_shader_cache", "pip", "npm", "gnome", "kde", "mozilla", "pulse", "ibus", "icons", "themes", "applications", "recently-used.xbel"}


def _size(p: Path, older_than: float, pat: tuple | None, only: str | None) -> tuple[int, int, list[str]]:
    total = n = 0
    items: list[str] = []
    if p.is_file():
        walker = [(str(p.parent), [], [p.name])]
    else:
        walker = os.walk(p, onerror=lambda e: None, followlinks=False)
    for cur, _d, files in walker:
        if only and only not in cur.lower() and only not in str(p).lower():
            continue
        for f in files:
            fp = Path(cur) / f
            try:
                st = fp.lstat()
            except OSError:
                continue
            if pat and not any(fp.match(x) for x in pat):
                continue
            if st.st_mtime > older_than or st.st_atime > older_than and False:
                continue
            total += st.st_size; n += 1
            if len(items) < 3000:
                items.append(str(fp))
    return total, n, items


def scan_start() -> dict:
    cats = categories()
    names = installed_names()

    def make(cid, spec):
        def fn(ctx: Ctx, task: Task) -> Output:
            res = {"id": cid, "label": spec["label"], "tip": spec["tip"], "safe": spec["safe"], "bytes": 0, "files": 0, "items": [], "folders": []}
            cutoff = time.time() - spec.get("age", 0) * 86400
            if spec.get("special") == "leftovers":
                roots = ([_env("APPDATA"), _env("LOCALAPPDATA"), _env("ProgramData")] if WIN else [HOME / "Library/Application Support", HOME / "Library/Preferences"] if MAC else [HOME / ".config", HOME / ".local/share"])
                lim = time.time() - 90 * 86400
                for r in roots:
                    if not r.is_dir():
                        continue
                    for d in r.iterdir():
                        ctx.check()
                        nm = d.name.lower()
                        if not d.is_dir() or nm in PROTECTED or nm.startswith((".", "microsoft", "windows")) or any(nm in i or (len(nm) > 3 and i in nm) for i in names if len(i) > 2):
                            continue
                        try:
                            if d.stat().st_mtime > lim:
                                continue
                        except OSError:
                            continue
                        s, n, items = _size(d, time.time(), None, None)
                        if n:
                            res["bytes"] += s; res["files"] += n; res["folders"].append({"path": str(d), "bytes": s, "files": n})
            else:
                for r in spec["roots"]:
                    if not r.exists():
                        continue
                    s, n, items = _size(r, cutoff, spec.get("pat"), spec.get("only"))
                    res["bytes"] += s; res["files"] += n; res["items"].extend(items[:3000 - len(res["items"])]) if len(res["items"]) < 3000 else None
            ctx.job.data.setdefault("cats", {})[cid] = res  # type: ignore[attr-defined]
            return Output([], f"{res['files']} files", extra={"bytes": res["bytes"], "files": res["files"]})
        return fn

    tasks = [Task(s["label"], make(i, s)) for i, s in cats.items()]
    return {"job": ops.start("junk", "Looking for junk", tasks, workers=4).id}


def clear(job_id: str, cat_ids: list[str], mode: str = "recycle", folders: list[str] | None = None) -> dict:
    job = ops.OPJOBS.get(job_id)
    if not job or "cats" not in job.data:
        raise UserError("Scan first, then choose what to clear.")
    done = freed = 0
    failed: list[str] = []
    allowed = {f["path"] for c in job.data["cats"].values() for f in c.get("folders", [])}

    def kill(p: Path, size: int) -> bool:
        nonlocal done, freed
        try:
            if mode == "delete":
                shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
            else:
                recycle.to_recycle_bin(p, keep=False)
            done += 1; freed += size
            return True
        except Exception:
            failed.append(str(p)); return False

    for cid in cat_ids:
        c = job.data["cats"].get(cid)
        if not c:
            continue
        if cid == "leftovers":
            for f in c["folders"]:
                if (not folders or f["path"] in folders) and f["path"] in allowed:
                    kill(Path(f["path"]), f["bytes"])
        else:
            for it in c["items"]:
                p = Path(it)
                try:
                    sz = p.lstat().st_size
                except OSError:
                    continue
                kill(p, sz)
    return {"cleared": done, "freed": freed, "failed": failed[:50], "failed_count": len(failed), "mode": mode}
