"""IA de l'app : Claude Code en ligne de commande, sans outils ni connecteurs, tout le contexte en entrée.

L'IA ne lit et n'écrit aucun fichier : elle répond avec un JSON que l'app extrait, valide puis enregistre.
Lancée « nue » (--strict-mcp-config, aucun serveur, --disable-slash-commands) : sinon les descriptions des
connecteurs de l'ordinateur remplissent le contexte et la demande est refusée ou très lente (vu le 09/11/2026).
Modèle claude-sonnet-5-5 : l'alias « sonnet » réfléchissait sans fin sur la demande des shorts.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

MODELE, EFFORT, DELAI, ESSAIS = "claude-sonnet-5-5", "medium", 150, 3


class IAIndisponible(Exception):
    """aucune IA sur cet ordinateur"""


class IAEchec(Exception):
    """l'IA n'a pas donné de réponse exploitable"""


def commande(config: dict) -> str | None:
    if config.get("ia_commande") or shutil.which("claude"):
        return config.get("ia_commande") or shutil.which("claude")
    # installés hors du PATH vu par l'app : Homebrew (Mac), installateur officiel (~/.local/bin, Mac et Windows)
    for c in (Path("/opt/homebrew/bin/claude"), Path.home() / ".local/bin/claude.exe", Path.home() / ".local/bin/claude"):
        if c.is_file():
            return str(c)
    return None


def demande(consignes: str, personnes: dict, transcript: str, plage: tuple, tache: str, brief: str = "",
            noms=(), extra: dict | None = None) -> str:
    parts = ["Tu es l'assistant de montage d'une app de montage de podcasts. Respecte strictement ces consignes :",
             "<consignes>", consignes, "</consignes>",
             "<qui_est_qui>", json.dumps(personnes, ensure_ascii=False), "</qui_est_qui>",
             "<transcript>", transcript, "</transcript>",
             f"<plage_filmee>Toutes les caméras filment de {plage[0]:.1f} s à {plage[1]:.1f} s : chaque extrait doit "
             "commencer et finir dans cette plage, sur des phrases complètes.</plage_filmee>"]
    if brief.strip():
        parts += ["<brief>", "Demandes du client pour ce podcast (à respecter) :", brief.strip(), "</brief>"]
    if noms:
        parts += ["<noms_propres>", "Orthographe exacte à utiliser : " + ", ".join(noms), "</noms_propres>"]
    for k, v in (extra or {}).items():
        parts += [f"<{k}>", v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=1), f"</{k}>"]
    parts.append("Tâche : " + tache + " Pas de texte avant ou après, pas de balises de code.")
    return "\n".join(parts)


def extraire_json(txt: str):
    t = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
    if "{" not in t:
        raise ValueError("pas de JSON dans la réponse")
    return json.loads(t[t.find("{"):t.rfind("}") + 1])


def proposer(texte: str, valider, *, cmd: str | None, modele: str = MODELE, effort: str = EFFORT,
             delai: float = DELAI, essais: int = ESSAIS, executer=subprocess.run, journal=None, cwd=None, sur_essai=None):
    """envoie la demande, renvoie l'objet validé ; IAIndisponible / IAEchec sinon"""
    if not cmd:
        raise IAIndisponible("Aucune IA n'est installée sur cet ordinateur.")
    args = [cmd, "-p", "--model", modele, "--effort", effort, "--tools", "", "--output-format", "text",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
            "--no-session-persistence"]
    derniere = ""
    for essai in range(1, essais + 1):
        if sur_essai:
            sur_essai(essai)
        try:
            r = executer(args, input=texte, cwd=cwd, capture_output=True, text=True, timeout=delai)
        except subprocess.TimeoutExpired:
            derniere = "delai"
            _noter(journal, f"essai {essai} : pas de réponse en {delai:.0f} s")
            continue
        try:
            return valider(extraire_json(r.stdout))
        except Exception as e:  # noqa: BLE001 (réponse de l'IA : tout peut arriver)
            derniere = "format"
            _noter(journal, f"essai {essai} : réponse inexploitable ({e})\n{r.stdout[:2000]}\n{r.stderr[:500]}")
    if derniere == "delai":
        raise IAEchec("L'IA ne répond pas (3 essais). Réessaie plus tard, ou choisis les passages dans le transcript.")
    raise IAEchec("L'IA a répondu dans un format inexploitable (3 essais). Réessaie, ou choisis les passages dans le transcript.")


def _noter(journal, txt: str):
    if journal:
        Path(journal).parent.mkdir(parents=True, exist_ok=True)
        with open(journal, "a", encoding="utf-8") as f:
            f.write(txt + "\n")
