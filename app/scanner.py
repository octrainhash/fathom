"""Import from a physical scanner, using Windows' own WIA (Windows Image Acquisition) service — the same system
component the built-in Windows Scan app and every ordinary scanner driver plug into. Fathom does not write a
hardware driver; it automates the driver your scanner's manufacturer already installed, through the OS's documented
scanning API. Windows only. Needs `pywin32` and a scanner that is turned on and already set up in Windows.

Besides WIA, two more scanner "languages" are spoken by Fathom's own code (see app/twain.py and app/sane.py): TWAIN (the older
driver standard, Windows) and SANE (Linux / Mac scanners, locally or over the network from a `saned` server). All three show up in one list."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from app import ops
from app.convert.core import ConvertError, Ctx, unique_path
from app.ops import Output, OutputPolicy, Task
from app.service import UserError

WIN = sys.platform == "win32"
WIA_SCANNER = 1
FMT_BMP = "{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}"


def _wia():
    if not WIN:
        raise UserError("Scanning is only available on Windows, through the scanner driver Windows already uses.")
    try:
        import win32com.client  # type: ignore
    except ImportError:
        raise UserError("Scanning needs the 'pywin32' add-on. Run: pip install pywin32   then restart Fathom.")
    try:
        return win32com.client.Dispatch("WIA.DeviceManager")
    except Exception as e:
        raise UserError(f"Windows' scanning service did not respond: {e}")


def list_scanners() -> list[dict]:
    dm = _wia()
    out = []
    try:
        infos = dm.DeviceInfos
        for i in range(1, infos.Count + 1):
            info = infos.Item(i)
            if int(info.Type) != WIA_SCANNER:
                continue
            name = ""
            try:
                name = info.Properties("Name").Value
            except Exception:
                name = f"Scanner {i}"
            out.append({"id": info.DeviceID, "name": name})
    except Exception as e:
        raise UserError(f"Could not list scanners: {e}")
    return out


def list_all(sane_host: str = "") -> dict:
    """Every scanner Fathom can reach through WIA, TWAIN and SANE. A backend that is not available is explained in `notes`, never fatal."""
    found, notes = [], []
    try:
        for d in list_scanners():
            found.append({"id": "wia:" + d["id"], "name": d["name"], "kind": "WIA"})
    except UserError as e:
        if WIN:
            notes.append(str(e))
    if WIN:
        try:
            from app import twain
            for n in twain.list_sources():
                found.append({"id": "twain:" + n, "name": n, "kind": "TWAIN"})
        except Exception as e:
            notes.append(f"TWAIN: {e}")
    try:
        from app import sane
        devs, how = sane.list_devices((sane_host or "").strip())
        for d in devs:
            found.append({"id": f"sane:{(sane_host or '').strip()}|{d.name}", "name": d.label, "kind": "SANE" + (f" @ {sane_host.strip()}" if how == "net" else "")})
    except Exception as e:
        if sane_host or not WIN:      # on Windows without a server address, SANE is simply not in play
            notes.append(f"SANE: {e}")
    return {"scanners": found, "notes": notes, "available": True}


def _set(props, name: str, value) -> None:
    try:
        props(name).Value = value
    except Exception:
        pass  # not every scanner supports every setting; carry on with its default


def scan_start(device_id: str, dpi: int, mode: str, out_kind: str, output: dict, extra: dict | None = None) -> dict:
    """mode: color | gray | bw. out_kind: jpg | png | pdf."""
    if not device_id:
        raise UserError("Choose a scanner.")
    dpi = max(75, min(1200, int(dpi or 300)))
    pol = OutputPolicy.from_dict(output)
    if pol.mode != "folder" or not pol.dir:
        raise UserError("Choose a folder to save the scan in (on the left).")

    extra = extra or {}
    if device_id.startswith("wia:"):
        device_id = device_id[4:]

    def save_image(ctx: Ctx, imgs: list) -> Output:
        """Shared by TWAIN and SANE: a list of Pillow pages -> jpg / png / one multi-page pdf, placed where the person chose."""
        d = ctx.scratch_dir()
        if out_kind == "pdf":
            dst = unique_path(d / "scan.pdf")
            rgb = [i.convert("RGB") for i in imgs]
            rgb[0].save(dst, "PDF", save_all=True, append_images=rgb[1:], resolution=float(dpi))
            made = [dst]
        else:
            made = []
            for n, im in enumerate(imgs, 1):
                ext = "png" if out_kind == "png" else "jpg"
                dst = unique_path(d / (f"scan.{ext}" if len(imgs) == 1 else f"scan {n}.{ext}"))
                (im.save(dst, "PNG", dpi=(dpi, dpi)) if ext == "png" else im.convert("RGB").save(dst, "JPEG", quality=92, dpi=(dpi, dpi)))
                made.append(dst)
        return Output(pol.place(made, Path("scan"), Path(".")), f"Scanned at {dpi} DPI." if len(imgs) == 1 else f"Scanned {len(imgs)} pages at {dpi} DPI.")

    def fn_twain(ctx: Ctx, task: Task) -> Output:
        from app import twain
        ctx.status("Scanning… the scanner's own light and motor take over now")
        try:
            imgs = twain.scan_images(device_id[6:], dpi, mode, bool(extra.get("ui")), bool(extra.get("pages")), ctx.check)
        except twain.TwainError as e:
            raise ConvertError(str(e))
        return save_image(ctx, imgs)

    def fn_sane(ctx: Ctx, task: Task) -> Output:
        from app import sane
        host, _, dev = device_id[5:].partition("|")
        try:
            backend = sane.open_backend(host)
            try:
                img = sane.scan(backend, dev, dpi, mode, ctx.check, ctx.status)
            finally:
                backend.exit()
        except sane.SaneError as e:
            raise ConvertError(str(e))
        return save_image(ctx, [img])

    if device_id.startswith("twain:"):
        return {"job": ops.start("scanner", "Scanning", [Task("Scanner", fn_twain, None, heavy=True)], workers=1).id}
    if device_id.startswith("sane:"):
        return {"job": ops.start("scanner", "Scanning", [Task("Scanner", fn_sane, None, heavy=True)], workers=1).id}

    def fn(ctx: Ctx, task: Task) -> Output:
        dm = _wia()
        try:
            dev = dm.DeviceInfos.Item(next(i for i in range(1, dm.DeviceInfos.Count + 1) if dm.DeviceInfos.Item(i).DeviceID == device_id)).Connect()
        except StopIteration:
            raise ConvertError("That scanner is no longer connected.")
        except Exception as e:
            raise ConvertError(f"Could not connect to the scanner: {e}")
        item = dev.Items.Item(1)
        intent = {"color": 1, "gray": 2, "bw": 4}.get(mode, 1)
        _set(item.Properties, "6146", intent)            # WIA_IPS_CUR_INTENT
        _set(item.Properties, "6147", dpi)                # Horizontal resolution
        _set(item.Properties, "6148", dpi)                # Vertical resolution
        ctx.status("Scanning… the scanner's own light and motor take over now")
        try:
            img = item.Transfer(FMT_BMP)
        except Exception as e:
            raise ConvertError(f"The scanner reported a problem: {e}")
        d = ctx.scratch_dir()
        tmp = d / "page.bmp"
        img.SaveFile(str(tmp))
        from PIL import Image
        im = Image.open(tmp)
        if out_kind == "pdf":
            dst = unique_path(d / "scan.pdf"); im.convert("RGB").save(dst, "PDF")
        elif out_kind == "png":
            dst = unique_path(d / "scan.png"); im.save(dst, "PNG")
        else:
            dst = unique_path(d / "scan.jpg"); im.convert("RGB").save(dst, "JPEG", quality=92)
        return Output(pol.place([dst], Path("scan"), Path(".")), f"Scanned at {dpi} DPI.")

    return {"job": ops.start("scanner", "Scanning", [Task("Scanner", fn, None, heavy=True)], workers=1).id}
