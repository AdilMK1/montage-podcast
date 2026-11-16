"""Quelles tâches lancer maintenant, lesquelles doivent céder leur place (fonction pure)."""


def _cle(t):
    return (t["projet"], t["type"])


def choisir(attente: list, en_cours: list, places: dict) -> tuple[list, list]:
    actifs = list(en_cours)
    occupe = {_cle(t) for t in actifs}
    a_lancer, a_ceder = [], []
    ordre = sorted(attente, key=lambda t: (t["priorite"], t["cree"]))

    def lourdes():
        return sum(1 for x in actifs if x["poids"] in ("lourde", "fond"))

    def legeres():
        return sum(1 for x in actifs if x["poids"] == "legere")

    def lancer(t):
        a_lancer.append(t)
        actifs.append(t)
        occupe.add(_cle(t))

    for t in ordre:
        if _cle(t) in occupe:
            continue
        if t["poids"] == "legere":
            if legeres() < places["legere"]:
                lancer(t)
        elif t["poids"] == "lourde":
            if lourdes() < places["lourde"]:
                lancer(t)
            else:
                fond = next((x for x in actifs if x["poids"] == "fond"), None)
                if fond is not None:
                    actifs.remove(fond)
                    a_ceder.append(fond)
                    lancer(t)
        else:  # fond : seulement sur une place lourde libre, et si aucune lourde lançable n'attend
            lourde_en_attente = any(x["poids"] == "lourde" and x not in a_lancer and _cle(x) not in occupe
                                    for x in ordre)
            if lourdes() < places["lourde"] and not lourde_en_attente:
                lancer(t)
    return a_lancer, a_ceder
