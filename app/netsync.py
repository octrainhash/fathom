"""Network sync engine: copy folders to and from remote places, many files at once, optionally encrypted before they leave this PC.

Backends: local/USB, SMB (Windows share), NFS (mounted), FTP/FTPS, SFTP, WebDAV, Amazon S3 (and S3-compatible), Azure Blob,
Android over ADB, Windows MTP phones, and anything else (Google Drive, Dropbox, OneDrive ...) through rclone if it is installed."""
from __future__ import annotations

import fnmatch
import json
import os
import posixpath
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib import parse, request

from app import ops, recycle
from app.convert.core import ConvertError, Ctx
from app.ops import Output, Task
from app.service import UserError

WIN = sys.platform == "win32"
NOWIN = 0x08000000 if WIN else 0
LOCKED = ".locked"

KINDS = {
    "local": "This PC / USB drive", "smb": "Windows share (SMB / CIFS)", "nfs": "NFS share", "sftp": "SFTP (SSH)", "ftp": "FTP", "ftps": "FTP over TLS",
    "webdav": "WebDAV", "s3": "Amazon S3 / S3-compatible", "azure": "Azure Blob Storage", "gdrive": "Google Drive", "adb": "Android (ADB, USB debugging)",
    "mtp": "Phone / camera (MTP, Windows)", "rclone": "Other cloud (rclone)",
}


class Entry(dict):
    pass


def _e(name: str, rel: str, size: int, mtime: float, isdir: bool) -> dict:
    return {"name": name, "rel": rel, "size": size, "mtime": mtime, "dir": isdir}


def _join(a: str, b: str) -> str:
    return posixpath.join(a, b) if a else b


class Remote:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.root = str(cfg.get("path") or "").replace("\\", "/").strip("/")

    def connect(self) -> None: ...
    def close(self) -> None: ...
    def listdir(self, rel: str) -> list[dict]: raise NotImplementedError
    def get(self, rel: str, dst: Path) -> None: raise NotImplementedError
    def put(self, src: Path, rel: str) -> None: raise NotImplementedError
    def mkdirs(self, rel: str) -> None: ...
    def remove(self, rel: str) -> None: raise NotImplementedError

    def walk(self, rel: str = "", limit: int = 2_000_000):
        stack, n = [rel], 0
        while stack:
            cur = stack.pop()
            try:
                items = self.listdir(cur)
            except Exception:
                if cur == rel:
                    raise
                continue
            for it in items:
                if it["dir"]:
                    stack.append(it["rel"])
                else:
                    yield it
                    n += 1
                    if n >= limit:
                        return

    def full(self, rel: str) -> str:
        return _join(self.root, rel)


# ------------------------------------------------------------------ local, SMB, NFS
class LocalRemote(Remote):
    def __init__(self, cfg):
        super().__init__(cfg)
        k, p = cfg.get("type"), str(cfg.get("path") or "")
        if k == "smb":
            host = str(cfg.get("host") or "").strip("\\/")
            share = p.replace("/", "\\").strip("\\")
            if WIN:
                p = f"\\\\{host}\\{share}" if host else p
                self._smb_login()
            elif not p.startswith("/"):
                raise UserError("On Mac and Linux, mount the share first (for example under /mnt or /Volumes) and enter that folder as the path.")
        elif k == "nfs":
            if WIN and cfg.get("host") and not p.startswith("\\\\"):
                p = f"\\\\{cfg['host']}\\{p.strip('/').replace('/', chr(92))}"
            elif not WIN and not p.startswith("/"):
                raise UserError("Mount the NFS export first and enter the mounted folder as the path.")
        self.base = Path(p)

    def _smb_login(self) -> None:
        c = self.cfg
        if c.get("user") and c.get("host"):
            subprocess.run(["net", "use", f"\\\\{c['host']}\\{str(c.get('path') or '').strip(chr(92) + '/').split(chr(92))[0].split('/')[0]}", c.get("password") or "", f"/user:{c['user']}"],
                           capture_output=True, creationflags=NOWIN)

    def connect(self) -> None:
        if not self.base.is_dir():
            try:
                self.base.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise UserError(f"Cannot reach {self.base}: {e}")

    def _p(self, rel): return self.base / rel if rel else self.base

    def listdir(self, rel):
        out = []
        with os.scandir(self._p(rel)) as it:
            for d in it:
                try:
                    st = d.stat()
                except OSError:
                    continue
                out.append(_e(d.name, _join(rel, d.name), 0 if d.is_dir() else st.st_size, st.st_mtime, d.is_dir()))
        return out

    def get(self, rel, dst): shutil.copyfile(self._p(rel), dst)

    def put(self, src, rel):
        d = self._p(rel); d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, d); os.utime(d, (time.time(), src.stat().st_mtime))

    def mkdirs(self, rel): self._p(rel).mkdir(parents=True, exist_ok=True)
    def remove(self, rel):
        p = self._p(rel)
        shutil.rmtree(p) if p.is_dir() else p.unlink()


# ------------------------------------------------------------------ FTP / FTPS
class FtpRemote(Remote):
    def connect(self):
        import ftplib
        c = self.cfg
        ftp = ftplib.FTP_TLS() if c["type"] == "ftps" else ftplib.FTP()
        ftp.connect(c.get("host", ""), int(c.get("port") or 21), timeout=30)
        ftp.login(c.get("user") or "anonymous", c.get("password") or "")
        if c["type"] == "ftps":
            ftp.prot_p()
        ftp.encoding = "utf-8"
        self.ftp = ftp

    def close(self):
        try: self.ftp.quit()
        except Exception: pass

    def listdir(self, rel):
        out = []
        base = "/" + self.full(rel)
        try:
            for name, f in self.ftp.mlsd(base, facts=["type", "size", "modify"]):
                if f.get("type") in ("cdir", "pdir") or name in (".", ".."):
                    continue
                m = time.mktime(time.strptime(f.get("modify", "19700101000000")[:14], "%Y%m%d%H%M%S")) - time.timezone if f.get("modify") else 0
                out.append(_e(name, _join(rel, name), int(f.get("size") or 0), m, f.get("type") == "dir"))
            return out
        except Exception:
            pass
        lines: list[str] = []
        self.ftp.retrlines("LIST " + base, lines.append)
        for ln in lines:
            parts = ln.split(None, 8)
            if len(parts) < 9 or parts[8] in (".", ".."):
                continue
            out.append(_e(parts[8], _join(rel, parts[8]), int(parts[4]) if parts[4].isdigit() else 0, 0, parts[0].startswith("d")))
        return out

    def get(self, rel, dst):
        with open(dst, "wb") as f:
            self.ftp.retrbinary("RETR /" + self.full(rel), f.write, 1 << 20)

    def mkdirs(self, rel):
        cur = ""
        for part in self.full(rel).split("/"):
            if not part: continue
            cur += "/" + part
            try: self.ftp.mkd(cur)
            except Exception: pass

    def put(self, src, rel):
        self.mkdirs(posixpath.dirname(rel))
        with open(src, "rb") as f:
            self.ftp.storbinary("STOR /" + self.full(rel), f, 1 << 20)

    def remove(self, rel):
        try: self.ftp.delete("/" + self.full(rel))
        except Exception: self.ftp.rmd("/" + self.full(rel))


# ------------------------------------------------------------------ SFTP
class SftpRemote(Remote):
    def connect(self):
        try:
            import paramiko
        except ImportError:
            raise UserError("SFTP needs the 'paramiko' add-on. Run: pip install paramiko")
        c = self.cfg
        self.t = paramiko.Transport((c.get("host", ""), int(c.get("port") or 22)))
        kw = {"username": c.get("user") or None}
        if c.get("key_file"):
            kw["pkey"] = paramiko.PKey.from_path(c["key_file"], c.get("password") or None) if hasattr(paramiko.PKey, "from_path") else paramiko.RSAKey.from_private_key_file(c["key_file"], c.get("password") or None)
        else:
            kw["password"] = c.get("password") or None
        self.t.connect(**kw)
        self.s = paramiko.SFTPClient.from_transport(self.t)

    def close(self):
        try: self.s.close(); self.t.close()
        except Exception: pass

    def _f(self, rel): return "/" + self.full(rel) if not self.cfg.get("path", "").startswith("~") else self.full(rel)

    def listdir(self, rel):
        import stat
        return [_e(a.filename, _join(rel, a.filename), a.st_size or 0, a.st_mtime or 0, stat.S_ISDIR(a.st_mode)) for a in self.s.listdir_attr(self._f(rel) or ".")]

    def get(self, rel, dst): self.s.get(self._f(rel), str(dst))

    def mkdirs(self, rel):
        cur = ""
        for part in self._f(rel).split("/"):
            if not part: cur += "/"; continue
            cur = cur.rstrip("/") + "/" + part
            try: self.s.stat(cur)
            except IOError:
                try: self.s.mkdir(cur)
                except IOError: pass

    def put(self, src, rel):
        self.mkdirs(posixpath.dirname(rel))
        self.s.put(str(src), self._f(rel))
        try: self.s.utime(self._f(rel), (time.time(), src.stat().st_mtime))
        except IOError: pass

    def remove(self, rel):
        try: self.s.remove(self._f(rel))
        except IOError: self.s.rmdir(self._f(rel))


# ------------------------------------------------------------------ WebDAV
class DavRemote(Remote):
    def connect(self):
        c = self.cfg
        url = c.get("host", "").rstrip("/")
        if not url.startswith("http"):
            url = "https://" + url
        self.url = url
        pw = request.HTTPPasswordMgrWithDefaultRealm(); pw.add_password(None, url, c.get("user") or "", c.get("password") or "")
        self.op = request.build_opener(request.HTTPBasicAuthHandler(pw), request.HTTPDigestAuthHandler(pw))

    def _u(self, rel): return self.url + "/" + parse.quote(self.full(rel).strip("/")) if self.full(rel) else self.url + "/"

    def _req(self, method, rel, data=None, headers=None):
        r = request.Request(self._u(rel), data=data, method=method, headers=headers or {})
        return self.op.open(r, timeout=60)

    def listdir(self, rel):
        body = b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:getcontentlength/><d:getlastmodified/><d:resourcetype/></d:prop></d:propfind>'
        with self._req("PROPFIND", rel, body, {"Depth": "1", "Content-Type": "application/xml"}) as r:
            tree = ET.fromstring(r.read())
        out, self_href = [], self._u(rel).rstrip("/")
        ns = {"d": "DAV:"}
        for resp in tree.findall("d:response", ns):
            href = parse.unquote(parse.urlparse(resp.findtext("d:href", "", ns)).path).rstrip("/")
            if href.rstrip("/") == parse.unquote(parse.urlparse(self_href).path).rstrip("/"):
                continue
            isdir = resp.find(".//d:resourcetype/d:collection", ns) is not None
            size = int(resp.findtext(".//d:getcontentlength", "0", ns) or 0)
            lm = resp.findtext(".//d:getlastmodified", "", ns)
            try:
                from email.utils import parsedate_to_datetime
                mt = parsedate_to_datetime(lm).timestamp()
            except Exception:
                mt = 0
            name = href.split("/")[-1]
            out.append(_e(name, _join(rel, name), size, mt, isdir))
        return out

    def get(self, rel, dst):
        with self._req("GET", rel) as r, open(dst, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)

    def mkdirs(self, rel):
        cur = ""
        for part in [p for p in rel.split("/") if p]:
            cur = _join(cur, part)
            try: self._req("MKCOL", cur).close()
            except Exception: pass

    def put(self, src, rel):
        self.mkdirs(posixpath.dirname(rel))
        with open(src, "rb") as f:
            r = request.Request(self._u(rel), data=f, method="PUT", headers={"Content-Length": str(src.stat().st_size)})
            self.op.open(r, timeout=600).close()

    def remove(self, rel): self._req("DELETE", rel).close()


# ------------------------------------------------------------------ S3
class S3Remote(Remote):
    def connect(self):
        try:
            import boto3
        except ImportError:
            raise UserError("Amazon S3 needs the 'boto3' add-on. Run: pip install boto3")
        c = self.cfg
        self.bucket = c.get("bucket") or ""
        if not self.bucket:
            raise UserError("Type the bucket name.")
        self.s3 = boto3.client("s3", aws_access_key_id=c.get("user") or None, aws_secret_access_key=c.get("password") or None, region_name=c.get("region") or None, endpoint_url=c.get("host") or None)

    def listdir(self, rel):
        pre = self.full(rel).strip("/") + "/" if self.full(rel) else ""
        out, tok = [], None
        while True:
            kw = dict(Bucket=self.bucket, Prefix=pre, Delimiter="/")
            if tok: kw["ContinuationToken"] = tok
            r = self.s3.list_objects_v2(**kw)
            for p in r.get("CommonPrefixes", []):
                n = p["Prefix"][len(pre):].strip("/")
                out.append(_e(n, _join(rel, n), 0, 0, True))
            for o in r.get("Contents", []):
                n = o["Key"][len(pre):]
                if n:
                    out.append(_e(n, _join(rel, n), o["Size"], o["LastModified"].timestamp(), False))
            tok = r.get("NextContinuationToken")
            if not tok: return out

    def _k(self, rel): return self.full(rel).strip("/")
    def get(self, rel, dst): self.s3.download_file(self.bucket, self._k(rel), str(dst))
    def put(self, src, rel): self.s3.upload_file(str(src), self.bucket, self._k(rel), ExtraArgs={"Metadata": {"mtime": str(int(src.stat().st_mtime))}})
    def remove(self, rel): self.s3.delete_object(Bucket=self.bucket, Key=self._k(rel))


# ------------------------------------------------------------------ Azure Blob
class AzureRemote(Remote):
    def connect(self):
        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError:
            raise UserError("Azure Blob needs the 'azure-storage-blob' add-on. Run: pip install azure-storage-blob")
        c = self.cfg
        if c.get("conn"):
            svc = BlobServiceClient.from_connection_string(c["conn"])
        else:
            svc = BlobServiceClient(account_url=f"https://{c.get('host')}.blob.core.windows.net", credential=c.get("password"))
        self.cc = svc.get_container_client(c.get("bucket") or "")

    def listdir(self, rel):
        pre = self.full(rel).strip("/") + "/" if self.full(rel) else ""
        out = []
        for b in self.cc.walk_blobs(name_starts_with=pre, delimiter="/"):
            n = b.name[len(pre):].strip("/")
            if hasattr(b, "size"):
                out.append(_e(n, _join(rel, n), b.size, b.last_modified.timestamp(), False))
            else:
                out.append(_e(n, _join(rel, n), 0, 0, True))
        return out

    def get(self, rel, dst):
        with open(dst, "wb") as f:
            self.cc.download_blob(self.full(rel).strip("/")).readinto(f)

    def put(self, src, rel):
        with open(src, "rb") as f:
            self.cc.upload_blob(self.full(rel).strip("/"), f, overwrite=True)

    def remove(self, rel): self.cc.delete_blob(self.full(rel).strip("/"))


# ------------------------------------------------------------------ rclone (Google Drive, Dropbox, OneDrive ...)
class RcloneRemote(Remote):
    def connect(self):
        self.exe = shutil.which("rclone")
        if not self.exe:
            raise UserError("Google Drive and other cloud drives use the free 'rclone' program. Install it from rclone.org, run 'rclone config' once to log in, and enter the remote's name here.")
        name = (self.cfg.get("host") or ("gdrive" if self.cfg.get("type") == "gdrive" else "")).rstrip(":")
        if not name:
            raise UserError("Type the rclone remote's name (the one you made with 'rclone config').")
        self.rem = name + ":"

    def _r(self, args):
        p = subprocess.run([self.exe] + args, capture_output=True, text=True, errors="replace", creationflags=NOWIN)
        if p.returncode:
            raise UserError("rclone: " + (p.stderr.strip().splitlines() or ["failed"])[-1][:200])
        return p.stdout

    def _path(self, rel): return self.rem + self.full(rel)

    def listdir(self, rel):
        from datetime import datetime
        out = []
        for o in json.loads(self._r(["lsjson", self._path(rel)]) or "[]"):
            try: mt = datetime.fromisoformat(o["ModTime"].replace("Z", "+00:00")).timestamp()
            except Exception: mt = 0
            out.append(_e(o["Name"], _join(rel, o["Name"]), max(0, o.get("Size", 0)), mt, bool(o.get("IsDir"))))
        return out

    def get(self, rel, dst): self._r(["copyto", self._path(rel), str(dst)])
    def put(self, src, rel): self._r(["copyto", str(src), self._path(rel)])
    def remove(self, rel): self._r(["deletefile", self._path(rel)])


# ------------------------------------------------------------------ Android over ADB
class AdbRemote(Remote):
    def connect(self):
        self.exe = shutil.which("adb")
        if not self.exe:
            raise UserError("Android needs Google's free 'adb' tool (Platform Tools). Install it, turn on USB debugging on the phone, then try again.")
        self.serial = self.cfg.get("host") or ""
        out = self._r(["devices"])
        if "\tdevice" not in out:
            raise UserError("No Android phone found. Plug it in, enable USB debugging and accept the prompt on the phone.")
        if not self.root:
            self.root = "sdcard"

    def _r(self, args, check=True):
        cmd = [self.exe] + (["-s", self.serial] if self.serial else []) + args
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", creationflags=NOWIN)
        if p.returncode and check:
            raise UserError("adb: " + ((p.stderr or p.stdout).strip().splitlines() or ["failed"])[-1][:200])
        return p.stdout

    def _q(self, rel): return "'/" + self.full(rel).replace("'", "'\\''") + "'"

    def listdir(self, rel):
        out = []
        txt = self._r(["shell", f"cd {self._q(rel)} && stat -c '%n|%s|%Y|%F' .[!.]* * 2>/dev/null"], check=False)
        for ln in txt.splitlines():
            p = ln.rsplit("|", 3)
            if len(p) != 4 or p[0] in ("*", ".[!.]*"):
                continue
            n = p[0]
            out.append(_e(n, _join(rel, n), int(p[1] or 0), float(p[2] or 0), "directory" in p[3]))
        return out

    def get(self, rel, dst): self._r(["pull", "/" + self.full(rel), str(dst)])
    def mkdirs(self, rel): self._r(["shell", "mkdir -p " + self._q(rel)])
    def put(self, src, rel):
        self.mkdirs(posixpath.dirname(rel)); self._r(["push", str(src), "/" + self.full(rel)])
    def remove(self, rel): self._r(["shell", "rm -rf " + self._q(rel)])


# ------------------------------------------------------------------ MTP (Windows portable devices) through the shell
class MtpRemote(Remote):
    PS = r"""
$ErrorActionPreference='Stop'
$sh=New-Object -ComObject Shell.Application
$pc=$sh.Namespace(17)
function Nav($rel){
  $dev=$pc.Items() | Where-Object { $_.Name -eq '%DEV%' } | Select-Object -First 1
  if(-not $dev){ throw 'Device not found' }
  $f=$dev.GetFolder
  foreach($seg in ($rel -split '/' | Where-Object {$_})){
    $it=$f.Items() | Where-Object { $_.Name -eq $seg } | Select-Object -First 1
    if(-not $it){ throw "Not found: $seg" }
    $f=$it.GetFolder
  }
  return $f
}
"""

    def connect(self):
        if not WIN:
            raise UserError("MTP phones are read through Windows. On Mac or Linux use the Android (ADB) option, or mount the phone as a folder and use 'This PC'.")
        if not self.cfg.get("host"):
            raise UserError("Type the device name exactly as it shows in File Explorer under This PC (for example: Pixel 8).")

    def _ps(self, body: str, timeout=600) -> str:
        script = (self.PS.replace("%DEV%", self.cfg["host"].replace("'", "''")) + body)
        p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], capture_output=True, text=True, errors="replace", creationflags=NOWIN, timeout=timeout)
        if p.returncode:
            raise UserError("Phone: " + (p.stderr.strip().splitlines() or ["failed"])[0][:200])
        return p.stdout

    def listdir(self, rel):
        out = []
        txt = self._ps(f"$f=Nav '{rel.replace(chr(39), chr(39)*2)}'; foreach($i in $f.Items()){{ '{{0}}|{{1}}|{{2}}' -f $i.Name,$i.IsFolder,$i.Size }}")
        for ln in txt.splitlines():
            p = ln.rstrip("\r").split("|")
            if len(p) == 3:
                out.append(_e(p[0], _join(rel, p[0]), int(float(p[2] or 0)) if p[2].strip().replace(".", "").isdigit() else 0, 0, p[1] == "True"))
        return out

    def get(self, rel, dst):
        d = posixpath.dirname(rel).replace("'", "''"); n = posixpath.basename(rel).replace("'", "''")
        tmp = Path(dst).parent
        self._ps(f"$f=Nav '{d}'; $it=$f.Items() | Where-Object {{$_.Name -eq '{n}'}} | Select-Object -First 1; $t=$sh.Namespace('{tmp}'); $t.CopyHere($it,0x14); Start-Sleep -Milliseconds 300")
        got = tmp / posixpath.basename(rel)
        if got != Path(dst) and got.exists():
            got.replace(dst)

    def put(self, src, rel):
        d = posixpath.dirname(rel).replace("'", "''")
        self._ps(f"$f=Nav '{d}'; $f.CopyHere('{src}',0x14); Start-Sleep -Milliseconds 500")

    def remove(self, rel): raise UserError("Deleting on a phone through Windows is not supported. Delete on the phone itself.")


def make_remote(cfg: dict) -> Remote:
    k = cfg.get("type", "local")
    cls = {"local": LocalRemote, "smb": LocalRemote, "nfs": LocalRemote, "ftp": FtpRemote, "ftps": FtpRemote, "sftp": SftpRemote, "webdav": DavRemote, "s3": S3Remote,
           "azure": AzureRemote, "gdrive": RcloneRemote, "rclone": RcloneRemote, "adb": AdbRemote, "mtp": MtpRemote}.get(k)
    if not cls:
        raise UserError("Choose what kind of place to connect to.")
    return cls(cfg)


# ================================================================== API pieces
def browse(cfg: dict, rel: str = "") -> dict:
    r = make_remote(cfg)
    try:
        r.connect()
        items = sorted(r.listdir(rel.strip("/")), key=lambda x: (not x["dir"], x["name"].lower()))
    except UserError:
        raise
    except Exception as e:
        raise UserError(f"Could not connect: {e}")
    finally:
        r.close()
    return {"items": items[:5000], "count": len(items)}


def _match(name: str, include: str, exclude: str) -> bool:
    inc = [x.strip() for x in include.replace(";", ",").split(",") if x.strip()]
    exc = [x.strip() for x in exclude.replace(";", ",").split(",") if x.strip()]
    if inc and not any(fnmatch.fnmatch(name.lower(), x.lower()) for x in inc):
        return False
    return not any(fnmatch.fnmatch(name.lower(), x.lower()) for x in exc)


def sync_start(cfg: dict, direction: str, local_dir: str, remote_dir: str, opts: dict) -> dict:
    """direction: up | down. opts: threads, password (encrypt/decrypt), algo, skip_same, mirror, include, exclude, dry."""
    from app.filetools2 import _decrypt_file, _encrypt_file
    local = Path(local_dir)
    if direction == "up" and not local.is_dir():
        raise UserError("Choose the folder on this PC to send.")
    if direction == "down":
        local.mkdir(parents=True, exist_ok=True)
    threads = max(1, min(32, int(opts.get("threads") or 4)))
    pw = opts.get("password") or ""
    algo = opts.get("algo") or "aes"
    if pw and len(pw) < 4:
        raise UserError("Use an encryption password of at least 4 characters.")
    skip_same, mirror, dry = bool(opts.get("skip_same", True)), bool(opts.get("mirror")), bool(opts.get("dry"))
    inc, exc = str(opts.get("include") or ""), str(opts.get("exclude") or "")
    rdir = ""                      # the folder on the remote side is already the connection root (cfg["path"])
    cfg = {**cfg}
    tl = threading.local()
    conns: list[Remote] = []
    lock = threading.Lock()

    def conn() -> Remote:
        r = getattr(tl, "r", None)
        if r is None:
            r = make_remote(cfg); r.connect()
            tl.r = r
            with lock: conns.append(r)
        return r

    probe = make_remote(cfg)
    probe.connect()
    try:
        try:
            remote_files = {it["rel"]: it for it in probe.walk(rdir)}
        except UserError:
            raise
        except Exception as e:
            if direction == "down":
                raise UserError(f"Could not read the remote folder: {e}")
            remote_files = {}          # sending into a folder that does not exist yet is fine
    finally:
        probe.close()
    prefix = rdir + "/" if rdir else ""

    def rel_of(item_rel: str) -> str:
        return item_rel[len(prefix):] if prefix and item_rel.startswith(prefix) else item_rel

    tasks: list[Task] = []
    plan_up: set[str] = set()
    job_ref: dict = {}

    if direction == "up":
        for cur, _d, files in os.walk(local):
            for f in files:
                src = Path(cur) / f
                rel = src.relative_to(local).as_posix()
                if not _match(f, inc, exc):
                    continue
                dest_rel = _join(rdir, rel + (LOCKED if pw else ""))
                plan_up.add(dest_rel)
                ex = remote_files.get(dest_rel)
                st = src.stat()
                same = ex and ((not pw and ex["size"] == st.st_size) or pw) and (ex["mtime"] == 0 or ex["mtime"] >= st.st_mtime - 2)
                if skip_same and same:
                    continue

                def fn(ctx: Ctx, task: Task, src=src, dest_rel=dest_rel) -> Output:
                    if dry:
                        return Output([], "Would send.")
                    r = conn()
                    if pw:
                        tmp = ctx.scratch_dir() / (src.name + LOCKED)
                        _encrypt_file(src, tmp, pw, ctx, algo)
                        r.put(tmp, dest_rel)
                        os.utime(tmp, (time.time(), st_mtime(src)))
                    else:
                        r.put(src, dest_rel)
                    return Output([], "Sent" + (" (encrypted)." if pw else "."), extra={"bytes": src.stat().st_size})
                tasks.append(Task(rel, fn, src))
    else:
        for rrel, it in remote_files.items():
            name = it["name"]
            rel = rel_of(rrel)
            out_rel = rel[:-len(LOCKED)] if pw and rel.endswith(LOCKED) else rel
            if not _match(posixpath.basename(out_rel), inc, exc):
                continue
            dst = local / out_rel
            if skip_same and dst.exists() and (pw or dst.stat().st_size == it["size"]) and (it["mtime"] == 0 or dst.stat().st_mtime >= it["mtime"] - 2):
                continue

            def fn(ctx: Ctx, task: Task, rrel=rrel, dst=dst, it=it) -> Output:
                if dry:
                    return Output([], "Would fetch.")
                r = conn()
                dst.parent.mkdir(parents=True, exist_ok=True)
                if pw and rrel.endswith(LOCKED):
                    tmp = ctx.scratch_dir() / "dl.locked"
                    r.get(rrel, tmp)
                    _decrypt_file(tmp, dst, pw, ctx)
                else:
                    r.get(rrel, dst)
                if it["mtime"]:
                    try: os.utime(dst, (time.time(), it["mtime"]))
                    except OSError: pass
                return Output([dst], "Fetched" + (" and decrypted." if pw and rrel.endswith(LOCKED) else "."), extra={"bytes": it["size"]})
            tasks.append(Task(out_rel, fn, None))

    def st_mtime(p: Path) -> float:
        return p.stat().st_mtime

    def after(job) -> None:
        deleted = 0
        if mirror and not dry and not job.cancel.is_set():
            try:
                if direction == "up":
                    r = make_remote(cfg); r.connect()
                    try:
                        for rrel in remote_files:
                            if rrel not in plan_up:
                                try: r.remove(rrel); deleted += 1
                                except Exception: pass
                    finally:
                        r.close()
                else:
                    keep = {(rel_of(k)[:-len(LOCKED)] if pw and k.endswith(LOCKED) else rel_of(k)) for k in remote_files}
                    for cur, _d, files in os.walk(local):
                        for f in files:
                            p = Path(cur) / f
                            if p.relative_to(local).as_posix() not in keep:
                                try: recycle.to_recycle_bin(p); deleted += 1
                                except Exception: pass
            except Exception:
                pass
        job.data["deleted"] = deleted
        for c in conns:
            c.close()

    if not tasks:
        for c in conns: c.close()
    job = ops.start("sync", "Syncing", tasks, workers=threads, after=after)
    job.data["skipped_same"] = True
    return {"job": job.id, "count": len(tasks), "threads": threads}
