"""Réglages du son -> clés lues par moteur/son_v2.py (session.json)."""
AUTOMIX = {"leger": -6.0, "normal": -12.0, "fort": -20.0}
DEBRUITAGE = "afftdn=nr=18:nf=-45:tn=0"  # réglage validé à l'écoute sur un micro qui souffle


def config_son(reglages: dict) -> dict:
    return {"automix_plancher_db": AUTOMIX.get(reglages.get("automix", "normal"), -12.0),
            "debruitage": {k: DEBRUITAGE for k in reglages.get("debruitage", [])}}
