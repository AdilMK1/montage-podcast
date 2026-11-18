"""Le serveur local : HTTP stdlib, aucune logique de montage. Il construit des vues, fait passer chaque décision par
les règles du projet (refus -> 409, message français), crée les tâches de l'atelier et sert les médias.

Usage : python -m app.api.serveur [port]   puis http://localhost:8765
"""
import html
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app import mise_a_jour
from app.fichiers import lire_json
from app.ia.claude import commande as commande_ia
from app.packs import bibliotheque as B
from app.packs import projets as P
from app.projet.regles import Refus
from app.projet.stockage import EtatIllisible, Occupe, VerrouImpossible, lire_etat
from app.ressources.encodeur import encodeur
from app.ressources.profil import profil as mesurer_profil
from app.services import apercus, casting, couleur, ecoute, transcript
from app.taches import file
from app.taches.superviseur import assurer_atelier

from . import actions, creation, medias, rapport, rushes, vues
from . import packs as packs_api

RACINE = Path(__file__).resolve().parents[2]
MESSAGE_500 = "Erreur inattendue du serveur. Envoie un rapport."
PAGE_MINIMALE = ("<!doctype html><meta charset=utf-8><title>Montage Podcast</title>"
                 "<body style='font-family:sans-serif;padding:3rem'><h1>Montage Podcast</h1>"
                 "<p>Interface en cours de construction.</p>").encode()
CIBLES = {"export": "EXPORT", "shorts": "shorts", "episode": "sorties"}
NOM_DEFAUT = "Montage Podcast"
ACCENT_DEFAUT = b"#F75C03"  # couleur écrite dans app/web/style.css, remplacée par config.json["accent"]
ACCENT_VALIDE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
ID_TACHE = re.compile(r"^[\w-]+$")
HOTES = ("localhost", "127.0.0.1")  # le serveur n'écoute que sur 127.0.0.1
OCCUPE = "Le podcast est occupé, réessaie dans un instant."
ATTENTE_OUVERTURE = 0.3  # secondes : un projet occupé s'ouvre quand même, ses packs sont mis à jour plus tard
ACTIONS_CASTING = ("renommer_personne", "associer_micro", "echanger_personnes", "designer_large", "definir_animateur",
                   "valider_casting")


class Invalide(ValueError):
    """requête invalide dont le message est déjà en français : affiché tel quel"""


def systeme() -> str:
    return sys.platform


def _lancer(cmd, **kw):
    """point d'entrée unique des sous-processus du serveur (remplacé dans les tests)"""
    return subprocess.run(cmd, **kw)


class Application:
    def __init__(self, racine_app=RACINE, racine_projets=None, battement=None, superviser=True, profil=None,
                 racine_packs=None):
        self.racine_app = Path(racine_app)
        self.racine_projets = Path(racine_projets) if racine_projets else self.racine_app / "projets"
        self.racine_packs = Path(racine_packs) if racine_packs else self.racine_app / "packs"
        self.battement = Path(battement) if battement else self.racine_app / ".atelier" / "battement.json"
        self.superviser = superviser
        self._profil = profil
        self._dernier = 0.0
        # fichiers trouvés par un scan : seules les images de ces vidéos et l'écoute de ces micros sont servies
        self.rushes_vus: set[str] = set()
        self.micros_vus: set[str] = set()

    def scanner(self, dossier) -> dict:
        r = creation.scanner(dossier)
        self.rushes_vus.update(f["chemin"] for f in r["fichiers"] if f["type"] == "camera")
        self.micros_vus.update(f["chemin"] for f in r["fichiers"] if f["type"] == "micro")
        return r

    def cache_rushes(self) -> Path:
        return self.racine_app / ".cache" / "rushes"

    def cache_packs(self) -> Path:
        return self.racine_app / ".cache" / "packs"

    def preparer_packs(self):
        """au démarrage : presets migrés en packs (une fois), projets d'avant les packs repris, empreintes des
        packs à jour (pack modifié pendant qu'un projet était occupé)"""
        B.migrer(self.racine_packs, self.racine_app / "presets")
        P.adopter_tous(self.racine_projets, self.racine_packs, self.racine_app / "presets")
        P.synchroniser_tous(self.racine_projets, self.racine_packs)

    def pack_defaut(self) -> str:
        """pack proposé à la création : le dernier utilisé, sinon preset_defaut de config.json, sinon neutre"""
        for p in (B.dernier(self.racine_packs), self.config().get("preset_defaut"), "neutre"):
            if isinstance(p, str) and B.existe(self.racine_packs, p):
                return p
        return B.AUCUN

    def pack_creation(self, demande) -> str:
        if demande is None:
            return self.pack_defaut()
        if not isinstance(demande, str) or not B.existe(self.racine_packs, demande):
            raise Refus("Ce pack n'existe pas : choisis-en un autre.")
        return demande

    def assurer(self, forcer: bool = False):
        """s'assure que l'atelier tourne ; au plus une vérification toutes les 5 s"""
        if not self.superviser:
            return
        now = time.time()
        if forcer or now - self._dernier >= 5:
            self._dernier = now
            assurer_atelier(self.racine_app, self.racine_projets, self.battement)

    def profil(self) -> dict:
        if self._profil is None:
            self._profil = mesurer_profil(self.racine_app / ".cache" / "profil.json")
        return self._profil

    def config(self) -> dict:
        return lire_json(self.racine_app / "config.json", {}) or {}

    def nom(self) -> str:
        n = self.config().get("nom")
        return n.strip() if isinstance(n, str) and n.strip() else NOM_DEFAUT

    def accent(self) -> str:
        """couleur d'accent de config.json, si c'est bien une couleur hexadécimale ; sinon celle par défaut"""
        a = self.config().get("accent")
        return a if isinstance(a, str) and ACCENT_VALIDE.match(a) else ACCENT_DEFAUT.decode()

    def etat_maj(self) -> dict:
        """dernière vérification de mise à jour (au lancement, puis toutes les 6 h tant que l'app tourne)"""
        e = mise_a_jour.lire_etat(self.racine_app)
        if self.superviser and time.time() - e.get("t", 0) > 6 * 3600 and not getattr(self, "_maj_en_cours", False):
            self._maj_en_cours = True

            def verifier():
                try:
                    v = mise_a_jour.verifier(self.racine_app)
                    mise_a_jour._ecrire_etat(self.racine_app, {**e, **v, "faite": False})
                finally:
                    self._maj_en_cours = False
            threading.Thread(target=verifier, daemon=True).start()
        if e.get("faite") and time.time() - e.get("t", 0) > 24 * 3600:
            e = {**e, "faite": False}  # « version installée » : affiché un jour, pas plus
        return {"locale": self.version(), "distante": e.get("distante"), "faite": bool(e.get("faite")),
                "disponible": bool(e.get("distante")) and mise_a_jour.plus_recente(e["distante"], self.version())}

    def version(self) -> str:
        f = self.racine_app / "VERSION"
        return f.read_text().strip() if f.exists() else "dev"

    def pdir(self, pid) -> Path:
        """dossier d'un projet ; il doit être DANS la racine des projets"""
        if not isinstance(pid, str) or not pid:
            raise Invalide("Identifiant de projet invalide.")
        d = (self.racine_projets / pid).resolve()
        if self.racine_projets.resolve() not in d.parents:
            raise Invalide("Identifiant de projet invalide.")
        if not d.is_dir():
            raise FileNotFoundError("Ce podcast est introuvable.")
        return d

    def journal_erreur(self, methode: str, chemin: str):
        try:
            f = self.racine_app / ".atelier" / "serveur.log"
            f.parent.mkdir(parents=True, exist_ok=True)
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} {methode} {chemin}\n{traceback.format_exc()}\n")
        except OSError:
            pass


def _est_francais(msg: str) -> bool:
    # l'apostrophe ne compte que dans une élision (l', d', n', qu'…) : « float: 'abc' » n'est pas du français
    return bool(re.search(r"[éèàêçôùâîû]|\b(?:[cdjlmnst]|qu)'\w", msg, re.I)) or msg.startswith(("Il ", "Un ", "Une ", "Le ", "La ", "Ce ", "Cette "))


class Gestionnaire(BaseHTTPRequestHandler):
    server_version = "MontagePodcast"

    @property
    def app(self) -> Application:
        return self.server.app

    def log_message(self, *a):
        pass

    # ---- réponses
    def envoyer_json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def erreur(self, code: int, message: str):
        self.envoyer_json({"erreur": message, "actions": []}, code)

    def envoyer_octets(self, b: bytes, type_: str, nom: str | None = None):
        self.send_response(200)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        if nom:
            self.send_header("Content-Disposition", f'attachment; filename="{nom}"')
        self.end_headers()
        self.wfile.write(b)

    # ---- aiguillage
    def _origine_refusee(self, methode: str) -> bool:
        """requête d'une autre page que l'app (CSRF), ou adressée à un autre nom que localhost (DNS rebinding)"""
        port = self.server.server_address[1]
        permis = {f"{h}:{port}" for h in HOTES}
        hote = self.headers.get("Host")
        if hote is not None and hote.strip().lower() not in permis:
            return True
        origine = self.headers.get("Origin")
        return methode == "POST" and origine is not None and origine.strip().lower() not in {
            f"http://{h}" for h in permis}

    def _traiter(self, methode: str):
        u = urlparse(self.path)
        if self._origine_refusee(methode):
            self.close_connection = True  # le corps éventuel n'est pas lu
            return self.repondre_erreur(403, "Requête refusée : elle ne vient pas de l'app.")
        try:
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if methode == "GET":
                self.get(u.path, q)
            elif u.path in packs_api.BRUTS:
                packs_api.post_brut(self, u.path, q, self.octets())
            else:
                self.post(u.path, self.corps())
        except (BrokenPipeError, ConnectionResetError):
            return
        except Refus as e:
            self.repondre_erreur(409, str(e))
        except EtatIllisible as e:
            self.repondre_erreur(409, str(e))
        except Occupe:
            self.repondre_erreur(409, OCCUPE)
        except json.JSONDecodeError:
            self.repondre_erreur(400, "Requête invalide : le corps n'est pas du JSON.")
        except Invalide as e:
            self.repondre_erreur(400, str(e))
        except ValueError as e:
            m = str(e)
            self.repondre_erreur(400, m if _est_francais(m) else f"Requête invalide : {m}")
        except KeyError as e:
            self.repondre_erreur(400, f"Requête invalide : il manque « {e.args[0] if e.args else '?'} ».")
        except FileNotFoundError as e:
            # nos 404 (sans nom de fichier) ont un message français complet ; une erreur du système (avec un
            # chemin) ne passe jamais telle quelle
            m = str(e)
            self.repondre_erreur(404, m if e.filename is None and _est_francais(m) else "Ce fichier est introuvable.")
        except Exception:
            self.app.journal_erreur(methode, self.path)
            self.repondre_erreur(500, MESSAGE_500)

    def repondre_erreur(self, code: int, message: str):
        try:
            self.erreur(code, message)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self._traiter("GET")

    def do_POST(self):
        self._traiter("POST")

    def _taille(self) -> int:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0:
            self.close_connection = True
            raise Invalide("Requête invalide : taille du corps incorrecte.")
        return n

    def octets(self) -> bytes:
        """corps brut (zip d'un pack, logo, police)"""
        n = self._taille()
        if n > packs_api.TAILLE_MAX:
            self.close_connection = True  # le corps n'est pas lu
            raise Invalide(f"Ce fichier est trop gros ({packs_api.TAILLE_MAX // (1024 * 1024)} Mo au plus).")
        return self.rfile.read(n)

    def corps(self) -> dict:
        n = self._taille()
        b = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(b, dict):
            raise Invalide("Requête invalide : le corps doit être un objet.")
        return b

    # ---- GET
    def get(self, chemin: str, q: dict):
        a = self.app
        if chemin == "/api/accueil":
            self.envoyer_json({"nom": a.nom(), "version": a.version(), "maj": a.etat_maj(),
                               "projets": self.cartes()})
        elif chemin == "/api/projet":
            a.assurer()
            d = a.pdir(q["id"])
            vues.importer_v1_si_besoin(d)
            if (d / "etat.json").exists():
                # projet d'avant les packs (copié pendant que l'app tourne) : repris ; packs modifiés pendant qu'il
                # était occupé : empreintes à jour. Occupé maintenant : la vue s'affiche, ce sera pour la prochaine fois
                try:
                    P.adopter_si_besoin(d, a.racine_packs, attente=ATTENTE_OUVERTURE,
                                        presets=a.racine_app / "presets")
                    P.synchroniser(d, a.racine_packs, attente=ATTENTE_OUVERTURE)
                except (Occupe, VerrouImpossible):
                    pass
            self.envoyer_json(vues.vue_projet(d, packs=a.racine_packs))
        elif chemin == "/api/packs" or chemin.startswith("/api/packs/"):
            packs_api.get(self, chemin, q)
        elif chemin == "/api/activite":
            a.assurer()
            self.envoyer_json(vues.vue_activite(a.racine_projets, a.battement, a.profil(),
                                                bool(commande_ia(a.config()))))
        elif chemin == "/api/media":
            d = a.pdir(q["projet"])
            if not medias.autorise(d, q["f"]):
                return self.erreur(403, "Ce fichier n'est pas accessible.")
            if not Path(q["f"]).is_file():
                raise FileNotFoundError("Ce fichier est introuvable.")
            medias.envoyer(self, q["f"])
        elif chemin == "/api/image_couleur":
            d = a.pdir(q["projet"])
            if q["cam"] not in ((lire_json(d / "projet.json", {}) or {}).get("cams") or {}):
                raise Invalide("Caméra inconnue.")
            p = json.loads(q.get("p") or "{}")
            if not isinstance(p, dict):
                raise Invalide("Réglages d'image invalides.")
            medias.envoyer(self, couleur.apercu_image(d, q["cam"], p))
        elif chemin == "/api/ecoute":
            d = a.pdir(q["projet"])
            if q["version"] not in ("avant", "apres"):
                raise Invalide("Version inconnue : avant ou apres.")
            f, debut = ecoute.apercu_son(d, q["version"], lire_etat(d)["son"]["reglages"])
            self.envoyer_json({"src": str(f), "debut": debut})
        elif chemin == "/api/image_rush":
            if q["f"] not in a.rushes_vus:
                return self.erreur(403, "Ce fichier n'est pas accessible.")
            medias.envoyer(self, rushes.image_rush(a.cache_rushes(), q["f"]), garder=True)
        elif chemin in ("/api/micro_rush", "/api/son_rush"):
            if q["f"] not in a.micros_vus:
                return self.erreur(403, "Ce fichier n'est pas accessible.")
            if chemin == "/api/micro_rush":
                self.envoyer_json(rushes.analyse_micro(a.cache_rushes(), q["f"]))
            else:
                medias.envoyer(self, rushes.son_micro(a.cache_rushes(), q["f"]), garder=True)
        elif chemin == "/api/casting":
            a.assurer()
            self.envoyer_json(vues.vue_casting(a.pdir(q["projet"])))
        elif chemin == "/api/niveaux":
            self.envoyer_json({"niveaux": ecoute.niveaux(a.pdir(q["projet"]))})
        elif chemin == "/api/transcript":
            d = a.pdir(q["projet"])
            pers = (lire_json(d / "projet.json", {}) or {}).get("personnes") or {}
            self.envoyer_json({"phrases": [
                {"a": p["a"], "b": p["b"], "qui": (pers.get(p["sp"]) or {}).get("nom") or str(p["sp"]).title(), "t": p["t"]}
                for p in transcript.phrases(d)]})
        else:
            self.statique(chemin)

    def cartes(self) -> list[dict]:
        out = []
        fs = sorted(self.app.racine_projets.glob("*/projet.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in fs:
            try:
                out.append(vues.vue_carte(f.parent))
            except Exception:  # un projet abîmé ne doit pas vider l'accueil
                self.app.journal_erreur("GET", f"/api/accueil ({f.parent.name})")
                out.append({"id": f.parent.name, "titre": f.parent.name, "cree": "", "personnes": "", "vignette": None,
                            "etape": "", "statuts": {}, "tache": None, "erreur": "Projet illisible : envoie un rapport."})
        return out

    def statique(self, chemin: str):
        if chemin.startswith("/api/"):
            raise FileNotFoundError("Cette adresse n'existe pas dans l'app.")
        web = (self.app.racine_app / "app" / "web").resolve()
        rel = "index.html" if chemin in ("", "/") else chemin.lstrip("/")
        f = (web / rel).resolve()
        if not web.is_dir():
            if chemin in ("", "/"):
                return self.envoyer_octets(PAGE_MINIMALE, "text/html; charset=utf-8")
            raise FileNotFoundError("Ce fichier est introuvable.")
        if web != f and web not in f.parents:
            return self.erreur(403, "Accès refusé.")
        if not f.is_file():
            raise FileNotFoundError("Ce fichier est introuvable.")
        type_ = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}.get(
            f.suffix.lower()) or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        b = f.read_bytes()
        if f == web / "index.html":
            b = (b.replace(b"{{NOM}}", html.escape(self.app.nom()).encode())
                 .replace(b"{{VERSION}}", html.escape(self.app.version()).encode()))
        elif f == web / "style.css":
            b = b.replace(ACCENT_DEFAUT, self.app.accent().encode())
        self.envoyer_octets(b, type_ + ("; charset=utf-8" if type_.startswith("text/") else ""))

    # ---- POST
    def post(self, chemin: str, b: dict):
        a = self.app
        if chemin == "/api/action":
            d = a.pdir(b["projet"])
            action = b["action"]
            if isinstance(action, dict) and action.get("type") == "ajouter_short" and "a" in action and "b" in action:
                action = {"type": "ajouter_short", "spec": creation.short_depuis_texte(d, float(action["a"]), float(action["b"]))}
            actions.executer(d, action, packs=a.racine_packs)
            a.assurer(forcer=True)
            r = {"ok": True, "projet": vues.vue_projet(d, packs=a.racine_packs)}
            if isinstance(action, dict) and action.get("type") in ACTIONS_CASTING:
                r["casting"] = vues.vue_casting(d)
            self.envoyer_json(r)
        elif chemin == "/api/tache":
            self.tache(a.pdir(b["projet"]), b["id"], b["geste"])
            a.assurer(forcer=True)
            self.envoyer_json({"ok": True})
        elif chemin == "/api/choisir_dossier":
            dossier = self.choisir_dossier()
            self.envoyer_json({"dossier": dossier, **(a.scanner(dossier) if dossier else {"fichiers": [], "identiques": []})})
        elif chemin == "/api/choisir_lut":
            self.envoyer_json({"lut": self.choisir_lut()})
        elif chemin == "/api/scanner":
            self.envoyer_json(a.scanner(b["dossier"]))
        elif chemin in ("/api/creer", "/api/creer_dossier"):
            pack = a.pack_creation(b.get("pack"))  # vérifié AVANT de créer quoi que ce soit
            creer = creation.creer_projet if chemin == "/api/creer" else creation.creer_depuis_dossier
            pid = creer(a.racine_projets, b)
            P.choisir(a.racine_projets / pid, a.racine_packs, pack)
            a.assurer(forcer=True)
            self.envoyer_json({"ok": True, "projet": pid})
        elif chemin.startswith("/api/packs/"):
            packs_api.post(self, chemin, b)
        elif chemin == "/api/casting/verifier":
            self.envoyer_json(casting.verification(a.pdir(b["projet"]), self._texte(b, "micro")))
        elif chemin == "/api/casting/boucle":
            self.envoyer_json({"src": str(casting.boucle(a.pdir(b["projet"]), self._texte(b, "camera")))})
        elif chemin == "/api/apercu_passage":
            self.envoyer_json({"src": str(self.apercu_passage(a.pdir(b["projet"]), b["id"]))})
        elif chemin == "/api/harmoniser":
            self.envoyer_json({"gains": couleur.harmoniser(a.pdir(b["projet"]))})
        elif chemin == "/api/ouvrir":
            cible = b.get("cible", "")
            self.ouvrir(a.racine_app / "rapports" if cible == "rapports"
                        else self.dossier_projet(a.pdir(b["projet"]), cible, b.get("nom")))
            self.envoyer_json({"ok": True})
        elif chemin == "/api/rapport":
            pid = b.get("projet")
            projet = a.pdir(pid).name if pid else None
            self.envoyer_json({"fichier": str(rapport.creer_rapport(a.racine_app, a.racine_projets, projet))})
        else:
            raise FileNotFoundError("Cette adresse n'existe pas dans l'app.")

    @staticmethod
    def _texte(b: dict, cle: str) -> str:
        v = b[cle]
        if not isinstance(v, str) or not v:
            raise Invalide(f"Requête invalide : « {cle} » doit être un identifiant.")
        return v

    def tache(self, d: Path, tid, geste):
        if not isinstance(tid, str) or not ID_TACHE.match(tid):
            raise Invalide("Identifiant de tâche invalide.")
        t = file.lire(d, tid)
        if t is None:
            raise FileNotFoundError("Cette tâche est introuvable.")
        if geste == "annuler" and t.get("statut") == "echec":
            (file.dossier(d) / f"{tid}.remplacee").touch()  # échec laissé tombé : il ne compte plus, nulle part
        elif geste == "annuler":
            file.demander_annulation(d, tid)
        elif geste == "reessayer":
            if t.get("statut") != "echec":
                raise Refus("Seule une tâche en échec peut être relancée.")
            if (file.dossier(d) / f"{tid}.remplacee").exists():
                raise Refus("Cette tâche a déjà été relancée.")
            file.creer(d, t["type"], t.get("params"))
            (file.dossier(d) / f"{tid}.remplacee").touch()
        else:
            raise Invalide("Geste inconnu : annuler ou réessayer.")

    def apercu_passage(self, d: Path, pid) -> Path:
        passage = next((p for p in (lire_etat(d)["episode"]["passages"] or []) if str(p["id"]) == str(pid)), None)
        if passage is None:
            raise FileNotFoundError("Ce passage est introuvable.")
        a, b = passage["a"], passage["b"]
        out = apercus.chemin_apercu_passage(d, a, b)
        if not out.exists():
            pj = lire_json(d / "projet.json", {}) or {}
            sync = (lire_json(d / "sync.json", {}) or {}).get("cams", {})
            out.parent.mkdir(exist_ok=True)
            tmp = out.with_name(f"{out.stem}.{uuid.uuid4().hex[:6]}.tmp.mp4")
            try:
                _lancer(apercus.commande_apercu_passage(d, pj, sync, a, b, tmp, encodeur("apercu", self.app.profil())),
                        check=True, capture_output=True, stdin=subprocess.DEVNULL)
                os.replace(tmp, out)
            finally:
                tmp.unlink(missing_ok=True)
        return out

    def choisir_dossier(self) -> str | None:
        if systeme() == "darwin":
            r = _lancer(["osascript", "-e", 'POSIX path of (choose folder with prompt "Choisis le dossier qui contient '
                         'les rushes (micros et caméras)")'], capture_output=True, text=True)
        else:  # Windows / Linux : fenêtre tkinter dans un sous-processus (écrit, testé au lot Windows)
            r = _lancer([sys.executable, "-c", "import tkinter, tkinter.filedialog as f; t = tkinter.Tk(); t.withdraw(); "
                         "t.attributes('-topmost', True); print(f.askdirectory(title='Choisis le dossier des rushes'))"],
                        capture_output=True, text=True)
        if r.returncode != 0:
            return None
        return r.stdout.strip().rstrip("/\\") or None

    def choisir_lut(self) -> str | None:
        """fenêtre du système pour choisir un fichier LUT ; None si annulée ; refus clair si ce n'est pas un .cube"""
        if systeme() == "darwin":
            r = _lancer(["osascript", "-e", 'POSIX path of (choose file with prompt "Choisis un fichier LUT (.cube)")'],
                        capture_output=True, text=True)
        else:  # Windows / Linux : fenêtre tkinter dans un sous-processus, comme choisir_dossier
            r = _lancer([sys.executable, "-c", "import tkinter, tkinter.filedialog as f; t = tkinter.Tk(); t.withdraw(); "
                         "t.attributes('-topmost', True); print(f.askopenfilename(title='Choisis un fichier LUT (.cube)', "
                         "filetypes=[('LUT', '*.cube'), ('Tous les fichiers', '*')]))"],
                        capture_output=True, text=True)
        if r.returncode != 0:
            return None
        f = r.stdout.strip()
        if not f:
            return None
        if not f.lower().endswith(".cube"):
            raise Invalide("Ce fichier n'est pas une LUT. Choisis un fichier qui finit par .cube.")
        return f

    @staticmethod
    def dossier_projet(d: Path, cible: str, nom=None) -> Path:
        """dossier du projet à ouvrir ; « livraison » = un dossier daté précis, forcément DANS EXPORT/"""
        if cible != "livraison":
            return d / CIBLES[cible] if cible in CIBLES else d
        export = (d / "EXPORT").resolve()
        p = (export / nom).resolve() if isinstance(nom, str) and nom else None
        if p is None or p.parent != export or not p.is_dir():
            raise Invalide("Cette livraison est introuvable. Ouvre le dossier des livraisons.")
        return p

    def ouvrir(self, p: Path):
        p.mkdir(exist_ok=True)
        s = systeme()
        if s == "darwin":
            _lancer(["open", str(p)])
        elif s.startswith("win"):
            os.startfile(str(p))  # noqa: S606
        else:
            _lancer(["xdg-open", str(p)])


def creer_serveur(app: Application, port: int = 8765) -> ThreadingHTTPServer:
    app.preparer_packs()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Gestionnaire)
    srv.daemon_threads = True
    srv.app = app
    app.assurer(forcer=True)
    return srv


def lancer(port: int = 8765, racine_app=RACINE, racine_projets=None):
    app = Application(racine_app=racine_app, racine_projets=racine_projets)
    srv = creer_serveur(app, port)
    print(f"Montage Podcast : http://localhost:{srv.server_address[1]}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    lancer(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
