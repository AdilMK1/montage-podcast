@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Montage Podcast - installation
echo == Montage Podcast : installation (Windows)
echo.

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo ffmpeg manque : installation automatique avec winget...
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
  echo.
  echo ffmpeg est installe. FERME cette fenetre puis relance Installer.bat.
  pause
  exit /b 1
)

set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python manque : installation automatique avec winget...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  echo.
  echo Python est installe. FERME cette fenetre puis relance Installer.bat.
  pause
  exit /b 1
)

if not exist .venv\Scripts\python.exe %PY% -m venv .venv
if errorlevel 1 ( echo Impossible de creer l'environnement Python. & pause & exit /b 1 )
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 ( echo L'installation des modules a echoue : verifie la connexion internet et relance. & pause & exit /b 1 )

where nvidia-smi >nul 2>nul
if not errorlevel 1 (
  echo == Carte NVIDIA trouvee : bibliotheques pour une transcription rapide
  .venv\Scripts\python.exe -m pip install -q nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
)

echo == Modele de transcription (premiere fois, environ 1,5 Go)
set PYTHONUTF8=1
.venv\Scripts\python.exe moteur\whisper_local.py
echo.
echo == C'est pret. Double-clique Lancer.bat
pause
