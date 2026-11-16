"""Musique et bruitages du teaser, composés par code (pas de droits, calés à l'image sur les coupes).

- musique rythmée qui fait monter la curiosité (ré mineur, Rém - Sib - Fa - Do, 124 bpm) : tic-tac +
  arpège filtré dès le début, le filtre s'ouvre tout du long, basse et kick au 2e extrait, kick à chaque
  temps + clap à mi-parcours, roulement final ; coupée net juste avant chaque transition ;
- bruitages : descente grave à l'ouverture, whoosh d'air qui suit le glissé de chaque transition (pas de
  sifflement « sabre laser »), clic d'obturateur discret sur les coupes internes, coup sourd sur chaque
  mot clé, obturateur + gros impact final avant l'intro.
Deux WAV stéréo 48 kHz séparés pour doser dans Premiere.
"""
import numpy as np
import soundfile as sf
from scipy.signal import butter, fftconvolve, sosfilt

SR = 48000
rng = np.random.default_rng(7)


def hz(n):
    return 440 * 2 ** ((n - 69) / 12)


def lp(x, f, o=2):
    return sosfilt(butter(o, f, "low", fs=SR, output="sos"), x)


def hp(x, f, o=2):
    return sosfilt(butter(o, f, "high", fs=SR, output="sos"), x)


def bp(x, f0, f1):
    return sosfilt(butter(2, [f0, f1], "band", fs=SR, output="sos"), x)


def saw(f, n, ph=0.0):
    t = np.arange(n) / SR
    return 2 * ((f * t + ph) % 1) - 1


def reverb(x, sec=1.8, mix=0.35):
    n = int(sec * SR)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / SR * 4.5 / sec)
    ir = lp(ir, 5000)
    wet = fftconvolve(x, ir)[: len(x)]
    wet *= np.sqrt(np.mean(x ** 2) / (np.mean(wet ** 2) + 1e-12))
    return (1 - mix) * x + mix * wet


def sweep_noise(n, f0, f1, up=True):
    """bruit filtré dont la bande glisse de f0 à f1 (montée ou whoosh)"""
    x = rng.standard_normal(n)
    out = np.zeros(n)
    k = 1024
    for i in range(0, n, k):
        p = i / n
        f = f0 * (f1 / f0) ** p
        seg = x[max(0, i - 2048): i + k]
        y = bp(seg, f * 0.7, min(f * 1.4, SR / 2 - 100))
        out[i: i + k] = y[-len(out[i: i + k]):]
    return out


def place(buf, x, t, gain=1.0):
    i = int(t * SR)
    if i < 0:
        x, i = x[-i:], 0
    j = min(len(buf), i + len(x))
    if j > i:
        buf[i:j] += gain * x[: j - i]


def boom(big=False):
    n = int((2.2 if big else 1.3) * SR)
    t = np.arange(n) / SR
    f = 38 + 70 * np.exp(-t * 9)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * (1.6 if big else 2.6))
    click = hp(rng.standard_normal(n), 2000) * np.exp(-t * 60) * 0.25
    return reverb(np.tanh(1.6 * body) + click, 2.5 if big else 1.4, 0.3)


def whoosh(dur=0.55):
    n = int(dur * SR)
    t = np.linspace(0, 1, n)
    x = sweep_noise(n, 4000, 300) * np.sin(np.pi * t) ** 1.5
    return reverb(x / (np.abs(x).max() + 1e-9), 1.0, 0.25)


def riser(dur=0.9):
    n = int(dur * SR)
    t = np.linspace(0, 1, n)
    x = sweep_noise(n, 300, 6000) * t ** 2.2
    tone = np.sin(2 * np.pi * np.cumsum(200 + 600 * t ** 2) / SR) * t ** 3 * 0.3
    x = x / (np.abs(x).max() + 1e-9) + tone
    return x


def key_hit():
    """mot clé : petit coup sourd + scintillement métallique, discret sous la voix"""
    n = int(0.9 * SR)
    t = np.arange(n) / SR
    thump = np.sin(2 * np.pi * np.cumsum(60 + 90 * np.exp(-t * 40)) / SR) * np.exp(-t * 14)
    return reverb(thump, 0.8, 0.25)


def sub_drop():
    n = int(1.8 * SR)
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * np.cumsum(90 * np.exp(-t * 1.4) + 30) / SR) * np.minimum(1, t / 0.02) * np.exp(-t * 1.8)


def kick():
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    f = 45 + 110 * np.exp(-t * 30)
    return np.tanh(2 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7))


def hat(open_=False):
    n = int((0.12 if open_ else 0.04) * SR)
    t = np.arange(n) / SR
    return hp(rng.standard_normal(n), 7000) * np.exp(-t * (25 if open_ else 110))


CHORDS = [[50, 53, 57, 62], [46, 50, 53, 58], [53, 57, 60, 65], [48, 52, 55, 60]]  # Rém Sib Fa Do


def shutter(soft=False):
    """obturateur d'appareil photo : 2 clics mécaniques (ouverture / fermeture) à ~70 ms d'écart"""
    n = int(0.2 * SR)
    out = np.zeros(n)
    t = np.arange(int(0.05 * SR)) / SR

    def clic(ring, low, g):
        burst = bp(rng.standard_normal(len(t)), 1800, 9000) * np.exp(-t * 900)
        metal = np.sin(2 * np.pi * ring * t) * np.exp(-t * 180) * 0.35
        thunk = np.sin(2 * np.pi * low * t) * np.exp(-t * 120) * 0.6
        return g * (burst + metal + thunk)

    place(out, clic(3300, 160, 1.0), 0)
    if not soft:
        place(out, clic(2700, 130, 0.8), 0.072)
        place(out, bp(rng.standard_normal(int(0.06 * SR)), 3000, 8000) * 0.05, 0.01)  # petit frottement du rideau
    return reverb(out, 0.25, 0.12)


def air_whoosh(direction, rise=0.32, fall=0.26):
    """whoosh d'air (pas de sifflement tonal) qui traverse l'image dans le sens du glissé : stéréo (n, 2),
    culmine sur la coupe (à rise secondes du début)."""
    n = int((rise + fall) * SR)
    t = np.arange(n) / SR
    env = np.where(t < rise, (t / rise) ** 2.5, np.exp(-(t - rise) / fall * 4))
    x = rng.standard_normal(n)
    out = np.zeros(n)
    k = 512
    for i in range(0, n, k):  # filtre passe-bas qui s'ouvre avec la vitesse (sombre -> clair -> sombre)
        f = 350 + 4500 * env[min(i + k // 2, n - 1)] ** 1.5
        seg = x[max(0, i - 2048): i + k]
        out[i: i + k] = lp(seg, f)[-len(out[i: i + k]):]
    out *= env
    out += 0.4 * lp(rng.standard_normal(n), 180) * env  # souffle grave
    pan = np.clip(0.5 + direction * 0.45 * np.tanh((t - rise) / 0.15), 0, 1)  # traverse gauche <-> droite
    return np.stack([out * np.sqrt(1 - pan), out * np.sqrt(pan)], 1)


def tick(accent):
    """tic d'horloge : bois sec, fait monter la curiosité"""
    n = int(0.06 * SR)
    t = np.arange(n) / SR
    f = 1900 if accent else 1500
    return (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 2.7 * t)) * np.exp(-t * 90) \
        + bp(rng.standard_normal(n), 2000, 6000) * np.exp(-t * 300) * 0.3


def clap():
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    env = sum(np.exp(-np.maximum(t - d, 0) * 60) * (t >= d) for d in (0, 0.011, 0.022))
    return bp(rng.standard_normal(n), 900, 3500) * env * 0.6


def snare():
    n = int(0.18 * SR)
    t = np.arange(n) / SR
    return bp(rng.standard_normal(n), 1500, 7000) * np.exp(-t * 35) + np.sin(2 * np.pi * 190 * t) * np.exp(-t * 40) * 0.5


BPM = 124
BEAT = 60 / BPM
ARP = [0, 2, 1, 3, 2, 1, 3, 2]  # ordre des notes de l'accord en doubles croches


def music(total, trans):
    """Ambiance rythmée qui monte : tic-tac + arpège filtré dès le début, puis basse et kick,
    puis kick à chaque temps + clap, roulement de caisse claire à la fin. Trou bref avant chaque transition."""
    n = int(total * SR)
    pad, arp, bass, drums = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
    bar = 4 * BEAT
    s16 = BEAT / 4
    t1 = trans[0] if trans else total * 0.2           # entrée basse + kick
    t2 = trans[len(trans) // 2] if trans else total * 0.55  # kick à chaque temps + clap
    roll = total - 2 * bar                            # roulement final
    # nappe discrète
    for ci, t0 in enumerate(np.arange(0, total, 2 * bar)):
        m = int(2 * bar * SR) + int(0.5 * SR)
        env = np.minimum(1, np.arange(m) / (0.3 * SR)) * np.minimum(1, (m - np.arange(m)) / (0.4 * SR))
        x = sum(saw(hz(note) * d, m, rng.random()) for note in CHORDS[ci % 4][:3] for d in (0.997, 1.003))
        place(pad, x * env, t0)
    pad = reverb(lp(pad, 700), 2.5, 0.45)
    # arpège pincé en doubles croches, le filtre s'ouvre tout au long du teaser (la tension monte)
    for k, t0 in enumerate(np.arange(0, total, s16)):
        chord = CHORDS[int(t0 // (2 * bar)) % 4]
        note = chord[ARP[k % 8]] + 12
        m = int(0.16 * SR)
        x = saw(hz(note), m) * np.exp(-np.arange(m) / SR * 22)
        place(arp, x * (1.0 if k % 4 == 0 else 0.7), t0)
    prog = np.linspace(0, 1, n) ** 1.3
    arp = (1 - prog) * lp(arp, 700) + prog * lp(arp, 3500)
    arp = reverb(arp, 0.9, 0.3) * (0.55 + 0.45 * prog)
    # basse pulsée en croches
    for t0 in np.arange(t1, total, BEAT / 2):
        root = CHORDS[int(t0 // (2 * bar)) % 4][0] - 12
        m = int(BEAT / 2 * SR)
        e = np.exp(-np.arange(m) / SR * 8)
        place(bass, (np.sin(2 * np.pi * hz(root) * np.arange(m) / SR) + 0.35 * lp(saw(hz(root), m), 500)) * e, t0)
    # batterie
    for k, t0 in enumerate(np.arange(0, total, s16)):
        b16 = k % 16
        if k % 2 == 0:
            place(drums, tick(b16 % 4 == 0), t0, 0.16 if t0 < t1 else 0.1)
        if t0 >= t1 and t0 < roll:
            if (b16 in (0, 8)) or (t0 >= t2 and b16 % 4 == 0):
                place(drums, kick(), t0, 0.9)
            if t0 >= t2 and b16 in (4, 12):
                place(drums, clap(), t0, 0.55)
            if b16 % 2 == 1:
                place(drums, hat(), t0, 0.1)
            if t0 >= t2 and b16 % 4 == 2:
                place(drums, hat(True), t0, 0.12)
        if t0 >= roll:  # roulement : doubles croches puis triples, crescendo
            p = (t0 - roll) / (total - roll)
            place(drums, snare(), t0, 0.15 + 0.5 * p)
            if p > 0.5:
                place(drums, snare(), t0 + s16 / 2, 0.15 + 0.5 * p)
            if k % 4 == 0:
                place(drums, kick(), t0, 0.8)
    mix = 0.12 * pad / (np.abs(pad).max() + 1e-9) * 2 + 0.25 * arp / (np.abs(arp).max() + 1e-9) * 2 \
        + 0.35 * bass + 0.5 * drums
    # trou bref avant chaque transition : le clic de l'obturateur tombe dans le silence
    gate = np.ones(n)
    f = int(0.02 * SR)
    for t in trans:
        a, b = int((t - 0.14) * SR), int(t * SR)
        gate[max(0, a): b] = 0
        gate[max(0, a - f): max(0, a)] *= np.linspace(1, 0, min(f, max(0, a)))
    end = max(0, n - int(0.2 * SR))
    gate[end:] = 0
    gate[max(0, end - f): end] *= np.linspace(1, 0, min(f, end))
    return stereo(mix * gate, 0.3)


KEY_GAIN = 0.25  # impact sur les mots clés (spec « bruitages_mots »)


def sfx(total, trans, cuts, keys=(), dirs=(), whooshes=()):
    """whooshes : [(temps, sens)] en plus des transitions (ex. entrée de la carte invité dans l'intro)"""
    n = int((max([total + 2.5] + [w + 1.0 for w, _ in whooshes])) * SR)  # l'impact final déborde sur l'intro
    out = np.zeros(n)
    place(out, sub_drop(), 0, 0.5)
    for t in keys:
        if all(abs(t - x) > 0.4 for x in trans):  # pas par-dessus une transition
            place(out, key_hit(), t, KEY_GAIN)
    for t in trans:
        place(out, kick(), t, 0.2)  # un peu de poids dans le grave sous le whoosh
    for t in cuts:  # coupe sèche à l'intérieur d'un extrait : clic d'obturateur discret
        place(out, shutter(soft=True), t - 0.01, 0.4)
    place(out, shutter(), total - 0.03, 1.0)
    place(out, boom(True), total, 0.8)
    st = stereo(out, 0.15)
    # glissés : whoosh d'air qui suit le sens de l'image
    for t, d in list(zip(trans, dirs or [1] * len(trans))) + list(whooshes):
        w = air_whoosh(d)
        i = int((t - 0.32) * SR)
        st[i: i + len(w)] += 0.9 * w[: len(st) - i]
    return st


def stereo(x, width):
    """élargit un signal mono avec un léger décalage gauche/droite"""
    d = int(0.011 * SR)
    r = np.concatenate([np.zeros(d), x[:-d]])
    return np.stack([x + width * (x - r), x - width * (x - r) * 0.5 + width * 0.5 * r], 1)


def write(path, x, peak_db):
    x = x / (np.abs(x).max() + 1e-9) * 10 ** (peak_db / 20)
    sf.write(path, x.astype(np.float32), SR, subtype="PCM_24")


def render(total, trans, cuts, keys, out_music, out_sfx, dirs=(), whooshes=()):
    """out_music=None : la musique vient d'une piste existante (voir teaser.music_from_track)"""
    if out_music:
        write(out_music, music(total, trans), -23)  # déjà dosée sous une voix à -16 LUFS
    write(out_sfx, sfx(total, trans, cuts, keys, dirs, whooshes), -13)
