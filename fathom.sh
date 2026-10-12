#!/usr/bin/env bash
# Fathom for macOS and Linux (also Raspberry Pi, Chromebooks with Linux, WSL).
#   ./fathom.sh                 install on first run, then open Fathom
#   ./fathom.sh repair          run the setup again
#   ./fathom.sh --serve         run as a private web server so phones, tablets and other computers can use it
#                               (add --https for the microphone on phones, --port 9000 to change the port)
set -u
cd "$(dirname "$0")"
APP="$PWD"
# the folder for Fathom's data: FATHOM_HOME if set, else the one chosen in ./install.sh (saved in .data-dir), else ~/.fathom
if [ -z "${FATHOM_HOME:-}" ] && [ -f "$APP/.data-dir" ]; then FATHOM_HOME="$(head -1 "$APP/.data-dir")"; fi
if [ -n "${FATHOM_HOME:-}" ]; then export FATHOM_HOME; fi
DATA="${FATHOM_HOME:-$HOME/.fathom}"
mkdir -p "$DATA"
LOG="$DATA/setup.log"
say() { printf '%s\n' "$*"; }

VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' app/paths.py | head -1)"
HAVE=""; [ -f "$DATA/build.txt" ] && HAVE="$(cat "$DATA/build.txt")"
VENV_PY="$DATA/venv/bin/python"

if [ "${1:-}" = "repair" ]; then shift; rm -f "$DATA/build.txt"; HAVE=""; fi

find_python() {
  for c in python3.12 python3 python; do
    if command -v "$c" >/dev/null 2>&1; then
      if "$c" -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,12) else 1)' 2>/dev/null; then command -v "$c"; return 0; fi
    fi
  done
  return 1
}

install_python() {
  say "Python 3.12 was not found. Getting it with 'uv' (a small, safe tool that installs Python for you; no administrator rights needed)..."
  if ! command -v uv >/dev/null 2>&1; then
    if command -v curl >/dev/null 2>&1; then curl -LsSf https://astral.sh/uv/install.sh | sh >>"$LOG" 2>&1
    elif command -v wget >/dev/null 2>&1; then wget -qO- https://astral.sh/uv/install.sh | sh >>"$LOG" 2>&1
    else say "Neither curl nor wget is installed. Install Python 3.12 yourself (macOS: brew install python@3.12, Ubuntu/Debian: sudo apt install python3.12 python3.12-venv) and run this again."; exit 1; fi
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  fi
  uv python install 3.12 >>"$LOG" 2>&1 || { say "Could not install Python 3.12 (see $LOG)."; exit 1; }
  uv python find 3.12
}

if [ ! -x "$VENV_PY" ] || [ "$HAVE" != "$VERSION" ] || [ ! -f "$DATA/installed-2.ok" ]; then
  say "Setting up Fathom $VERSION (first run only; a few minutes, needs internet). Details: $LOG"
  PY="$(find_python)" || PY="$(install_python)"
  [ -n "${PY:-}" ] || { say "No Python 3.12 available."; exit 1; }
  if ! "$PY" -c 'import venv, ensurepip' 2>/dev/null; then
    say "Python's 'venv' part is missing. On Ubuntu/Debian run: sudo apt install python3.12-venv   then run ./fathom.sh again."; exit 1
  fi
  "$PY" setup_app.py || { say "Setup did not finish. Send me $LOG"; exit 1; }
  # a launcher entry for Linux desktops (macOS: drag Fathom.command to the Dock)
  if [ "$(uname -s)" = "Linux" ]; then
    mkdir -p "$HOME/.local/share/applications"
    cat > "$HOME/.local/share/applications/fathom.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Fathom
Comment=Find, convert, edit and organise any file
Exec=bash "$APP/fathom.sh"
Icon=$APP/assets/fathom.png
Terminal=false
Categories=Utility;
DESK
  fi
fi

if ! command -v ffmpeg >/dev/null 2>&1; then :; fi   # Fathom brings its own ffmpeg
if [ "$(uname -s)" = "Darwin" ] && ! command -v soffice >/dev/null 2>&1 && [ ! -d /Applications/LibreOffice.app ]; then
  say "(Tip: for Word/Excel/PowerPoint conversion install LibreOffice:  brew install --cask libreoffice )"
elif [ "$(uname -s)" = "Linux" ] && ! command -v soffice >/dev/null 2>&1; then
  say "(Tip: for Word/Excel/PowerPoint conversion install LibreOffice, e.g.:  sudo apt install libreoffice-core libreoffice-writer libreoffice-calc libreoffice-impress )"
fi
exec "$VENV_PY" launch.py "$@"
