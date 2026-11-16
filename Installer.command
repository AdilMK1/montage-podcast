#!/bin/zsh
# Montage Podcast : installation (une fois). Mac Apple Silicon.
cd "$(dirname "$0")"
echo "== Montage Podcast : installation"
command -v ffmpeg >/dev/null || { echo "ffmpeg manquant : installe Homebrew puis « brew install ffmpeg »"; read; exit 1; }
PY=$(command -v python3.14 || command -v python3.13 || command -v python3.12 || command -v python3)
[ -z "$PY" ] && { echo "Python 3 manquant : « brew install python@3.12 »"; read; exit 1; }
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "Python trop ancien (3.10 minimum) : « brew install python@3.12 »"; read; exit 1; }
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt
echo "== Modèle de transcription (première fois, environ 1,5 Go)"
.venv/bin/python -c "import mlx_whisper, numpy as np, soundfile as sf, tempfile; f=tempfile.mktemp(suffix='.wav'); sf.write(f, np.zeros(16000, np.float32), 16000); mlx_whisper.transcribe(f, path_or_hf_repo='mlx-community/whisper-large-v3-turbo', language='fr')" >/dev/null 2>&1
echo "== C'est prêt. Double-clique « Lancer.command »."
read -k1 "?Appuie sur une touche pour fermer."
