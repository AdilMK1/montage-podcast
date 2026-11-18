"""Hésitations (« euh », voyelles traînées) à retirer des shorts.

Whisper efface les « euh » du transcript : on les retrouve dans le son (voyelle voisée, tenue, timbre stable
au moins 0,22 s), puis chaque coupe candidate est validée en retranscrivant la zone avec et sans elle :
la coupe n'est gardée que si aucun mot ne disparaît. Résultats mis en cache (dossier du projet)."""
import json
import re
from pathlib import Path

import numpy as np
import soundfile as sf

MIN_DUREE = 0.22   # voyelle tenue minimale (s)
GARDE = 0.04       # on garde un peu du début / de la fin de la voyelle (attaque, chute naturelles)
FENETRE = 2.0      # contexte retranscrit de part et d'autre (s)
SR = 16000


def _lire(path, a, b):
    f = sf.SoundFile(path)
    f.seek(max(0, int(a * f.samplerate)))
    x = f.read(max(1, int((b - a) * f.samplerate)), dtype="float32", always_2d=True).mean(1)
    if f.samplerate != SR:
        import librosa
        x = librosa.resample(x, orig_sr=f.samplerate, target_sr=SR)
    return x


def candidats(path, a, b):
    """plages (temps micro) où la voix tient une voyelle stable : « euh » probables"""
    import librosa
    x = _lire(path, a, b)
    if len(x) < SR // 2:
        return []
    hop = 160
    f0, voise, _ = librosa.pyin(x, fmin=70, fmax=400, sr=SR, frame_length=1024, hop_length=hop)
    L = librosa.power_to_db(librosa.feature.melspectrogram(y=x, sr=SR, n_fft=512, hop_length=hop, n_mels=40))
    flux = np.r_[0, np.sqrt((np.diff(L, axis=1) ** 2).mean(0))]
    db = 20 * np.log10(librosa.feature.rms(y=x, frame_length=512, hop_length=hop)[0] + 1e-9)
    n = min(len(f0), len(flux), len(db))
    cents = np.r_[0, np.abs(np.diff(1200 * np.log2(np.nan_to_num(f0[:n], nan=1.0) + 1e-9)))]
    stable = voise[:n] & (flux[:n] < 3.0) & (db[:n] > db.max() - 35) & (cents < 60)
    out, s = [], None
    for i, v in enumerate(list(stable) + [False]):
        if v and s is None:
            s = i
        elif not v and s is not None:
            if (i - s) * hop / SR >= MIN_DUREE:
                out.append((a + s * hop / SR, a + i * hop / SR))
            s = None
    return out


def _mots(x):
    import whisper_local
    t = whisper_local.transcrire(x, temperatures=(0.0,))["text"].lower()
    t = re.sub(r"\b(euh|heu|hum|hmm|bah|ben)\b", " ", t)
    return re.findall(r"[a-zàâçéèêëîïôûùüÿœæ0-9]+", t)


def _sans_perte(path, c0, c1):
    """la coupe [c0, c1] ne fait disparaître aucun mot ?"""
    a, b = c0 - FENETRE, c1 + FENETRE
    x = _lire(path, a, b)
    i0, i1 = int((c0 - a) * SR), int((c1 - a) * SR)
    fd = int(0.01 * SR)
    y = np.concatenate([x[:i0], x[i1:]])
    if i0 > fd and len(y) > i0 + fd:  # fondu comme au rendu
        y[i0 - fd:i0] *= np.linspace(1, 0, fd)
        y[i0:i0 + fd] *= np.linspace(0, 1, fd)
    avant, apres = _mots(x), _mots(y)
    return avant == apres and len(avant) > 0


def _place_libre(c0, c1, mots):
    """le transcript laisse-t-il la place d'un « euh » ici ? Whisper étire le mot voisin sur l'hésitation :
    un mot qui chevauche la coupe doit durer nettement plus que sa durée normale (sinon on couperait dans le mot)"""
    for txt, w0, w1 in mots or []:
        o = min(c1, w1) - max(c0, w0)
        if o <= 0.02:
            continue
        lettres = len(re.findall(r"\w", txt))
        normal = 0.06 * lettres + 0.10
        if (w1 - w0) - normal < 0.8 * o:
            return False
    return True


def hesitations(path, a, b, cache_dir=None, mots=None):
    """coupes validées [(début, fin)] dans [a, b] (temps micro) ; mots = [(texte, début, fin)] du transcript"""
    cache_f = Path(cache_dir) / "euh_cache.json" if cache_dir else None
    cache = json.loads(cache_f.read_text()) if cache_f and cache_f.exists() else {}
    cle = f"{Path(path).name}|{a:.2f}|{b:.2f}|v2"
    if cle in cache:
        return [tuple(c) for c in cache[cle]]
    ok = []
    for c0, c1 in candidats(path, a, b):
        c0, c1 = c0 + GARDE, c1 - GARDE
        if c1 - c0 >= 0.12 and _place_libre(c0, c1, mots) and _sans_perte(path, c0, c1):
            ok.append((round(c0, 3), round(c1, 3)))
    if cache_f:
        cache[cle] = ok
        cache_f.write_text(json.dumps(cache, indent=1))
    return ok
