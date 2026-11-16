"""Aperçu d'un pack de shorts : UNE image 1080x1920 dessinée avec les fonctions de vertical.py (mêmes réglages,
même dessin que la fabrication) : fond, dégradés de la DA, logo, accroche, deux lignes de sous-titres avec un mot clé.

Importé par l'app (pas de sous-processus : ~0,1 s par image une fois le moteur chargé). vertical.py garde ses
réglages dans des variables globales : un verrou empêche deux aperçus de se mélanger.

Usage (essai à la main) : python apercu_pack.py spec_du_pack.json sortie.jpg [fond.jpg]
"""
import json
import sys
import threading
from pathlib import Path

import numpy as np
from PIL import Image

import teaser
import vertical as V

VERROU = threading.Lock()
ACCROCHE = ["Ce que personne", "ne te *dit* jamais"]
LIGNES = [["Et", "là,", "je", "me", "suis", "dit"], ["c'est", "le", "moment"]]


def fond_neutre() -> Image.Image:
    """dégradé sombre et chaud (aucun podcast sous la main)"""
    y = np.sin(np.pi * np.linspace(0, 1, V.H))[:, None]
    haut, milieu = np.array([44, 40, 37]), np.array([92, 82, 74])
    col = (haut + (milieu - haut) * y).astype(np.uint8)
    return Image.fromarray(np.repeat(col[:, None, :], V.W, axis=1), "RGB")


def couvrir(img: Image.Image) -> Image.Image:
    """recadre une image (16:9 en général) pour remplir le 9:16 du short, centrée"""
    s = max(V.W / img.width, V.H / img.height)
    im = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    x, y = (im.width - V.W) // 2, (im.height - V.H) // 2
    return im.crop((x, y, x + V.W, y + V.H))


def _page(lignes):
    """lignes de sous-titres au format de vertical.vlayout ; le dernier mot de la dernière ligne est le mot clé"""
    t, out = 0.0, []
    for i, ln in enumerate(lignes):
        mots = []
        for w in ln:
            mots.append((teaser.clean(w), t, t + 0.2, w))
            t += 0.2
        out.append({"words": mots, "key": "vert" if i == len(lignes) - 1 else None, "from": len(mots) - 1})
    return out


def image(spec, fond=None, accroche=None, lignes=None) -> Image.Image:
    """spec : réglages du pack pour le moteur (app/packs/bibliotheque.spec_moteur) ; fond : image (chemin) ou None ;
    accroche : lignes de l'accroche (*mot* en couleur), [] = sans ; lignes : sous-titres (listes de mots), [] = sans"""
    accroche = ACCROCHE if accroche is None else accroche
    lignes = [ln for ln in (LIGNES if lignes is None else lignes) if ln]
    with VERROU:
        try:
            return _dessiner(spec, fond, accroche, lignes)
        finally:
            _oublier_polices()


def _oublier_polices():
    """vide le cache des polices de vertical.py (vfont, cache à deux étages) : l'aperçu tourne dans le serveur, une
    police du pack gardée en cache resterait ouverte (Windows : fichier bloqué, pack impossible à modifier ou
    supprimer) et une police remplacée sous le même nom serait encore dessinée avec l'ancienne. La fabrication (autre
    processus) n'est pas concernée."""
    f = V.vfont
    while f is not None:
        if hasattr(f, "cache_clear"):
            f.cache_clear()
        f = getattr(f, "__wrapped__", None)


def _dessiner(spec, fond, accroche, lignes) -> Image.Image:
    V.configurer(spec, {})
    if fond:
        with Image.open(fond) as f:  # fichier refermé tout de suite (Windows)
            im = couvrir(f.convert("RGB")).convert("RGBA")
    else:
        im = fond_neutre().convert("RGBA")
    if V.DA == "craie":
        im.alpha_composite(V.craie_vignette())
    if V.USE_LOGO:
        V.poser_logo(im, {})
    if accroche:
        im.alpha_composite(V.craie_hook(accroche, 1.6) if V.DA == "craie" else V.hook_layer(accroche, 1.0))
    if lignes:
        bite = {"pages": [_page(lignes)], "map": lambda x: x, "seq_end": 60.0}
        ev = V.sub_events([bite])[0]
        im.alpha_composite(V.draw_subs(ev, 30.0, V.H * V.SUB_Y))  # 30 s : tous les mots sont apparus
    return im.convert("RGB")


if __name__ == "__main__":
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    image(spec, sys.argv[3] if len(sys.argv) > 3 else None).save(sys.argv[2], quality=90)
