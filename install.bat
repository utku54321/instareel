@echo off
setlocal
cd /d "%~dp0"
title Lyric Studio - one-time setup
echo.
echo  ==============================================
echo    Lyric Studio - one-time setup
echo    Takes 15-40 minutes (mostly downloading).
echo    You never need to run this again.
echo  ==============================================
echo.

rem ---------- 1. Find Python 3.10 - 3.12 ----------
set "PY="
py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
if not defined PY (py -3.11 -c "import sys" >nul 2>&1 && set "PY=py -3.11")
if not defined PY (py -3.10 -c "import sys" >nul 2>&1 && set "PY=py -3.10")
if defined PY goto :have_python

echo [1/7] Python 3.10-3.12 not found. Installing Python 3.12 with winget...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
if defined PY goto :have_python
echo.
echo  Could not set up Python automatically.
echo  Install Python 3.12 from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo  then double-click install.bat again.
goto :fail

:have_python
echo [1/7] Using %PY%

rem ---------- 2. Private environment ----------
if exist ".venv\Scripts\python.exe" goto :have_venv
echo [2/7] Creating private environment (.venv)...
%PY% -m venv .venv || goto :fail
:have_venv
set "VPY=%~dp0.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip setuptools wheel -q || goto :fail
echo [2/7] Environment ready.

rem ---------- 3. PyTorch ----------
"%VPY%" -c "import torch" >nul 2>&1 && goto :have_torch
nvidia-smi >nul 2>&1 && goto :torch_gpu
echo [3/7] Installing PyTorch (CPU version, big download)...
"%VPY%" -m pip install "torch>=2.1,<2.9" "torchaudio>=2.1,<2.9" --index-url https://download.pytorch.org/whl/cpu
goto :torch_check
:torch_gpu
echo [3/7] NVIDIA GPU found. Installing PyTorch GPU version (big download)...
"%VPY%" -m pip install "torch>=2.1,<2.9" "torchaudio>=2.1,<2.9" --index-url https://download.pytorch.org/whl/cu124
:torch_check
"%VPY%" -c "import torch" >nul 2>&1 && goto :have_torch
echo PyTorch server not reachable, trying the normal package index...
"%VPY%" -m pip install "torch>=2.1,<2.9" "torchaudio>=2.1,<2.9" || goto :fail
:have_torch
echo [3/7] PyTorch ready.

rem ---------- 4. Other packages ----------
echo [4/7] Installing Whisper, Demucs, Flask, Gemini SDK...
"%VPY%" -m pip install -r requirements.txt || goto :fail

rem ---------- 5. ffmpeg ----------
echo [5/7] Setting up ffmpeg...
"%VPY%" -c "import static_ffmpeg; static_ffmpeg.add_paths(); print('      ffmpeg ready')" || goto :fail

rem ---------- 6. AI models ----------
echo [6/7] Downloading AI models (one time, about 2 GB)...
"%VPY%" -c "import whisper; whisper.load_model('large-v3-turbo', device='cpu'); print('      Whisper model ready')" || goto :fail
"%VPY%" -c "from demucs.pretrained import get_model; get_model('htdemucs'); print('      Demucs model ready')" || goto :fail

rem ---------- 7. Gemini key (optional) ----------
if exist gemini_key.txt goto :have_key
echo.
echo [7/7] Optional: a free Gemini API key converts Hindi (Devanagari) lyrics to Hinglish.
echo       Get one at https://aistudio.google.com/apikey
set "GK="
set /p GK=      Paste the key and press Enter (or just press Enter to skip):
if not defined GK goto :done
> gemini_key.txt echo %GK%
echo       Key saved.
goto :done
:have_key
echo [7/7] Gemini key already saved.

:done
echo.
echo  ==============================================
echo    Setup complete!
echo    Double-click start.bat to open Lyric Studio.
echo  ==============================================
echo.
pause
exit /b 0

:fail
echo.
echo  Setup stopped because a step failed (see the message above).
echo  Check your internet connection and run install.bat again -
echo  finished steps are skipped, so it continues where it stopped.
echo.
pause
exit /b 1
