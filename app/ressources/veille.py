"""Empêche l'ordinateur de se mettre en veille tant qu'une tâche tourne.

Mac : caffeinate (s'arrête tout seul si l'atelier meurt, grâce à -w <pid>). Windows : SetThreadExecutionState
(à appeler depuis le même fil ; lot 2 pour les essais réels). Autres systèmes : rien.
"""
import os
import platform
import subprocess

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


class AntiVeille:
    def __init__(self, lancer=subprocess.Popen, systeme: str | None = None):
        self._lancer, self._systeme = lancer, systeme or platform.system()
        self._proc, self.actif = None, False

    def activer(self):
        if self._systeme == "Darwin":
            if self.actif and self._proc is not None and self._proc.poll() is None:
                return
            # premier appel, ou caffeinate mort entre-temps (tué, plantage) : on le relance
            self._proc = self._lancer(["caffeinate", "-ims", "-w", str(os.getpid())],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.actif = True
        elif self._systeme == "Windows":
            if self.actif:
                return
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            self.actif = True

    def relacher(self):
        if not self.actif:
            return
        if self._systeme == "Darwin" and self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(5)  # ramassé : pas de processus zombie
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            self._proc = None
        elif self._systeme == "Windows":
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        self.actif = False
