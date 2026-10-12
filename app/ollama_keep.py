"""Keeps Ollama (the free local AI) available while Fathom is open, so the Assistant never says "Could not reach Ollama".

 * ensure_running() - if Ollama is not answering, start it quietly: the Ollama tray program with --hide (no window opens; only its
                      llama icon sits in the system tray), or a hidden `ollama serve` as a fallback; waits until it answers;
 * stop_if_ours()   - when Fathom closes, close the Ollama that Fathom started (an Ollama the person started themselves is left alone);
 * drop_autostart() - removes the "start with Windows" entry that an earlier Fathom version added (only that one value).
Only the standard library is used."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("fathom")
IS_WIN = sys.platform.startswith("win")
_lock = threading.Lock()
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "Ollama (Fathom)"          # the value an earlier Fathom version added; drop_autostart() and Uninstall-Fathom.cmd remove it
TRAY_ARGS = ["--hide"]                # Ollama's own option: start without opening its window, tray icon only
OLLAMA_SETTINGS = ("OLLAMA_MODELS", "OLLAMA_CONTEXT_LENGTH", "OLLAMA_KEEP_ALIVE", "OLLAMA_HOST")


def base_url() -> str:
    host = (os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434").strip()
    if "://" not in host:
        host = "http://" + host
    return host.replace("0.0.0.0", "127.0.0.1").rstrip("/")


def is_up(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(base_url() + "/api/version", timeout=timeout) as r:
            json.loads(r.read().decode("utf-8", "replace") or "{}")
        return True
    except Exception:
        return False


def _exe() -> str | None:
    cands = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")]
    for pf in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if pf:
            cands.append(os.path.join(pf, "Ollama", "ollama.exe"))
    for c in cands:
        if c and os.path.exists(c):
            return c
    return shutil.which("ollama")


def tray_app() -> str | None:
    """'ollama app.exe': the Ollama program that lives in the system tray and runs the server for you."""
    exe = _exe()
    if not exe:
        return None
    p = os.path.join(os.path.dirname(exe), "ollama app.exe")
    return p if os.path.exists(p) else None


def _user_env() -> dict:
    """Ollama's settings as saved for this Windows user (a program started a moment ago may not have them yet)."""
    env = dict(os.environ)
    if not IS_WIN:
        return env
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            for n in OLLAMA_SETTINGS:
                try:
                    env[n] = str(winreg.QueryValueEx(k, n)[0])
                except OSError:
                    pass
    except Exception:
        pass
    return env


def _marker() -> Path:
    d = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Fathom"
    d.mkdir(parents=True, exist_ok=True)
    return d / "ollama-started-by-fathom.txt"


def _mark_ours(how: str) -> None:
    try:
        _marker().write_text(f"{how} {time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8")
    except Exception:
        pass


def stop_if_ours() -> str:
    """Close Ollama when Fathom closes, but only if Fathom was the one that started it. Returns a short sentence for the log."""
    try:
        m = _marker()
        if not m.exists():
            return "Ollama was not started by Fathom: left running"
        if IS_WIN:
            def kill(image: str, force: bool) -> None:
                subprocess.run(["taskkill", "/IM", image, "/T"] + (["/F"] if force else []), capture_output=True, timeout=15,
                               creationflags=0x08000000)
            kill("ollama app.exe", False)                  # a polite close first: the tray icon then disappears cleanly
            for _ in range(8):
                if not is_up(0.5):
                    break
                time.sleep(0.5)
            for image in ("ollama app.exe", "ollama.exe", "ollama_llama_server.exe"):
                kill(image, True)
        else:
            subprocess.run(["pkill", "-f", "ollama serve"], capture_output=True, timeout=15)
        try:
            os.replace(m, m.with_suffix(".done"))        # renamed: the next start writes a new marker
        except Exception:
            pass
        return "Ollama closed together with Fathom"
    except Exception as exc:
        return f"could not close Ollama: {exc}"


def _wait_up(seconds: int) -> bool:
    for _ in range(seconds):
        if is_up(1.5):
            return True
        time.sleep(1)
    return False


def ensure_running(wait: int = 45) -> bool:
    """True when Ollama answers (after starting it if it was not running)."""
    if is_up():
        return True
    with _lock:
        if is_up():
            return True
        env = _user_env()
        try:
            if IS_WIN:
                tray = tray_app()
                if tray:
                    log.info("Ollama is not running: starting the Ollama tray app (hidden, tray icon only)")
                    _mark_ours("tray app")
                    subprocess.Popen([tray] + TRAY_ARGS, cwd=os.path.dirname(tray), env=env, creationflags=0x00000008 | 0x00000200, close_fds=True,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if _wait_up(wait):
                        return True
            exe = _exe()
            if not exe:
                return False
            log.info("Ollama is not running: starting `ollama serve`")
            _mark_ours("serve")
            try:
                d = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Fathom"
                d.mkdir(parents=True, exist_ok=True)
                logf = open(d / "ollama-serve.log", "ab")
            except Exception:
                logf = subprocess.DEVNULL
            subprocess.Popen([exe, "serve"], env=env, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             creationflags=(0x08000000 if IS_WIN else 0))
            return _wait_up(wait)
        except Exception:
            log.exception("could not start Ollama")
            return False


def drop_autostart() -> str:
    """An earlier Fathom version made Ollama start with Windows. Ollama now starts and closes together with Fathom, so remove that
    one entry (only the value named RUN_NAME; Ollama's own entries are never touched). Returns a sentence for the log."""
    if not IS_WIN:
        return "not Windows: skipped"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_WRITE) as k:
            try:
                winreg.QueryValueEx(k, RUN_NAME)
            except OSError:
                return "Ollama starts when Fathom opens and closes with it."
            winreg.DeleteValue(k, RUN_NAME)
        return "Removed the old 'Ollama starts with Windows' entry; Ollama now starts when Fathom opens and closes with it."
    except Exception as exc:
        return f"could not check the Windows startup list: {exc}"
