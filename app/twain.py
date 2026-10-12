"""TWAIN scanner support for Windows, written from the TWAIN 2.x specification with ctypes (no third-party TWAIN package).

TWAIN is the older scanner interface many manufacturer drivers still provide, with features Windows' own scanning service lacks
(feeders, duplex, the maker's own scan window). Fathom talks to the TWAIN Data Source Manager (twaindsm.dll) and through it to the
driver ("data source") the scanner's maker installed.

Needs: Windows, 64-bit TWAIN DSM (twaindsm.dll - most scanner drivers install it; otherwise get it from twain.org), a TWAIN driver.
Written from the specification; it could not be tested against a physical scanner here."""
from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import POINTER, Structure, byref, c_int16, c_int32, c_uint16, c_uint32, c_void_p, sizeof
from typing import Callable

from PIL import Image

WIN = sys.platform == "win32"


class TwainError(Exception):
    pass


# ---- constants (TWAIN 2.x twain.h)
DG_CONTROL, DG_IMAGE = 0x1, 0x2
DAT_CAPABILITY, DAT_EVENT, DAT_IDENTITY, DAT_PARENT, DAT_PENDINGXFERS, DAT_USERINTERFACE = 0x1, 0x2, 0x3, 0x4, 0x5, 0x9
DAT_IMAGENATIVEXFER = 0x104
MSG_GET, MSG_GETFIRST, MSG_GETNEXT, MSG_SET, MSG_RESET = 0x1, 0x4, 0x5, 0x6, 0x7
MSG_OPENDSM, MSG_CLOSEDSM, MSG_OPENDS, MSG_CLOSEDS = 0x301, 0x302, 0x401, 0x402
MSG_DISABLEDS, MSG_ENABLEDS, MSG_PROCESSEVENT, MSG_ENDXFER = 0x501, 0x502, 0x601, 0x701
MSG_XFERREADY, MSG_CLOSEDSREQ, MSG_CLOSEDSOK = 0x101, 0x102, 0x103
RC_SUCCESS, RC_FAILURE, RC_CHECKSTATUS, RC_CANCEL, RC_DSEVENT, RC_NOTDSEVENT, RC_XFERDONE, RC_ENDOFLIST = range(8)
ICAP_PIXELTYPE, ICAP_XRESOLUTION, ICAP_YRESOLUTION = 0x101, 0x1118, 0x1119
TWTY_UINT16, TWTY_FIX32 = 4, 7
TWON_ONEVALUE = 5
TWPT_BW, TWPT_GRAY, TWPT_RGB = 0, 1, 2
DF_APP2 = 0x20000000


# ---- structures (TWAIN packs everything on 2-byte boundaries)
class TW_VERSION(Structure):
    _pack_ = 2
    _fields_ = [("MajorNum", c_uint16), ("MinorNum", c_uint16), ("Language", c_uint16), ("Country", c_uint16), ("Info", ctypes.c_char * 34)]


class TW_IDENTITY(Structure):
    _pack_ = 2
    _fields_ = [("Id", c_uint32), ("Version", TW_VERSION), ("ProtocolMajor", c_uint16), ("ProtocolMinor", c_uint16), ("SupportedGroups", c_uint32),
                ("Manufacturer", ctypes.c_char * 34), ("ProductFamily", ctypes.c_char * 34), ("ProductName", ctypes.c_char * 34)]


class TW_CAPABILITY(Structure):
    _pack_ = 2
    _fields_ = [("Cap", c_uint16), ("ConType", c_uint16), ("hContainer", c_void_p)]


class TW_ONEVALUE(Structure):
    _pack_ = 2
    _fields_ = [("ItemType", c_uint16), ("Item", c_uint32)]


class TW_USERINTERFACE(Structure):
    _pack_ = 2
    _fields_ = [("ShowUI", c_uint16), ("ModalUI", c_uint16), ("hParent", c_void_p)]


class TW_EVENT(Structure):
    _pack_ = 2
    _fields_ = [("pEvent", c_void_p), ("TWMessage", c_uint16)]


class TW_PENDINGXFERS(Structure):
    _pack_ = 2
    _fields_ = [("Count", c_uint16), ("EOJ", c_uint32)]


class _POINT(Structure):
    _fields_ = [("x", c_int32), ("y", c_int32)]


class _MSG(Structure):
    _fields_ = [("hwnd", c_void_p), ("message", ctypes.c_uint), ("wParam", c_void_p), ("lParam", c_void_p), ("time", c_uint32), ("pt", _POINT)]


def _text(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("cp1252", "replace")


def _load_dsm():
    if not WIN:
        raise TwainError("TWAIN scanner drivers only exist on Windows.")
    last = None
    cands = ["twaindsm.dll"]
    for base in (os.environ.get("SystemRoot", r"C:\Windows"), os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")):
        cands.append(os.path.join(base, "twaindsm.dll"))
    for pf in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
        if pf:
            cands.append(os.path.join(pf, "TWAIN DSM", "twaindsm.dll"))
    for c in cands:
        try:
            return ctypes.WinDLL(c)
        except OSError as e:
            last = e
    bits = "64-bit" if sys.maxsize > 2 ** 32 else "32-bit"
    raise TwainError(f"The {bits} TWAIN Data Source Manager (twaindsm.dll) is not installed. Installing your scanner's own software normally adds it; "
                     f"or download 'TWAIN DSM' from twain.org. ({last})")


class Twain:
    """One TWAIN session: open the manager, list or use scanners, close it again (use `with`)."""

    def __init__(self):
        self.dsm = _load_dsm()
        self.entry = self.dsm.DSM_Entry
        self.entry.restype = c_uint16
        self.entry.argtypes = [POINTER(TW_IDENTITY), POINTER(TW_IDENTITY), c_uint32, c_uint16, c_uint16, c_void_p]
        k, u = ctypes.windll.kernel32, ctypes.windll.user32
        k.GlobalAlloc.restype = c_void_p
        k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        k.GlobalLock.restype = c_void_p
        k.GlobalLock.argtypes = [c_void_p]
        k.GlobalUnlock.argtypes = [c_void_p]
        k.GlobalFree.argtypes = [c_void_p]
        k.GlobalSize.restype = ctypes.c_size_t
        k.GlobalSize.argtypes = [c_void_p]
        u.CreateWindowExW.restype = c_void_p
        u.CreateWindowExW.argtypes = [c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p, c_uint32, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, c_void_p, c_void_p, c_void_p, c_void_p]
        u.DestroyWindow.argtypes = [c_void_p]
        u.PeekMessageW.argtypes = [POINTER(_MSG), c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        u.TranslateMessage.argtypes = [POINTER(_MSG)]
        u.DispatchMessageW.argtypes = [POINTER(_MSG)]
        self.k, self.u = k, u
        self.hwnd = u.CreateWindowExW(0, "STATIC", "Fathom TWAIN", 0, 0, 0, 0, 0, None, None, None, None)
        self.app = TW_IDENTITY()
        self.app.Version.MajorNum, self.app.Version.MinorNum, self.app.Version.Language, self.app.Version.Country = 2, 1, 13, 1
        self.app.Version.Info = b"2.1"
        self.app.ProtocolMajor, self.app.ProtocolMinor = 2, 1
        self.app.SupportedGroups = DG_CONTROL | DG_IMAGE | DF_APP2
        self.app.Manufacturer, self.app.ProductFamily, self.app.ProductName = b"Fathom", b"Fathom", b"Fathom"
        hwnd = c_void_p(self.hwnd)
        if self.entry(byref(self.app), None, DG_CONTROL, DAT_PARENT, MSG_OPENDSM, byref(hwnd)) != RC_SUCCESS:
            self._close_window()
            raise TwainError("The TWAIN manager would not start.")
        self._hwnd_ref = hwnd
        self.opened = True

    def _close_window(self) -> None:
        if getattr(self, "hwnd", None):
            self.u.DestroyWindow(self.hwnd)
            self.hwnd = None

    def close(self) -> None:
        if getattr(self, "opened", False):
            self.entry(byref(self.app), None, DG_CONTROL, DAT_PARENT, MSG_CLOSEDSM, byref(self._hwnd_ref))
            self.opened = False
        self._close_window()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # -- scanners
    def sources(self) -> list[TW_IDENTITY]:
        out = []
        ident = TW_IDENTITY()
        rc = self.entry(byref(self.app), None, DG_CONTROL, DAT_IDENTITY, MSG_GETFIRST, byref(ident))
        while rc == RC_SUCCESS and len(out) < 64:
            copy = TW_IDENTITY()
            ctypes.memmove(byref(copy), byref(ident), sizeof(TW_IDENTITY))
            out.append(copy)
            rc = self.entry(byref(self.app), None, DG_CONTROL, DAT_IDENTITY, MSG_GETNEXT, byref(ident))
        return out

    def names(self) -> list[str]:
        return [_text(s.ProductName) for s in self.sources()]

    # -- helpers for talking to one driver
    def _ds(self, src: TW_IDENTITY, dg: int, dat: int, msg: int, data) -> int:
        return self.entry(byref(self.app), byref(src), dg, dat, msg, data)

    def _set_cap(self, src: TW_IDENTITY, cap: int, item_type: int, value: int) -> bool:
        h = self.k.GlobalAlloc(0x42, sizeof(TW_ONEVALUE))        # GHND
        if not h:
            return False
        try:
            p = self.k.GlobalLock(h)
            ov = TW_ONEVALUE(item_type, value & 0xFFFFFFFF)
            ctypes.memmove(p, byref(ov), sizeof(ov))
            self.k.GlobalUnlock(h)
            capab = TW_CAPABILITY(cap, TWON_ONEVALUE, h)
            return self._ds(src, DG_CONTROL, DAT_CAPABILITY, MSG_SET, byref(capab)) in (RC_SUCCESS, RC_CHECKSTATUS)
        finally:
            self.k.GlobalFree(h)

    def _dib_to_image(self, h) -> Image.Image:
        size = self.k.GlobalSize(h)
        p = self.k.GlobalLock(h)
        if not p or size < 40:
            raise TwainError("The scanner sent an empty picture.")
        try:
            dib = ctypes.string_at(p, size)
        finally:
            self.k.GlobalUnlock(h)
        header, bit_count, compression, clr_used = int.from_bytes(dib[0:4], "little"), int.from_bytes(dib[14:16], "little"), int.from_bytes(dib[16:20], "little"), int.from_bytes(dib[32:36], "little")
        palette = (clr_used or (1 << bit_count)) * 4 if bit_count <= 8 else clr_used * 4
        masks = 12 if compression == 3 and header == 40 else 0
        offset = 14 + header + palette + masks
        bmp = b"BM" + (14 + len(dib)).to_bytes(4, "little") + b"\0\0\0\0" + offset.to_bytes(4, "little") + dib
        import io
        im = Image.open(io.BytesIO(bmp))
        im.load()
        return im

    def acquire(self, name: str, dpi: int = 300, mode: str = "color", show_ui: bool = False, all_pages: bool = False,
                check: Callable[[], None] = lambda: None, timeout: float = 600.0) -> list[Image.Image]:
        src = next((s for s in self.sources() if _text(s.ProductName) == name), None)
        if src is None:
            raise TwainError("That scanner is no longer available.")
        if self.entry(byref(self.app), None, DG_CONTROL, DAT_IDENTITY, MSG_OPENDS, byref(src)) != RC_SUCCESS:
            raise TwainError("Could not open the scanner's driver. Is the scanner turned on and connected?")
        enabled = False
        images: list[Image.Image] = []
        try:
            ptype = {"color": TWPT_RGB, "gray": TWPT_GRAY, "bw": TWPT_BW}.get(mode, TWPT_RGB)
            self._set_cap(src, ICAP_PIXELTYPE, TWTY_UINT16, ptype)
            fixv = (dpi & 0xFFFF)                                  # TW_FIX32: whole = dpi, fraction = 0
            self._set_cap(src, ICAP_XRESOLUTION, TWTY_FIX32, fixv)
            self._set_cap(src, ICAP_YRESOLUTION, TWTY_FIX32, fixv)
            ui = TW_USERINTERFACE(1 if show_ui else 0, 0, self.hwnd)
            if self._ds(src, DG_CONTROL, DAT_USERINTERFACE, MSG_ENABLEDS, byref(ui)) not in (RC_SUCCESS, RC_CHECKSTATUS):
                raise TwainError("The scanner would not start scanning.")
            enabled = True
            end = time.time() + timeout
            ready = closing = False
            msg = _MSG()
            while not (ready or closing):
                check()
                if time.time() > end:
                    raise TwainError("The scanner did not respond in time.")
                if self.u.PeekMessageW(byref(msg), None, 0, 0, 1):
                    ev = TW_EVENT(ctypes.addressof(msg), 0)
                    rc = self._ds(src, DG_CONTROL, DAT_EVENT, MSG_PROCESSEVENT, byref(ev))
                    if rc == RC_DSEVENT:
                        if ev.TWMessage == MSG_XFERREADY:
                            ready = True
                        elif ev.TWMessage in (MSG_CLOSEDSREQ, MSG_CLOSEDSOK):
                            closing = True
                    else:
                        self.u.TranslateMessage(byref(msg))
                        self.u.DispatchMessageW(byref(msg))
                else:
                    time.sleep(0.02)
            while ready:
                check()
                h = c_void_p()
                rc = self._ds(src, DG_IMAGE, DAT_IMAGENATIVEXFER, MSG_GET, byref(h))
                if rc == RC_XFERDONE and h.value:
                    try:
                        images.append(self._dib_to_image(h.value))
                    finally:
                        self.k.GlobalFree(h.value)
                pend = TW_PENDINGXFERS()
                self._ds(src, DG_CONTROL, DAT_PENDINGXFERS, MSG_ENDXFER, byref(pend))
                if rc != RC_XFERDONE or not all_pages or pend.Count == 0:
                    if pend.Count:
                        self._ds(src, DG_CONTROL, DAT_PENDINGXFERS, MSG_RESET, byref(pend))
                    break
            return images
        finally:
            if enabled:
                self._ds(src, DG_CONTROL, DAT_USERINTERFACE, MSG_DISABLEDS, byref(TW_USERINTERFACE(0, 0, self.hwnd)))
            self.entry(byref(self.app), None, DG_CONTROL, DAT_IDENTITY, MSG_CLOSEDS, byref(src))


def list_sources() -> list[str]:
    with Twain() as t:
        return t.names()


def scan_images(name: str, dpi: int, mode: str, show_ui: bool, all_pages: bool, check: Callable[[], None] = lambda: None) -> list[Image.Image]:
    with Twain() as t:
        imgs = t.acquire(name, dpi, mode, show_ui, all_pages, check)
    if not imgs:
        raise TwainError("The scanner did not send a page (the scan was cancelled, or there was no paper).")
    return imgs
