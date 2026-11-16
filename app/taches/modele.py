"""Une tâche de fond (analyse, rendu de shorts, montage, proxys…), stockée dans projets/<ID>/taches/<id>.json."""
import time
import uuid

ACTIFS = ("en_cours", "semble_bloquee")
FINIS = ("terminee", "echec", "annulee")
PRIORITES = {"pre_analyse": 0, "analyse": 0, "son": 1, "ia_shorts": 1, "ia_passages": 1, "apercus": 1, "shorts": 2, "livraison": 2,
             "montage": 3, "essai": 3, "coupes": 3, "export": 4, "proxys": 9}
# l'IA ne charge pas la machine (Claude Code travaille à distance) : poids « legere »
POIDS = {"proxys": "fond", "apercus": "legere", "livraison": "legere", "ia_shorts": "legere", "ia_passages": "legere"}


def nouvelle_tache(projet: str, type_: str, params: dict | None = None, maintenant: float | None = None) -> dict:
    t = time.time() if maintenant is None else maintenant
    return {
        "id": f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(t))}-{uuid.uuid4().hex[:6]}",
        "projet": projet, "type": type_, "params": params or {},
        "priorite": PRIORITES.get(type_, 5), "poids": POIDS.get(type_, "lourde"),
        "statut": "en_attente", "cree": t, "debut": None, "fin": None,
        "progression": {"fraction": 0.0, "texte": ""}, "signe_vie": None, "tentatives": 0,
        "erreur": None, "morceaux_faits": [], "atelier": None,
    }
