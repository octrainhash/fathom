"""Torrenting: a plain, neutral BitTorrent client plus tools to make and read .torrent files, and a simple link downloader.

* Making and reading .torrent files needs nothing extra (pure Python).
* Downloading and seeding uses libtorrent (installed by Fathom's setup: pip install libtorrent). If it is missing the screen says so in plain words.
* Fathom has no search engine for torrents and does not point at any content; you bring the magnet link or .torrent file.
  Only download and share files you have the right to."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from app import ops
from app.convert.core import ConvertError, Ctx
from app.ops import Output, OutputPolicy, Task
from app.paths import data_root
from app.service import UserError

# ================================================================== bencode (the .torrent format)


def bencode(x) -> bytes:
    if isinstance(x, bool):
        x = int(x)
    if isinstance(x, int):
        return b"i%de" % x
    if isinstance(x, str):
        x = x.encode("utf-8")
    if isinstance(x, (bytes, bytearray)):
        return b"%d:" % len(x) + bytes(x)
    if isinstance(x, (list, tuple)):
        return b"l" + b"".join(bencode(i) for i in x) + b"e"
    if isinstance(x, dict):
        items = sorted(((k.encode() if isinstance(k, str) else k), v) for k, v in x.items())
        return b"d" + b"".join(bencode(k) + bencode(v) for k, v in items) + b"e"
    raise TypeError(type(x))


def bdecode(data: bytes):
    def parse(i: int):
        c = data[i:i + 1]
        if c == b"i":
            j = data.index(b"e", i)
            return int(data[i + 1:j]), j + 1
        if c == b"l":
            i += 1
            out = []
            while data[i:i + 1] != b"e":
                v, i = parse(i)
                out.append(v)
            return out, i + 1
        if c == b"d":
            i += 1
            out = {}
            while data[i:i + 1] != b"e":
                k, i = parse(i)
                v, i = parse(i)
                out[k] = v
            return out, i + 1
        if c.isdigit():
            j = data.index(b":", i)
            n = int(data[i:j])
            return data[j + 1:j + 1 + n], j + 1 + n
        raise ValueError("not a torrent file")
    v, end = parse(0)
    return v


def _text(b) -> str:
    return b.decode("utf-8", "replace") if isinstance(b, (bytes, bytearray)) else str(b)


def info_of(path: Path) -> dict:
    """Reads a .torrent file: name, size, files, trackers, info hash, magnet link."""
    try:
        raw = path.read_bytes()
        meta = bdecode(raw)
        info = meta[b"info"]
    except Exception:
        raise UserError("That is not a valid .torrent file.")
    ih = hashlib.sha1(bencode(info)).hexdigest()
    files = []
    if b"files" in info:
        for f in info[b"files"]:
            files.append({"path": "/".join(_text(p) for p in f[b"path"]), "size": int(f[b"length"])})
    else:
        files.append({"path": _text(info[b"name"]), "size": int(info[b"length"])})
    trackers = []
    if b"announce" in meta:
        trackers.append(_text(meta[b"announce"]))
    for tier in meta.get(b"announce-list", []):
        for t in tier:
            if _text(t) not in trackers:
                trackers.append(_text(t))
    name = _text(info[b"name"])
    magnet = f"magnet:?xt=urn:btih:{ih}&dn={urllib.parse.quote(name)}" + "".join("&tr=" + urllib.parse.quote(t, safe="") for t in trackers)
    return {"name": name, "size": sum(f["size"] for f in files), "files": files, "trackers": trackers, "hash": ih, "magnet": magnet,
            "pieces": len(info.get(b"pieces", b"")) // 20, "piece_length": int(info.get(b"piece length", 0)), "private": bool(info.get(b"private", 0)),
            "comment": _text(meta.get(b"comment", b"")), "created_by": _text(meta.get(b"created by", b"")), "created": int(meta.get(b"creation date", 0))}


def _piece_len(total: int) -> int:
    for pl in (1 << 15, 1 << 16, 1 << 17, 1 << 18, 1 << 19, 1 << 20, 1 << 21, 1 << 22, 1 << 23, 1 << 24):
        if total / pl <= 2200:
            return pl
    return 1 << 24


def make_start(paths: list[str], trackers: list[str], comment: str, private: bool, piece_kb: int, web_seeds: list[str], output: dict) -> dict:
    """One .torrent for each item you added (a folder becomes one torrent holding everything inside it)."""
    items = [Path(p) for p in paths if Path(p).exists()]
    if not items:
        raise UserError("Add the file or folder to make a torrent from.")
    pol = OutputPolicy.from_dict(output)
    trackers = [t.strip() for t in trackers if t.strip()]
    for t in trackers:
        if not re.match(r"^(udp|http|https|ws|wss)://", t, re.I):
            raise UserError(f"'{t}' is not a tracker address (it should start with udp:// or http://).")

    def make(src: Path):
        def fn(ctx: Ctx, task: Task) -> Output:
            if src.is_dir():
                entries = sorted(((p, p.relative_to(src)) for p in src.rglob("*") if p.is_file()), key=lambda e: str(e[1]).lower())
                if not entries:
                    return Output([], "The folder is empty.", skipped=True)
            else:
                entries = [(src, Path(src.name))]
            total = sum(p.stat().st_size for p, _ in entries)
            plen = piece_kb * 1024 if piece_kb else _piece_len(total)
            pieces = bytearray()
            buf = bytearray()
            done = 0
            for p, _rel in entries:
                with open(p, "rb") as f:
                    while True:
                        ctx.check()
                        chunk = f.read(1 << 20)
                        if not chunk:
                            break
                        buf += chunk
                        done += len(chunk)
                        while len(buf) >= plen:
                            pieces += hashlib.sha1(bytes(buf[:plen])).digest()
                            del buf[:plen]
                        ctx.progress(done / max(1, total))
            if buf:
                pieces += hashlib.sha1(bytes(buf)).digest()
            info: dict = {"name": src.name, "piece length": plen, "pieces": bytes(pieces)}
            if src.is_dir():
                info["files"] = [{"length": p.stat().st_size, "path": list(rel.parts)} for p, rel in entries]
            else:
                info["length"] = total
            if private:
                info["private"] = 1
            meta: dict = {"info": info, "creation date": int(time.time()), "created by": "Fathom"}
            if trackers:
                meta["announce"] = trackers[0]
                if len(trackers) > 1:
                    meta["announce-list"] = [[t] for t in trackers]
            if comment:
                meta["comment"] = comment
            if web_seeds:
                meta["url-list"] = web_seeds
            d = ctx.scratch_dir()
            dst = d / (src.name + ".torrent")
            dst.write_bytes(bencode(meta))
            ih = hashlib.sha1(bencode(info)).hexdigest()
            out = pol.place([dst], src, Path("."))
            magnet = f"magnet:?xt=urn:btih:{ih}&dn={urllib.parse.quote(src.name)}" + "".join("&tr=" + urllib.parse.quote(t, safe="") for t in trackers)
            return Output(out, f"{len(pieces) // 20} pieces of {plen // 1024} KB. Magnet link: {magnet}", extra={"magnet": magnet, "hash": ih})
        return fn

    tasks = [Task(s.name, make(s), s) for s in items]
    return {"job": ops.start("torrent-make", "Making torrents", tasks, workers=1).id, "count": len(tasks)}


# ================================================================== libtorrent client
_lock = threading.RLock()
_ses = None
_handles: dict[str, object] = {}          # info hash -> handle
_meta: dict[str, dict] = {}               # info hash -> {source, save, added}
_limits = {"down": 0, "up": 0}
_STATES = ["Waiting to check", "Checking files", "Getting info", "Downloading", "Finished", "Seeding", "Allocating", "Checking resume data"]


def _state_file() -> Path:
    return data_root() / "torrents.json"


def available() -> tuple[bool, str]:
    try:
        import libtorrent  # type: ignore  # noqa: F401
        return True, ""
    except Exception:
        return False, ("Downloading torrents needs the 'libtorrent' component, which was not installed. Run Fathom.bat again with internet, or open a command window and type: "
                       "python -m pip install libtorrent")


def _lt():
    ok, why = available()
    if not ok:
        raise UserError(why)
    import libtorrent as lt  # type: ignore
    return lt


def _session():
    global _ses
    with _lock:
        if _ses is None:
            lt = _lt()
            _ses = lt.session({"listen_interfaces": "0.0.0.0:6881,[::]:6881", "enable_dht": True, "enable_lsd": True, "enable_upnp": True, "enable_natpmp": True,
                               "user_agent": "Fathom/2", "alert_mask": 0})
            for name in ("dht.libtorrent.org:25401", "router.bittorrent.com:6881", "router.utorrent.com:6881", "dht.transmissionbt.com:6881"):
                try:
                    _ses.add_dht_router(*name.rsplit(":", 1)[:1], int(name.rsplit(":", 1)[1]))
                except Exception:
                    pass
            _ses.start_dht()
            _restore()
        return _ses


def _save_state() -> None:
    try:
        _state_file().write_text(json.dumps(list(_meta.values())), "utf-8")
    except OSError:
        pass


def _restore() -> None:
    try:
        saved = json.loads(_state_file().read_text("utf-8"))
    except (OSError, ValueError):
        return
    for m in saved:
        try:
            _add(m["source"], m["save"], m.get("paused", False), restoring=True, sequential=m.get("sequential", False))
        except Exception:
            continue


def _hash_of(h) -> str:
    try:
        return str(h.info_hashes().get_best())
    except Exception:
        try:
            return str(h.info_hash())
        except Exception:
            return ""


def _add(source: str, save_dir: str, paused: bool = False, restoring: bool = False, sequential: bool = False) -> str:
    lt = _lt()
    ses = _session() if not restoring else _ses
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    if source.lower().startswith("magnet:"):
        params = lt.parse_magnet_uri(source)
    else:
        p = Path(source)
        if not p.is_file():
            raise UserError("That .torrent file was not found.")
        params = lt.add_torrent_params()
        params.ti = lt.torrent_info(str(p))
    params.save_path = str(save_dir)
    if paused:
        params.flags |= lt.torrent_flags.paused
    if sequential:
        params.flags |= lt.torrent_flags.sequential_download
    h = ses.add_torrent(params)
    key = _hash_of(h)
    with _lock:
        _handles[key] = h
        _meta[key] = {"source": source, "save": str(save_dir), "paused": paused, "sequential": sequential, "added": time.time()}
        _save_state()
    return key


def add(source: str, save_dir: str, sequential: bool = False) -> dict:
    source = (source or "").strip()
    if not source:
        raise UserError("Paste a magnet link or choose a .torrent file.")
    if not save_dir.strip():
        raise UserError("Choose a folder to download into.")
    return {"id": _add(source, save_dir.strip(), False, sequential=sequential)}


def _row(key: str, h) -> dict:
    s = h.status()
    paused = bool(s.flags & _lt().torrent_flags.paused) if hasattr(s, "flags") else bool(getattr(s, "paused", False))
    state = _STATES[int(s.state)] if int(s.state) < len(_STATES) else "Working"
    if paused:
        state = "Paused"
    elif s.errc.value():
        state = "Problem: " + s.errc.message()
    elif getattr(s, "is_finished", False) and not getattr(s, "is_seeding", False):
        state = "Finished"
    name = s.name or key[:12]
    eta = 0
    if s.download_rate > 0 and s.total_wanted > s.total_wanted_done:
        eta = int((s.total_wanted - s.total_wanted_done) / s.download_rate)
    return {"id": key, "name": name, "state": state, "progress": round(float(s.progress), 4), "down": int(s.download_rate), "up": int(s.upload_rate), "peers": int(s.num_peers),
            "seeds": int(s.num_seeds), "size": int(s.total_wanted), "done": int(s.total_wanted_done), "uploaded": int(s.total_upload), "eta": eta, "paused": paused,
            "save": _meta.get(key, {}).get("save", ""), "ratio": round(s.total_upload / s.total_done, 2) if s.total_done else 0.0,
            "sequential": bool(_meta.get(key, {}).get("sequential"))}


def status() -> dict:
    ok, why = available()
    if not ok:
        return {"available": False, "why": why, "items": []}
    _session()
    with _lock:
        rows = []
        for k, h in list(_handles.items()):
            try:
                rows.append(_row(k, h))
            except Exception:
                continue
    return {"available": True, "items": rows, "down": sum(r["down"] for r in rows), "up": sum(r["up"] for r in rows), "limits": dict(_limits)}


def files_of(key: str) -> list[dict]:
    lt = _lt()
    h = _handles.get(key)
    if h is None:
        raise UserError("That download is not in the list any more.")
    try:
        ti = h.torrent_file() if hasattr(h, "torrent_file") else h.get_torrent_info()
    except Exception:
        ti = None
    if ti is None:
        return []
    fs = ti.files()
    prios = h.get_file_priorities()
    prog = h.file_progress()
    return [{"index": i, "path": fs.file_path(i), "size": fs.file_size(i), "done": prog[i] if i < len(prog) else 0, "wanted": prios[i] > 0 if i < len(prios) else True} for i in range(fs.num_files())]


def act(key: str, action: str, value=None) -> dict:
    lt = _lt()
    h = _handles.get(key)
    if h is None:
        raise UserError("That download is not in the list any more.")
    if action == "pause":
        h.pause(); _meta[key]["paused"] = True
    elif action == "resume":
        h.resume(); _meta[key]["paused"] = False
    elif action == "recheck":
        h.force_recheck()
    elif action == "sequential":
        h.set_sequential_download(bool(value)); _meta[key]["sequential"] = bool(value)
    elif action == "files":
        wanted = set(int(i) for i in (value or []))
        n = len(files_of(key))
        h.prioritize_files([4 if i in wanted else 0 for i in range(n)])
    elif action in ("remove", "delete"):
        ses = _session()
        flag = getattr(getattr(lt, "options_t", None), "delete_files", None) if action == "delete" else None
        if action == "delete" and flag is None:
            flag = getattr(lt.session, "delete_files", 1)
        ses.remove_torrent(h, flag) if flag is not None else ses.remove_torrent(h)
        with _lock:
            _handles.pop(key, None); _meta.pop(key, None)
    else:
        raise UserError("Unknown action.")
    with _lock:
        _save_state()
    return {"ok": True}


def set_limits(down_kb: int, up_kb: int) -> dict:
    ses = _session()
    _limits["down"], _limits["up"] = max(0, int(down_kb)), max(0, int(up_kb))
    ses.apply_settings({"download_rate_limit": _limits["down"] * 1024, "upload_rate_limit": _limits["up"] * 1024})
    return {"limits": dict(_limits)}


# ================================================================== link downloader (http / https / ftp)
def _name_from(url: str, headers) -> str:
    cd = headers.get("Content-Disposition", "") if headers else ""
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
    if m:
        return urllib.parse.unquote(m.group(1)).strip()
    n = urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name)
    return n or "download"


def download_start(urls: list[str], output: dict, name: str = "") -> dict:
    urls = [u.strip() for u in urls if u.strip()]
    if not urls:
        raise UserError("Paste one or more links (one per line).")
    for u in urls:
        if not re.match(r"^(https?|ftp)://", u, re.I):
            raise UserError(f"'{u[:60]}' is not a web link (it should start with http:// or https://).")
    pol = OutputPolicy.from_dict(output)
    if pol.mode != "folder" or not pol.dir:
        raise UserError("Choose a folder to save the downloads in (on the left).")

    def make(url: str):
        def fn(ctx: Ctx, task: Task) -> Output:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Fathom"})
            d = ctx.scratch_dir()
            try:
                resp = urllib.request.urlopen(req, timeout=30)
            except Exception as e:
                raise ConvertError(f"Could not reach the link: {e}")
            nm = (name if len(urls) == 1 and name else _name_from(url, resp.headers)) or "download"
            nm = re.sub(r'[\\/:*?"<>|]', "_", nm)
            total = int(resp.headers.get("Content-Length") or 0)
            dst = d / nm
            got = 0
            with open(dst, "wb") as f:
                while True:
                    ctx.check()
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        ctx.progress(got / total)
                    ctx.status(f"{got / 1048576:.1f} MB downloaded")
            if total and got < total:
                raise ConvertError("The download stopped early. Try again.")
            return Output(pol.place([dst], Path(nm), Path(".")), f"Downloaded {got / 1048576:.1f} MB.")
        return fn

    tasks = [Task(u.rsplit("/", 1)[-1][:60] or u[:60], make(u), None) for u in urls]
    return {"job": ops.start("download", "Downloading", tasks, workers=2).id, "count": len(tasks)}
