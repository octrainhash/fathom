"""Settings, secret keys and saved chats of the assistant. Keys are protected with Windows' own data-protection (DPAPI) when on Windows, so a stolen
settings file is useless on another PC or user account; they are never sent to the screen."""
from __future__ import annotations

import base64
import json
import os
import threading
import time
import uuid
from pathlib import Path

from app.paths import data_root

_LOCK = threading.RLock()

DEFAULTS = {
    "provider": "ollama",                                       # ollama (free, on this PC, no key) | anthropic | openai
    "models": {"anthropic": "claude-sonnet-5-5", "openai": "gpt-4.1", "ollama": "qwen3-vl:4b-instruct"},
    "base_urls": {"anthropic": "https://api.anthropic.com", "openai": "https://api.openai.com/v1", "ollama": "http://localhost:11434/v1"},
    "approval": "ask_changes",                                  # ask_changes | ask_all | never
    "max_steps": 40,
    "image": {"provider": "none", "model": "gpt-image-1", "base_url": "https://api.openai.com/v1", "size": "1024x1024"},   # none | openai | a1111
    "tts": {"provider": "system", "voice": "", "model": "tts-1", "base_url": "https://api.openai.com/v1"},                  # system | openai
    "handwriting": "auto",                                      # auto | ai | trocr | off
    "output_dir": "",                                           # where the assistant puts new files ("" = Documents\Fathom AI)
    "memory": [],                                               # things the assistant was asked to remember
    "web": True,                                                # may search the web and read web pages
}

SECRET_NAMES = ("anthropic", "openai", "ollama", "image", "tts")


def root() -> Path:
    p = data_root() / "ai"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ------------------------------------------------------------------ protecting keys
def _protect(raw: bytes) -> bytes:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class BLOB(ctypes.Structure):
                _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

            buf = ctypes.create_string_buffer(raw, len(raw))
            inb, out = BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), BLOB()
            if ctypes.windll.crypt32.CryptProtectData(ctypes.byref(inb), "Fathom", None, None, None, 0, ctypes.byref(out)):
                data = ctypes.string_at(out.pbData, out.cbData)
                ctypes.windll.kernel32.LocalFree(out.pbData)
                return b"dpapi:" + base64.b64encode(data)
        except Exception:
            pass
    return b"b64:" + base64.b64encode(raw)


def _unprotect(blob: bytes) -> bytes:
    if blob.startswith(b"dpapi:") and os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        raw = base64.b64decode(blob[6:])
        buf = ctypes.create_string_buffer(raw, len(raw))
        inb, out = BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), BLOB()
        if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(out)):
            data = ctypes.string_at(out.pbData, out.cbData)
            ctypes.windll.kernel32.LocalFree(out.pbData)
            return data
        raise ValueError("cannot unlock")
    if blob.startswith(b"b64:"):
        return base64.b64decode(blob[4:])
    return blob


def _secrets_path() -> Path:
    return root() / "keys.json"


def get_secret(name: str) -> str:
    env = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(name)
    with _LOCK:
        try:
            d = json.loads(_secrets_path().read_text(encoding="utf-8"))
            if d.get(name):
                return _unprotect(d[name].encode()).decode("utf-8")
        except Exception:
            pass
    return os.environ.get(env, "") if env else ""


def set_secret(name: str, value: str) -> None:
    if name not in SECRET_NAMES:
        raise ValueError("unknown key")
    with _LOCK:
        try:
            d = json.loads(_secrets_path().read_text(encoding="utf-8"))
        except Exception:
            d = {}
        if value.strip():
            d[name] = _protect(value.strip().encode("utf-8")).decode()
        else:
            d.pop(name, None)
        p = _secrets_path()
        p.write_text(json.dumps(d), encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass


# ------------------------------------------------------------------ settings
def _merge(base: dict, new: dict) -> dict:
    out = dict(base)
    for k, v in (new or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load() -> dict:
    with _LOCK:
        try:
            d = json.loads((root() / "settings.json").read_text(encoding="utf-8"))
        except Exception:
            d = {}
    out = _merge(DEFAULTS, d)
    # llama3.2-vision no longer loads in current Ollama ("unknown model architecture: mllama"): move old settings to the working default
    # qwen3-vl:4b is the always-thinking edition (very slow to answer); the -instruct edition is the same model without the long thinking
    if out.get("models", {}).get("ollama") in ("llama3.2-vision", "llama3.2-vision:11b", "qwen3-vl:4b"):
        out["models"]["ollama"] = DEFAULTS["models"]["ollama"]
    return out


def save(patch: dict) -> dict:
    with _LOCK:
        cur = load()
        allowed = set(DEFAULTS)
        cur = _merge(cur, {k: v for k, v in (patch or {}).items() if k in allowed})
        (root() / "settings.json").write_text(json.dumps(cur, indent=1), encoding="utf-8")
        return cur


def public() -> dict:
    s = load()
    s["has_key"] = {n: bool(get_secret(n)) for n in SECRET_NAMES}
    return s


def output_dir() -> Path:
    s = load().get("output_dir") or ""
    if s:
        p = Path(s)
    else:
        docs = Path.home() / "Documents"
        p = (docs if docs.exists() else Path.home()) / "Fathom AI"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ------------------------------------------------------------------ chats
def chats_dir() -> Path:
    p = root() / "chats"
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_chat(chat: dict) -> None:
    with _LOCK:
        (chats_dir() / f"{chat['id']}.json").write_text(json.dumps(chat, ensure_ascii=False), encoding="utf-8")


def list_chats() -> list[dict]:
    out = []
    for f in sorted(chats_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:200]:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({"id": d["id"], "title": d.get("title") or "Chat", "updated": d.get("updated", 0), "messages": len(d.get("messages", []))})
        except Exception:
            continue
    return out


def load_chat(cid: str) -> dict | None:
    if not cid.isalnum():
        return None
    try:
        return json.loads((chats_dir() / f"{cid}.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def delete_chat(cid: str) -> None:
    if cid.isalnum():
        try:
            (chats_dir() / f"{cid}.json").unlink()
        except OSError:
            pass


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def now() -> float:
    return time.time()
