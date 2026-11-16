"""Chien de garde : une tâche qui ne donne plus signe de vie est marquée, puis relancée une fois, puis en échec."""
DELAIS = {"analyse": (300, 900), "proxys": (120, 300)}
DEFAUT = (90, 240)
TENTATIVES_MAX = 2


def _delais(t):
    d = (t.get("params") or {}).get("delais")
    return tuple(d) if d else DELAIS.get(t["type"], DEFAUT)


def etat_vie(t: dict, maintenant: float) -> str:
    ref = t.get("signe_vie") or t.get("debut")
    if ref is None:
        return "ok"
    marque, bloque = _delais(t)
    age = maintenant - ref
    if age >= bloque:
        return "bloquee"
    return "semble_bloquee" if age >= marque else "ok"


def decision(t: dict, maintenant: float) -> str | None:
    e = etat_vie(t, maintenant)
    if e == "bloquee":
        return "relancer" if t.get("tentatives", 0) < TENTATIVES_MAX else "echec"
    return "marquer" if e == "semble_bloquee" else None
