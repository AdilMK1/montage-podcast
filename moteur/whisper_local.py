"""Whisper sur la machine, quel que soit le système : mlx-whisper sur Mac à puce Apple, faster-whisper ailleurs
(Windows, Linux, Mac Intel), sur la carte NVIDIA si elle répond, sinon sur le processeur.

Même modèle des deux côtés (large-v3-turbo) et même forme de résultat que mlx_whisper.transcribe :
{"text": ..., "segments": [{"start", "end", "text", "words": [{"word", "start", "end", "probability"}]}]}.
MONTAGE_WHISPER=mlx|faster force un moteur (essais)."""
import os
import platform
import sys

MLX = "mlx-community/whisper-large-v3-turbo"
FASTER = os.environ.get("MONTAGE_WHISPER_MODELE", "large-v3-turbo")  # (autre modèle : essais)
_MODELE = {}


def moteur() -> str:
    force = os.environ.get("MONTAGE_WHISPER")
    if force in ("mlx", "faster"):
        return force
    if sys.platform == "darwin" and platform.machine() == "arm64":
        try:
            import mlx_whisper  # noqa: F401
            return "mlx"
        except ImportError:
            pass
    return "faster"


def _dll_nvidia():
    """Windows : bibliothèques CUDA installées par pip (nvidia-cublas-cu12, nvidia-cudnn-cu12) rendues trouvables"""
    if os.name != "nt":
        return
    import site
    from pathlib import Path
    for sp in site.getsitepackages():
        for b in Path(sp).glob("nvidia/*/bin"):
            try:
                os.add_dll_directory(str(b))
                os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")
            except OSError:
                pass


def _faster(cpu: bool = False):
    cle = "cpu" if cpu else "auto"
    if cle not in _MODELE:
        from faster_whisper import WhisperModel
        if not cpu:
            _dll_nvidia()
            try:
                import ctranslate2
                if ctranslate2.get_cuda_device_count() > 0:
                    _MODELE[cle] = WhisperModel(FASTER, device="cuda", compute_type="float16")
                    return _MODELE[cle]
            except Exception:  # pilotes ou bibliothèques CUDA absents : processeur
                pass
        _MODELE[cle] = WhisperModel(FASTER, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    return _MODELE[cle]


def _faster_transcrire(modele, audio, mots, temperatures, prompt, avance):
    segs, info = modele.transcribe(
        audio, language="fr", word_timestamps=mots, condition_on_previous_text=False, temperature=list(temperatures),
        compression_ratio_threshold=2.4, log_prob_threshold=-1.0, no_speech_threshold=0.6,
        hallucination_silence_threshold=2.0 if mots else None, initial_prompt=prompt, vad_filter=False)
    out = []
    for s in segs:  # générateur : la transcription se fait ici, segment par segment
        out.append({"start": s.start, "end": s.end, "text": s.text,
                    "words": [{"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
                              for w in (s.words or [])]})
        if avance and info.duration:
            avance(min(1.0, s.end / info.duration))
    return {"text": "".join(s["text"] for s in out), "segments": out}


def transcrire(audio, prompt=None, mots=False, temperatures=(0.0, 0.2, 0.4), avance=None, barre=False) -> dict:
    """audio : tableau float32 mono 16 kHz, ou chemin d'un fichier son. avance(f) : 0 à 1 (faster seulement ; mlx
    passe par sa barre tqdm, affichée si barre=True et suivie à part par transcribe.py)"""
    if moteur() == "mlx":
        import mlx_whisper
        return mlx_whisper.transcribe(
            audio, path_or_hf_repo=MLX, language="fr", word_timestamps=mots, condition_on_previous_text=False,
            temperature=tuple(temperatures), compression_ratio_threshold=2.4, logprob_threshold=-1.0,
            no_speech_threshold=0.6, hallucination_silence_threshold=2.0, initial_prompt=prompt, verbose=False if barre else None)
    try:
        return _faster_transcrire(_faster(), audio, mots, temperatures, prompt, avance)
    except RuntimeError as e:  # carte NVIDIA vue mais inutilisable (cuDNN/cuBLAS manquant) : on refait au processeur
        if "cpu" in _MODELE or not any(k in str(e).lower() for k in ("cuda", "cudnn", "cublas", "dll", "library")):
            raise
        return _faster_transcrire(_faster(cpu=True), audio, mots, temperatures, prompt, avance)


def precharger():
    """télécharge le modèle à l'installation (environ 1,5 Go) en transcrivant une seconde de silence"""
    import numpy as np
    transcrire(np.zeros(16000, np.float32))
    print(f"Transcription prête ({moteur()}).")


if __name__ == "__main__":
    precharger()
