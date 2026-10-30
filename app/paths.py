# Copyright (C) 2026 The Fathomist. Licensed under AGPL-3.0-or-later (see LICENSE).
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "Fathom"
VERSION = "1.3.0"
BRAND = "Fathom"


def data_root() -> Path:
    """Everything Fathom writes (models, results, logs) lives here, never in the app folder."""
    override = os.environ.get("FATHOM_HOME")
    if override:
        base = Path(override)
    elif (ROOT / "portable.txt").exists():
        base = ROOT / "FathomData"           # portable mode: settings, history and saved tools travel with this folder (for example on a USB stick)
    elif os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"]) / APP_NAME
    else:
        base = Path.home() / ".fathom"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sub(name: str) -> Path:
    path = data_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def sessions_dir() -> Path:
    return _sub("sessions")


def models_dir() -> Path:
    return _sub("models")


def logs_dir() -> Path:
    return _sub("logs")


def temp_dir() -> Path:
    return _sub("tmp")


def _caches_beside_data() -> None:
    """Model caches (Hugging Face) go next to Fathom's data, so they follow it to another drive instead of filling C:."""
    try:
        if "HF_HOME" not in os.environ:
            target = data_root() / "hf"
            target.mkdir(parents=True, exist_ok=True)
            os.environ["HF_HOME"] = str(target)
    except OSError:
        pass


_caches_beside_data()
