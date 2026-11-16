"""Tâches de l'épisode : montage multicam (calcul rapide), essai d'export de 3 minutes, export, livraison.

L'essai est rendu EXACTEMENT comme l'export final (même script, même format, mêmes réglages, depuis les rushes
d'origine), sur 3 minutes de l'épisode monté : par défaut le début, ce que le public voit en premier. Sa durée de
rendu mesurée recale l'estimation de l'export complet.
"""
import math
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from app.fichiers import lire_json
from app.projet import modele as M
from app.projet.stockage import lire_etat, modifier
from app.ressources import disque
from app.ressources.encodeur import choisir
from app.taches.atelier import ErreurTache

from . import coupes as C
from .contexte import creer_si_absente, lancer_script, profil
from .couleur import ecrire_etalonnage
from .session import construire_session

FORMATS = {"1080p": ("apercu_xml.py", "1920x1080", 12e6), "4k": ("apercu_xml_4k.py", "3840x2160", 50e6)}
ESSAI_S = 180.0  # durée de l'essai d'export
ESSAI = "ESSAI 3 MIN.mp4"
# sans mesure : secondes de rendu par seconde d'épisode pour l'export (ordre de grandeur sur un Mac M) ; une mesure
# d'un format donne l'autre par le même rapport (la 4K coûte ~2 fois la 1080p)
FACTEURS = {"1080p": 2.0, "4k": 4.0}
# l'export complet coûte plus par seconde que l'essai (son de tout l'épisode mixé d'un bloc, encodage final de toute
# la timeline) : mesuré sur la démo de référence en 1080p, essai 0,38 s/s, export 0,52 s/s
EXPORT_SUR_ESSAI = 1.35


def duree_xml(xml) -> float | None:
    """durée de la timeline d'un XML de montage (secondes), None s'il est illisible"""
    try:
        seq = ET.parse(xml).getroot().find(".//sequence")
        return round(int(seq.findtext("duration")) / int(seq.findtext("rate/timebase")), 3)
    except (OSError, ET.ParseError, AttributeError, TypeError, ValueError, ZeroDivisionError):
        return None


def bornes_essai(debut, duree: float) -> tuple[float, float]:
    """passage [a, b] de l'essai : 3 minutes à partir de debut, ramenées dans l'épisode (tout l'épisode s'il est court)"""
    duree = float(duree)
    if duree <= ESSAI_S:
        return 0.0, duree
    a = min(max(0.0, float(debut)), duree - ESSAI_S)
    return round(a, 3), round(a + ESSAI_S, 3)


def _ok(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


def _vitesse_export(vitesses: dict, fmt: str) -> tuple[float, bool]:
    """(secondes de rendu de l'export par seconde d'épisode, mesurée pour ce format ?) : export déjà mesuré, sinon
    essai mesuré x EXPORT_SUR_ESSAI, sinon un autre format mesuré au prorata, sinon le facteur par défaut"""
    export, essai = (vitesses or {}).get("export") or {}, (vitesses or {}).get("essai") or {}
    if _ok(export.get(fmt)):
        return float(export[fmt]), True
    if _ok(essai.get(fmt)):
        return essai[fmt] * EXPORT_SUR_ESSAI, True
    for autre in FACTEURS:
        if autre != fmt and (_ok(export.get(autre)) or _ok(essai.get(autre))):
            v = export[autre] if _ok(export.get(autre)) else essai[autre] * EXPORT_SUR_ESSAI
            return v * FACTEURS[fmt] / FACTEURS[autre], False
    return FACTEURS[fmt], False


def estimations(vitesses: dict, duree: float | None) -> dict:
    """durées estimées (s) de l'essai et de l'export complet par format, d'après les vitesses de rendu mesurées
    ({"essai": {format: s/s}, "export": {format: s/s}}) ; mesure[format] : estimation tirée d'un rendu de ce format"""
    essai = (vitesses or {}).get("essai") or {}
    out = {"essai": {}, "export": {}, "mesure": {}}
    for fmt in FORMATS:
        v, mesure = _vitesse_export(vitesses, fmt)
        ve = float(essai[fmt]) if _ok(essai.get(fmt)) else v / EXPORT_SUR_ESSAI
        out["mesure"][fmt] = mesure
        out["export"][fmt] = round(v * duree, 1) if duree else None
        out["essai"][fmt] = round(ve * min(ESSAI_S, duree or ESSAI_S), 1)
    return out


def _etalonnage_args(d) -> list[str]:
    out = []
    for stem, f in ((lire_json(Path(d) / "projet.json", {}) or {}).get("etalonnage") or {}).items():
        out += ["--etalonnage", stem, f]
    return out


def _preparer(d, e):
    ecrire_etalonnage(d, e["couleur"]["reglages"])
    s = construire_session(d, e)
    return s, Path(s["dossier_sortie"]) / f'{s["sortie"]}.xml'


def montage(ctx):
    """calcul du montage (rapide) ; l'essai d'export de 3 minutes part ensuite tout seul, en tâche à part"""
    d = Path(ctx.projet_dir)
    e = lire_etat(d)
    emp = M.empreinte_episode(e)
    if emp is None:
        raise ErreurTache("Vérifie d'abord les passages retirés de l'épisode et valide la couleur et le son.", [])
    s, xml = _preparer(d, e)
    lancer_script(ctx, "edit.py", d / "session.json", texte="Montage selon qui parle", debut=0.0, fin=0.8)
    lancer_script(ctx, "dynamise.py", d / "session.json", xml, texte="Zooms lents", debut=0.8, fin=1.0)
    precedent = e["episode"].get("essai") or {}  # un remontage refait l'essai au même endroit, dans le même format
    modifier(d, {"type": "montage_fini", "empreinte": emp, "duree": duree_xml(xml) or 0.0})
    creer_si_absente(d, "essai", {"format": precedent.get("format", "1080p"), "debut": float(precedent.get("debut", 0.0))})


def _format(ctx) -> str:
    fmt = ctx.params.get("format", "1080p")
    if fmt not in FORMATS:
        raise ErreurTache(f"Format inconnu : {fmt}.", [])
    return fmt


def _env(fmt: str) -> dict | None:
    hw = choisir(profil()) if fmt == "4k" else None
    return {"CRAIE_HW": hw} if hw else None


def _verifier_disque(d, secondes: float, debit: float):
    besoin = int(secondes * debit / 8 * 2.5)
    ok, libre = disque.verifier(d, besoin)
    if not ok:
        raise ErreurTache(disque.message_manque(besoin, libre), ["liberer_disque", "reessayer"])


def essai(ctx):
    """3 minutes de l'épisode rendues comme l'export final (même script, format, étalonnage, son, zooms)"""
    d = Path(ctx.projet_dir)
    e = lire_etat(d)
    emp = M.empreinte_episode(e)
    if emp is None or e["episode"]["montage"] != emp:
        raise ErreurTache("Le montage n'est pas à jour : remonte l'épisode avant l'essai.", [])
    fmt = _format(ctx)
    script, taille, debit = FORMATS[fmt]
    s, xml = _preparer(d, e)
    duree = e["episode"].get("duree") or duree_xml(xml)
    if not duree:
        raise ErreurTache("Le fichier de montage est illisible : remonte l'épisode.", ["reessayer", "rapport"])
    a, b = bornes_essai(ctx.params.get("debut", 0.0), duree)
    _verifier_disque(d, b - a, debit)
    sorties = Path(s["dossier_sortie"])
    tmp, out = sorties / "ESSAI 3 MIN (en cours).mp4", sorties / ESSAI  # l'ancien essai reste lisible pendant ce temps
    t0 = time.time()
    lancer_script(ctx, script, xml, tmp, "--export", taille, "--extrait", a, b, *_etalonnage_args(d),
                  texte=f"Essai de 3 minutes en {fmt}, comme l'export final", env=_env(fmt))
    rendu = round(time.time() - t0, 1)
    tmp.replace(out)
    modifier(d, {"type": "essai_fini", "empreinte": emp, "format": fmt, "debut": a, "duree": round(b - a, 3),
                 "rendu_s": rendu})


def export(ctx):
    d = Path(ctx.projet_dir)
    e = lire_etat(d)
    emp = M.empreinte_episode(e)
    if M.statuts(e)["apercu"] != "valide":
        raise ErreurTache("Valide d'abord l'essai de 3 minutes.", [])
    fmt = _format(ctx)
    script, taille, debit = FORMATS[fmt]
    s, xml = _preparer(d, e)
    duree = e["episode"].get("duree") or duree_xml(xml) or 0.0
    _verifier_disque(d, duree or sum(m["rush"][1] - m["rush"][0] for m in s.get("montage", []) if "rush" in m), debit)
    out = Path(s["dossier_sortie"]) / f'{s["sortie"]} {fmt}.mp4'
    t0 = time.time()
    lancer_script(ctx, script, xml, out, "--export", taille, *_etalonnage_args(d),
                  texte=f"Export de l'épisode en {fmt} (le plus long)", env=_env(fmt))
    mesure = {"format": fmt, "duree": duree, "rendu_s": round(time.time() - t0, 1)} if duree else {}
    modifier(d, {"type": "export_fini", "empreinte": emp, **mesure})


def livraison(ctx):
    d = Path(ctx.projet_dir)
    e = lire_etat(d)
    liv = M.livrables(e)
    if not (liv["shorts"] or liv["episode"]):
        raise ErreurTache("Rien à livrer : garde au moins un short ou exporte l'épisode.", [])
    titre = (lire_json(d / "projet.json", {}) or {}).get("titre", d.name)
    out = Path(ctx.params.get("dossier") or d / "EXPORT" / time.strftime("%Y-%m-%d %Hh%M"))
    if "dossier" not in ctx.params:
        ctx.tache["params"]["dossier"] = str(out)  # une reprise écrit dans le même dossier
    out.mkdir(parents=True, exist_ok=True)
    items = [("short", sid) for sid in liv["shorts"]] + ([("episode", "episode")] if liv["episode"] else [])
    for i, (kind, k) in enumerate(items):
        if ctx.est_fait(k):
            continue
        ctx.progres(i / len(items), "Préparation des fichiers à publier")
        if kind == "short":
            nom = M.trouver_short(e, k)["spec"]["nom"]
            src = d / "shorts" / e["serie_active"] / f"{nom}.mp4"
            rc = ctx.executer(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(src), "-map", "0", "-c:v", "copy",
                               "-af", "loudnorm=I=-14:TP=-1.0:LRA=9", "-ar", "48000", "-c:a", "aac", "-b:a", "256k",
                               "-movflags", "+faststart", str(out / f"{titre} - {nom}.mp4")],
                              debut=i / len(items), fin=(i + 1) / len(items))
            if rc:
                raise ErreurTache(f"Le short « {nom} » n'a pas pu être préparé pour la livraison.", ["reessayer", "rapport"])
        else:
            src = fichier_episode(d, e)
            if src is None:
                raise ErreurTache("Le fichier de l'épisode est introuvable : exporte-le (ou applique les coupes) à nouveau.",
                                  ["reessayer", "rapport"])
            shutil.copy2(src, out / src.name)
        ctx.morceau_fait(k)
    modifier(d, {"type": "livrer"})


# ---------- coupes rapides dans l'épisode exporté ----------

def fichier_episode(d, e) -> Path | None:
    """le fichier de l'épisode à livrer : la version coupée s'il y a des coupes (à jour), sinon le dernier export"""
    srcs = C.sources(d)
    if not srcs:
        return None
    if not M.coupes(e):
        return srcs[-1]
    f = C.chemin_coupe(srcs[-1])
    return f if f.exists() and M.coupes_a_jour(e) else None


def _encodage_complet() -> list[str]:
    """export pas en x264 : tout est réencodé depuis l'export (puce vidéo si possible, en haut débit)"""
    hw = choisir(profil())
    if hw:
        return ["-c:v", hw, "-b:v", "20M", "-maxrate", "30M", "-bufsize", "40M", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p"]


def _ffmpeg(ctx, args, texte, debut, fin, total_s, erreur):
    ctx.progres(debut, texte)
    rc = ctx.executer(["ffmpeg", "-v", "error", "-nostdin", "-y", *args], debut=debut, fin=fin, total_s=total_s)
    if rc:
        raise ErreurTache(erreur, ["reessayer", "rapport"])


def coupes(ctx):
    """retire les coupes demandées du fichier exporté : quelques secondes réencodées autour de chaque coupe, le reste
    recopié tel quel ; le résultat « … (coupé).mp4 » est vérifié (nombre d'images) avant de remplacer l'ancien"""
    d = Path(ctx.projet_dir)
    e = lire_etat(d)
    if M.statuts(e)["export"] != "valide":
        raise ErreurTache("Exporte d'abord l'épisode : les coupes se font dans le fichier exporté.", [])
    emp = M.empreinte_coupes(e)
    if emp is None:
        raise ErreurTache("Aucune coupe à appliquer.", [])
    srcs = C.sources(d)
    if not srcs:
        raise ErreurTache("Le fichier exporté de l'épisode est introuvable : exporte-le à nouveau.", ["rapport"])
    src = srcs[-1]
    out = C.chemin_coupe(src)
    ok, libre = disque.verifier(d, int(src.stat().st_size * 1.2))
    if not ok:
        raise ErreurTache(disque.message_manque(int(src.stat().st_size * 1.2), libre), ["liberer_disque", "reessayer"])
    ctx.progres(0.0, "Lecture de l'épisode exporté")
    try:
        inf = C.infos(src)
    except (OSError, ValueError, KeyError, StopIteration):
        raise ErreurTache("L'épisode exporté est illisible : exporte-le à nouveau.", ["rapport"])
    norm = C.normaliser([(c["a"], c["b"]) for c in M.coupes(e)], inf["duree"], inf["fps"])
    garder = C.a_garder(norm, inf["duree"])
    if not garder:
        raise ErreurTache("Ces coupes retirent tout l'épisode : enlèves-en au moins une.", [])
    x = inf["x264"] if inf["video_id"] == 1 else None
    morceaux = C.plan(garder, sorted(inf["cles"]), copie=x is not None)
    venc = (["-c:v", "libx264", "-preset", "veryfast", "-crf", x["crf"], "-x264-params",
             f"ref={x['ref']}:bframes={x['bframes']}", "-pix_fmt", "yuv420p", *inf["couleurs"]]
            if x else [*_encodage_complet(), *inf["couleurs"]])
    tmp = d / "sorties" / ".coupes"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        a_enc = [(i, m) for i, m in enumerate(morceaux) if m[0] == "enc"]
        total = sum(m[2] - m[1] for _, m in a_enc) or 1.0
        v1 = 0.5 if x else 0.75  # sans copie, l'image est le plus long
        fichiers, fait = {}, 0.0
        for i, m in a_enc:
            f = tmp / f"{i:03d}.mp4"
            deb = 0.05 + (v1 - 0.05) * fait / total
            fait += m[2] - m[1]
            _ffmpeg(ctx, ["-ss", f"{m[1]:.6f}", "-i", str(src), "-t", f"{m[2] - m[1]:.6f}", "-map", "0:v:0", "-an",
                          *venc, "-progress", "pipe:1", "-nostats", str(f)],
                    "Réencodage des secondes autour des coupes" if x else "Réencodage de l'épisode",
                    deb, 0.05 + (v1 - 0.05) * fait / total, m[2] - m[1], "Le réencodage autour d'une coupe a échoué.")
            fichiers[i] = f
        duree = sum(b - a for a, b in garder)
        son = []
        if inf["son"]:
            _ffmpeg(ctx, ["-vn", "-i", str(src), "-filter_complex", C.filtre_son(garder), "-map", "[a]", "-c:a",
                          C.encodeur_son(), "-b:a", str(inf["son_debit"]), "-progress", "pipe:1", "-nostats",
                          str(tmp / "son.m4a")],
                    "Son recoupé à l'échantillon près", v1, 0.92, duree, "Le son de l'épisode n'a pas pu être recoupé.")
            son = ["-i", str(tmp / "son.m4a"), "-map", "1:a"]
        (tmp / "liste.txt").write_text(C.liste_concat(src, morceaux, inf["cles"], fichiers), encoding="utf-8")
        part = tmp / "episode.mp4"
        _ffmpeg(ctx, ["-f", "concat", "-safe", "0", "-i", str(tmp / "liste.txt"), *son, "-map", "0:v", "-c", "copy",
                      "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(part)],
                "Assemblage de l'épisode coupé", 0.92, 0.99, duree, "L'assemblage de l'épisode coupé a échoué.")
        n, attendu = C.compter_images(part), round(duree * inf["fps"])
        if abs(n - attendu) > 1:
            raise ErreurTache(f"L'épisode coupé n'a pas le bon nombre d'images ({n} au lieu de {attendu}) : il n'a pas "
                              f"été gardé. Envoie un rapport.", ["rapport"])
        part.replace(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    modifier(d, {"type": "coupes_finies", "empreinte": emp})
