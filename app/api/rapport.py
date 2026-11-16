"""Rapport de dépannage : un zip de journaux et d'états, jamais de média."""
import time
import zipfile
from pathlib import Path


def creer_rapport(racine_app, racine_projets, projet=None) -> Path:
    """zip dans <racine_app>/rapports/rapport-<date>.zip : VERSION, profil, journal de l'atelier, et pour le projet
    donné (ou tous) etat.json, projet.json, session.json, taches/*.json et taches/*.log"""
    racine_app, racine_projets = Path(racine_app), Path(racine_projets)
    sortie = racine_app / "rapports"
    sortie.mkdir(exist_ok=True)
    z = sortie / f"rapport-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    projets = [racine_projets / projet] if projet else sorted(p for p in racine_projets.iterdir() if p.is_dir())
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in ("VERSION", ".cache/profil.json", ".atelier/atelier.log"):
            f = racine_app / rel
            if f.is_file():
                zf.write(f, rel)
        for d in projets:
            if not d.is_dir():
                continue
            fichiers = [d / "etat.json", d / "projet.json", d / "session.json"]
            fichiers += sorted((d / "taches").glob("*.json")) + sorted((d / "taches").glob("*.log"))
            for f in fichiers:
                if f.is_file():
                    zf.write(f, f"{d.name}/{f.relative_to(d).as_posix()}")
    return z
