"""Small shared helpers (locks, thread counts, Windows flags)."""
from __future__ import annotations

import os
import threading

# OCR and CLIP both use every CPU core internally, so we run one model call at a time.
ML_LOCK = threading.RLock()


def cpu_threads() -> int:
    return max(2, min(os.cpu_count() or 4, 8))


def no_window_flags() -> int:
    """CREATE_NO_WINDOW on Windows so helper processes never flash a console."""
    return 0x08000000 if os.name == "nt" else 0
