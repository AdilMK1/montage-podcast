"""Espace disque : vérification avant une tâche lourde, niveau d'alerte pour l'écran Activité."""
import shutil

GO = 1_000_000_000
MARGE = 2 * GO            # toujours garder 2 Go libres
SEUIL_ORANGE = 30 * GO


def libre(dossier) -> int:
    return shutil.disk_usage(dossier).free


def verifier(dossier, besoin: int) -> tuple[bool, int]:
    l = libre(dossier)
    return l - besoin >= MARGE, l


def niveau(libre_octets: int) -> str:
    if libre_octets < MARGE:
        return "rouge"
    return "orange" if libre_octets < SEUIL_ORANGE else "ok"


def texte(octets: int) -> str:
    g = octets / GO
    return f"{g:.0f} Go" if g >= 10 else f"{g:.1f} Go".replace(".", ",")


def message_manque(besoin: int, libre_octets: int) -> str:
    return (f"Pas assez de place sur le disque : il faut environ {texte(besoin + MARGE)}, il reste {texte(libre_octets)}. "
            "Libère de la place (anciens projets, corbeille) puis réessaie.")
