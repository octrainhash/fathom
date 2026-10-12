"""Drives: see every drive, check / repair / optimise / format / convert it, find where the space went,
and test files against the rules of a file system (FAT32, exFAT, NTFS, APFS, ext4 ...)."""
from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app import ops
from app.convert import formats
from app.convert.core import ConvertError, Ctx
from app.ops import Output, Task
from app.paths import ROOT, data_root
from app.runtime import no_window_flags
from app.service import UserError

IS_WIN = os.name == "nt"
GB = 1024 ** 3

# ------------------------------------------------------------------ what each file system is
FS_INFO = {
    "NTFS": {"name": "NTFS", "maker": "Windows", "max_file": "16 TB (practically unlimited)", "max_volume": "256 TB",
             "windows": "Read and write", "mac": "Read only", "linux": "Read and write (with a free driver)", "tv": "Often read only",
             "features": ["Journal (survives power cuts)", "Permissions", "Compression", "Encryption (EFS, BitLocker)", "Hard links and snapshots"],
             "best": "Your Windows system drive and any drive only Windows uses.",
             "simple": "The normal Windows format. Safe, fast and full-featured. Macs can look at it but not save to it."},
    "exFAT": {"name": "exFAT", "maker": "Microsoft", "max_file": "16 EB (no real limit)", "max_volume": "128 PB",
              "windows": "Read and write", "mac": "Read and write", "linux": "Read and write", "tv": "Most TVs, cameras and consoles",
              "features": ["No 4 GB file limit", "Works on Windows, Mac and Linux", "Light (no journal)"],
              "best": "USB sticks, SD cards and external drives you share between computers.",
              "simple": "The best format for a drive you carry between Windows and Mac. No 4 GB limit. No safety journal, so always eject it before pulling it out."},
    "FAT32": {"name": "FAT32", "maker": "Microsoft", "max_file": "4 GB minus 1 byte", "max_volume": "2 TB (Windows only formats up to 32 GB)",
              "windows": "Read and write", "mac": "Read and write", "linux": "Read and write", "tv": "Works almost everywhere",
              "features": ["Oldest and most compatible", "Max file size 4 GB", "No journal, no permissions"],
              "best": "Small drives for old cameras, car stereos, game consoles, printers and bios updates.",
              "simple": "Works on nearly everything ever made, but cannot hold a single file bigger than 4 GB."},
    "FAT": {"name": "FAT16 / FAT12", "maker": "Microsoft", "max_file": "2 GB (FAT16)", "max_volume": "4 GB",
            "windows": "Read and write", "mac": "Read and write", "linux": "Read and write", "tv": "Very old devices",
            "features": ["Very old", "Tiny limits"], "best": "Only very old devices.", "simple": "The grandparent of FAT32. Only for very old gear."},
    "ReFS": {"name": "ReFS", "maker": "Microsoft", "max_file": "35 PB", "max_volume": "35 PB",
             "windows": "Windows Pro for Workstations / Server", "mac": "No", "linux": "No", "tv": "No",
             "features": ["Self-healing checksums", "Built for huge volumes"], "best": "Servers and big storage pools.", "simple": "A newer, tougher Windows format for servers. Not for everyday drives."},
    "APFS": {"name": "APFS", "maker": "Apple", "max_file": "8 EB", "max_volume": "8 EB",
             "windows": "Not readable without extra software", "mac": "Read and write", "linux": "Read only (with a driver)", "tv": "No",
             "features": ["Snapshots", "Encryption", "Made for SSDs"], "best": "Macs, iPhones and iPads.",
             "simple": "Apple's modern format. Windows cannot open it by itself. If you need the files on Windows, copy them from a Mac to an exFAT drive."},
    "HFS+": {"name": "HFS+ (Mac OS Extended)", "maker": "Apple", "max_file": "8 EB", "max_volume": "8 EB",
             "windows": "Not readable without extra software", "mac": "Read and write", "linux": "Read only", "tv": "No",
             "features": ["Older Mac format", "Time Machine on hard drives"], "best": "Older Macs.", "simple": "Apple's older format. Same advice as APFS."},
    "ext4": {"name": "ext4", "maker": "Linux", "max_file": "16 TB", "max_volume": "1 EB",
             "windows": "Not readable without extra software", "mac": "Not readable without extra software", "linux": "Read and write", "tv": "Some Android TVs",
             "features": ["Journal", "Permissions", "Case sensitive"], "best": "Linux computers.", "simple": "The usual Linux format. Windows cannot open it by itself."},
}
GPT = {"7C3457EF-0000-11AA-AA11-00306543ECAC": "APFS", "48465300-0000-11AA-AA11-00306543ECAC": "HFS+", "0FC63DAF-8483-4772-8E79-3D69D8477DE4": "ext4",
       "E6D6D379-F507-44C2-A23C-238F2A3DF928": "Linux LVM", "0657FD6D-A4AB-43C4-84E5-0933C84B4F4F": "Linux swap", "A19D880F-05FC-4D3B-A006-743F0F84911E": "Linux RAID"}
PLUMBING = {"E3C9E316-0B5C-4DB8-817D-F92DF00215AE", "C12A7328-F81F-11D2-BA4B-00A0C93EC93B", "DE94BBA4-06D1-4D40-A16A-BFD50179D6AC"}   # MSR, EFI, recovery
DRIVE_TYPES = {2: "Removable", 3: "Fixed", 4: "Network", 5: "Disc", 6: "RAM disk"}


# ------------------------------------------------------------------ PowerShell
def _enc(script: str) -> list[str]:
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", base64.b64encode(script.encode("utf-16-le")).decode()]


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def is_admin() -> bool:
    if not IS_WIN:
        return os.geteuid() == 0
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ps_quick(script: str, timeout: float = 45) -> str:
    """Runs a short PowerShell script and returns what it printed ('' if it failed)."""
    if not IS_WIN:
        return ""
    try:
        r = subprocess.run(_enc(script), capture_output=True, timeout=timeout, creationflags=no_window_flags())
        return r.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def ps_run(ctx: Ctx, script: str, elevate: bool = True, on_line=None) -> tuple[int, str]:
    """Runs PowerShell for a job. Needs administrator rights for most disk work: Windows shows its normal permission prompt."""
    if not IS_WIN:
        raise ConvertError("Drive tools work on Windows.")
    if not elevate or is_admin():
        return ctx.run(_enc(script), on_line)
    tmp = Path(tempfile.mkdtemp(prefix="fathom-ps-"))
    try:
        body, out = tmp / "job.ps1", tmp / "out.txt"
        body.write_text("$ErrorActionPreference='Continue'\n& {\n" + script + "\n} *>&1 | Out-File -Encoding utf8 -FilePath " + _q(str(out)) + "\nexit $LASTEXITCODE\n", encoding="utf-8")
        outer = ("try { $p = Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -PassThru -Wait -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File'," + _q(str(body)) +
                 "; exit $p.ExitCode } catch { Write-Output 'PERMISSION_DECLINED'; exit 1223 }")
        rc, text = ctx.run(_enc(outer), None)
        if "PERMISSION_DECLINED" in text or rc == 1223:
            raise ConvertError("Windows asked for permission to change the drive and it was declined. Click Yes on the prompt to continue.")
        try:
            text = out.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            text = text or ""
        if on_line:
            for line in text.splitlines():
                on_line(line)
        return rc, text
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ listing
def _win_basic() -> list[dict]:
    import ctypes
    from ctypes import wintypes

    k = ctypes.windll.kernel32
    k.SetErrorMode(1)   # never pop up "no disk in drive"
    out = []
    mask = k.GetLogicalDrives()
    for i in range(26):
        if not mask >> i & 1:
            continue
        letter = chr(65 + i)
        root = f"{letter}:\\"
        dtype = DRIVE_TYPES.get(k.GetDriveTypeW(root), "Unknown")
        label, fs = ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(261)
        serial, maxc, flags = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
        ready = bool(k.GetVolumeInformationW(root, label, 261, ctypes.byref(serial), ctypes.byref(maxc), ctypes.byref(flags), fs, 261))
        free_u, total, free = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
        have_sizes = bool(k.GetDiskFreeSpaceExW(root, ctypes.byref(free_u), ctypes.byref(total), ctypes.byref(free))) if ready else False
        spc, bps, fc, tc = (wintypes.DWORD() for _ in range(4))
        cluster = spc.value * bps.value if ready and k.GetDiskFreeSpaceW(root, ctypes.byref(spc), ctypes.byref(bps), ctypes.byref(fc), ctypes.byref(tc)) else 0
        out.append({"letter": letter, "root": root, "label": label.value, "fs": fs.value or "", "type": dtype, "ready": ready,
                    "size": total.value if have_sizes else 0, "free": free_u.value if have_sizes else 0, "cluster": cluster,
                    "compressed_vol": bool(flags.value & 0x10), "readonly": bool(flags.value & 0x80000), "serial": f"{serial.value:08X}" if ready else ""})
    return out


def _posix_basic() -> list[dict]:
    out, seen = [], set()
    try:
        lines = Path("/proc/mounts").read_text().splitlines()
    except OSError:
        lines = []
    for ln in lines:
        dev, mnt, fs = (ln.split() + ["", "", ""])[:3]
        if not dev.startswith("/") and fs not in ("overlay", "zfs", "btrfs", "tmpfs") or mnt in seen or mnt.startswith(("/proc", "/sys", "/dev", "/run", "/etc")) or fs in ("tmpfs", "devtmpfs"):
            continue
        seen.add(mnt)
        try:
            u = shutil.disk_usage(mnt)
        except OSError:
            continue
        out.append({"letter": mnt, "root": mnt, "label": Path(mnt).name, "fs": fs, "type": "Fixed", "ready": True, "size": u.total, "free": u.free, "cluster": 4096,
                    "compressed_vol": False, "readonly": False, "serial": ""})
    return out


_ENRICH = r"""
$ErrorActionPreference='SilentlyContinue'
$o=@{parts=@();disks=@();bl=@()}
foreach($p in Get-Partition){ $o.parts += [pscustomobject]@{letter=[string]$p.DriveLetter; disk=$p.DiskNumber; number=$p.PartitionNumber; size=$p.Size; gpt=[string]$p.GptType; mbr=[string]$p.MbrType; system=[bool]$p.IsSystem; boot=[bool]$p.IsBoot; hidden=[bool]$p.IsHidden} }
$pds=@(Get-PhysicalDisk)
foreach($d in Get-Disk){ $pd=$pds | Where-Object { $_.DeviceId -eq [string]$d.Number } | Select-Object -First 1
 $o.disks += [pscustomobject]@{number=$d.Number; name=[string]$d.FriendlyName; bus=[string]$d.BusType; style=[string]$d.PartitionStyle; size=$d.Size; health=[string]$d.HealthStatus; media=[string]$pd.MediaType; offline=[bool]$d.IsOffline} }
foreach($b in Get-BitLockerVolume){ $o.bl += [pscustomobject]@{mount=[string]$b.MountPoint; prot=[string]$b.ProtectionStatus; status=[string]$b.VolumeStatus} }
$o | ConvertTo-Json -Depth 4 -Compress
"""


def _as_list(v) -> list:
    return v if isinstance(v, list) else ([v] if v else [])


def list_drives() -> dict:
    basic = _win_basic() if IS_WIN else _posix_basic()
    extra = {"parts": [], "disks": [], "bl": []}
    if IS_WIN:
        raw = ps_quick(_ENRICH)
        try:
            data = json.loads(raw[raw.index("{"):]) if "{" in raw else {}
            extra = {k: _as_list(data.get(k)) for k in extra}
        except Exception:
            pass
    disks = {d["number"]: d for d in extra["disks"]}
    parts = {p["letter"].upper(): p for p in extra["parts"] if p.get("letter")}
    bl = {b["mount"].rstrip(":\\").upper(): b for b in extra["bl"]}
    sysdrive = (os.environ.get("SystemDrive") or "C:")[0].upper()
    here = [ROOT.drive[:1].upper() if ROOT.drive else "", data_root().drive[:1].upper() if data_root().drive else ""]
    drives = []
    for d in basic:
        L = d["letter"].upper()
        p, dk = parts.get(L, {}), disks.get(parts.get(L, {}).get("disk"), {})
        media = dk.get("media", "") if dk.get("media") not in ("Unspecified", "", None) else ""
        bus = dk.get("bus", "")
        kind = "USB" if bus.upper() == "USB" else ("SD" if bus.upper() == "SD" else media or ("Network" if d["type"] == "Network" else ""))
        d.update({"system": bool(p.get("system") or p.get("boot")) or L == sysdrive, "runs_app": L in here, "media": media or ("USB" if kind == "USB" else ""), "bus": bus,
                  "disk": p.get("disk"), "partition": p.get("number"), "disk_name": dk.get("name", ""), "health": dk.get("health", ""), "style": dk.get("style", ""),
                  "kind": kind, "bitlocker": (bl.get(L) or {}).get("prot", ""), "used": max(0, d["size"] - d["free"])})
        d["fs_key"] = {"FAT32": "FAT32", "EXFAT": "exFAT", "NTFS": "NTFS", "REFS": "ReFS", "FAT": "FAT", "CDFS": "", "UDF": ""}.get(d["fs"].upper(), d["fs"])
        d["protected"] = d["system"] or d["runs_app"] or d["type"] in ("Network", "Disc", "RAM disk")
        drives.append(d)
    other = []
    for p in extra["parts"]:
        if p.get("letter") or p.get("gpt", "").strip("{}").upper() in PLUMBING or p.get("hidden") and not p.get("gpt"):
            continue
        guid = p.get("gpt", "").strip("{}").upper()
        what = GPT.get(guid, "")
        if not what and guid != "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7":
            continue
        dk = disks.get(p.get("disk"), {})
        other.append({"disk": p.get("disk"), "partition": p.get("number"), "size": p.get("size", 0), "what": what or "Windows data (no drive letter)", "disk_name": dk.get("name", ""),
                      "readable": not what, "fs_key": what if what in FS_INFO else ""})
    return {"drives": drives, "other": other, "admin": is_admin(), "windows": IS_WIN, "info": FS_INFO}


def _drive(letter: str) -> dict:
    letter = (letter or "").strip().rstrip(":\\/").upper()
    if not IS_WIN:
        raise UserError("Drive tools work on Windows. They are switched off here.")
    if not re.fullmatch(r"[A-Z]", letter):
        raise UserError("Choose a drive first.")
    for d in list_drives()["drives"]:
        if d["letter"].upper() == letter:
            return d
    raise UserError(f"Drive {letter}: was not found. Was it unplugged?")


# ------------------------------------------------------------------ health (SMART) and tuning state
def health() -> dict:
    script = r"""
$ErrorActionPreference='SilentlyContinue'
$r=@()
foreach($d in Get-PhysicalDisk){ $c = $d | Get-StorageReliabilityCounter
 $r += [pscustomobject]@{id=[string]$d.DeviceId; name=[string]$d.FriendlyName; media=[string]$d.MediaType; bus=[string]$d.BusType; health=[string]$d.HealthStatus; op=[string]$d.OperationalStatus; size=$d.Size;
  temp=$c.Temperature; wear=$c.Wear; hours=$c.PowerOnHours; rerr=$c.ReadErrorsTotal; werr=$c.WriteErrorsTotal} }
ConvertTo-Json -Compress -InputObject @($r)
"""
    raw = ps_quick(script, 60)
    try:
        return {"disks": _as_list(json.loads(raw[raw.index("["):])) if "[" in raw else []}
    except Exception:
        return {"disks": []}


TUNES = {
    "lastaccess": ("disablelastaccess", "Stop writing a 'last opened' time on every read", "1"),
    "8dot3": ("disable8dot3", "Stop making old 8-character file names", "1"),
    "trim": ("disabledeletenotify", "Let Windows tell SSDs which space is free (TRIM)", "0"),
    "memory": ("memoryusage", "Let NTFS use more memory for caching", "2"),
    "mftzone": ("mftzone", "Reserve more room for the file table so it stays in one piece", "2"),
}


def tune_state() -> dict:
    out = {}
    if not IS_WIN:
        return {"windows": False, "items": []}
    for key, (cmd, text, good) in TUNES.items():
        raw = ps_quick(f"fsutil behavior query {cmd}", 20)
        m = re.search(r"=\s*(\d+)", raw)
        out[key] = int(m.group(1)) if m else None
    items = []
    for key, (cmd, text, good) in TUNES.items():
        v = out.get(key)
        # for 'memory' and 'mftzone' a value at or above the good one counts as tuned
        tuned = v is not None and (v >= int(good) if key in ("memory", "mftzone") else str(v) == good)
        items.append({"key": key, "text": text, "value": v, "good": int(good), "tuned": tuned, "known": v is not None})
    return {"windows": True, "items": items, "admin": is_admin()}


# ------------------------------------------------------------------ actions
def _check_letter_job(letter: str) -> dict:
    d = _drive(letter)
    if not d["ready"]:
        raise UserError(f"Drive {d['letter']}: is not ready (no disc or card inside?).")
    return d


def _result(text: str, ok_words: tuple = ()) -> str:
    low = text.lower()
    for w in ok_words:
        if w in low:
            return w
    return ""


def drive_job(kind: str, letter: str, params: dict) -> dict:
    d = _check_letter_job(letter)
    L, root = d["letter"], d["root"]
    fs = (d["fs"] or "").upper()
    params = params or {}
    elevate = True
    title = {"scan": "Checking", "repair": "Repairing", "optimize": "Optimising", "format": "Formatting", "to_ntfs": "Converting to NTFS", "label": "Renaming",
             "eject": "Ejecting", "wipe": "Wiping free space on", "compress": "Compressing", "tune": "Tuning"}.get(kind, "Working on")

    if kind == "scan":
        script = f"chkdsk {L}:"
        done = lambda t: ("No problems found. The drive's file system is healthy." if re.search(r"found no problems|no problems", t, re.I) else
                          ("Problems were found. Use Repair to fix them." if re.search(r"found problems|errors found|corrupt", t, re.I) else "Check finished. See the details below."))
    elif kind == "repair":
        if d["system"]:
            raise UserError("Windows repairs its own system drive when you restart. Open a command prompt as administrator and type: chkdsk C: /f   (then restart).")
        script = f"Repair-Volume -DriveLetter {L} -OfflineScanAndFix" if fs == "NTFS" else f"'Y' | chkdsk {L}: /f"
        done = lambda t: "Repair finished. See the details below."
    elif kind == "optimize":
        mode = params.get("mode", "auto")
        if d["type"] in ("Network", "Disc", "RAM disk"):
            raise UserError("This kind of drive cannot be optimised.")
        if mode == "auto":
            mode = "trim" if d["media"] == "SSD" or d["kind"] in ("SSD", "SCM") else ("defrag" if d["media"] == "HDD" else "analyze")
        flag = {"trim": "-ReTrim", "defrag": "-Defrag", "analyze": "-Analyze", "consolidate": "-SlabConsolidate"}.get(mode)
        if not flag:
            raise UserError("Unknown optimise mode.")
        script = f"Optimize-Volume -DriveLetter {L} {flag} -Verbose"
        done = lambda t, m=mode: {"trim": "TRIM sent. The SSD now knows which space is free, so it keeps its speed.", "defrag": "Defragmentation finished. Files are in fewer pieces.",
                                  "analyze": "Analysis finished. See the details below.", "consolidate": "Space consolidated."}[m]
    elif kind == "format":
        target = params.get("fs", "exFAT")
        if target not in ("NTFS", "exFAT", "FAT32", "ReFS"):
            raise UserError("Choose NTFS, exFAT, FAT32 or ReFS.")
        if d["protected"]:
            raise UserError(f"Drive {L}: is protected because " + ("it holds Windows." if d["system"] else "it holds this app." if d["runs_app"] else "it is not a normal disk.") + " It cannot be formatted from here.")
        if str(params.get("confirm", "")).strip().upper().rstrip(":") != L:
            raise UserError(f"To format, type the drive letter {L} to confirm. Everything on the drive will be erased.")
        if target == "FAT32" and d["size"] > 32 * GB:
            raise UserError("Windows cannot format FAT32 above 32 GB. Choose exFAT (works on Windows, Mac and Linux, no 4 GB file limit) or NTFS.")
        label = re.sub(r"[^\w .\-]", "", str(params.get("label", ""))).strip()[:32 if target == "NTFS" else 11 if target in ("FAT32",) else 15]
        alloc = int(params.get("cluster") or 0)
        if alloc not in (0, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576, 2097152, 4194304, 8388608, 16777216, 33554432):
            raise UserError("That cluster size is not valid.")
        full = "-Full" if params.get("full") else ""
        size_arg = f"-AllocationUnitSize {alloc}" if alloc else ""
        script = f"Format-Volume -DriveLetter {L} -FileSystem {target} -NewFileSystemLabel {_q(label)} {size_arg} {full} -Confirm:$false -Force:$false | Out-String"
        done = lambda t: f"Drive {L}: is now {target}."
    elif kind == "to_ntfs":
        if fs not in ("FAT", "FAT32"):
            raise UserError("Windows can convert FAT and FAT32 drives to NTFS without erasing them. exFAT drives must be copied off and formatted instead.")
        if d["system"]:
            raise UserError("This is the Windows drive.")
        script = f"{_q(d['label'])} | & convert.exe {L}: /fs:ntfs /x"
        done = lambda t: "Converted to NTFS. Your files were kept. This cannot be undone without formatting."
    elif kind == "label":
        label = re.sub(r"[^\w .\-]", "", str(params.get("label", ""))).strip()[:32]
        script = f"Set-Volume -DriveLetter {L} -NewFileSystemLabel {_q(label)}"
        done = lambda t: f"Renamed to “{label}”." if label else "Name removed."
    elif kind == "eject":
        if d["type"] != "Removable":
            raise UserError("Only USB sticks, SD cards and other removable drives can be ejected.")
        script = ("$s=New-Object -ComObject Shell.Application; $ns=$s.Namespace(17); $it=$ns.ParseName(" + _q(f"{L}:") + "); if(-not $it){ throw 'Drive not found' }; $it.InvokeVerb('Eject'); Start-Sleep 2")
        elevate = False
        done = lambda t: "Ejected. It is safe to unplug it."
    elif kind == "wipe":
        script = f"cipher /w:{L}:\\"
        done = lambda t: "Free space wiped. Deleted files on this drive can no longer be recovered."
    else:
        raise UserError("Unknown drive action.")

    def fn(ctx: Ctx, task: Task) -> Output:
        lines: list[str] = []

        def on_line(line: str) -> None:
            lines.append(line)
            ctx.status(line[:120])
            m = re.search(r"(\d{1,3})\s*%", line)
            if m:
                ctx.progress(min(1.0, int(m.group(1)) / 100.0))

        rc, text = ps_run(ctx, script, elevate, on_line)
        if rc != 0 and kind not in ("scan",):
            tail = " ".join(l for l in text.splitlines() if l.strip())[-300:]
            raise ConvertError(f"Windows reported a problem (code {rc}). {tail}")
        ctx.job.data["details"] = "\n".join(l for l in text.splitlines() if l.strip())[-6000:]  # type: ignore[attr-defined]
        return Output([], done(text))

    job = ops.start("drive-" + kind, f"{title} {L}:", [Task(f"{title} {L}:", fn)], workers=1)
    return {"job": job.id}


def tune_apply(keys: list[str]) -> dict:
    if not IS_WIN:
        raise UserError("Drive tools work on Windows.")
    keys = [k for k in keys if k in TUNES]
    if not keys:
        raise UserError("Choose at least one setting.")
    script = "\n".join(f"fsutil behavior set {TUNES[k][0]} {TUNES[k][2]}" for k in keys)

    def fn(ctx: Ctx, task: Task) -> Output:
        rc, text = ps_run(ctx, script, True)
        if rc != 0:
            raise ConvertError("Windows did not accept the change. " + " ".join(text.split())[-200:])
        return Output([], "Done. Some settings take effect after a restart.")

    return {"job": ops.start("drive-tune", "Tuning NTFS", [Task("Tuning NTFS", fn)], workers=1).id}


def compress_folder(path: str, undo: bool, strength: str) -> dict:
    p = Path(path)
    if not IS_WIN:
        raise UserError("NTFS compression works on Windows.")
    if not p.is_dir():
        raise UserError("Choose a folder.")
    alg = {"fast": "xpress4k", "balanced": "xpress8k", "strong": "lzx"}.get(strength, "xpress8k")
    script = f"compact {'/u' if undo else '/c /exe:' + alg} /s:{_q(str(p))} /a /i /q"

    def fn(ctx: Ctx, task: Task) -> Output:
        before = ops.path_bytes(p)
        rc, text = ps_run(ctx, script, False, lambda l: ctx.status(l[:100]))
        ctx.job.data["details"] = text[-4000:]  # type: ignore[attr-defined]
        if "not supported" in text.lower() or "not allowed" in text.lower():
            raise ConvertError("This folder's drive does not support compression. Only NTFS drives do.")
        m = re.search(r"([\d.,]+)\s+to\s+1", text) or re.search(r"compression ratio.*?([\d.,]+)", text, re.I)
        return Output([], ("Folder expanded again." if undo else "Folder compressed. It takes less room on the drive and opens as normal.") + (f" Ratio about {m.group(1)}:1." if m else ""))

    return {"job": ops.start("drive-compress", "Compressing folder", [Task(p.name, fn, p)], workers=1).id}


def image_action(path: str, mount: bool) -> dict:
    p = Path(path)
    if not IS_WIN:
        raise UserError("Disk images are mounted on Windows.")
    if mount and not p.is_file():
        raise UserError("Choose an .iso, .vhd or .vhdx file.")
    script = (f"Mount-DiskImage -ImagePath {_q(str(p))} | Out-Null; Start-Sleep 1; (Get-DiskImage -ImagePath {_q(str(p))} | Get-Volume).DriveLetter" if mount else
              f"Dismount-DiskImage -ImagePath {_q(str(p))} | Out-Null")

    def fn(ctx: Ctx, task: Task) -> Output:
        rc, text = ps_run(ctx, script, False)
        if rc != 0:
            raise ConvertError("Windows could not " + ("mount" if mount else "unmount") + " this image. " + " ".join(text.split())[-200:])
        m = re.search(r"\b([A-Z])\b\s*$", text.strip())
        return Output([], (f"Mounted as drive {m.group(1)}:." if m else "Mounted.") if mount else "Unmounted.")

    return {"job": ops.start("drive-image", "Disk image", [Task(p.name, fn, p)], workers=1).id}


# ------------------------------------------------------------------ where did the space go
def space_scan(path: str) -> dict:
    root = Path(path)
    if not root.exists():
        raise UserError("That folder or drive was not found.")
    cluster = 4096
    if IS_WIN and root.drive:
        for d in _win_basic():
            if d["letter"].upper() == root.drive[:1].upper() and d["cluster"]:
                cluster = d["cluster"]

    def fn(ctx: Ctx, task: Task) -> Output:
        children: list[dict] = []
        biggest: list[tuple[int, str]] = []
        types: dict[str, list[int]] = {}
        totals = {"bytes": 0, "alloc": 0, "files": 0, "dirs": 0, "denied": 0}

        def walk(top: Path) -> tuple[int, int]:
            size = files = 0
            stack = [top]
            while stack:
                cur = stack.pop()
                try:
                    it = os.scandir(cur)
                except OSError:
                    totals["denied"] += 1
                    continue
                with it:
                    for e in it:
                        try:
                            if e.is_symlink() or (hasattr(e, "is_junction") and e.is_junction()):
                                continue
                            if e.is_dir(follow_symlinks=False):
                                totals["dirs"] += 1
                                stack.append(Path(e.path))
                            else:
                                s = e.stat(follow_symlinks=False).st_size
                                size += s
                                files += 1
                                totals["alloc"] += math.ceil(s / cluster) * cluster if s else 0
                                cat = formats.category(formats.ext_of(e.name) or "bin") or "other"
                                t = types.setdefault(cat, [0, 0])
                                t[0] += s
                                t[1] += 1
                                if len(biggest) < 60 or s > biggest[-1][0]:
                                    biggest.append((s, e.path))
                                    biggest.sort(reverse=True)
                                    del biggest[60:]
                        except OSError:
                            totals["denied"] += 1
                    if files % 500 == 0:
                        ctx.check()
                        ctx.status(str(cur)[-90:])
            return size, files

        ctx.status("Measuring…")
        if root.is_file():
            s = root.stat().st_size
            children.append({"name": root.name, "path": str(root), "bytes": s, "files": 1, "dir": False})
            totals.update(bytes=s, files=1, alloc=math.ceil(s / cluster) * cluster)
        else:
            entries = []
            try:
                entries = list(os.scandir(root))
            except OSError as exc:
                raise ConvertError(f"Windows did not allow opening this folder ({exc.strerror or exc}).")
            for n, e in enumerate(entries):
                ctx.check()
                ctx.progress(n / max(1, len(entries)))
                try:
                    if e.is_symlink() or (hasattr(e, "is_junction") and e.is_junction()):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        totals["dirs"] += 1
                        s, f = walk(Path(e.path))
                        children.append({"name": e.name, "path": e.path, "bytes": s, "files": f, "dir": True})
                    else:
                        s = e.stat(follow_symlinks=False).st_size
                        totals["alloc"] += math.ceil(s / cluster) * cluster if s else 0
                        cat = formats.category(formats.ext_of(e.name) or "bin") or "other"
                        t = types.setdefault(cat, [0, 0])
                        t[0] += s
                        t[1] += 1
                        biggest.append((s, e.path)); biggest.sort(reverse=True); del biggest[60:]
                        children.append({"name": e.name, "path": e.path, "bytes": s, "files": 1, "dir": False})
                except OSError:
                    totals["denied"] += 1
            totals["bytes"] = sum(c["bytes"] for c in children)
            totals["files"] = sum(c["files"] for c in children)
        children.sort(key=lambda c: -c["bytes"])
        d = ctx.job.data  # type: ignore[attr-defined]
        d.update(root=str(root), cluster=cluster, children=children[:200], biggest=[{"path": p, "bytes": s} for s, p in biggest], types=[{"category": k, "bytes": v[0], "files": v[1]} for k, v in sorted(types.items(), key=lambda kv: -kv[1][0])],
                 total=totals["bytes"], allocated=totals["alloc"], slack=max(0, totals["alloc"] - totals["bytes"]), files=totals["files"], dirs=totals["dirs"], denied=totals["denied"])
        return Output([], f"{totals['files']:,} files, {totals['bytes'] / GB:.2f} GB.")

    return {"job": ops.start("space", "Measuring", [Task("Measuring " + root.name, fn, root)], workers=1).id}


# ------------------------------------------------------------------ will my files work on this file system?
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RULES = {
    "FAT32": {"label": "FAT32", "max_file": 4 * GB - 1, "chars": True, "reserved": True, "dotspace": True, "path": 260, "case": True},
    "exFAT": {"label": "exFAT", "max_file": None, "chars": True, "reserved": True, "dotspace": True, "path": 260, "case": True},
    "NTFS": {"label": "NTFS", "max_file": None, "chars": True, "reserved": True, "dotspace": True, "path": 260, "case": True},
    "APFS": {"label": "APFS (Mac)", "max_file": None, "chars": False, "colon": True, "reserved": False, "dotspace": False, "path": 0, "case": True},
    "ext4": {"label": "ext4 (Linux)", "max_file": None, "chars": False, "reserved": False, "dotspace": False, "path": 0, "case": False},
}


def safe_name(name: str, rule: dict) -> str:
    stem, dot, ext = name.rpartition(".") if "." in name.strip(".") else (name, "", "")
    base = (stem + dot + ext) if dot else name
    if rule.get("chars"):
        base = BAD.sub("_", base)
    elif rule.get("colon"):
        base = base.replace(":", "-")
    if rule.get("dotspace"):
        base = base.rstrip(" .") or "_"
    if rule.get("reserved") and base.split(".")[0].upper() in RESERVED:
        base = "_" + base
    if len(base) > 255:
        s, d, e = base.rpartition(".")
        base = (s[: 255 - len(e) - 1] + d + e) if d and len(e) < 20 else base[:255]
    return base


def compat_check(paths: list[str], fs: str, recursive: bool = True) -> dict:
    rule = RULES.get(fs)
    if not rule:
        raise UserError("Choose a file system to check against.")
    roots = [Path(p) for p in paths if Path(p).exists()]
    if not roots:
        raise UserError("Add the files or folders you plan to copy.")

    def fn(ctx: Ctx, task: Task) -> Output:
        issues: list[dict] = []
        total = count = 0
        base_len = {str(r): len(str(r.parent)) for r in roots}

        def flag(p: Path, problem: str, kind: str, fixable: bool, new: str = "") -> None:
            if len(issues) < 5000:
                issues.append({"path": str(p), "name": p.name, "problem": problem, "kind": kind, "fixable": fixable, "new": new, "dir": p.is_dir()})

        def check_dir_names(parent: Path, names: list[str]) -> None:
            if rule["case"]:
                seen: dict[str, str] = {}
                for n in names:
                    k = n.lower()
                    if k in seen and seen[k] != n:
                        flag(parent / n, f"Same name as “{seen[k]}” except for capital letters. This system treats them as one file, so one would overwrite the other.", "case", False)
                    seen[k] = n

        for r in roots:
            top = [r] if r.is_file() else None
            stack = [r]
            while stack:
                ctx.check()
                cur = stack.pop()
                try:
                    kids = sorted(os.scandir(cur), key=lambda e: e.name) if cur.is_dir() else []
                except OSError:
                    continue
                check_dir_names(cur, [k.name for k in kids])
                items = [cur] if cur is r else []
                items += [Path(k.path) for k in kids]
                for p in items:
                    name = p.name
                    isdir = p.is_dir()
                    if p is not r or True:
                        count += 1
                    if rule.get("chars") and BAD.search(name):
                        flag(p, "The name has a character this system does not allow ( < > : \" / \\ | ? * ).", "chars", True, safe_name(name, rule))
                    elif rule.get("colon") and ":" in name:
                        flag(p, "A colon (:) shows up as a slash on a Mac.", "chars", True, safe_name(name, rule))
                    if rule.get("dotspace") and (name.endswith((" ", ".")) and name not in (".", "..")):
                        flag(p, "The name ends with a space or a dot, which Windows removes.", "dotspace", True, safe_name(name, rule))
                    if rule.get("reserved") and name.split(".")[0].upper() in RESERVED:
                        flag(p, "This name is reserved by Windows (like CON, NUL, COM1).", "reserved", True, safe_name(name, rule))
                    if len(name.encode("utf-8")) > 255:
                        flag(p, "The name is longer than 255 characters.", "long", True, safe_name(name, rule))
                    if rule["path"] and len(str(p)) - base_len.get(str(r), 0) > rule["path"]:
                        flag(p, f"The full path is longer than {rule['path']} characters. Older programs cannot open it.", "path", False)
                    if not isdir:
                        try:
                            s = p.stat().st_size
                        except OSError:
                            continue
                        total += s
                        if rule["max_file"] and s > rule["max_file"]:
                            flag(p, f"The file is {s / GB:.1f} GB. {rule['label']} cannot hold a file bigger than 4 GB. Use exFAT or NTFS, or split the file (Tools → Split).", "size", False)
                for k in kids:
                    try:
                        if k.is_dir(follow_symlinks=False) and recursive:
                            stack.append(Path(k.path))
                    except OSError:
                        pass
                if r.is_file():
                    break
            ctx.progress(0.5)
        ctx.job.data.update(issues=issues, fs=fs, checked=count, bytes=total, fixable=sum(1 for i in issues if i["fixable"]))  # type: ignore[attr-defined]
        return Output([], "Everything fits." if not issues else f"{len(issues)} problem(s) found.")

    return {"job": ops.start("compat", "Checking files", [Task("Checking files", fn)], workers=1).id}


def compat_fix(job_id: str) -> dict:
    from app.filetools import _write_journal

    job = ops.OPJOBS.get(job_id)
    if not job or "issues" not in job.data:
        raise UserError("Run the check again first.")
    fs = job.data["fs"]
    rule = RULES[fs]
    todo = [i for i in job.data["issues"] if i["fixable"] and i["new"]]
    todo.sort(key=lambda i: -len(Path(i["path"]).parts))   # deepest first, so parents keep their path while children are renamed
    journal, failed = [], []
    for i in todo:
        p = Path(i["path"])
        if not p.exists():
            continue
        new = i["new"]
        target = p.with_name(new)
        n = 2
        while target.exists() and target != p:
            stem, dot, ext = new.rpartition(".") if "." in new else (new, "", "")
            target = p.with_name(f"{stem} ({n}){dot}{ext}" if dot else f"{new} ({n})")
            n += 1
        try:
            p.rename(target)
            journal.append({"from": str(p), "to": str(target)})
        except OSError as exc:
            failed.append({"path": str(p), "error": str(exc)})
    if journal:
        _write_journal("compat-fix", journal)
    return {"renamed": len(journal), "failed": failed}


# ------------------------------------------------------------------ which file system should I use?
def advise(uses: list[str], size_gb: float, has_big_files: bool) -> dict:
    uses = set(uses or [])
    reasons: list[str] = []
    old = bool(uses & {"tv", "camera", "console", "car"})
    others = bool(uses & {"mac", "linux"})
    if "internal" in uses and not others and not old:
        best, alt = "NTFS", "ReFS only on Windows Pro for Workstations or Server"
        reasons += ["It is the format Windows is built around and has the safety journal.", "Only Windows needs to read this drive."]
    elif uses == {"mac"}:
        best, alt = "APFS", "exFAT if you also need it on Windows"
        reasons += ["APFS is Apple's own format. Format it on a Mac (Windows cannot create APFS)."]
    elif uses == {"linux"}:
        best, alt = "ext4", "exFAT if you also need it on Windows"
        reasons += ["ext4 is the normal Linux format. Format it on Linux (Windows cannot create ext4)."]
    elif old:
        if has_big_files or size_gb > 32:
            best, alt = "exFAT", "FAT32 (only for drives up to 32 GB and files under 4 GB)"
            reasons += ["Newer TVs, cameras and consoles read exFAT.", "FAT32 would break on big files or drives above 32 GB."]
        else:
            best, alt = "FAT32", "exFAT if the device is from the last 10 years"
            reasons += ["FAT32 works with almost every device ever made.", "The drive is small and files are under 4 GB, so FAT32's limits do not hurt."]
    elif others:
        best, alt = "exFAT", "NTFS if you only copy to a Mac, never from it"
        reasons += ["Windows, Mac and Linux can all read and write it.", "No 4 GB file limit."]
    elif "windows" in uses:
        best, alt = "NTFS", "exFAT if you may plug it into other computers later"
        reasons += ["Windows only means NTFS gives the most safety and features."]
    else:
        best, alt = "exFAT", "NTFS for a Windows-only drive"
        reasons += ["It is the safest all-round choice for an external drive."]
    if "ssd" in uses:
        reasons.append("For an SSD, keep TRIM on (Optimise → Auto does this).")
    return {"best": best, "info": FS_INFO.get(best, {}), "alternative": alt, "reasons": reasons, "table": list(FS_INFO.values())}
