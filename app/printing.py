"""Digital to paper (Print) and paper to paper (Copy = scan, then print).

* Windows: printers are listed with PowerShell / pywin32. Pictures are drawn straight to the printer when pywin32 is installed (so size, fit and
  copies are exact); every other file is handed to the program Windows uses for it ("print to" verb), which is how Explorer's own Print works.
* macOS and Linux: CUPS ('lp' / 'lpstat'). Documents that CUPS cannot print itself are turned into a PDF first.
Nothing is changed on the file; printing only reads it."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app import ops
from app.convert import formats
from app.convert.core import ConvertError, Ctx, Opts, no_window_flags
from app.ops import Output, Task
from app.opsvc import expand_sources
from app.service import UserError

WIN = sys.platform.startswith("win")


def _run(cmd: list[str], timeout: float = 25) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=no_window_flags() if WIN else 0)
        return p.returncode, (p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")).strip()
    except FileNotFoundError:
        return 127, "missing"
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def list_printers() -> dict:
    printers: list[dict] = []
    notes: list[str] = []
    if WIN:
        ps = ("Get-CimInstance Win32_Printer | Select-Object Name,Default,PrinterStatus,WorkOffline,PortName | ConvertTo-Json -Compress")
        code, out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])
        if code == 0 and out.strip():
            try:
                data = json.loads(out)
                for x in ([data] if isinstance(data, dict) else data):
                    printers.append({"name": x.get("Name", ""), "default": bool(x.get("Default")), "offline": bool(x.get("WorkOffline")), "port": x.get("PortName", "")})
            except ValueError:
                pass
        if not printers:
            try:
                import win32print  # type: ignore
                default = win32print.GetDefaultPrinter()
                for fl in (2, 4):
                    for _f, _d, name, _c in win32print.EnumPrinters(fl, None, 1):
                        if not any(p["name"] == name for p in printers):
                            printers.append({"name": name, "default": name == default, "offline": False, "port": ""})
            except Exception:
                pass
    else:
        code, out = _run(["lpstat", "-p", "-d"])
        if code == 127:
            notes.append("Printing needs CUPS ('lp' and 'lpstat'). On Linux install it with your package manager (for example: sudo apt install cups).")
        default = ""
        for line in out.splitlines():
            m = re.match(r"printer (\S+) (.*)", line)
            if m:
                printers.append({"name": m.group(1), "default": False, "offline": "disabled" in m.group(2), "port": ""})
            m = re.match(r"system default destination: (\S+)", line)
            if m:
                default = m.group(1)
        for p in printers:
            p["default"] = p["name"] == default
    printers.sort(key=lambda p: (not p["default"], p["name"].lower()))
    return {"printers": printers, "notes": notes, "windows": WIN}


def _page_ranges(spec: str, path: Path | None = None) -> str:
    """what the printer program understands (1-3,5) from anything pagesel understands (odd, last, every 2 ...); words need the file's page count"""
    spec = (spec or "").strip()
    if not spec:
        return ""
    if re.fullmatch(r"(\d+(-\d+)?)([,; ]\s*\d+(-\d+)?)*", spec):
        return spec.replace(";", ",").replace(" ", "")
    from app import pagesel
    pagesel.parse(spec, 100000)                      # says so when the words make no sense
    if path is None:
        return ""
    total = 0
    try:
        from app.pdfview import info
        total = info(str(path)).get("pages", 0)
    except Exception:
        pass
    if not total:
        raise UserError("Page words like 'odd' or 'last' need a PDF (Fathom counts its pages). For other files write numbers like 1-3,5.")
    return pagesel.compact(pagesel.parse(spec, total))


# ---------------------------------------------------------------- Windows
def _win_print_image(path: Path, printer: str, copies: int, fit: str, color: bool, landscape: str) -> None:
    import win32con  # type: ignore
    import win32print  # type: ignore
    import win32ui  # type: ignore
    from PIL import Image, ImageWin
    im = Image.open(path)
    im = im.convert("RGB" if color else "L")
    if not color:
        im = im.convert("RGB")
    dc = win32ui.CreateDC()
    dc.CreatePrinterDC(printer)
    try:
        pw, ph = dc.GetDeviceCaps(win32con.HORZRES), dc.GetDeviceCaps(win32con.VERTRES)
        iw, ih = im.size
        rotate = landscape == "landscape" or (landscape == "auto" and (iw > ih) != (pw > ph))
        if rotate:
            im = im.rotate(90, expand=True)
            iw, ih = im.size
        scale = min(pw / iw, ph / ih) if fit != "fill" else max(pw / iw, ph / ih)
        if fit == "actual":
            dpi = im.info.get("dpi", (96, 96))[0] or 96
            scale = dc.GetDeviceCaps(win32con.LOGPIXELSX) / dpi
        w, h = int(iw * scale), int(ih * scale)
        x, y = (pw - w) // 2, (ph - h) // 2
        dc.StartDoc(path.name)
        for _ in range(max(1, copies)):
            dc.StartPage()
            ImageWin.Dib(im).draw(dc.GetHandleOutput(), (x, y, x + w, y + h))
            dc.EndPage()
        dc.EndDoc()
    finally:
        dc.DeleteDC()


def _win_printto(path: Path, printer: str, copies: int) -> None:
    for _ in range(max(1, copies)):
        ps = f"Start-Process -FilePath '{str(path).replace(chr(39), chr(39) * 2)}' -Verb PrintTo -ArgumentList '\"{printer.replace(chr(39), chr(39) * 2)}\"' -WindowStyle Hidden"
        code, out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=60)
        if code != 0:
            ps2 = f"Start-Process -FilePath '{str(path).replace(chr(39), chr(39) * 2)}' -Verb Print -WindowStyle Hidden"
            code, out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps2], timeout=60)
            if code != 0:
                raise ConvertError("Windows has no program set up to print this kind of file. " + out[:200])
        time.sleep(1.5)


# ---------------------------------------------------------------- CUPS
def _cups_print(path: Path, printer: str, copies: int, o: dict) -> str:
    cmd = ["lp"]
    if printer:
        cmd += ["-d", printer]
    cmd += ["-n", str(max(1, copies)), "-t", path.name[:60]]
    if o.get("color") is False:
        cmd += ["-o", "print-color-mode=monochrome", "-o", "ColorModel=Gray"]
    if o.get("duplex") in ("long", "short"):
        cmd += ["-o", "sides=two-sided-long-edge" if o["duplex"] == "long" else "sides=two-sided-short-edge"]
    if o.get("paper"):
        cmd += ["-o", f"media={o['paper']}"]
    if o.get("orientation") == "landscape":
        cmd += ["-o", "landscape"]
    if o.get("fit", "fit") == "fit":
        cmd += ["-o", "fit-to-page"]
    pages = _page_ranges(o.get("pages", ""), path)
    if pages:
        cmd += ["-P", pages]
    cmd.append(str(path))
    code, out = _run(cmd, 60)
    if code == 127:
        raise ConvertError("Printing needs CUPS ('lp'). Install it first (sudo apt install cups).")
    if code != 0:
        raise ConvertError("The printer system said: " + (out[:300] or "failed"))
    return out


CUPS_OK = {"pdf", "png", "jpg", "gif", "tif", "bmp", "txt", "webp"}


def print_file(path: Path, printer: str, copies: int, o: dict, ctx: Ctx) -> str:
    """Sends one file to the printer; returns a short note."""
    fmt = formats.detect(path)
    cat = formats.category(fmt)
    copies = max(1, min(999, int(copies or 1)))
    if WIN:
        if not printer:
            raise ConvertError("Choose a printer.")
        if cat == "image" and fmt != "gif" or fmt in ("png", "jpg", "bmp", "tif"):
            try:
                _win_print_image(path, printer, copies, str(o.get("fit", "fit")), o.get("color") is not False, str(o.get("orientation", "auto")))
                return "Sent to the printer."
            except ImportError:
                pass
        _win_printto(path, printer, copies)
        return "Sent to the printer through the program Windows uses for this file."
    tmp = path
    if fmt not in CUPS_OK and cat in ("document", "presentation", "spreadsheet", "ebook", "text", "data", "image"):
        from app.convert.engines import convert_file
        ctx.status("Turning it into a PDF to print")
        outs, _n = convert_file(path, fmt, "pdf", Opts(), ctx)
        tmp = outs[0]
    elif fmt not in CUPS_OK:
        raise ConvertError("This kind of file cannot be printed (it is not a document or picture).")
    _cups_print(tmp, printer, copies, o)
    return "Sent to the printer."


def print_start(paths: list[str], recursive: bool, printer: str, copies: int, o: dict) -> dict:
    files = expand_sources(paths, recursive, skip_junk=True)
    if not files:
        raise UserError("Add the files to print.")
    _page_ranges(o.get("pages", ""))

    def make(src: Path):
        def fn(ctx: Ctx, task: Task) -> Output:
            return Output([], print_file(src, printer, copies, o, ctx) + f" ({copies} cop{'ies' if copies != 1 else 'y'})")
        return fn

    tasks = [Task(s.name, make(s), s) for s, _r in files]
    return {"job": ops.start("print", "Printing", tasks, workers=1).id, "count": len(tasks)}


def copy_start(scanner_id: str, printer: str, copies: int, dpi: int, mode: str, host: str, o: dict) -> dict:
    """Paper to paper: scans one page (or the whole feeder with TWAIN) into a scratch folder, then prints it. Nothing is kept unless you ask."""
    from app import scanner
    if not scanner_id:
        raise UserError("Choose a scanner.")
    if not printer and WIN:
        raise UserError("Choose a printer.")
    keep = str(o.get("keep_dir") or "").strip()

    def fn(ctx: Ctx, task: Task) -> Output:
        work = Path(keep) if keep else ctx.scratch_dir()
        work.mkdir(parents=True, exist_ok=True)
        ctx.status("Scanning the page")
        r = scanner.scan_start(scanner_id, dpi, mode, "pdf", {"mode": "folder", "dir": str(work), "keep_structure": False}, {"ui": False, "pages": bool(o.get("feeder"))})
        job = ops.OPJOBS[r["job"]]
        while job.status in ("starting", "running"):
            ctx.check()
            time.sleep(0.4)
        bad = [x for x in job.results if x["status"] == "error"]
        if bad or not job.results:
            raise ConvertError(bad[0]["error"] if bad else "The scanner did not return a page.")
        files = [Path(p["path"]) for x in job.results for p in x["outputs"]]
        ctx.status("Printing the copy")
        for f in files:
            print_file(f, printer, copies, {"color": mode != "bw" and mode != "gray", **o}, ctx)
        return Output([], f"Copied: scanned {len(files)} file{'s' if len(files) != 1 else ''} and printed {copies} cop{'ies' if copies != 1 else 'y'} of each." + (f" The scan was kept in {keep}." if keep else ""))

    return {"job": ops.start("copy", "Copying", [Task("Photocopy", fn, None)], workers=1).id}
