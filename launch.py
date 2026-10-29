# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Starts Fathom: the local engine + the desktop window. (Fathom.bat and the Desktop shortcut run this.)"""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.paths import logs_dir  # noqa: E402

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
TITLE = "Fathom"
APP_ID = "Fathom.Desktop.1"           # Windows groups the taskbar button by this, so Fathom gets its own icon and name instead of "Python"
ICON = ROOT / "assets" / "fathom.ico"


def note(text: str) -> None:
    with (logs_dir() / "launch.log").open("a", encoding="utf-8") as fh:
        fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")


def message_box(text: str) -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, text, "Fathom", 0x10 | 0x1000)
            return
        except Exception:
            pass
    print(text)


def lan_addresses() -> list[str]:
    """This computer's addresses on the local network (so a phone or tablet knows where to connect)."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.append(s.getsockname()[0])
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except Exception:
        pass
    return found


def make_certificate() -> tuple[Path, Path]:
    """A self-signed certificate so a phone can use https (browsers only allow the microphone and some features on https)."""
    from app.paths import data_root
    crt, key = data_root() / "serve-cert.pem", data_root() / "serve-key.pem"
    if crt.exists() and key.exists():
        return crt, key
    import datetime
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fathom")])
    sans = [x509.DNSName("localhost"), x509.DNSName(socket.gethostname())] + [x509.IPAddress(__import__("ipaddress").ip_address(a)) for a in lan_addresses()]
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False).sign(k, hashes.SHA256()))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        os.chmod(key, 0o600)
    except OSError:
        pass
    return crt, key


def serve_token() -> str:
    """In server mode the private link must stay the same between runs, so it is kept in a file (or set with FATHOM_TOKEN)."""
    from app.paths import data_root
    env = os.environ.get("FATHOM_TOKEN", "").strip()
    if env:
        return env
    f = data_root() / "serve-token.txt"
    if f.exists() and f.read_text(encoding="utf-8").strip():
        return f.read_text(encoding="utf-8").strip()
    tok = secrets.token_urlsafe(24)
    f.write_text(tok, encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return tok


def free_port() -> int:
    """Use the same port as last time when it is free: the browser part of the app keeps its saved settings per port, so a new random port every start made it forget them (the welcome tour came back every time)."""
    from app.paths import data_root
    saved = data_root() / "port.txt"
    try:
        want = int(saved.read_text().strip())
        if 1024 <= want <= 65535:
            with socket.socket() as s:
                s.bind(("127.0.0.1", want))
                return want
    except (OSError, ValueError):
        pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    try:
        saved.write_text(str(port))
    except OSError:
        pass
    return port


def server_python() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def wait_until_up(port: int, server: subprocess.Popen, timeout: float = 120.0, https: bool = False) -> bool:
    end = time.time() + timeout
    ctx = None
    if https:
        import ssl
        ctx = ssl._create_unverified_context()
    while time.time() < end:
        if server.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"{'https' if https else 'http'}://127.0.0.1:{port}/api/health", timeout=2, context=ctx) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def claim_taskbar_identity() -> None:
    """Gives this process its own app id, before any window exists, so the taskbar does not show it as Python."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        note("could not set the app id:\n" + traceback.format_exc())


def style_window(title: str) -> None:
    """Sets the taskbar / title-bar icon and a dark title bar (when Windows is in dark mode). Runs after the window appears."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = 0
    for _ in range(80):
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            break
        time.sleep(0.1)
    if not hwnd:
        return
    try:
        if ICON.exists():
            user32.LoadImageW.restype = wintypes.HANDLE
            for kind, size in ((1, 32), (0, 16)):   # ICON_BIG for the taskbar, ICON_SMALL for the title bar
                h = user32.LoadImageW(None, str(ICON), 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
                if h:
                    user32.SendMessageW(hwnd, 0x0080, kind, h)   # WM_SETICON
    except Exception:
        note("icon failed:\n" + traceback.format_exc())
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            dark = winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def open_window(url: str) -> bool:
    """The real desktop window (Edge WebView2). False if it is not available on this PC."""
    try:
        import webview
        from webview.dom import DOMEventHandler
    except Exception:
        note("pywebview not available:\n" + traceback.format_exc())
        return False
    window = webview.create_window(TITLE, url, width=1440, height=920, min_size=(1000, 680), background_color="#0e1020")

    def on_drop(event):  # files/folders dragged in from Explorer: pywebview gives their full paths
        transfer = event.get("dataTransfer") or event.get("domTransfer") or {}
        paths = [f.get("pywebviewFullPath") for f in transfer.get("files") or [] if f.get("pywebviewFullPath")]
        if paths:
            window.evaluate_js("window.Fathom && window.Fathom.addPaths(" + json.dumps(paths) + ")")

    def bind(win):
        threading.Thread(target=style_window, args=(TITLE,), daemon=True).start()
        try:
            win.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        except Exception:
            note("drag-and-drop hook failed:\n" + traceback.format_exc())

    try:
        webview.start(bind, window)
        return True
    except Exception:
        note("window failed:\n" + traceback.format_exc())
        return False


def parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(prog="launch.py", description="Starts Fathom. With --serve it runs as a small private web server so a phone, tablet or another computer can use it in a browser.")
    ap.add_argument("--serve", action="store_true", help="server mode: no window; open the printed link from any device on your network")
    ap.add_argument("--host", default="", help="address to listen on (server mode default 0.0.0.0 = every device on the network; 127.0.0.1 = this computer only)")
    ap.add_argument("--port", type=int, default=0, help="port (server mode default 8777)")
    ap.add_argument("--https", action="store_true", help="use https with a self-made certificate (needed for the microphone on phones)")
    ap.add_argument("--no-window", action="store_true", help="do not open a window or browser, just run")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    serve = args.serve
    claim_taskbar_identity()
    try:
        import fastapi, uvicorn  # noqa: F401
    except Exception:
        message_box("Fathom is not set up yet.\n\n" + ("Run Fathom.bat once (it asks for administrator permission) to finish the installation." if os.name == "nt" else "Run ./fathom.sh once to finish the installation."))
        return 1
    host = args.host or ("0.0.0.0" if serve else "127.0.0.1")
    port = args.port or (8777 if serve else free_port())
    token = serve_token() if serve else secrets.token_urlsafe(18)
    env = dict(os.environ, FATHOM_TOKEN=token, PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    cmd = [server_python(), "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port), "--log-level", "warning"]
    if serve:
        env["FATHOM_SERVE"] = "1"
        if args.https:
            crt, key = make_certificate()
            cmd += ["--ssl-certfile", str(crt), "--ssl-keyfile", str(key)]
    server_log = open(logs_dir() / "server.log", "a", encoding="utf-8", errors="replace")
    server = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=server_log, stderr=server_log, creationflags=NO_WINDOW)
    try:
        if not wait_until_up(port, server, https=serve and args.https):
            message_box(f"Fathom's engine did not start.\n\nDetails are in:\n{logs_dir() / 'server.log'}")
            return 1
        scheme = "https" if serve and args.https else "http"
        if serve:
            print("\nFathom is running. Open one of these links on any device on your network (keep the whole link, it is your password):\n", flush=True)
            print(f"   {scheme}://127.0.0.1:{port}/?token={token}   (this computer)", flush=True)
            if host in ("0.0.0.0", "::"):
                for ip in lan_addresses():
                    print(f"   {scheme}://{ip}:{port}/?token={token}", flush=True)
            if args.https:
                print("\n(The browser will warn about the certificate because Fathom made it itself; choose Advanced > Continue.)", flush=True)
            print("\nPress Ctrl+C to stop.", flush=True)
            note(f"serving on {host}:{port}")
            if not args.no_window and host in ("127.0.0.1", "localhost"):
                webbrowser.open(f"{scheme}://127.0.0.1:{port}/?token={token}")
            server.wait()
            return 0
        url = f"http://127.0.0.1:{port}/?token={token}"
        if args.no_window:
            print(url, flush=True)
            server.wait()
            return 0
        if not open_window(url):
            webbrowser.open(url)  # fallback: your normal browser; the Quit button in the page stops Fathom
            server.wait()
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        try:      # Ollama that Fathom started closes together with Fathom
            sys.path.insert(0, str(ROOT))
            from app import ollama_keep
            note("closing: " + ollama_keep.stop_if_ours())
        except Exception:
            pass
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except Exception:
                server.kill()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        text = traceback.format_exc()
        note(text)
        message_box("Fathom hit a problem while starting:\n\n" + text[-600:])
        raise SystemExit(1)
