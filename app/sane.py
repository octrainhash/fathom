"""SANE scanner support, written from the SANE standard (no scanner library needed for the network part).

Two ways to reach a scanner:
  * NetSane   - speaks the SANE *network protocol* (the one `saned` uses, TCP port 6566) in plain Python. This is how a Windows PC
                can use a scanner that is plugged into a Linux box, a Raspberry Pi, a print server or a Mac running saned.
  * LibSane   - talks to the system's own libsane (Linux / macOS) through ctypes, for scanners plugged into this computer.

Both give the same small interface (devices / open / options / set / parameters / start+read), and `scan()` turns the result into a
Pillow image. Written from the published standard; it has been tested against a simulated saned, not against every real scanner."""
from __future__ import annotations

import ctypes
import ctypes.util
import socket
import struct
import sys
from dataclasses import dataclass, field
from typing import Callable, Iterator

from PIL import Image

# ---- numbers from the SANE standard
ST_GOOD, ST_UNSUPPORTED, ST_CANCELLED, ST_BUSY, ST_INVAL, ST_EOF, ST_JAMMED, ST_NO_DOCS, ST_COVER_OPEN, ST_IO_ERROR, ST_NO_MEM, ST_ACCESS_DENIED = range(12)
STATUS_TEXT = {1: "the scanner does not support that", 2: "the scan was cancelled", 3: "the scanner is busy", 4: "invalid setting",
               6: "paper jam", 7: "no paper in the feeder", 8: "the scanner cover is open", 9: "communication error with the scanner",
               10: "out of memory", 11: "access denied (the scanner needs a password, which Fathom does not support yet)"}
T_BOOL, T_INT, T_FIXED, T_STRING, T_BUTTON, T_GROUP = range(6)
UNIT_DPI = 4
CAP_SOFT_SELECT, CAP_INACTIVE = 1, 32
C_NONE, C_RANGE, C_WORD_LIST, C_STRING_LIST = range(4)
ACT_GET, ACT_SET, ACT_AUTO = 0, 1, 2
INFO_RELOAD_OPTIONS = 2
FRAME_GRAY, FRAME_RGB, FRAME_RED, FRAME_GREEN, FRAME_BLUE = range(5)
VERSION_CODE = (1 << 24) | (0 << 16) | 3        # SANE 1.0, network protocol revision 3
NET_PORT = 6566


class SaneError(Exception):
    pass


def _status_error(code: int) -> SaneError:
    return SaneError(STATUS_TEXT.get(code, f"the scanner reported error {code}"))


def fix(x: float) -> int:
    return int(round(x * 65536))


def unfix(v: int) -> float:
    return v / 65536.0


@dataclass
class Option:
    index: int
    name: str
    title: str
    desc: str
    type: int
    unit: int
    size: int
    cap: int
    ctype: int
    constraint: object = None      # (min, max, quant) | [words] | [strings] | None

    @property
    def active(self) -> bool:
        return not (self.cap & CAP_INACTIVE) and bool(self.cap & CAP_SOFT_SELECT)


@dataclass
class Params:
    format: int
    last_frame: bool
    bytes_per_line: int
    pixels_per_line: int
    lines: int
    depth: int


@dataclass
class Device:
    name: str
    vendor: str = ""
    model: str = ""
    type: str = ""

    @property
    def label(self) -> str:
        return (f"{self.vendor} {self.model}").strip() or self.name


# =====================================================================================================  network protocol
class NetSane:
    def __init__(self, host: str, port: int = NET_PORT, timeout: float = 15.0, user: str = "fathom"):
        self.host, self.port, self.timeout = host, port, timeout
        try:
            self.sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as e:
            raise SaneError(f"Could not reach a SANE server at {host}:{port} ({e}). On that computer, saned must be running and allow this PC.")
        self.sock.settimeout(timeout)
        self.byte_order = "little"
        self._send(self._word(0) + self._word(VERSION_CODE) + self._string(user))        # NET_INIT
        status = self._rword()
        self._rword()                                                                    # server's version code
        if status != ST_GOOD:
            raise _status_error(status)

    # -- wire primitives (everything big-endian; a string is a length word + bytes incl. the final NUL)
    @staticmethod
    def _word(v: int) -> bytes:
        return struct.pack(">I", v & 0xFFFFFFFF)

    @classmethod
    def _string(cls, s: str | None) -> bytes:
        if s is None:
            return cls._word(0)
        b = s.encode("latin-1", "replace") + b"\0"
        return cls._word(len(b)) + b

    def _send(self, data: bytes) -> None:
        try:
            self.sock.sendall(data)
        except OSError as e:
            raise SaneError(f"Lost the connection to the SANE server ({e}).")

    def _recv(self, n: int, sock: socket.socket | None = None) -> bytes:
        sock = sock or self.sock
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
            except OSError as e:
                raise SaneError(f"Lost the connection to the SANE server ({e}).")
            if not chunk:
                raise SaneError("The SANE server closed the connection.")
            buf += chunk
        return bytes(buf)

    def _rword(self) -> int:
        return struct.unpack(">I", self._recv(4))[0]

    def _rsword(self) -> int:
        return struct.unpack(">i", self._recv(4))[0]

    def _rstring(self) -> str:
        n = self._rword()
        if n > 1 << 20:
            raise SaneError("The SANE server sent something Fathom does not understand.")
        raw = self._recv(n) if n else b""
        return raw.rstrip(b"\0").decode("latin-1")

    # -- calls
    def devices(self) -> list[Device]:
        self._send(self._word(1))
        status = self._rword()
        if status != ST_GOOD:
            raise _status_error(status)
        out = []
        for _ in range(self._rword()):                      # array of pointers (the last one is NULL)
            if self._rword():                               # pointer is not NULL
                out.append(Device(self._rstring(), self._rstring(), self._rstring(), self._rstring()))
        return out

    def open(self, name: str) -> int:
        self._send(self._word(2) + self._string(name))
        status, handle, resource = self._rword(), self._rword(), self._rstring()
        if resource:
            raise SaneError("This scanner needs a username and password, which Fathom does not support yet.")
        if status != ST_GOOD:
            raise _status_error(status)
        return handle

    def close(self, handle: int) -> None:
        self._send(self._word(3) + self._word(handle))
        self._rword()

    def options(self, handle: int) -> list[Option]:
        self._send(self._word(4) + self._word(handle))
        self._rword()                                       # number of options
        out = []
        for i in range(self._rword()):
            if not self._rword():                           # NULL pointer
                continue
            name, title, desc = self._rstring(), self._rstring(), self._rstring()
            typ, unit, size, cap, ctype = (self._rword() for _ in range(5))
            constraint: object = None
            if ctype == C_STRING_LIST:
                constraint = [self._rstring() for _ in range(self._rword())]
                constraint = [s for s in constraint if s]
            elif ctype == C_WORD_LIST:
                n = self._rword()
                words = [self._rsword() for _ in range(n)]
                constraint = words[1:] if words else []     # the first word is the count again
            elif ctype == C_RANGE:
                if self._rword():
                    constraint = (self._rsword(), self._rsword(), self._rsword())
            out.append(Option(i, name, title, desc, typ, unit, size, cap, ctype, constraint))
        return out

    def set_option(self, handle: int, opt: Option, value) -> int:
        """Sets an option; returns the 'info' flags (e.g. INFO_RELOAD_OPTIONS)."""
        if opt.type == T_STRING:
            raw = str(value).encode("latin-1", "replace") + b"\0"
            raw = raw.ljust(max(opt.size, len(raw)), b"\0")
            body = self._word(len(raw)) + self._word(len(raw)) + raw                # value_size, array length, bytes
        else:
            body = self._word(4) + self._word(1) + self._word(int(value))           # one word
        self._send(self._word(5) + self._word(handle) + self._word(opt.index) + self._word(ACT_SET) + self._word(opt.type) + body)
        status, info = self._rword(), self._rword()
        self._rword()                                       # value type
        self._rword()                                       # value size
        n = self._rword()                                   # the returned value (array)
        self._recv(n if opt.type == T_STRING else n * 4) if n else None
        resource = self._rstring()
        if resource:
            raise SaneError("The scanner asked for a password, which Fathom does not support yet.")
        if status != ST_GOOD:
            raise _status_error(status)
        return info

    def parameters(self, handle: int) -> Params:
        self._send(self._word(6) + self._word(handle))
        status = self._rword()
        vals = [self._rsword() for _ in range(6)]
        if status != ST_GOOD:
            raise _status_error(status)
        return Params(vals[0], bool(vals[1]), vals[2], vals[3], vals[4], vals[5])

    def start(self, handle: int) -> Iterator[bytes]:
        """Starts one frame and yields its data in pieces. Data comes over a second connection."""
        self._send(self._word(7) + self._word(handle))
        status, port, order, resource = self._rword(), self._rword(), self._rword(), self._rstring()
        if resource:
            raise SaneError("The scanner asked for a password, which Fathom does not support yet.")
        if status != ST_GOOD:
            raise _status_error(status)
        self.byte_order = "little" if order == 0x1234 else "big"
        data = socket.create_connection((self.host, port), timeout=self.timeout)
        data.settimeout(max(self.timeout, 120.0))           # the scanner head may take a while to warm up
        try:
            while True:
                n = struct.unpack(">I", self._recv(4, data))[0]
                if n == 0xFFFFFFFF:                          # end of the frame; some servers add one status byte
                    try:
                        data.settimeout(1.0)
                        tail = data.recv(1)
                        if tail and tail[0] not in (0, ST_EOF):
                            raise _status_error(tail[0])
                    except (socket.timeout, OSError):
                        pass
                    return
                if n:
                    yield self._recv(n, data)
        finally:
            data.close()

    def cancel(self, handle: int) -> None:
        try:
            self._send(self._word(8) + self._word(handle))
            self._rword()
        except SaneError:
            pass

    def exit(self) -> None:
        try:
            self._send(self._word(10))
        except SaneError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


# =====================================================================================================  local libsane
class _CDevice(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p), ("vendor", ctypes.c_char_p), ("model", ctypes.c_char_p), ("type", ctypes.c_char_p)]


class _CRange(ctypes.Structure):
    _fields_ = [("min", ctypes.c_int), ("max", ctypes.c_int), ("quant", ctypes.c_int)]


class _CConstraint(ctypes.Union):
    _fields_ = [("string_list", ctypes.POINTER(ctypes.c_char_p)), ("word_list", ctypes.POINTER(ctypes.c_int)), ("range", ctypes.POINTER(_CRange))]


class _COption(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p), ("title", ctypes.c_char_p), ("desc", ctypes.c_char_p), ("type", ctypes.c_int), ("unit", ctypes.c_int),
                ("size", ctypes.c_int), ("cap", ctypes.c_int), ("constraint_type", ctypes.c_int), ("constraint", _CConstraint)]


class _CParams(ctypes.Structure):
    _fields_ = [("format", ctypes.c_int), ("last_frame", ctypes.c_int), ("bytes_per_line", ctypes.c_int), ("pixels_per_line", ctypes.c_int),
                ("lines", ctypes.c_int), ("depth", ctypes.c_int)]


def _lat(b: bytes | None) -> str:
    return (b or b"").decode("latin-1")


class LibSane:
    byte_order = sys.byteorder

    def __init__(self):
        name = ctypes.util.find_library("sane")
        if not name:
            for cand in ("libsane.so.1", "libsane.1.dylib", "libsane.dylib", "/opt/homebrew/lib/libsane.1.dylib", "/usr/local/lib/libsane.1.dylib"):
                try:
                    ctypes.CDLL(cand)
                    name = cand
                    break
                except OSError:
                    continue
        if not name:
            raise SaneError("SANE is not installed on this computer (libsane was not found).")
        try:
            self.lib = ctypes.CDLL(name)
        except OSError as e:
            raise SaneError(f"Could not load SANE ({e}).")
        L = self.lib
        L.sane_init.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_void_p]
        L.sane_get_devices.argtypes = [ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(_CDevice))), ctypes.c_int]
        L.sane_open.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        L.sane_close.argtypes = [ctypes.c_void_p]
        L.sane_get_option_descriptor.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.sane_get_option_descriptor.restype = ctypes.POINTER(_COption)
        L.sane_control_option.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        L.sane_get_parameters.argtypes = [ctypes.c_void_p, ctypes.POINTER(_CParams)]
        L.sane_start.argtypes = [ctypes.c_void_p]
        L.sane_read.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        L.sane_cancel.argtypes = [ctypes.c_void_p]
        ver = ctypes.c_int(0)
        st = L.sane_init(ctypes.byref(ver), None)
        if st != ST_GOOD:
            raise _status_error(st)

    def devices(self) -> list[Device]:
        lst = ctypes.POINTER(ctypes.POINTER(_CDevice))()
        st = self.lib.sane_get_devices(ctypes.byref(lst), 1)
        if st != ST_GOOD:
            raise _status_error(st)
        out, i = [], 0
        while lst and lst[i]:
            d = lst[i].contents
            out.append(Device(_lat(d.name), _lat(d.vendor), _lat(d.model), _lat(d.type)))
            i += 1
        return out

    def open(self, name: str):
        h = ctypes.c_void_p()
        st = self.lib.sane_open(name.encode("latin-1"), ctypes.byref(h))
        if st != ST_GOOD:
            raise _status_error(st)
        return h

    def close(self, handle) -> None:
        self.lib.sane_close(handle)

    def options(self, handle) -> list[Option]:
        out, i = [], 0
        while True:
            p = self.lib.sane_get_option_descriptor(handle, i)
            if not p:
                break
            d = p.contents
            constraint: object = None
            if d.constraint_type == C_STRING_LIST and d.constraint.string_list:
                constraint, k = [], 0
                while d.constraint.string_list[k]:
                    constraint.append(_lat(d.constraint.string_list[k]))
                    k += 1
            elif d.constraint_type == C_WORD_LIST and d.constraint.word_list:
                n = d.constraint.word_list[0]
                constraint = [d.constraint.word_list[k] for k in range(1, n + 1)]
            elif d.constraint_type == C_RANGE and d.constraint.range:
                r = d.constraint.range.contents
                constraint = (r.min, r.max, r.quant)
            out.append(Option(i, _lat(d.name), _lat(d.title), _lat(d.desc), d.type, d.unit, d.size, d.cap, d.constraint_type, constraint))
            i += 1
        return out

    def set_option(self, handle, opt: Option, value) -> int:
        info = ctypes.c_int(0)
        if opt.type == T_STRING:
            raw = str(value).encode("latin-1", "replace") + b"\0"
            buf = ctypes.create_string_buffer(raw, max(opt.size, len(raw)))
            st = self.lib.sane_control_option(handle, opt.index, ACT_SET, buf, ctypes.byref(info))
        else:
            v = ctypes.c_int(int(value))
            st = self.lib.sane_control_option(handle, opt.index, ACT_SET, ctypes.byref(v), ctypes.byref(info))
        if st != ST_GOOD:
            raise _status_error(st)
        return info.value

    def parameters(self, handle) -> Params:
        p = _CParams()
        st = self.lib.sane_get_parameters(handle, ctypes.byref(p))
        if st != ST_GOOD:
            raise _status_error(st)
        return Params(p.format, bool(p.last_frame), p.bytes_per_line, p.pixels_per_line, p.lines, p.depth)

    def start(self, handle) -> Iterator[bytes]:
        st = self.lib.sane_start(handle)
        if st != ST_GOOD:
            raise _status_error(st)
        buf = ctypes.create_string_buffer(1 << 16)
        got = ctypes.c_int(0)
        while True:
            st = self.lib.sane_read(handle, buf, len(buf), ctypes.byref(got))
            if got.value:
                yield buf.raw[: got.value]
            if st == ST_EOF:
                return
            if st != ST_GOOD:
                raise _status_error(st)

    def cancel(self, handle) -> None:
        self.lib.sane_cancel(handle)

    def exit(self) -> None:
        try:
            self.lib.sane_exit()
        except Exception:
            pass


# =====================================================================================================  scanning
def _find(options: list[Option], *names: str) -> Option | None:
    for n in names:
        for o in options:
            if o.name == n and o.type not in (T_GROUP, T_BUTTON):
                return o
    return None


def _pick_mode(allowed: list[str], mode: str) -> str | None:
    words = {"color": ("color", "colour", "rgb"), "gray": ("gray", "grey"), "bw": ("lineart", "binary", "black", "bw", "halftone")}[mode if mode in ("color", "gray", "bw") else "color"]
    for w in words:
        for a in allowed:
            if w in a.lower():
                return a
    return None


def configure(backend, handle, dpi: int, mode: str) -> None:
    """Colour mode and resolution. Anything this scanner does not offer is left at its own default."""
    options = backend.options(handle)
    m = _find(options, "mode")
    if m and m.active and m.type == T_STRING and isinstance(m.constraint, list):
        choice = _pick_mode(m.constraint, mode)
        if choice:
            try:
                if backend.set_option(handle, m, choice) & INFO_RELOAD_OPTIONS:
                    options = backend.options(handle)       # the list of available settings can change with the mode
            except SaneError:
                pass
    r = _find(options, "resolution", "x-resolution")
    if r and r.active and r.type in (T_INT, T_FIXED):
        target = dpi
        c = r.constraint
        if isinstance(c, list) and c:
            allowed = [unfix(v) if r.type == T_FIXED else v for v in c]
            target = min(allowed, key=lambda v: abs(v - dpi))
        elif isinstance(c, tuple):
            lo, hi, q = (unfix(v) if r.type == T_FIXED else v for v in c)
            target = max(lo, min(hi, dpi))
            if q:
                target = lo + round((target - lo) / q) * q
        try:
            backend.set_option(handle, r, fix(target) if r.type == T_FIXED else int(round(target)))
        except SaneError:
            pass


def _frame_to_image(p: Params, data: bytes, order: str) -> Image.Image:
    bpl, w, depth = p.bytes_per_line, p.pixels_per_line, p.depth
    h = p.lines if p.lines > 0 else len(data) // max(1, bpl)
    if h <= 0 or w <= 0:
        raise SaneError("The scanner sent no picture.")
    data = data[: bpl * h].ljust(bpl * h, b"\xff")
    if depth == 16:                                          # keep the high byte of each sample
        hi = 1 if order == "little" else 0
        data = data[hi::2]
        bpl //= 2
        depth = 8
    if p.format == FRAME_RGB:
        if depth != 8:
            raise SaneError(f"This scanner's {depth}-bit colour format is not supported yet.")
        return Image.frombytes("RGB", (w, h), data, "raw", "RGB", bpl, 1)
    if depth == 1:
        return Image.frombytes("1", (w, h), data, "raw", "1;I", bpl, 1).convert("L")     # SANE: bit 1 = black
    if depth == 8:
        return Image.frombytes("L", (w, h), data, "raw", "L", bpl, 1)
    raise SaneError(f"This scanner's {depth}-bit format is not supported yet.")


def scan(backend, device: str, dpi: int = 300, mode: str = "color", check: Callable[[], None] = lambda: None,
         status: Callable[[str], None] = lambda s: None) -> Image.Image:
    handle = backend.open(device)
    try:
        configure(backend, handle, dpi, mode)
        planes: dict[int, Image.Image] = {}
        while True:
            check()
            p = backend.parameters(handle)
            chunks = []
            status("Scanning… the scanner's own light and motor take over now")
            try:
                for piece in backend.start(handle):
                    check()
                    chunks.append(piece)
            except BaseException:
                backend.cancel(handle)
                raise
            data = b"".join(chunks)
            if p.format in (FRAME_RED, FRAME_GREEN, FRAME_BLUE):
                p2 = Params(FRAME_GRAY, p.last_frame, p.bytes_per_line, p.pixels_per_line, p.lines, p.depth)
                planes[p.format] = _frame_to_image(p2, data, backend.byte_order)
                if p.last_frame:
                    return Image.merge("RGB", (planes[FRAME_RED], planes[FRAME_GREEN], planes[FRAME_BLUE]))
                continue
            return _frame_to_image(p, data, backend.byte_order)
    finally:
        try:
            backend.close(handle)
        except Exception:
            pass


def list_devices(host: str = "") -> tuple[list[Device], str]:
    """(devices, how) - how is 'net' for a SANE server or 'local' for this computer's libsane."""
    if host:
        h, _, port = host.partition(":")
        b = NetSane(h.strip(), int(port) if port.isdigit() else NET_PORT)
        try:
            return b.devices(), "net"
        finally:
            b.exit()
    b = LibSane()
    try:
        return b.devices(), "local"
    finally:
        b.exit()


def open_backend(host: str = ""):
    if host:
        h, _, port = host.partition(":")
        return NetSane(h.strip(), int(port) if port.isdigit() else NET_PORT)
    return LibSane()
