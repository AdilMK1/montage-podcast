"""Lance un sous-processus (ffmpeg ou script du moteur), suit son avancement, l'arrête proprement.

- ffmpeg : passer total_s ; la commande doit contenir « -progress pipe:1 -nostats » (lu sur la sortie standard).
- script du moteur : passer fichier_progres ; le script y écrit son avancement (variable MONTAGE_PROGRES).
- rappel(fraction | None, vivant) est appelé à chaque pas ; vivant = la progression a bougé ou le journal a grossi.
- arret (threading.Event) : s'il est déclenché, le processus ET ses enfants sont tués, puis Arrete est levée.
- au_lancement(p) est appelé juste après le lancement : l'atelier y note signature(p.pid) dans la tâche, pour
  que tuer_orphelin() puisse tuer le rendu laissé par un atelier mort brutalement.
Le processus a son propre groupe (on tue toute la famille) et garde la priorité normale ; sous Windows, il est
lancé sans fenêtre. Lot Windows : rattacher chaque rendu à un Job Object « kill on close » pour qu'il meure
avec l'atelier (aujourd'hui, c'est la reprise qui tue les rendus orphelins).
"""
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

import psutil

from .progression import blocs_progres, fraction_ffmpeg, lire_fichier_progres


class Arrete(Exception):
    """la tâche a été arrêtée (annulation, relance, place cédée)"""


def _groupe() -> dict:
    """propre groupe de processus (toute la famille tuée d'un coup), sans fenêtre sous Windows"""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def _pgid(p: subprocess.Popen) -> int:
    """groupe noté au lancement ; à défaut, le pid (start_new_session : le chef est le groupe)"""
    return getattr(p, "pgid", None) or p.pid


def tuer(p: subprocess.Popen, delai: float = 3.0):
    """arrête toute la famille : SIGTERM au groupe, puis SIGKILL au groupe dans tous les cas (un enfant qui ignore
    SIGTERM, ou resté seul après la sortie du chef, ne survit pas)"""
    if os.name == "nt":
        if p.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        pgid = _pgid(p)
        if p.poll() is None:
            try:
                os.killpg(pgid, signal.SIGTERM)
                p.wait(delai)
            except (ProcessLookupError, PermissionError, subprocess.TimeoutExpired):
                pass
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        p.wait(10)
    except subprocess.TimeoutExpired:
        pass


def signature(pid: int) -> dict | None:
    """pid + heure de création : reconnaît ce processus même si son pid est réutilisé plus tard"""
    try:
        return {"pid": pid, "cree": psutil.Process(pid).create_time()}
    except psutil.Error:
        return None


def _mort(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.Error:
        return True


def tuer_orphelin(sig: dict | None, delai: float = 5.0) -> bool:
    """tue le processus noté par signature() et toute sa famille, s'il tourne encore ; True s'il a été tué"""
    if not sig:
        return False
    try:
        proc = psutil.Process(sig["pid"])
        if abs(proc.create_time() - sig["cree"]) > 0.01:
            return False  # pid réutilisé par un autre programme : on n'y touche pas
    except (psutil.Error, KeyError, TypeError):
        return False
    pid = sig["pid"]
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:
            if os.getpgid(pid) == pid:  # chef de son propre groupe (lancé par executer) : toute la famille
                os.killpg(pid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return False
    t0 = time.time()
    while not _mort(pid) and time.time() - t0 < delai:
        time.sleep(0.05)
    return True


def executer(cmd, journal, *, total_s=None, fichier_progres=None, rappel=None, arret=None, env=None, cwd=None,
             pas: float = 0.5, au_lancement=None) -> int:
    journal = Path(journal)
    journal.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **(env or {})}
    if fichier_progres:
        env["MONTAGE_PROGRES"] = str(fichier_progres)
        Path(fichier_progres).unlink(missing_ok=True)
    etat = {"fraction": None, "change": False}
    fil_lecteur = None
    with open(journal, "ab") as j:
        p = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE if total_s else j, stderr=j,
                             stdin=subprocess.DEVNULL, env=env, cwd=cwd, **_groupe())
        if os.name != "nt":
            try:
                p.pgid = os.getpgid(p.pid)  # mémorisé : tuer() vise le groupe même après la sortie du chef
            except OSError:
                p.pgid = p.pid
        if au_lancement is not None:
            try:
                au_lancement(p)
            except BaseException:
                tuer(p)
                raise
        if total_s:
            def lecteur():
                for bloc in blocs_progres(l.decode("utf-8", "replace") for l in p.stdout):
                    f = fraction_ffmpeg(bloc, total_s)
                    if f is not None and f != etat["fraction"]:
                        etat["fraction"], etat["change"] = f, True
            fil_lecteur = threading.Thread(target=lecteur, daemon=True)
            fil_lecteur.start()
        taille = journal.stat().st_size
        try:
            while p.poll() is None:
                if arret is not None:
                    if arret.wait(pas):
                        tuer(p)
                        raise Arrete()
                else:
                    time.sleep(pas)
                if fichier_progres:
                    f = lire_fichier_progres(fichier_progres)
                    if f is not None and f != etat["fraction"]:
                        etat["fraction"], etat["change"] = f, True
                t2 = journal.stat().st_size
                vivant = etat["change"] or t2 != taille
                taille, etat["change"] = t2, False
                if rappel:
                    rappel(etat["fraction"], vivant)
            if fil_lecteur is not None:
                fil_lecteur.join(timeout=2)  # le lecteur traite le dernier bloc (progress=end) avant le rappel final
            if fichier_progres:  # dernière valeur écrite juste avant la fin du script
                f = lire_fichier_progres(fichier_progres)
                if f is not None:
                    etat["fraction"] = f
            if rappel:
                rappel(etat["fraction"], True)
        except BaseException:
            tuer(p)
            raise
    return p.returncode
