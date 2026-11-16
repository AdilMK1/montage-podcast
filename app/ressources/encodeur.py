"""Arguments ffmpeg d'encodage vidéo selon l'usage et la machine : matériel si possible, sinon x264."""
import os

MATERIELS = {"h264_videotoolbox": "Apple VideoToolbox", "h264_nvenc": "NVIDIA", "h264_qsv": "Intel QuickSync",
             "h264_amf": "AMD"}
REGLAGES = {
    "proxy": {"debit": "4M", "preset": "veryfast", "crf": 23},
    "apercu": {"debit": "2M", "preset": "veryfast", "crf": 28},
    "final": {"debit": "12M", "preset": "medium", "crf": 18},
}


def choisir(profil: dict) -> str | None:
    if os.environ.get("CRAIE_ENCODEUR") == "logiciel":
        return None
    return next((e for e in MATERIELS if e in profil.get("encodeurs", [])), None)


def encodeur(usage: str, profil: dict) -> list[str]:
    if usage not in REGLAGES:
        raise ValueError(f"usage d'encodage inconnu : {usage}")
    r = REGLAGES[usage]
    hw = choisir(profil)
    if hw:
        return ["-c:v", hw, "-b:v", r["debit"], "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", r["preset"], "-crf", str(r["crf"]), "-pix_fmt", "yuv420p"]


def libelle(profil: dict) -> str:
    hw = choisir(profil)
    return f"matériel ({MATERIELS[hw]})" if hw else "logiciel (x264)"
