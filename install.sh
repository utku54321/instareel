#!/usr/bin/env bash
# Lyric Studio one-time setup for Mac / Linux.  Run:  bash install.sh
set -e
cd "$(dirname "$0")"
PY=""
for v in 3.12 3.11 3.10; do command -v "python$v" >/dev/null 2>&1 && { PY="python$v"; break; }; done
if [ -z "$PY" ]; then
  echo "Python 3.10-3.12 not found. Install it first:"
  echo "  Mac:   brew install python@3.12"
  echo "  Linux: sudo apt install python3.12 python3.12-venv"
  exit 1
fi
echo "[1/6] Using $PY"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
VPY=.venv/bin/python
"$VPY" -m pip install --upgrade pip setuptools wheel -q
echo "[2/6] Installing PyTorch..."
if ! "$VPY" -c "import torch" 2>/dev/null; then
  if [ "$(uname)" = "Darwin" ]; then
    "$VPY" -m pip install "torch>=2.1,<2.9" "torchaudio>=2.1,<2.9"
  else
    "$VPY" -m pip install "torch>=2.1,<2.9" "torchaudio>=2.1,<2.9" --index-url https://download.pytorch.org/whl/cpu \
      || "$VPY" -m pip install "torch>=2.1,<2.9" "torchaudio>=2.1,<2.9"
  fi
fi
echo "[3/6] Installing packages..."
"$VPY" -m pip install -r requirements.txt
echo "[4/6] Setting up ffmpeg..."
"$VPY" -c "import static_ffmpeg; static_ffmpeg.add_paths(); print('ffmpeg ready')"
echo "[5/6] Downloading AI models (one time)..."
"$VPY" -c "import whisper; whisper.load_model('large-v3-turbo', device='cpu'); print('Whisper model ready')"
"$VPY" -c "from demucs.pretrained import get_model; get_model('htdemucs'); print('Demucs model ready')"
if [ ! -f gemini_key.txt ]; then
  echo "[6/6] Optional Gemini key for Hinglish conversion (https://aistudio.google.com/apikey)."
  read -r -p "Paste key or press Enter to skip: " GK
  [ -n "$GK" ] && echo "$GK" > gemini_key.txt
fi
echo "Setup complete. Run:  bash start.sh"
