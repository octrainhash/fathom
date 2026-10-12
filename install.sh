#!/usr/bin/env bash
# Fathom installer for macOS and Linux (also Raspberry Pi, Chromebook Linux, WSL, and most distros).
# It asks what you want and where to put it. Nothing is chosen for you. Run:   bash install.sh
set -u
cd "$(dirname "$0")"
APP="$PWD"
OS="$(uname -s)"
ask() {  # ask "question" default(y|n)  -> returns 0 for yes
  local q="$1" d="${2:-n}" a hint="[y/N]"
  [ "$d" = "y" ] && hint="[Y/n]"
  read -r -p "$q $hint " a || a=""
  a="${a:-$d}"
  case "$a" in y|Y|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}
echo
echo "Fathom installer"
echo "================"
echo "Fathom itself is always installed. Say yes or no to each extra."
echo

# 1. where the data goes
DEF="$HOME/.fathom"
echo "Fathom keeps its Python packages, models and saved results in one data folder."
df -h "$HOME" 2>/dev/null | tail -1 | awk '{print "  Free space in your home: " $4}'
read -r -p "Data folder (press Enter for $DEF): " DATA_DIR || DATA_DIR=""
DATA_DIR="${DATA_DIR:-$DEF}"
DATA_DIR="${DATA_DIR/#\~/$HOME}"
mkdir -p "$DATA_DIR" || { echo "Cannot create $DATA_DIR."; exit 1; }
if [ "$DATA_DIR" != "$DEF" ]; then printf '%s\n' "$DATA_DIR" > "$APP/.data-dir"; else rm -f "$APP/.data-dir"; fi
echo "  -> data goes in $DATA_DIR"
echo

# 2. LibreOffice (Word, Excel, PowerPoint)
WANT_OFFICE=0
if ! command -v soffice >/dev/null 2>&1 && [ ! -d /Applications/LibreOffice.app ]; then
  if ask "Install LibreOffice (open and convert Word, Excel, PowerPoint)? About 350 MB, may ask for your password." n; then WANT_OFFICE=1; fi
fi
# 3. Ollama (free AI on this computer)
WANT_AI=0
if ! command -v ollama >/dev/null 2>&1; then
  if ask "Install the free AI assistant that runs on this computer (Ollama + a 3.3 GB model)? No key or account needed." n; then WANT_AI=1; fi
else
  if ask "Ollama is already here. Download the 3.3 GB model Fathom uses (qwen3-vl:4b)?" n; then WANT_AI=2; fi
fi
echo

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

if [ "$WANT_OFFICE" = 1 ]; then
  echo "Installing LibreOffice ..."
  if [ "$OS" = "Darwin" ]; then
    if command -v brew >/dev/null 2>&1; then brew install --cask libreoffice || echo "  (LibreOffice install did not finish; get it from libreoffice.org)"
    else echo "  Homebrew is not installed. Get LibreOffice from https://www.libreoffice.org/download/ then run Fathom again."; fi
  elif command -v apt-get >/dev/null 2>&1; then $SUDO apt-get install -y libreoffice-core libreoffice-writer libreoffice-calc libreoffice-impress || echo "  (did not finish)"
  elif command -v dnf >/dev/null 2>&1; then $SUDO dnf install -y libreoffice-core libreoffice-writer libreoffice-calc libreoffice-impress || echo "  (did not finish)"
  elif command -v pacman >/dev/null 2>&1; then $SUDO pacman -S --noconfirm libreoffice-fresh || echo "  (did not finish)"
  elif command -v zypper >/dev/null 2>&1; then $SUDO zypper install -y libreoffice || echo "  (did not finish)"
  else echo "  Could not find a package manager. Get LibreOffice from https://www.libreoffice.org/download/"; fi
fi

if [ "$WANT_AI" = 1 ]; then
  echo "Installing Ollama ..."
  if [ "$OS" = "Darwin" ]; then
    if command -v brew >/dev/null 2>&1; then brew install ollama || echo "  (did not finish; get the app from https://ollama.com/download)"
    else echo "  Get the Ollama app from https://ollama.com/download then run this again."; fi
  else
    echo "  This uses Ollama's own official installer (https://ollama.com/install.sh)."
    if command -v curl >/dev/null 2>&1; then curl -fsSL https://ollama.com/install.sh | sh || echo "  (did not finish)"
    else echo "  curl is missing. Install curl, or get Ollama from https://ollama.com/download"; fi
  fi
fi
if [ "$WANT_AI" != 0 ] && command -v ollama >/dev/null 2>&1; then
  if ! curl -fs http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    (nohup ollama serve >/dev/null 2>&1 &) ; sleep 4
  fi
  echo "Downloading the AI model (3.3 GB, can be stopped and resumed by running this again) ..."
  ollama pull qwen3-vl:4b || echo "  (the model download did not finish; run   ollama pull qwen3-vl:4b   later)"
fi

echo
echo "Setting up Fathom ..."
exec bash ./fathom.sh
