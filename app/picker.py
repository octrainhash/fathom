# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
"""Native 'choose files / choose a folder' windows. Runs in a helper process so it never blocks the app."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from app.runtime import no_window_flags

_TK = r'''
import json, sys
import tkinter as tk
from tkinter import filedialog
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
root.update()
kind = sys.argv[1]
if kind == "files":
    paths = filedialog.askopenfilenames(parent=root, title="Choose files")
elif kind == "pictures":
    paths = filedialog.askopenfilenames(parent=root, title="Choose reference pictures", filetypes=[("Pictures", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff *.heic *.avif"), ("All files", "*.*")])
elif kind == "image":
    p = filedialog.askopenfilename(parent=root, title="Choose a disk image", filetypes=[("Disk images", "*.iso *.vhd *.vhdx"), ("All files", "*.*")])
    paths = [p] if p else []
else:
    chosen = filedialog.askdirectory(parent=root, title="Choose where to save" if kind == "outfolder" else "Choose a folder", mustexist=(kind != "outfolder"))
    paths = [chosen] if chosen else []
print(json.dumps([str(p) for p in paths]))
'''

_PS_FILES = r'''
Add-Type -AssemblyName System.Windows.Forms
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Multiselect = $true; $d.Title = 'Choose files'; $d.Filter = 'All files (*.*)|*.*'
$owner = New-Object System.Windows.Forms.Form -Property @{TopMost=$true}
if ($d.ShowDialog($owner) -eq 'OK') { ConvertTo-Json -Compress @($d.FileNames) } else { '[]' }
'''
_PS_PICS = _PS_FILES.replace("'Choose files'", "'Choose reference pictures'").replace("'All files (*.*)|*.*'", "'Pictures|*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.gif;*.tif;*.tiff;*.heic;*.avif|All files (*.*)|*.*'")
_PS_FOLDER = r'''
Add-Type -AssemblyName System.Windows.Forms
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = 'Choose a folder'; $d.ShowNewFolderButton = $true
$owner = New-Object System.Windows.Forms.Form -Property @{TopMost=$true}
if ($d.ShowDialog($owner) -eq 'OK') { ConvertTo-Json -Compress @($d.SelectedPath) } else { '[]' }
'''


def _parse(out: str) -> list[str]:
    lines = [l for l in out.strip().splitlines() if l.strip()]
    if not lines:
        return []
    data = json.loads(lines[-1])
    return [data] if isinstance(data, str) else list(data)


def pick(kind: str) -> list[str]:
    kind = kind if kind in ("files", "image", "outfolder", "pictures") else "folder"
    errors = []
    try:  # tkinter dialog (nice multi-select, ships with Python)
        proc = subprocess.run([sys.executable, "-c", _TK, kind], capture_output=True, text=True, creationflags=no_window_flags(), timeout=1800)
        if proc.returncode == 0:
            return [os.path.normpath(p) for p in _parse(proc.stdout)]
        errors.append(proc.stderr.strip()[-200:])
    except Exception as exc:
        errors.append(str(exc))
    if os.name == "nt":  # fallback: the standard Windows dialog through PowerShell
        script = _PS_PICS if kind == "pictures" else (_PS_FILES if kind in ("files", "image") else _PS_FOLDER)
        proc = subprocess.run(["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script],
                              capture_output=True, text=True, creationflags=no_window_flags(), timeout=1800)
        if proc.returncode == 0:
            return [os.path.normpath(p) for p in _parse(proc.stdout)]
        errors.append(proc.stderr.strip()[-200:])
    raise RuntimeError("; ".join(e for e in errors if e) or "no file picker available")
