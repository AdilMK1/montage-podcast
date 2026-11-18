"""Mise à jour automatique de l'app, au lancement (Lancer.command / Lancer.bat).

Deux cas :
- dossier cloné avec git : `git pull --ff-only` sur la branche suivie (dépôt privé, identifiants de la machine) ;
- dossier téléchargé en zip : version publique sur GitHub (config.json « mise_a_jour », par défaut
  AdilMK1/montage-podcast, branche main), fichiers de l'app remplacés, données de la personne gardées.

Jamais pendant un rendu : si l'atelier a des tâches en cours, on reporte au prochain lancement. Après une mise à
jour, l'atelier inoccupé est arrêté (le serveur le relance avec le nouveau code), et les modules Python sont
réinstallés si requirements.txt a changé. Sans internet ou en cas d'erreur, l'app se lance comme avant.
Le résultat est écrit dans .atelier/mise_a_jour.json (lu par l'accueil de l'app).

Usage : python -m app.mise_a_jour [--verifier]   (--verifier : regarde seulement s'il y a une nouvelle version)
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DEPOT, BRANCHE = "AdilMK1/montage-podcast", "main"
# ce qui appartient à la personne (jamais écrasé par une mise à jour zip)
GARDER = {"projets", "config.json", ".venv", ".atelier", ".cache", "rapports", ".git"}
GARDER_SOUS = {"demo/rushes", "demo/archives"}
DELAI = 8  # s : pas d'attente longue au lancement sans internet


def cle_version(v: str) -> tuple:
    """« 2.0.0-beta.3 » < « 2.0.0-beta.10 » < « 2.0.0 » < « 2.0.1 »"""
    m = re.match(r"\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-?([a-z]+)\.?(\d+)?)?", v or "", re.I)
    if not m:
        return (0, 0, 0, 0, 0)
    a, b, c, pre, n = m.groups()
    return (int(a), int(b or 0), int(c or 0), 0 if pre else 1, int(n or 0))


def plus_recente(distante: str, locale: str) -> bool:
    return cle_version(distante) > cle_version(locale)


def version_locale(racine=RACINE) -> str:
    f = Path(racine) / "VERSION"
    return f.read_text(encoding="utf-8").strip() if f.exists() else "0"


def _reglages(racine) -> dict:
    try:
        c = json.loads((Path(racine) / "config.json").read_text(encoding="utf-8")).get("mise_a_jour") or {}
    except (OSError, ValueError, AttributeError):
        c = {}
    return {"auto": c.get("auto", True), "depot": c.get("depot", DEPOT), "branche": c.get("branche", BRANCHE)}


def _git(racine, *args, timeout=DELAI * 3) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(racine), capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})  # jamais de demande de mot de passe


def _lire_url(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "montage-podcast-maj"})
    with urllib.request.urlopen(req, timeout=DELAI) as r:
        return r.read()


def _ecrire_etat(racine, etat: dict):
    f = Path(racine) / ".atelier" / "mise_a_jour.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({**etat, "t": time.time()}, ensure_ascii=False, indent=1), encoding="utf-8")


def lire_etat(racine=RACINE) -> dict:
    try:
        return json.loads((Path(racine) / ".atelier" / "mise_a_jour.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def taches_en_cours(racine) -> bool:
    """l'atelier a-t-il des tâches en cours (battement récent qui en liste) ?"""
    try:
        b = json.loads((Path(racine) / ".atelier" / "battement.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(b, dict) and time.time() - b.get("t", 0) < 15 and bool(b.get("en_cours"))


def _arreter_atelier(racine):
    """l'atelier inoccupé tourne encore avec l'ancien code : on l'arrête, le serveur le relance"""
    try:
        import psutil
        b = json.loads((Path(racine) / ".atelier" / "battement.json").read_text(encoding="utf-8"))
        psutil.Process(int(b["pid"])).terminate()
    except Exception:  # noqa: BLE001 : pas d'atelier, déjà arrêté
        pass


# ---------- version distante ----------

def _distante_git(racine) -> tuple[str | None, str | None]:
    br = _git(racine, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if br.returncode:
        return None, "pas de branche suivie"
    suivie = br.stdout.strip()
    f = _git(racine, "fetch", "--quiet", suivie.split("/")[0])
    if f.returncode:
        return None, "dépôt injoignable"
    v = _git(racine, "show", f"{suivie}:VERSION")
    return (v.stdout.strip(), None) if v.returncode == 0 else (None, "VERSION absente")


def _distante_zip(reg) -> tuple[str | None, str | None]:
    try:
        return _lire_url(f"https://raw.githubusercontent.com/{reg['depot']}/{reg['branche']}/VERSION").decode().strip(), None
    except Exception as x:  # noqa: BLE001 : hors ligne, GitHub indisponible…
        return None, f"pas de connexion ({type(x).__name__})"


def verifier(racine=RACINE) -> dict:
    racine = Path(racine)
    reg = _reglages(racine)
    mode = "git" if (racine / ".git").exists() else "zip"
    distante, err = _distante_git(racine) if mode == "git" else _distante_zip(reg)
    locale = version_locale(racine)
    return {"mode": mode, "locale": locale, "distante": distante, "erreur": err,
            "disponible": bool(distante and plus_recente(distante, locale))}


# ---------- installation ----------

def _installer_git(racine) -> str | None:
    if _git(racine, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        return "fichiers de l'app modifiés sur cette machine : mise à jour à faire à la main (git pull)"
    p = _git(racine, "pull", "--ff-only", "--quiet", timeout=120)
    return None if p.returncode == 0 else "git pull a échoué : " + (p.stderr.strip().splitlines() or ["?"])[-1]


def _garde(rel: Path) -> bool:
    s = rel.as_posix()
    return rel.parts[0] in GARDER or any(s == g or s.startswith(g + "/") for g in GARDER_SOUS)


def _installer_zip(racine, reg) -> str | None:
    data = _lire_url(f"https://codeload.github.com/{reg['depot']}/zip/refs/heads/{reg['branche']}")
    with tempfile.TemporaryDirectory() as tmp:
        zipfile.ZipFile(io.BytesIO(data)).extractall(tmp)
        src = next(Path(tmp).iterdir())  # « montage-podcast-main/ »
        if not (src / "VERSION").exists() or not (src / "app").is_dir():
            return "archive téléchargée incomplète"
        for f in sorted(src.rglob("*")):
            rel = f.relative_to(src)
            if f.is_dir() or _garde(rel):
                continue
            if rel.parts[0] == "packs" and (racine / rel.parts[0] / rel.parts[1]).exists() and len(rel.parts) > 2:
                continue  # pack déjà présent : la personne a pu le régler, on n'y touche pas
            dest = racine / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
    return None


def _modules(racine, avant: str):
    req = racine / "requirements.txt"
    if req.exists() and req.read_text(encoding="utf-8") != avant:
        print("Mise à jour des modules (quelques minutes)…", flush=True)
        py = racine / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
        subprocess.run([str(py if py.exists() else sys.executable), "-m", "pip", "install", "-q", "-r", str(req)],
                       cwd=str(racine))


def mettre_a_jour(racine=RACINE) -> dict:
    racine = Path(racine)
    reg = _reglages(racine)
    if not reg["auto"]:
        return {"faite": False, "message": "mise à jour automatique désactivée (config.json)"}
    v = verifier(racine)
    etat = {**v, "faite": False}
    if not v["disponible"]:
        etat["message"] = v["erreur"] or "à jour"
    elif taches_en_cours(racine):
        etat["message"] = f"version {v['distante']} disponible : installée au prochain lancement (rendu en cours)"
    else:
        print(f"Nouvelle version {v['distante']} (tu as la {v['locale']}) : installation…", flush=True)
        req = racine / "requirements.txt"
        avant = req.read_text(encoding="utf-8") if req.exists() else ""
        try:
            err = _installer_git(racine) if v["mode"] == "git" else _installer_zip(racine, reg)
        except Exception as x:  # noqa: BLE001 : l'app doit se lancer quoi qu'il arrive
            err = f"{type(x).__name__} : {x}"
        if err:
            etat["message"] = "mise à jour impossible : " + err
        else:
            _modules(racine, avant)
            _arreter_atelier(racine)
            etat.update(faite=True, avant=v["locale"], locale=version_locale(racine),
                        message=f"version {version_locale(racine)} installée")
    _ecrire_etat(racine, etat)
    return etat


if __name__ == "__main__":
    if "--verifier" in sys.argv:
        print(json.dumps(verifier(), ensure_ascii=False))
    else:
        e = mettre_a_jour()
        if e.get("faite") or "impossible" in e.get("message", "") or "prochain" in e.get("message", ""):
            print(e["message"].capitalize() + ".", flush=True)
