# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Fathom setup. Fathom.bat runs this with Python 3.12 (as administrator, first time only).

It installs the Windows pieces Fathom needs, creates a private Python environment, installs the packages,
downloads the models, runs a self-test, and creates the Desktop / Start-menu shortcuts. Safe to run again."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from app.paths import VERSION, data_root  # noqa: E402

IS_WIN = os.name == "nt"
DATA = data_root()
LOG = DATA / "setup.log"
VENV = DATA / "venv"
TOTAL = 10
def _read_choice() -> dict:
    """The installer (Fathom-Setup.vbs) saves what the person chose in install-choice.txt: KEY=value lines."""
    out: dict = {}
    try:
        for line in (ROOT / "install-choice.txt").read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip().upper()] = v.strip()
    except OSError:
        pass
    return out


CHOICE = _read_choice()
SKIP = {x.strip().lower() for x in CHOICE.get("SKIP", "").replace(";", ",").split(",") if x.strip()}   # libreoffice, calibre, 7zip, ollama
LITE = (os.environ.get("FATHOM_LITE") == "1"
        or (ROOT / "LITE").exists() or CHOICE.get("EDITION", "").lower() == "lite")   # Lite: skip the big office / e-book programs and the local AI
if os.environ.get("FATHOM_FULL") == "1":   # "Fathom.bat full": add everything, even if an earlier install chose Lite or unticked parts
    LITE = False
    SKIP = set()
if LITE:
    SKIP |= {"libreoffice", "calibre", "7zip", "ollama"}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def say(msg: str = "") -> None:
    print(msg, flush=True)
    with LOG.open("a", encoding="utf-8", errors="replace") as fh:
        fh.write(msg + "\n")


def step(n: int, title: str) -> None:
    say()
    say(f"[{n}/{TOTAL}] {title}")


def venv_python(gui: bool = False) -> Path:
    if IS_WIN:
        return VENV / "Scripts" / ("pythonw.exe" if gui else "python.exe")
    return VENV / "bin" / "python"


def run(cmd: list, check: bool = True, cwd: Path | None = None, env: dict | None = None, timeout: int | None = None) -> int:
    say("  > " + " ".join(str(c) for c in cmd)[:200])
    proc = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd) if cwd else None, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    assert proc.stdout is not None
    if timeout:
        import threading

        def _kill() -> None:
            if proc.poll() is None:
                say(f"    (still not finished after {timeout // 60} minutes; stopping it so setup can go on)")
                try:
                    proc.kill()
                except Exception:
                    pass
        _t = threading.Timer(timeout, _kill)
        _t.daemon = True
        _t.start()
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            say("    " + line)
    rc = proc.wait()
    if check and rc != 0:
        raise RuntimeError(f"command failed with exit code {rc}: {cmd[0]} ...")
    return rc


def download(url: str, dest: Path, label: str) -> None:
    last: Exception | None = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Fathom-Setup"})
            with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as out:
                total = int(resp.headers.get("Content-Length") or 0)
                done, last_say = 0, time.time()
                say(f"    {label}: downloading" + (f" ({total >> 20} MB)" if total else "") + " ...")
                while True:
                    block = resp.read(1 << 20)
                    if not block:
                        break
                    out.write(block)
                    done += len(block)
                    if time.time() - last_say >= 10:
                        last_say = time.time()
                        say(f"    {label}: {done >> 20} MB" + (f" of {total >> 20} MB ({done * 100 // total}%)" if total else ""))
                say(f"    {label}: download finished ({done >> 20} MB).")
            return
        except Exception as exc:  # network hiccup: try again
            last = exc
            say(f"    download attempt {attempt} failed: {exc}")
            time.sleep(3)
    raise RuntimeError(f"Could not download {label} ({last}). Check your internet connection and run Fathom.bat again.")


# ------------------------------------------------------------------ Windows components
def _reg_value(hive, key: str, name: str):
    import winreg

    try:
        with winreg.OpenKey(hive, key) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def vcredist_ok() -> bool:
    import winreg

    for key in (r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64", r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"):
        if _reg_value(winreg.HKEY_LOCAL_MACHINE, key, "Installed") == 1 and int(_reg_value(winreg.HKEY_LOCAL_MACHINE, key, "Bld") or 0) >= 33000:
            return True
    return False


def webview2_ok() -> bool:
    import winreg

    guid = r"\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node" + guid), (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE" + guid), (winreg.HKEY_CURRENT_USER, r"Software" + guid)):
        pv = _reg_value(hive, key, "pv")
        if pv and pv != "0.0.0.0":
            return True
    return False


def install_windows_components() -> None:
    tmp = Path(os.environ.get("TEMP") or DATA)
    step(2, "Checking Windows components (Visual C++ runtime, WebView2)")
    if vcredist_ok():
        say("  Visual C++ runtime: already installed.")
    else:
        say("  Installing the Visual C++ runtime...")
        exe = tmp / "vc_redist.x64.exe"
        download("https://aka.ms/vs/17/release/vc_redist.x64.exe", exe, "Visual C++ runtime")
        rc = run([exe, "/install", "/quiet", "/norestart"], check=False)
        if rc not in (0, 1638, 3010):
            say(f"  !! The Visual C++ installer returned {rc}; continuing anyway.")
    if webview2_ok():
        say("  WebView2 (the window engine): already installed.")
    else:
        say("  Installing WebView2 (the window engine)...")
        exe = tmp / "MicrosoftEdgeWebview2Setup.exe"
        try:
            download("https://go.microsoft.com/fwlink/p/?LinkId=2124703", exe, "WebView2")
            run([exe, "/silent", "/install"], check=False)
        except Exception as exc:
            say(f"  !! WebView2 could not be installed ({exc}). Fathom will open in your browser instead.")
    try:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "LongPathsEnabled", 0, winreg.REG_DWORD, 1)
        say("  Long file paths enabled (so very deep folders can be scanned).")
    except Exception as exc:
        say(f"  (could not enable long paths: {exc})")


# ------------------------------------------------------------------ Python environment
def ensure_venv() -> None:
    step(3, "Creating Fathom's private Python environment")
    py = venv_python()
    if py.exists():
        out = subprocess.run([str(py), "-c", "import sys;print(sys.version_info[:2])"], capture_output=True, text=True).stdout.strip()
        if out == "(3, 12)":
            say("  Already exists.")
            return
        shutil.rmtree(VENV, ignore_errors=True)
    run([sys.executable, "-m", "venv", VENV])


def pip_install(args: list, what: str, required: bool = True, retries: int = 3) -> bool:
    cmd = [venv_python(), "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
           "--prefer-binary", "--retries", "10", "--timeout", "60", *args]
    for attempt in range(1, retries + 1):
        if run(cmd, check=False) == 0:
            return True
        say(f"  {what}: attempt {attempt} did not finish" + ("; retrying in 5 seconds..." if attempt < retries else "."))
        time.sleep(5)
    if required:
        raise RuntimeError(f"Could not install {what}. See {LOG} for the reason (usually: no internet connection).")
    say(f"  (optional) {what} was skipped.")
    return False


def install_packages() -> None:
    step(4, "Installing packages (a few minutes the first time)")
    pip_install(["--upgrade", "pip"], "pip", required=False, retries=1)
    reqs = [ln.strip() for ln in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if run([venv_python(), "-c", "import cv2"], check=False) == 0:   # an OpenCV is already there (updating): do not install a second, conflicting one
        reqs = [r for r in reqs if not r.lower().startswith("opencv")]
    pip_install(reqs, "the required packages")
    step(5, "Installing the text-in-pictures reader (OCR)")
    pip_install(["--no-deps", "rapidocr-onnxruntime==1.4.4"], "the OCR engine")
    step(6, "Installing converters and extras (HEIC photos, RAW, 7z, speech, PDF to Word, 3D, fonts)")
    for line in (ROOT / "requirements-optional.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            pip_install([line], line.split(">")[0], required=False, retries=2)
    code = "import fastapi, uvicorn, cv2, numpy, onnxruntime, tokenizers, huggingface_hub, openpyxl, imageio_ffmpeg, rapidocr_onnxruntime, pymupdf, cryptography, fontTools, send2trash, pypdf, reportlab"
    if run([venv_python(), "-c", code], check=False) != 0:
        raise RuntimeError("Some packages did not install correctly (see the lines above).")
    say("  All required packages are installed.")



# ------------------------------------------------------------------ big programs: LibreOffice (Office formats), Calibre (e-books), 7-Zip (RAR and friends)
def _exists_any(paths: list[str]) -> bool:
    return any(p and os.path.exists(p) for p in paths)


def _pf() -> list[str]:
    return [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]


def _latest_libreoffice() -> str | None:
    try:
        req = urllib.request.Request("https://download.documentfoundation.org/libreoffice/stable/", headers={"User-Agent": "Fathom-Setup"})
        html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")
        import re

        vers = sorted({tuple(int(x) for x in m.split(".")) for m in re.findall(r'href="(\d+\.\d+\.\d+(?:\.\d+)?)/"', html)})
        return ".".join(map(str, vers[-1])) if vers else None
    except Exception as exc:
        say(f"    could not look up the newest LibreOffice ({exc})")
        return None


def _latest_calibre() -> str | None:
    try:
        req = urllib.request.Request("https://code.calibre-ebook.com/latest", headers={"User-Agent": "Fathom-Setup"})
        ver = urllib.request.urlopen(req, timeout=40).read().decode().strip()
        return ver if ver and ver[0].isdigit() else None
    except Exception as exc:
        say(f"    could not look up the newest Calibre ({exc})")
        return None


def _winget(pkg: str) -> bool:
    """Windows Package Manager. Some Windows builds (Tiny11, Server, LTSC) do not have it: then this just returns False and the direct download is used."""
    if not shutil.which("winget"):
        say("    (this Windows has no Windows Package Manager; using the direct download instead)")
        return False
    try:
        return run(["winget", "install", "-e", "--id", pkg, "--silent", "--accept-package-agreements", "--accept-source-agreements"], check=False, timeout=1800) == 0
    except OSError as exc:
        say(f"    (winget could not start: {exc})")
        return False


def _latest_7zip_msi() -> str | None:
    try:
        import re

        req = urllib.request.Request("https://www.7-zip.org/download.html", headers={"User-Agent": "Fathom-Setup"})
        html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")
        found = re.findall(r'href="a/(7z\d+-x64\.msi)"', html)
        return "https://www.7-zip.org/a/" + found[0] if found else None
    except Exception as exc:
        say(f"    could not look up the newest 7-Zip ({exc})")
        return None


def _ollama_direct() -> bool:
    """Official Ollama installer, for PCs without winget."""
    exe = Path(os.environ.get("TEMP") or DATA) / "OllamaSetup.exe"
    try:
        download("https://ollama.com/download/OllamaSetup.exe", exe, "Ollama")
    except Exception as exc:
        say(f"    {exc}")
        return False
    say("    Ollama: installing (silent, one to three minutes)...")
    return run([exe, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=False, timeout=900) == 0


def _winget_upgrade(pkg: str) -> bool:
    if not shutil.which("winget"):
        return _ollama_direct() if pkg == "Ollama.Ollama" else False
    return run(["winget", "upgrade", "-e", "--id", pkg, "--silent", "--accept-package-agreements", "--accept-source-agreements"], check=False) == 0


def _msi(url: str, label: str) -> bool:
    msi = Path(os.environ.get("TEMP") or DATA) / (label.replace(" ", "_") + ".msi")
    try:
        download(url, msi, label)
    except Exception as exc:
        say(f"    {exc}")
        return False
    rc = run(["msiexec", "/i", msi, "/qn", "/norestart"], check=False)
    return rc in (0, 3010)


def _heal_stale(name_pattern: str, why: str = "") -> int:
    """An old, half-removed program leaves its install record behind, and then its installer says "already installed" and does nothing.
    Called only when the program's files are NOT there: removes that program's stale records (running its own uninstaller first when it still works). Returns how many records were cleared."""
    if not IS_WIN:
        return 0
    import re
    try:
        import winreg
    except ImportError:
        return 0
    pat = re.compile(name_pattern, re.I)
    cleared = 0
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", winreg.KEY_WOW64_64KEY),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", winreg.KEY_WOW64_32KEY),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0)]
    for hive, path, view in roots:
        try:
            top = winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        names = []
        i = 0
        while True:
            try:
                names.append(winreg.EnumKey(top, i))
                i += 1
            except OSError:
                break
        for sub in names:
            try:
                k = winreg.OpenKey(top, sub)
                try:
                    disp = winreg.QueryValueEx(k, "DisplayName")[0]
                except OSError:
                    continue
                if not pat.search(str(disp)):
                    continue
                try:
                    unin = str(winreg.QueryValueEx(k, "UninstallString")[0])
                except OSError:
                    unin = ""
                say(f"    clearing an old leftover record of {disp} ...")
                import re as _re
                guid = _re.search(r"\{[0-9A-Fa-f-]{36}\}", unin)
                try:
                    if guid:
                        run(["msiexec", "/x", guid.group(0), "/qn", "/norestart"], check=False, timeout=600)
                    else:
                        exe = _re.match(r'^"?([^"]+?\.exe)"?', unin)
                        if exe and os.path.exists(exe.group(1)):
                            run([exe.group(1), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=False, timeout=600)
                except Exception:
                    pass
                try:
                    winreg.DeleteKey(top, sub)       # a record that survived its own uninstaller is the stale one
                except OSError:
                    pass
                cleared += 1
            except OSError:
                continue
    return cleared


def install_programs() -> None:
    step(7, "Installing LibreOffice, Calibre and 7-Zip (they let Fathom convert Word, Excel, PowerPoint, e-books, RAR and 100+ more formats)")
    if not IS_WIN:
        say("  (not Windows - skipped)")
        return
    if {"libreoffice", "calibre", "7zip"} <= SKIP:
        say("  Skipped (Lite, or you chose none of them). Fathom still converts pictures, audio, video, PDF, text and data files.")
        return
    jobs = [
        ("LibreOffice", [os.path.join(p, "LibreOffice", "program", "soffice.exe") for p in _pf()], "TheDocumentFoundation.LibreOffice"),
        ("Calibre", [os.path.join(p, "Calibre2", "ebook-convert.exe") for p in _pf()], "calibre.calibre"),
        ("7-Zip", [os.path.join(p, "7-Zip", "7z.exe") for p in _pf()], "7zip.7zip"),
    ]
    for name, exes, winget_id in jobs:
        key = {"LibreOffice": "libreoffice", "Calibre": "calibre", "7-Zip": "7zip"}[name]
        if key in SKIP:
            say(f"  {name}: skipped (you chose not to install it).")
            continue
        if _exists_any(exes):
            say(f"  {name}: already installed.")
            continue
        say(f"  Installing {name}... (this takes a few minutes)")

        def attempt() -> bool:
            if name == "LibreOffice":
                v = _latest_libreoffice()
                if v:
                    return _msi(f"https://download.documentfoundation.org/libreoffice/stable/{v}/win/x86_64/LibreOffice_{v}_Win_x86-64.msi", "LibreOffice")
            elif name == "Calibre":
                v = _latest_calibre()
                if v:
                    return _msi(f"https://download.calibre-ebook.com/{v}/calibre-64bit-{v}.msi", "Calibre")
            elif name == "7-Zip":
                url = _latest_7zip_msi()
                if url:
                    return _msi(url, "7-Zip")
            return False

        ok = attempt()
        if not (ok and _exists_any(exes)):
            # the usual reason for a silent do-nothing: an old half-removed copy left its record, so the installer thinks it is already there
            if _heal_stale({"LibreOffice": r"^LibreOffice", "Calibre": r"^calibre", "7-Zip": r"^7-Zip"}[name]):
                say(f"  Trying {name} again...")
                ok = attempt()
        if not (ok and _exists_any(exes)):
            say(f"  Trying the Windows Package Manager for {name}...")
            _winget(winget_id)
        say(f"  {name}: " + ("installed." if _exists_any(exes) else "!! not installed. Fathom still works, just without the formats that need it. Run Fathom.bat repair later."))

# ------------------------------------------------------------------ models, self-test, shortcuts
def app_env() -> dict:
    return dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")


def _ollama_exe() -> str | None:
    cands = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")]
    cands += [os.path.join(p, "Ollama", "ollama.exe") for p in _pf()]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return shutil.which("ollama")


def _drop_old_vision_manifest() -> None:
    """A half-downloaded llama3.2-vision leaves a broken record that makes `ollama list` show NOTHING (even models that are fine).
    Delete that record directly; Ollama frees the leftover pieces by itself the next time it starts."""
    try:
        base = os.environ.get("OLLAMA_MODELS") or str(Path.home() / ".ollama" / "models")
        d = Path(base) / "manifests" / "registry.ollama.ai" / "library" / "llama3.2-vision"
        if d.exists():
            say("  Removing the old model llama3.2-vision (it no longer works with current Ollama)...")
            shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


_OLLAMA_URL = "http://127.0.0.1:11434"


def _ollama_get(path: str, timeout: float = 5.0):
    try:
        with urllib.request.urlopen(_OLLAMA_URL + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except Exception:
        return None


def _ollama_up() -> bool:
    return _ollama_get("/api/version") is not None


# Ollama before 0.40.1 has Windows bugs that can hide downloaded models ("bad manifest", empty `ollama list`); 0.40.1 fixed manifest handling on Windows.
_OLLAMA_MIN = (0, 40, 1)


def _ollama_version() -> tuple:
    v = _ollama_get("/api/version")
    try:
        return tuple(int(x) for x in str((v or {}).get("version", "")).split("-")[0].split(".")[:3])
    except Exception:
        return ()


def _ollama_show_ok(model: str) -> bool:
    """Can Ollama really OPEN this model's record? (a model can be listed and still fail to open)"""
    try:
        req = urllib.request.Request(_OLLAMA_URL + "/api/show", data=json.dumps({"model": model}).encode("utf-8"),
                                     headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except Exception:
        return False


def _ollama_has(model: str) -> bool:
    """Does the running Ollama list this model AND open it? (asks the server itself, not the folder)"""
    names = _ollama_names()
    hit = [n for n in names if n == model or (":" not in model and n == model + ":latest")]
    return bool(hit) and _ollama_show_ok(hit[0])


def _fix_links() -> int:
    """Replace symbolic links in Ollama's records by real files (Windows refuses to follow them)."""
    try:
        from app import ollama_fix
        return ollama_fix.repair_links(_ollama_models_dir(), say)
    except Exception as exc:
        say(f"    link check failed: {exc}")
        return 0


def _ollama_stop() -> None:
    for img in ("ollama app.exe", "ollama.exe", "ollama_llama_server.exe"):
        subprocess.run(["taskkill", "/f", "/im", img], capture_output=True, creationflags=0x08000000)
    time.sleep(3)


def _serve_log() -> Path:
    d = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Fathom"
    d.mkdir(parents=True, exist_ok=True)
    return d / "ollama-serve.log"


def _ollama_names() -> list:
    tags = _ollama_get("/api/tags", 15.0)
    return [m.get("name", "") for m in (tags or {}).get("models", [])]


def _ollama_report(note: str = "") -> Path | None:
    """One text file with everything needed to see why Ollama hides a model (so nobody has to guess)."""
    try:
        out = []
        out.append("Fathom Ollama report  " + time.strftime("%Y-%m-%d %H:%M:%S"))
        out.append("note: " + note)
        out.append("version: " + (".".join(map(str, _ollama_version())) or "(server not answering)"))
        out.append("listed models: " + (", ".join(_ollama_names()) or "(none)"))
        out.append("OLLAMA_MODELS env: " + repr(os.environ.get("OLLAMA_MODELS")))
        md = _ollama_models_dir()
        out.append("models folder: " + str(md) + "   (real path: " + str(_real(md)) + ")")
        out.append("OLLAMA_MODELS user setting: " + repr(_user_env_get("OLLAMA_MODELS")))
        for sub in ("manifests", "manifests-v2"):
            q = md / sub
            out.append("--- files under " + sub)
            try:
                for f in sorted(q.rglob("*"))[:200]:
                    if f.is_file():
                        out.append("  " + str(f.relative_to(md)) + "  (" + str(f.stat().st_size) + " bytes)")
            except Exception as exc:
                out.append("  (cannot read: " + str(exc) + ")")
        try:
            from app import ollama_fix
            out.append("--- link files found in the records (these are what Windows may refuse to follow)")
            out += ["  " + x for x in ollama_fix.describe_links(md)] or ["  (none)"]
        except Exception as exc:
            out.append("  (link check failed: " + str(exc) + ")")
        out.append("--- last lines of the Ollama server log")
        for lg in (_serve_log(), Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "server.log"):
            try:
                out.append("[" + str(lg) + "]")
                out += lg.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
            except Exception as exc:
                out.append("  (no log: " + str(exc) + ")")
        p = _serve_log().with_name("ollama-report.txt")
        p.write_text("\n".join(out), encoding="utf-8")
        return p
    except Exception:
        return None


def _ollama_start(exe: str, env: dict, wait: int = 45) -> bool:
    if _ollama_up():
        return True
    say("  Starting Ollama...")
    try:
        logf = open(_serve_log(), "ab")
    except Exception:
        logf = subprocess.DEVNULL
    subprocess.Popen([exe, "serve"], creationflags=0x08000000, env=env, stdout=logf, stderr=subprocess.STDOUT)
    for _ in range(wait):
        time.sleep(1)
        if _ollama_up():
            return True
    return False


def _user_env_get(name: str) -> str:
    if not IS_WIN:
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except Exception:
        return ""


def _user_env_set(name: str, value: str) -> None:
    """Save a setting for this Windows user (what the 'Environment variables' window does) and tell running programs."""
    os.environ[name] = value
    if not IS_WIN:
        return
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        import ctypes
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 2, 3000, ctypes.byref(ctypes.c_ulong()))
    except Exception as exc:
        say(f"    could not save the setting {name}: {exc}")


def _ollama_models_dir() -> Path:
    v = os.environ.get("OLLAMA_MODELS") or _user_env_get("OLLAMA_MODELS")
    return Path(v) if v else (Path.home() / ".ollama" / "models")


def _real(p: Path) -> Path:
    r = os.path.realpath(str(p))
    for pre in ("\\\\?\\", "\\\\??\\"):
        if r.startswith(pre):
            r = r[len(pre):]
    return Path(r)


# Fathom sends a long prompt (instructions + about 30 tools, over 5000 tokens). Ollama's default memory for a conversation is only
# 4096 tokens on a 8 GB card, which cuts the prompt off. 16384 fits an 8 GB card with this 4B model; keep-alive keeps the model loaded.
_TUNING = {"OLLAMA_CONTEXT_LENGTH": "16384", "OLLAMA_KEEP_ALIVE": "60m"}


def _ensure_tuning() -> bool:
    """Save Ollama's memory and keep-alive settings (only the ones the user has not set). Returns True if something was added."""
    changed = False
    for k, v in _TUNING.items():
        if not (os.environ.get(k) or _user_env_get(k)):
            _user_env_set(k, v)
            changed = True
    return changed


def _fix_model_path() -> bool:
    """Ollama 0.40 cannot read models that sit behind a folder link (a Windows 'junction'): it downloads them, then says
    'bad manifest ... The system cannot find the path specified' and lists nothing. Older Fathom versions made such a link
    when moving Ollama's folder to another drive. Fix: point Ollama straight at the real folder (OLLAMA_MODELS), the way
    Ollama documents it. Nothing is deleted or moved. Returns True when the setting was changed."""
    if not IS_WIN:
        return False
    try:
        md = _ollama_models_dir()
        real = _real(md)
        if os.path.normcase(str(real)) == os.path.normcase(str(md.absolute())):
            return False
        say(f"  Ollama's model folder is reached through a link ({md} -> {real}). Ollama cannot read models through links.")
        say("  Pointing Ollama straight at the real folder instead (nothing is moved or deleted)...")
        _user_env_set("OLLAMA_MODELS", str(real))
        return True
    except Exception as exc:
        say(f"    could not check the model folder: {exc}")
        return False


def _set_aside(p: Path) -> bool:
    """Rename a folder to <name>.old-<time> (nothing is deleted), so Ollama starts with a clean one."""
    try:
        if p.exists():
            p.rename(p.with_name(p.name + ".old-" + time.strftime("%Y%m%d-%H%M%S")))
        return True
    except Exception as exc:
        say(f"    could not set {p} aside: {exc}")
        return False


_PROBE = "qwen2.5:0.5b"
_ALTERNATES = ["qwen3-vl:4b", "qwen2.5vl:3b", "gemma3:4b", "llama3.2:3b"]


def _use_model(name: str) -> None:
    """Tell Fathom which Ollama model to use (saved in its settings)."""
    try:
        from app.ai import store
        store.save({"models": {"ollama": name}})
    except Exception as exc:
        say(f"    could not save the model choice: {exc}")


def _ollama_pull(exe: str, model: str, env: dict, big: bool = True) -> bool:
    say(f"  Downloading the model {model} ({'about 2 to 3.5 GB' if big else ('small model, about 270 MB' if model == 'nomic-embed-text' else 'small test model, about 400 MB')}; if its files are already here this takes seconds)...")
    say("  > ollama pull " + model)
    rc = subprocess.call([exe, "pull", model], env=env)   # Ollama draws its own progress bar in this window
    if rc == 0 and _fix_links():
        say("  (Windows could not follow Ollama's link files; they were replaced by real copies.)")
    return rc == 0


def _ollama_make_ready(exe: str, model: str) -> None:
    """Get the model into Ollama and PROVE Ollama lists it. If Ollama hides it (broken model records, an old buggy version),
    repair step by step: fresh records, newest Ollama, then a clean model folder. Never says 'ready' unless it is."""
    env = dict(os.environ)
    try:
        fixed = _fix_model_path()
        tuned = _ensure_tuning() if IS_WIN else False
        for k in ("OLLAMA_MODELS", *_TUNING):
            v = os.environ.get(k) or _user_env_get(k)
            if v:
                env[k] = v
        if fixed or tuned:
            _ollama_stop()   # a running Ollama still has the old settings
        say("  Checking that Ollama is running...")
        if not _ollama_start(exe, env):
            say("  Ollama did not start. Restarting it...")
            _ollama_stop()
            if not _ollama_start(exe, env, 60):
                say("  !! Ollama will not start. Open the Ollama app once, then run Fathom.bat repair.")
                return
        _drop_old_vision_manifest()
        updated = False
        ver = _ollama_version()
        if ver and ver < _OLLAMA_MIN:
            say("  Your Ollama is old (" + ".".join(map(str, ver)) + "). Installing the newest one first (it fixes bugs that hide downloaded models)...")
            _ollama_stop()
            _ollama_direct()
            updated = True
            exe = _ollama_exe() or exe
            if not _ollama_start(exe, env, 90):
                say("  Ollama did not start after the update. Open the Ollama app once, then open Fathom-Setup.vbs > Problems and Fixes > Ollama.")
                return
        if _fix_links():
            say("  (Windows could not follow Ollama's link files; they were replaced by real copies.)")
        if _ollama_has(model):
            say(f"  Model {model} is already downloaded and working.")
            return
        if not _ollama_pull(exe, model, env):
            say("  The download did not finish. Trying once more...")
            if not _ollama_pull(exe, model, env):
                say("  !! Not downloaded. Check the internet connection and run Fathom.bat repair.")
                return
        if _ollama_has(model):
            say(f"  Model {model}: ready.")
            return
        say("  Ollama downloaded the model but does not list it. Finding out whether this model or the whole Ollama is the problem...")
        # A tiny test model (about 400 MB) tells the two apart without re-downloading 3 GB again and again.
        probe = _PROBE
        if not (_ollama_pull(exe, probe, env, big=False) and _ollama_has(probe)):
            say("  Ollama hides even the tiny test model, so Ollama itself is stuck. Repairing it with the tiny model (fast), step 1 of 3: fresh records...")
            _ollama_stop()
            _set_aside(_ollama_models_dir() / "manifests")
            ok = _ollama_start(exe, env) and _ollama_pull(exe, probe, env, big=False) and _ollama_has(probe)
            if not ok and not updated:
                say("  Step 2 of 3: installing the newest Ollama...")
                _ollama_stop()
                _ollama_direct()
                exe = _ollama_exe() or exe
                ok = _ollama_start(exe, env, 60) and _ollama_pull(exe, probe, env, big=False) and _ollama_has(probe)
            if not ok:
                say("  Step 3 of 3: starting Ollama with a clean model folder (the old one is kept, renamed to models.old-...; delete it later to free space)...")
                _ollama_stop()
                _set_aside(_ollama_models_dir())
                ok = _ollama_start(exe, env, 60) and _ollama_pull(exe, probe, env, big=False) and _ollama_has(probe)
            if not ok:
                rp = _ollama_report("Ollama hides every model, even the tiny test model")
                say("  !! Ollama on this PC hides every model it downloads. Fathom still works without it: choose an online AI in Assistant > Settings.")
                if rp:
                    say("     A report was saved here (send it to the Fathom author if you want help): " + str(rp))
                return
            say("  Ollama works again after the repair.")
            if _ollama_pull(exe, model, env) and _ollama_has(model):
                say(f"  Model {model}: ready (repaired).")
                return
        # Ollama is fine, but it will not list this one model. Use a different model that it does list.
        say(f"  Ollama works, but it will not list {model}. Trying other free vision models...")
        for alt in _ALTERNATES:
            if _ollama_pull(exe, alt, env) and _ollama_has(alt):
                _use_model(alt)
                say(f"  Model {alt}: ready. Fathom will use it instead of {model}.")
                return
        if _ollama_has(probe):
            _use_model(probe)
            say(f"  Only the small text model {probe} works here. Fathom will use it (it answers questions but cannot look at pictures). Open Fathom-Setup.vbs > Problems and Fixes > Ollama.cmd later to try again.")
            _ollama_report("alternates failed; using the probe model")
            return
        rp = _ollama_report("no model could be listed")
        say("  !! Ollama still hides the models. Fathom works without it: choose an online AI in Assistant > Settings." + (" Report: " + str(rp) if rp else ""))
    except Exception as exc:
        say(f"  !! Ollama setup did not finish: {exc}")


def setup_ollama() -> None:
    """The free AI assistant: Ollama runs the model on this PC (no key, no bill). Optional: if anything fails, Fathom still works."""
    if not IS_WIN or "ollama" in SKIP:
        if IS_WIN:
            say("  Free AI assistant (Ollama): skipped. Use an online AI in Assistant > Settings, or run Fathom.bat full later.")
        return
    from app.ai import store
    model = store.DEFAULTS["models"]["ollama"]
    say("  Free AI assistant (Ollama) ...")
    exe = _ollama_exe()
    if not exe:
        say("  Installing Ollama (free, runs AI on this PC)... this can take a few minutes")
        if not _winget("Ollama.Ollama"):
            _ollama_direct()
        exe = _ollama_exe()
        if not exe and _heal_stale(r"^Ollama"):
            say("  Trying Ollama again...")
            if not _ollama_direct():
                _winget("Ollama.Ollama")
            exe = _ollama_exe()
    if not exe:
        say("  !! Ollama could not be installed. Get it from https://ollama.com and run Fathom.bat repair, or choose another AI in Assistant > Settings.")
        return
    _ollama_make_ready(exe, model)
    try:
        # the small model behind "Search by meaning" (about 270 MB). Optional: if it fails, only that one tool is affected.
        if _ollama_start(exe, dict(os.environ), 30) and not _ollama_has("nomic-embed-text"):
            say("  Downloading the small model for 'Search by meaning' (about 270 MB)...")
            _ollama_pull(exe, "nomic-embed-text", dict(os.environ), big=False)
    except Exception as exc:
        say(f"  ('Search by meaning' model not downloaded: {exc}. Run  ollama pull nomic-embed-text  later.)")
    try:
        # an earlier fallback (small test model, the slow thinking edition) is replaced by the proper model once that one works
        cur = store.load()["models"]["ollama"]
        if cur != model and (cur == _PROBE or cur in _ALTERNATES or cur.startswith("llama3.2-vision")) and _ollama_has(model):
            _use_model(model)
            say(f"  The Assistant now uses {model} (it works on this PC).")
    except Exception:
        pass
    rp = _ollama_report("setup finished")
    if rp:
        say("  (A report about Ollama was saved: " + str(rp) + ")")
    try:
        # Ollama starts (hidden, tray icon only) when Fathom opens and closes with it; remove the old 'start with Windows' entry if an earlier version made it
        from app import ollama_keep
        say("  " + ollama_keep.drop_autostart())
    except Exception as exc:
        say(f"  (could not check Ollama's startup entry: {exc})")


def download_models() -> bool:
    step(8, "Downloading every AI model Fathom uses (speech, object search, faces, handwriting - several GB, one time only, so nothing downloads later)")
    env = app_env()
    if LITE:
        env["FATHOM_LITE"] = "1"
    if CHOICE.get("WHISPER"):
        env["FATHOM_WHISPER"] = CHOICE["WHISPER"]   # e.g. WHISPER=all in install-choice.txt downloads every speech model
    rc = run([venv_python(), "-m", "app.bootstrap"], check=False, cwd=ROOT, env=env)
    if rc != 0:
        say("  !! A model download did not finish. Fathom will retry it the first time you use that feature.")
    setup_ollama()
    return rc == 0


def self_test() -> None:
    step(9, "Testing every feature on this PC")
    run([venv_python(), "-m", "app.selftest"], check=False, cwd=ROOT, env=app_env())


def ps_quote(text: str) -> str:
    return text.replace("'", "''")


def make_shortcuts() -> None:
    step(10, "Creating the Fathom shortcuts (with its own icon)")
    if not IS_WIN:
        say("  (not Windows - skipped)")
        return
    icon = DATA / "fathom.ico"
    try:
        shutil.copyfile(ROOT / "assets" / "fathom.ico", icon)
    except OSError as exc:
        say(f"  (could not copy the icon: {exc})")
    script = r"""
$ws = New-Object -ComObject WScript.Shell
function Make($path) {
  $s = $ws.CreateShortcut($path)
  $s.TargetPath = '__PYW__'
  $s.Arguments = '"__LAUNCH__"'
  $s.WorkingDirectory = '__ROOT__'
  $s.IconLocation = '__ICO__'
  $s.Description = 'Fathom - find, convert and manage any file'
  $s.Save()
}
$desk = [Environment]::GetFolderPath('Desktop'); $prog = [Environment]::GetFolderPath('Programs')
Make('__DATA__\Fathom.lnk')
if ('__DESK__' -eq '1') { Make((Join-Path $desk 'Fathom.lnk')) }
if ('__START__' -eq '1') { Make((Join-Path $prog 'Fathom.lnk')) }
"""
    for key, val in (("__PYW__", venv_python(gui=True)), ("__LAUNCH__", ROOT / "launch.py"), ("__ROOT__", ROOT), ("__ICO__", icon), ("__DATA__", DATA)):
        script = script.replace(key, ps_quote(str(val)))
    script = script.replace("__DESK__", "0" if CHOICE.get("DESKTOP_SHORTCUT") == "0" else "1").replace("__START__", "0" if CHOICE.get("START_SHORTCUT") == "0" else "1")
    rc = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], check=False)
    say("  Shortcuts created." if rc == 0 else "  !! Could not create shortcuts (Fathom.bat still starts the app).")
    # give the shortcuts the same app id the window uses, so the taskbar shows Fathom (not Python) and pinning works
    aumid = r"""
$code = @'
using System; using System.Runtime.InteropServices;
public static class LnkAumid {
  [StructLayout(LayoutKind.Sequential, Pack = 4)] public struct PROPERTYKEY { public Guid fmtid; public uint pid; }
  [StructLayout(LayoutKind.Explicit, Size = 24)] public struct PROPVARIANT { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; }
  [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IPropertyStore { void GetCount(out uint c); void GetAt(uint i, out PROPERTYKEY k); void GetValue(ref PROPERTYKEY k, out PROPVARIANT v); void SetValue(ref PROPERTYKEY k, ref PROPVARIANT v); void Commit(); }
  [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)] static extern void SHGetPropertyStoreFromParsingName(string path, IntPtr bc, int flags, ref Guid riid, out IPropertyStore ps);
  public static void Set(string lnk, string id) {
    Guid iid = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"); IPropertyStore ps;
    SHGetPropertyStoreFromParsingName(lnk, IntPtr.Zero, 2, ref iid, out ps);
    PROPERTYKEY key = new PROPERTYKEY(); key.fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"); key.pid = 5;
    PROPVARIANT v = new PROPVARIANT(); v.vt = 31; v.p = Marshal.StringToCoTaskMemUni(id);
    ps.SetValue(ref key, ref v); ps.Commit(); Marshal.ReleaseComObject(ps);
  }
}
'@
Add-Type -TypeDefinition $code
foreach($p in @('__DATA__\Fathom.lnk', (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Fathom.lnk'), (Join-Path ([Environment]::GetFolderPath('Programs')) 'Fathom.lnk'))) { if (Test-Path -LiteralPath $p) { [LnkAumid]::Set($p, 'Fathom.Desktop.1') } }
"""
    aumid = aumid.replace("__DATA__", ps_quote(str(DATA)))
    rc = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", aumid], check=False)
    say("  Taskbar identity set." if rc == 0 else "  (the taskbar identity could not be attached to the shortcuts; the window still uses its own icon)")


def main() -> int:
    LOG.write_text("", encoding="utf-8")
    say("Fathom setup " + VERSION + (" (Lite)" if LITE else ""))
    # downloads and caches go beside Fathom's data (which is on D: when the move script has run), not into C:\Users\...
    for var, sub in (("PIP_CACHE_DIR", "pip-cache"), ("HF_HOME", "hf"), ("TEMP", "tmp"), ("TMP", "tmp")):
        try:
            target = DATA / sub
            target.mkdir(parents=True, exist_ok=True)
            os.environ[var] = str(target)
        except OSError:
            pass
    step(1, "Checking Python")
    if sys.version_info[:2] != (3, 12):
        say(f"  Fathom needs Python 3.12 but this is {sys.version.split()[0]}. Run Fathom.bat (it installs 3.12 for you).")
        return 2
    say(f"  Python {sys.version.split()[0]} OK")
    try:
        free_gb = shutil.disk_usage(str(DATA)).free / 1e9
        say(f"  Free disk space for Fathom: {free_gb:.1f} GB")
        if free_gb < 3:
            say("SETUP DID NOT FINISH: not enough free disk space (Fathom needs at least 3 GB, 6 GB is comfortable). Free some space and run Fathom.bat again.")
            return 1
        if free_gb < 9 and not {"libreoffice", "calibre"} <= SKIP:
            SKIP.update({"libreoffice", "calibre"})
            say("  Only " + f"{free_gb:.1f}" + " GB free, so the two big optional programs (LibreOffice, Calibre) are skipped to protect your disk. Free more space and run Fathom.bat repair to add them.")
    except Exception as exc:
        say(f"  (could not check free disk space: {exc})")
    try:
        if IS_WIN:
            install_windows_components()
        else:
            step(2, "Windows components - skipped (not Windows)")
        ensure_venv()
        install_packages()
        install_programs()
        models_ok = download_models()
        self_test()
        make_shortcuts()
        if IS_WIN and "ollama" not in SKIP:
            # this setup window runs with administrator rights, so Ollama started here would be an elevated, icon-less copy. Stop it:
            # Fathom starts the normal Ollama (hidden, tray icon only) when it opens and closes it again when Fathom closes.
            say("  Closing the setup's copy of Ollama; Fathom starts it quietly (tray icon only) when it opens ...")
            _ollama_stop()
        (DATA / "installed-2.ok").write_text(json.dumps({"version": VERSION, "python": sys.version.split()[0],
                                                       "time": time.strftime("%Y-%m-%d %H:%M:%S"), "models": models_ok}), encoding="utf-8")
        (DATA / "build.txt").write_text(VERSION, encoding="ascii")   # Fathom.bat compares this with app/paths.py to know when to update
    except Exception as exc:
        say()
        say("SETUP DID NOT FINISH: " + str(exc))
        say(traceback.format_exc())
        return 1
    say()
    say("Fathom is ready. Starting it now...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
