"""L'atelier : processus séparé du serveur qui exécute les tâches de tous les projets.

Une boucle (tour toutes les 0,5 s) : annulations, chien de garde, choix des tâches à lancer, anti-veille, battement.
Chaque tâche tourne dans un fil ; l'atelier est le seul à modifier les fichiers de tâche existants.
Lancement : python -m app.taches.atelier --racine projets --battement .atelier/battement.json
Types de tâches : module donné par CRAIE_TYPES_TACHES (défaut app.taches.types), attribut TYPES.

Un seul atelier à la fois : au démarrage il prend un verrou exclusif sur `instance.verrou` (à côté du battement),
tenu toute la vie du processus et libéré par le système à sa mort ; sans verrou, il s'arrête tout de suite.

Fils et verrou : `_actives` (tâches lancées par cet atelier), `_suspens` (états finals pas encore écrits) et le
dict de chaque tâche active ne sont lus ou modifiés que sous `_verrou`. Une tâche est close une seule fois
(`_clore`) : son retrait de `_actives` et son état final se font ensemble, sous le verrou ; si l'écriture de l'état
final rate (disque plein, fichier tenu par un antivirus), il reste en suspens et est réécrit à chaque tour.
Un contexte qui n'est plus celui de la tâche active (fil abandonné, en retard) n'écrit plus rien.
Les écritures en cours de route (progrès, signe de vie, processus) sont « au mieux » : un échec est noté au
journal et l'état en mémoire sera écrit au passage suivant.

Windows (lot 2) : les sous-processus ont leur propre groupe, sans fenêtre ; il faudra ajouter un Job Object
« kill on close » pour que les rendus meurent avec l'atelier.
"""
import argparse
import importlib
import os
import signal
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

from app.fichiers import ecrire_json_atomique
from app.ressources.veille import AntiVeille

from . import chien, file
from .choix import choisir
from .execution import Arrete, signature, tuer_orphelin
from .execution import executer as executer_processus
from .modele import ACTIFS, FINIS

PLACES = {"lourde": 1, "legere": 1}
ABANDON_S = 30.0  # délai laissé à un gestionnaire pour obéir à un arrêt avant qu'on abandonne son fil
SAUT_S = 30.0  # plus de 30 s entre deux tours (pas : 0,5 s) = l'ordinateur était en veille, pas une tâche bloquée
MSG_BLOQUEE = "La tâche est restée bloquée deux fois. Réessaie ; si ça recommence, envoie un rapport."
MSG_INATTENDUE = "Erreur inattendue. Réessaie ; si ça recommence, envoie un rapport."
MSG_FIL_MORT = "La tâche s'est arrêtée sans prévenir. Réessaie ; si ça recommence, envoie un rapport."
MSG_TYPE_INCONNU = "Cette tâche n'est pas prise en charge par cette version de l'app."
MSG_INTERROMPUE = ("La tâche a été interrompue plusieurs fois (l'app s'est fermée brutalement pendant qu'elle "
                   "tournait). Réessaie ; si ça recommence, envoie un rapport.")


class ErreurTache(Exception):
    """échec expliqué : message affiché tel quel, actions proposées à l'utilisateur"""

    def __init__(self, message: str, actions=()):
        super().__init__(message)
        self.message, self.actions = message, list(actions)


def prendre_verrou_instance(chemin):
    """verrou exclusif non bloquant ; renvoie le fichier ouvert (à garder ouvert) ou None s'il est déjà pris"""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    f = open(chemin, "a+b")  # non hérité par les sous-processus (PEP 446) : un rendu orphelin ne le garde pas
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def _noter_stderr(message: str):
    sys.stderr.write(f"[atelier {time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    sys.stderr.flush()


class Contexte:
    def __init__(self, atelier, projet_dir: Path, tache: dict):
        self._a, self.projet_dir, self.tache = atelier, Path(projet_dir), tache
        self.arret, self.raison_arret, self.t_arret = threading.Event(), None, None
        self._verrou, self._fini = threading.Lock(), False
        self.journal = self.projet_dir / "taches" / f"{tache['id']}.log"

    @property
    def params(self) -> dict:
        return self.tache.get("params") or {}

    def arreter(self, raison: str):
        """demande l'arrêt ; sans effet si un arrêt est déjà demandé ou si le gestionnaire a déjà rendu la main"""
        with self._verrou:
            if self.raison_arret is None and not self._fini:
                self.raison_arret, self.t_arret = raison, self._a.horloge()
                self.arret.set()

    def _terminer(self) -> str | None:
        """le gestionnaire a rendu la main : plus aucun arrêt accepté ; renvoie la raison d'arrêt déjà demandée"""
        with self._verrou:
            self._fini = True
            return self.raison_arret

    def verifier_arret(self):
        if self.arret.is_set():
            raise Arrete()

    def progres(self, fraction=None, texte=None):
        def chg(t):
            p = dict(t["progression"])
            if fraction is not None:
                p["fraction"] = round(max(0.0, min(1.0, fraction)), 4)
            if texte is not None:
                p["texte"] = texte
            return {"progression": p, "signe_vie": self._a.horloge()}
        self._a._maj(self, chg)

    def vie(self):
        self._a._maj(self, lambda t: {"signe_vie": self._a.horloge()})

    def est_fait(self, k) -> bool:
        return k in self.tache["morceaux_faits"]

    def morceau_fait(self, k):
        self._a._maj(self, lambda t: {"morceaux_faits": [*t["morceaux_faits"], k], "signe_vie": self._a.horloge()})

    def executer(self, cmd, debut: float = 0.0, fin: float = 1.0, **kw) -> int:
        def rappel(f, vivant):
            if vivant:
                self.progres(debut + (fin - debut) * f if f is not None else None)
        def lance(p):  # noté dans la tâche : si l'atelier meurt, la reprise tuera ce rendu orphelin
            self._a._maj(self, lambda t: {"processus": signature(p.pid)})
        try:
            return executer_processus(cmd, self.journal, rappel=rappel, arret=self.arret, au_lancement=lance, **kw)
        finally:
            self._a._maj(self, lambda t: {"processus": None})


class Atelier:
    def __init__(self, racine_projets, types: dict, battement, places: dict | None = None, horloge=time.time,
                 anti_veille=None, abandon: float = ABANDON_S, noter=None):
        self.id = uuid.uuid4().hex[:8]
        self.racine, self.types, self.battement = Path(racine_projets), types, Path(battement)
        self.places, self.horloge, self.abandon = places or dict(PLACES), horloge, abandon
        self.veille = anti_veille if anti_veille is not None else AntiVeille()
        self.noter = noter or _noter_stderr  # journal de l'atelier (.atelier/atelier.log via la sortie d'erreur)
        self._verrou = threading.Lock()
        self._actives: dict[str, tuple[Contexte, threading.Thread]] = {}
        self._suspens: dict[str, tuple[Path, dict]] = {}  # état final pas encore écrit : réessayé à chaque tour
        self._signales: set = set()
        self._dernier_tour: float | None = None

    # ---------- journal ----------

    def _noter(self, message: str):
        try:
            self.noter(message)
        except Exception:
            pass

    def _noter_une_fois(self, cle, message: str):
        if cle not in self._signales:
            self._signales.add(cle)
            self._noter(message)

    def _noter_exception(self, quoi: str):
        self._noter(f"{quoi} : {traceback.format_exc().rstrip()}")

    def _lister(self):
        return file.lister(self.racine, signaler=lambda f, raison: self._noter_une_fois(
            ("fichier", str(f)), f"fichier de tâche ignoré ({raison}) : {f}"))

    # ---------- état des tâches actives (un seul écrivain : cet atelier) ----------

    def _est_active(self, ctx: Contexte) -> bool:
        """à appeler sous _verrou : ctx est-il le contexte de la tâche active (et pas un fil périmé) ?"""
        a = self._actives.get(ctx.tache["id"])
        return a is not None and a[0] is ctx

    def _ecrire_au_mieux(self, pd: Path, t: dict):
        """écriture non finale : un échec est noté, l'état en mémoire sera écrit au passage suivant"""
        try:
            file.ecrire(pd, t)
        except OSError as e:
            self._noter(f"tâche {t.get('id')} : écriture reportée ({e})")

    def _maj(self, ctx: Contexte, changement):
        """applique changement(tache) -> dict à la tâche de ctx, si ctx est toujours le contexte actif"""
        with self._verrou:
            if not self._est_active(ctx):
                return
            t = ctx.tache
            chg = changement(t)
            if "signe_vie" in chg and t["statut"] == "semble_bloquee" and "statut" not in chg:
                chg["statut"] = "en_cours"
            t.update(chg)
            self._ecrire_au_mieux(ctx.projet_dir, t)

    def _fin_arret(self, ctx: Contexte, raison: str | None) -> dict:
        if raison == "annulation":
            return {"statut": "annulee"}
        if raison == "ceder":  # céder sa place ne compte pas comme une tentative
            return {"statut": "en_attente", "atelier": None, "tentatives": ctx.tache["tentatives"] - 1}
        if raison == "relance":
            return {"statut": "en_attente", "atelier": None}
        if raison == "bloquee":
            return {"statut": "echec", "erreur": {"message": MSG_BLOQUEE, "actions": ["reessayer", "rapport"]}}
        return {"statut": "echec", "erreur": {"message": MSG_INATTENDUE, "actions": ["reessayer", "rapport"]}}

    def _ecrire_final(self, tid: str) -> bool:
        """à appeler sous _verrou : écrit l'état final en suspens ; il y reste si l'écriture rate"""
        pd, t = self._suspens[tid]
        try:
            file.ecrire(pd, t)
        except OSError as e:
            self._noter_une_fois(("suspens", tid), f"tâche {tid} : état final « {t['statut']} » pas encore "
                                                   f"écrit ({e}) ; nouvel essai à chaque tour")
            return False
        del self._suspens[tid]
        self._signales.discard(("suspens", tid))
        return True

    def _clore(self, ctx: Contexte, fin: dict):
        """retire la tâche et écrit son état final, d'un seul tenant ; sans effet si ctx n'est plus le contexte
        actif. Ne lève jamais : un état final non écrit reste en suspens (réécrit à chaque tour)."""
        tid = ctx.tache["id"]
        with self._verrou:
            if not self._est_active(ctx):
                return
            del self._actives[tid]
            try:
                if file.annulation_demandee(ctx.projet_dir, tid):
                    if fin["statut"] == "en_attente":  # annulée pendant qu'elle cédait sa place ou repartait
                        fin = {"statut": "annulee"}
                    # drapeau effacé AVANT d'écrire le statut final : « annulee » visible => plus de drapeau
                    file.nettoyer_annulation(ctx.projet_dir, tid)
            except OSError as e:
                self._noter(f"tâche {tid} : drapeau d'annulation illisible ({e})")
            if fin["statut"] in FINIS:
                fin["fin"] = self.horloge()
            fin["processus"] = None
            ctx.tache.update(fin)
            self._suspens[tid] = (ctx.projet_dir, ctx.tache)
            self._ecrire_final(tid)

    def _ecrire_suspens(self):
        with self._verrou:
            for tid in list(self._suspens):
                self._ecrire_final(tid)

    def _remettre(self, pd: Path, t: dict, quoi: str):
        """tâche laissée active sans fil pour la porter (atelier mort, ou fil perdu) : son rendu orphelin est tué,
        puis elle repart en attente, ou en échec si elle a déjà été interrompue trop souvent"""
        if tuer_orphelin(t.get("processus")):
            self._noter(f"tâche {t['id']} : rendu orphelin tué ({quoi})")
            try:
                with open(file.dossier(pd) / f"{t['id']}.log", "a", encoding="utf-8") as j:
                    j.write(f"\n[atelier] rendu orphelin ({quoi}) : tué\n")
            except OSError:
                pass
        if t["tentatives"] >= chien.TENTATIVES_MAX:
            t.update(statut="echec", atelier=None, processus=None, fin=self.horloge(),
                     erreur={"message": MSG_INTERROMPUE, "actions": ["reessayer", "rapport"]})
        else:
            t.update(statut="en_attente", atelier=None, processus=None)
        file.ecrire(pd, t)

    def reprendre(self):
        """au démarrage : les tâches laissées « en cours » par un atelier mort repartent en attente ; le rendu
        qu'il a laissé tourner (son propre groupe de processus, donc pas tué avec lui) est tué d'abord, pour ne pas
        écrire les mêmes fichiers que la relance. Le battement est réécrit après chaque tâche reprise (tuer un
        rendu peut prendre quelques secondes)."""
        try:
            toutes = self._lister()
        except Exception:
            self._noter_exception("reprise : liste des tâches illisible")
            return
        for pd, t in toutes:
            try:
                if t["statut"] in ACTIFS and t.get("atelier") != self.id:
                    self._remettre(pd, t, "atelier arrêté brutalement")
                    self._battre(self.horloge(), [])
            except Exception:
                self._noter_exception(f"reprise de la tâche {t.get('id')}")

    def _battre(self, now: float, ids: list):
        self.battement.parent.mkdir(parents=True, exist_ok=True)
        ecrire_json_atomique(self.battement, {"pid": os.getpid(), "atelier": self.id, "t": now, "en_cours": ids})

    def demarrer(self):
        """premier battement AVANT la reprise (le serveur ne relance pas d'atelier pendant qu'elle tourne)"""
        try:
            self._battre(self.horloge(), [])
        except OSError:
            self._noter_exception("premier battement")
        try:
            self.reprendre()
        except Exception:
            self._noter_exception("reprise")

    # ---------- un tour de boucle ----------

    def tour(self):
        now = self.horloge()
        if self._dernier_tour is not None and now - self._dernier_tour > SAUT_S:
            self._reveil(now - self._dernier_tour, now)
        self._dernier_tour = now
        try:
            self._tour(now)
        finally:
            with self._verrou:
                ids = sorted(self._actives)
            self._battre(now, ids)

    def _reveil(self, ecart: float, now: float):
        """l'ordinateur sort de veille : le temps passé à dormir n'est ni un blocage (chien de garde) ni du temps
        de rendu (temps restant). Les tâches actives repartent de maintenant."""
        self._noter(f"réveil après {ecart:.0f} s sans tour (ordinateur en veille ?) : tâches en cours reprises")
        with self._verrou:
            actives = [c for c, _ in self._actives.values()]
        for ctx in actives:
            self._maj(ctx, lambda t: {"signe_vie": now, **({"debut": t["debut"] + ecart} if t.get("debut") else {})})

    def _tour(self, now: float):
        self._ecrire_suspens()
        toutes = self._lister()  # photo des fichiers : peut être en retard sur les fils des tâches
        for pd, t in toutes:
            try:
                self._examiner(pd, t, now)
            except Exception:
                self._noter_exception(f"tâche {t.get('id')}")
        with self._verrou:
            actives = list(self._actives.values())
        for ctx, th in actives:
            try:
                self._surveiller(ctx, th, now)
            except Exception:
                self._noter_exception(f"surveillance de la tâche {ctx.tache.get('id')}")
        with self._verrou:
            exclus = set(self._actives) | set(self._suspens)
            en_cours = [dict(c.tache) for c, _ in self._actives.values()]
        attente = [t for _, t in toutes
                   if t["statut"] == "en_attente" and t["type"] in self.types and t["id"] not in exclus]
        a_lancer, a_ceder = choisir(attente, en_cours, self.places)
        for t in a_ceder:
            with self._verrou:
                a = self._actives.get(t["id"])  # peut avoir fini entre-temps
            if a:
                a[0].arreter("ceder")  # sans effet si le gestionnaire a déjà rendu la main
        dirs = {t["id"]: pd for pd, t in toutes}
        for t in a_lancer:
            try:
                self._demarrer(dirs[t["id"]], t, now)
            except Exception:
                self._noter_exception(f"lancement de la tâche {t.get('id')}")
                self._echec_au_lancement(dirs[t["id"]], t, now)
        with self._verrou:
            occupe = bool(self._actives)
        try:
            self.veille.activer() if occupe else self.veille.relacher()
        except Exception:
            self._noter_exception("anti-veille")

    def _examiner(self, pd: Path, t: dict, now: float):
        """une tâche vue sur le disque : annulation en attente, type inconnu, tâche active de cet atelier sans fil"""
        tid = t["id"]
        if t["statut"] == "en_attente" and file.annulation_demandee(pd, tid):
            with self._verrou:
                if tid in self._actives or tid in self._suspens:  # relancée entre-temps : traitée plus bas
                    return
                t.update(statut="annulee", fin=now)
                file.nettoyer_annulation(pd, tid)
                file.ecrire(pd, t)
            return
        if t["statut"] == "en_attente" and t["type"] not in self.types:
            with self._verrou:
                if tid in self._actives or tid in self._suspens:
                    return
                t.update(statut="echec", fin=now, erreur={"message": MSG_TYPE_INCONNU, "actions": ["rapport"]})
                file.ecrire(pd, t)
            self._noter(f"tâche {tid} : type « {t['type']} » inconnu de cet atelier")
            return
        if t["statut"] in ACTIFS and t.get("atelier") == self.id:
            with self._verrou:
                if tid in self._actives or tid in self._suspens:
                    return
                frais = file.lire(pd, tid)  # relu sous le verrou : la photo peut précéder une clôture normale
                if not (isinstance(frais, dict) and frais.get("statut") in ACTIFS and frais.get("atelier") == self.id):
                    return
                self._noter(f"tâche {tid} : active mais plus portée par aucun fil, traitée comme orpheline")
                self._remettre(pd, frais, "fil perdu")

    def _surveiller(self, ctx: Contexte, th: threading.Thread, now: float):
        tid = ctx.tache["id"]
        if not th.is_alive():
            # fil fini sans avoir clos sa tâche (ou jamais démarré) : sans ceci elle resterait active pour toujours
            with self._verrou:
                if not self._est_active(ctx):
                    return
            ctx._terminer()
            self._noter(f"tâche {tid} : fil arrêté sans clore la tâche")
            self._clore(ctx, {"statut": "echec", "erreur": {"message": MSG_FIL_MORT, "actions": ["reessayer", "rapport"]}})
            return
        if ctx.raison_arret is not None:
            # arrêt demandé : un gestionnaire sourd à l'arrêt ne doit pas bloquer la tâche pour toujours
            if now - ctx.t_arret >= self.abandon:
                self._abandonner(ctx)
            return
        if file.annulation_demandee(ctx.projet_dir, tid):
            ctx.arreter("annulation")
            return
        with self._verrou:
            if not self._est_active(ctx):  # close entre-temps
                return
            d = chien.decision(ctx.tache, now)
            if d == "marquer" and ctx.tache["statut"] != "semble_bloquee":
                ctx.tache["statut"] = "semble_bloquee"
                self._ecrire_au_mieux(ctx.projet_dir, ctx.tache)
        if d == "relancer":
            ctx.arreter("relance")
        elif d == "echec":
            ctx.arreter("bloquee")

    def _demarrer(self, pd: Path, t: dict, now: float):
        t.update(statut="en_cours", debut=now, signe_vie=now, tentatives=t["tentatives"] + 1, atelier=self.id,
                 erreur=None,  # fraction_debut : après une reprise, le temps restant ne compte que cette tentative
                 fraction_debut=(t.get("progression") or {}).get("fraction") or 0.0)
        ctx = Contexte(self, pd, t)
        th = threading.Thread(target=self._executer, args=(ctx,), daemon=True, name=f"tache-{t['id']}")
        with self._verrou:
            if t["id"] in self._actives:
                return
            file.ecrire(pd, t)
            self._actives[t["id"]] = (ctx, th)
        th.start()  # s'il ne démarre pas, le tour suivant voit un fil mort et clôt la tâche

    def _echec_au_lancement(self, pd: Path, t: dict, now: float):
        """une tâche qui ne peut pas démarrer (fichier corrompu) passe en échec, sinon elle bloquerait sa place"""
        with self._verrou:
            if t["id"] in self._actives or t["id"] in self._suspens:
                return
            t.update(statut="echec", fin=now, atelier=None,
                     erreur={"message": MSG_INATTENDUE, "actions": ["reessayer", "rapport"]})
            self._ecrire_au_mieux(pd, t)

    def _abandonner(self, ctx: Contexte):
        """le fil n'obéit pas à l'arrêt : la tâche est close sans lui (il n'écrira plus rien s'il revient)"""
        raison = ctx._terminer()
        try:
            with open(ctx.journal, "a", encoding="utf-8") as j:
                j.write(f"\n[atelier] arrêt « {raison} » ignoré depuis {self.abandon:.0f} s : fil abandonné\n")
        except OSError:
            pass
        self._clore(ctx, self._fin_arret(ctx, raison))

    def _executer(self, ctx: Contexte):
        fin, interruption = None, None
        try:
            self.types[ctx.tache["type"]](ctx)
            raison = ctx._terminer()
            # rendu la main alors qu'un arrêt était demandé : on ne sait pas s'il a fini, on suit l'arrêt
            fin = self._fin_arret(ctx, raison) if raison else {
                "statut": "terminee", "progression": {"fraction": 1.0, "texte": "Terminé"}}
        except Arrete:
            fin = self._fin_arret(ctx, ctx._terminer())
        except ErreurTache as e:
            raison = ctx._terminer()  # une erreur après un arrêt demandé en est la conséquence : on suit l'arrêt
            fin = self._fin_arret(ctx, raison) if raison else {
                "statut": "echec", "erreur": {"message": e.message, "actions": e.actions or ["reessayer"]}}
        except BaseException as e:  # Exception, mais aussi SystemExit levée par un gestionnaire
            raison = ctx._terminer()
            try:
                ctx.journal.parent.mkdir(parents=True, exist_ok=True)
                with open(ctx.journal, "a", encoding="utf-8") as j:
                    j.write(traceback.format_exc())
            except OSError:
                pass
            fin = self._fin_arret(ctx, raison)  # raison None => « Erreur inattendue »
            if isinstance(e, KeyboardInterrupt):
                interruption = e
        finally:
            if fin is None:  # garde-fou : jamais une tâche laissée active par son fil
                ctx._terminer()
                fin = self._fin_arret(ctx, None)
            self._clore(ctx, fin)
        if interruption is not None:
            raise interruption

    # ---------- vie du processus ----------

    def arreter_tout(self, delai: float = 15.0):
        """arrêt propre (fermeture de l'app) : les tâches en cours repartent en attente"""
        with self._verrou:
            actives = list(self._actives.values())
        for ctx, _ in actives:
            ctx.arreter("ceder")
        for ctx, th in actives:
            th.join(delai)
            if th.is_alive():
                self._abandonner(ctx)
        self._ecrire_suspens()
        self.veille.relacher()

    def boucle(self, pas: float = 0.5):
        stop = threading.Event()
        for s in (signal.SIGTERM, signal.SIGINT, getattr(signal, "SIGBREAK", None)):  # SIGBREAK : Windows
            if s is not None:
                signal.signal(s, lambda *_: stop.set())
        self.demarrer()
        while not stop.is_set():
            try:
                self.tour()
            except Exception:  # un tour raté (disque, fichier illisible) ne doit pas tuer l'atelier
                self._noter_exception("tour raté")
            stop.wait(pas)
        self.arreter_tout()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--racine", required=True)
    ap.add_argument("--battement", required=True)
    a = ap.parse_args(argv)
    verrou = prendre_verrou_instance(Path(a.battement).parent / "instance.verrou")
    if verrou is None:
        _noter_stderr(f"un autre atelier tourne déjà (pid {os.getpid()} s'arrête)")
        return 0
    types = importlib.import_module(os.environ.get("CRAIE_TYPES_TACHES", "app.taches.types")).TYPES
    try:
        Atelier(a.racine, types, a.battement).boucle()
    finally:
        verrou.close()
    return 0


if __name__ == "__main__":
    # lancé par « python -m app.taches.atelier », ce fichier tourne sous le nom __main__ : sa classe ErreurTache
    # n'est pas celle que les gestionnaires importent (app.taches.atelier.ErreurTache), et leurs erreurs expliquées
    # deviendraient « Erreur inattendue ». On passe donc par le module importé.
    from app.taches.atelier import main as _main
    sys.exit(_main())
