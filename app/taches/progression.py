"""Lecture de l'avancement (ffmpeg -progress, fichier MONTAGE_PROGRES des scripts du moteur) et temps restant."""
from pathlib import Path


def blocs_progres(lignes):
    """regroupe les lignes clé=valeur de « ffmpeg -progress pipe:1 » en blocs (un bloc finit par progress=…)"""
    bloc = {}
    for l in lignes:
        l = l.strip()
        if "=" not in l:
            continue
        k, v = l.split("=", 1)
        bloc[k] = v
        if k == "progress":
            yield bloc
            bloc = {}


def fraction_ffmpeg(bloc: dict, total_s: float) -> float | None:
    if bloc.get("progress") == "end":
        return 1.0
    try:
        t = int(bloc.get("out_time_us") or bloc.get("out_time_ms")) / 1e6  # out_time_ms est aussi en µs (ffmpeg)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, t / total_s)) if total_s > 0 else None


def lire_fichier_progres(f) -> float | None:
    try:
        return max(0.0, min(1.0, float(Path(f).read_text().strip())))
    except (OSError, ValueError):
        return None


def restant(debut: float, fraction: float | None, maintenant: float, fraction_debut: float | None = 0.0) -> float | None:
    """estimé sur l'avancement fait pendant la tentative en cours (débutée à « debut », à fraction_debut) : après
    une reprise, les morceaux déjà faits comptent dans la fraction mais pas dans le temps écoulé"""
    ecoule = maintenant - debut
    f0 = fraction_debut or 0.0
    if fraction is None or fraction - f0 < 0.02 or ecoule < 3:
        return None
    return ecoule * (1 - fraction) / (fraction - f0)


def texte_duree(s: float | None) -> str:
    if s is None:
        return ""
    if s < 60:
        return f"environ {max(5, round(s / 5) * 5)} s"
    if s < 3600:
        return f"environ {round(s / 60)} min"
    h, m = divmod(round(s / 60), 60)
    return f"environ {h} h {m:02d}"
