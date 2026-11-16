"""Habillage de l'intro façon référence (l'émission de référence) : B-roll et carte de présentation de l'invité.

- B-roll : extrait d'une vidéo libre de droits (Mixkit), recadré 16/9, ramené à 25 i/s, avec un léger
  zoom avant, en ProRes 1080p (Premiere l'agrandit sur la séquence 4K) ;
- carte invité : fond vert de la marque, photo de l'invité détourée en noir et blanc avec un contour
  blanc façon autocollant, nom en Oswald qui s'écrit lettre par lettre, entrée par une lumière chaude
  (light leak). Vidéo 4K ProRes 4444 avec transparence (l'entrée laisse voir le plan d'avant).
"""
import subprocess
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).parent
W, H = 3840, 2160
TEAL = (14, 157, 138)
OSWALD = ROOT / "fonts" / "Oswald.ttf"
LATO = ROOT / "fonts" / "Lato-Regular.ttf"


# ---------- B-roll ----------

def broll_clip(src, start, dur, out, fps=25, push=0.06):
    """Extrait [start, start+dur] de src -> ProRes 1080p 25 i/s avec un zoom avant lent (push).
    Le zoom est calculé au sous-pixel (OpenCV) : le zoompan de ffmpeg arrondit au pixel et fait vibrer l'image."""
    n = round(dur * fps)
    # 24 i/s ou 23,976 -> on accélère un peu (4 %) plutôt que de dupliquer des images ; 50/60 -> on en saute
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                        "-of", "csv=p=0", str(src)], capture_output=True, text=True).stdout.strip()
    a, b = map(int, r.split("/"))
    sf = a / b
    speed = fps / sf if sf < fps else 1.0
    w, h = 1920, 1080
    vf = (f"setpts=PTS/{speed:.5f}," if speed != 1 else "") + f"fps={fps}," \
         f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}"
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-i", str(src), "-frames:v", str(n), "-an",
                            "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb48le", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb48le", "-s", f"{w}x{h}",
                            "-r", str(fps), "-i", "-", "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le",
                            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", str(out)],
                           stdin=subprocess.PIPE)
    for k in range(n):
        buf = dec.stdout.read(w * h * 6)
        if len(buf) < w * h * 6:
            break
        z = 1 + push * k / max(n - 1, 1)
        m = np.float32([[z, 0, (1 - z) * w / 2], [0, z, (1 - z) * h / 2]])
        img = np.frombuffer(buf, np.uint16).reshape(h, w, 3)
        enc.stdin.write(cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT).tobytes())
    dec.stdout.close()
    dec.wait()
    enc.stdin.close()
    enc.wait()
    return out


# ---------- carte invité ----------

def cutout(photo, out_png):
    """Détoure l'invité (rembg), passe en noir et blanc contrasté, ajoute le contour blanc irrégulier."""
    from rembg import remove, new_session
    im = Image.open(photo).convert("RGB")
    cut = remove(im, session=new_session("u2net_human_seg"))
    a = np.asarray(cut.getchannel("A")).astype(np.uint8)
    g = np.asarray(im.convert("L")).astype(np.float32)
    g = np.clip((g - 128) * 1.25 + 128 + 6, 0, 255)  # noir et blanc un peu plus contrasté
    # contour blanc façon papier découpé : alpha dilaté avec un bord légèrement irrégulier
    k = max(9, int(min(im.size) * 0.014))
    rng = np.random.default_rng(4)
    noise = cv2.GaussianBlur(rng.random(a.shape).astype(np.float32), (0, 0), k * 0.8)
    noise = (noise - noise.min()) / (np.ptp(noise) + 1e-9)
    dil = cv2.dilate(a, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1)))
    dil2 = cv2.dilate(a, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k + 1, k + 1)))
    border = np.where(noise > 0.45, dil, dil2)
    rgb = np.where(a[..., None] > 128, np.repeat(g[..., None], 3, 2), 255).astype(np.uint8)
    alpha = np.maximum(border, a)
    Image.fromarray(np.dstack([rgb, alpha])).save(out_png)
    return out_png


@lru_cache(maxsize=None)
def oswald(size, weight):
    f = ImageFont.truetype(str(OSWALD), size)
    f.set_variation_by_axes([weight])
    return f


def ease_out(p):
    p = min(max(p, 0.0), 1.0)
    return 1 - (1 - p) ** 3


def light_leak(t, n_frames, w=W, h=H):
    """Lumière chaude qui balaie l'image (orange -> jaune), intensité 0..1 selon t (images)."""
    p = t / max(n_frames - 1, 1)
    inten = np.sin(np.pi * min(max(p, 0), 1)) ** 1.5
    sw, sh = w // 8, h // 8
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    cx = sw * (-0.2 + 1.4 * p)
    blob1 = np.exp(-(((xx - cx) / (sw * 0.45)) ** 2 + ((yy - sh * 0.6) / (sh * 0.9)) ** 2))
    blob2 = np.exp(-(((xx - cx + sw * 0.35) / (sw * 0.3)) ** 2 + ((yy - sh * 0.3) / (sh * 0.6)) ** 2))
    col = blob1[..., None] * np.array([255, 150, 40]) + blob2[..., None] * np.array([255, 230, 120])
    col = cv2.resize(col.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    return np.clip(col * inten, 0, 255)


def render_card(cut_png, name, title, tagline, out, fps=25, dur=3.2):
    """Carte invité animée -> ProRes 4444 avec alpha.

    Mise en page sur une grille (unité U = H/54, soit 40 px en 4K) :
    - un seul bord gauche pour tout le texte, placé à 3 U à droite de la silhouette (calculé sur la photo) ;
    - 3 niveaux, échelle nette : NOM (Oswald Bold, hauteur de capitale 7 U) > FONCTION au-dessus
      (Oswald Medium, 1/4 du nom) > MENTION en dessous (Oswald Regular espacé, plus petite, 85 % d'opacité,
      précédée d'un filet) ;
    - espacements fixes : fonction -> nom 1,5 U, nom -> filet 2 U ; bloc centré sur le centre optique (42 % H).
    """
    n = round(dur * fps)
    U = H / 54
    photo = Image.open(cut_png)
    ph = int(H * 0.97)
    photo = photo.resize((int(photo.width * ph / photo.height), ph), Image.LANCZOS)
    px_end, py_end = int(-W * 0.01), H - ph + int(H * 0.03)

    def cap(f):  # hauteur de capitale et retrait de la capitale par rapport au point d'ancrage
        x0, y0, x1, y1 = f.getbbox("H")
        return y1 - y0, y0

    # tailles : le nom vise 7 U de capitale, réduit s'il ne tient pas dans la colonne
    def font_for_cap(target, weight):
        f = oswald(100, weight)
        return oswald(int(100 * target / cap(f)[0]), weight)
    f_title = font_for_cap(1.75 * U, 500)
    f_label = font_for_cap(1.15 * U, 400)
    track_title, track_label = 0.04, 0.22  # espacement des lettres, en part de la taille

    def width(text, f, track):
        return sum(f.getlength(c) for c in text) + track * f.size * (len(text) - 1)

    # bloc vertical : [fonction][1,5 U + accents][nom][2 U][filet + mention]
    def layout(f_name):
        hn, ht, hl = cap(f_name)[0], cap(f_title)[0], cap(f_label)[0]
        # les accents des capitales (É) dépassent : l'espace fonction -> nom se compte depuis le haut des accents
        acc = max(0, cap(f_name)[1] - f_name.getbbox(name)[1])
        gap = 1.5 * U + acc
        total = ht + gap + hn + 2 * U + hl
        top = H * 0.42 - total / 2
        return top, top + ht + gap, top + ht + gap + hn + 2 * U, total

    # bord gauche : 3 U après le point le plus à droite de la silhouette sur la hauteur du bloc
    a = np.asarray(photo.getchannel("A"))
    f_name = font_for_cap(7 * U, 700)
    for _ in range(30):
        y_t, y_n, y_l, total = layout(f_name)
        rows = a[max(0, int(y_t - py_end)): max(0, int(y_t + total - py_end))]
        right = (np.nonzero(rows.max(0) > 40)[0].max() if rows.size and rows.max() > 40 else 0) + px_end
        x0 = right + 3 * U
        if x0 + width(name, f_name, 0) <= W - 4 * U:
            break
        f_name = oswald(int(f_name.size * 0.96), 700)

    def draw_tracked(d, x, y_cap_top, text, f, track, fill):
        y = y_cap_top - cap(f)[1]
        x -= f.getbbox(text[0])[0]  # bord optique : la première capitale touche exactement le bord gauche
        for c in text:
            d.text((x, y), c, font=f, fill=fill)
            x += f.getlength(c) + track * f.size

    name_x = [x0 - f_name.getbbox(name[0])[0]]
    for c in name[:-1]:
        name_x.append(name_x[-1] + f_name.getlength(c))
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                            "-r", str(fps), "-i", "-", "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le",
                            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", str(out)],
                           stdin=subprocess.PIPE)
    leak_n = 10
    rule_w, rule_h = 3 * U, max(4, int(0.16 * U))
    for k in range(n):
        frame = Image.new("RGBA", (W, H), TEAL + (int(255 * ease_out(k / 5)),))
        # photo : arrive d'en bas à gauche, puis zoom très lent
        p = ease_out((k - 2) / 9)
        s = 1.0 + 0.03 * k / n
        im = photo.resize((int(photo.width * s), int(photo.height * s)), Image.BILINEAR)
        if k >= 2:
            layer = Image.new("RGBA", (W, H))
            layer.paste(im, (int(px_end - (1 - p) * W * 0.12), int(H - im.height + H * 0.03 + (1 - p) * H * 0.45)))
            frame.alpha_composite(layer)
        d = ImageDraw.Draw(frame)
        # fonction : monte de 1 U en apparaissant
        q = ease_out((k - 6) / 6)
        if q > 0:
            draw_tracked(d, x0, y_t + (1 - q) * U, title, f_title, track_title, (255, 255, 255, int(255 * q)))
        # nom : lettre par lettre, chaque lettre arrive grisée et un peu plus grande puis se pose en blanc
        for i, c in enumerate(name):
            q = ease_out((k - 9 - i * 0.9) / 3)
            if q <= 0:
                continue
            col = int(170 + 85 * q)
            f = oswald(int(f_name.size * (1.15 - 0.15 * q)), 700) if q < 1 else f_name
            dx = (f.getlength(c) - f_name.getlength(c)) / 2
            d.text((name_x[i] - dx, y_n - cap(f)[1] - (cap(f)[0] - cap(f_name)[0])), c, font=f,
                   fill=(col, col, col, int(255 * (0.35 + 0.65 * q))))
        # filet qui s'étire, puis la mention
        q = ease_out((k - 16) / 6)
        if q > 0 and tagline:
            yc = y_l + cap(f_label)[0] / 2
            d.rectangle((x0, yc - rule_h / 2, x0 + rule_w * q, yc + rule_h / 2), fill=(255, 255, 255, 230))
            q2 = ease_out((k - 19) / 6)
            if q2 > 0:
                draw_tracked(d, x0 + rule_w + 1.2 * U, y_l, tagline, f_label, track_label, (255, 255, 255, int(217 * q2)))
        arr = np.asarray(frame).astype(np.float32)
        if k < leak_n:  # lumière chaude d'entrée, par-dessus (elle éclaire aussi le plan d'avant)
            lk = light_leak(k, leak_n)
            arr[..., :3] = np.clip(arr[..., :3] + lk * 0.7, 0, 255)
            arr[..., 3] = np.maximum(arr[..., 3], np.clip(lk.max(2) * 1.2, 0, 255))
        enc.stdin.write(arr.astype(np.uint8).tobytes())
    enc.stdin.close()
    enc.wait()
    return out


# ---------- logo de fin d'intro ----------

def render_logo_card(logo_png, out, fps=25, dur=3.2, hold_black=0.12):
    """Écran noir, le logo blanc arrive en grand sur un impact grave (bruit lourd de fin de suspense).
    -> ProRes 422 HQ 4K + son (WAV 48 kHz intégré), à poser comme un insert."""
    import teaser_son as ts
    n = round(dur * fps)
    logo = Image.open(logo_png)
    lh = int(H * 0.62)
    logo = logo.resize((int(logo.width * lh / logo.height), lh), Image.LANCZOS)
    t0 = round(hold_black * fps)
    raw = out.with_suffix(".video.mov")
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(fps), "-i", "-", "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le",
                            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", str(raw)],
                           stdin=subprocess.PIPE)
    for k in range(n):
        frame = Image.new("RGB", (W, H), (0, 0, 0))
        if k >= t0:
            p = ease_out((k - t0) / 14)
            s = 1.08 - 0.08 * p + 0.015 * (k - t0) / n  # se pose, puis respire très lentement
            a = min(1.0, (k - t0) / 3) * (1 - max(0.0, (k - (n - 8)) / 8))  # apparition franche, fondu au noir à la fin
            im = logo.resize((int(logo.width * s), int(logo.height * s)), Image.BILINEAR)
            alpha = im.getchannel("A").point(lambda v: int(v * a))
            frame.paste(im.convert("RGB"), ((W - im.width) // 2, (H - im.height) // 2), alpha)
        enc.stdin.write(frame.tobytes())
    enc.stdin.close()
    enc.wait()
    # son : gros impact grave + sous-grave qui descend, calé sur l'apparition du logo
    sr = ts.SR
    x = np.zeros(int(dur * sr))
    ts.place(x, ts.boom(True), hold_black, 1.0)
    ts.place(x, ts.sub_drop(), hold_black, 0.7)
    ts.place(x, ts.shutter(), hold_black - 0.02, 0.35)
    st = ts.stereo(x, 0.15)
    st *= 10 ** (-4 / 20) / (np.abs(st).max() + 1e-9)
    wav = out.with_suffix(".son.wav")
    import soundfile as sf
    sf.write(wav, st.astype(np.float32), sr, subtype="PCM_24")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-i", str(wav), "-c:v", "copy", "-c:a", "pcm_s24le",
                    "-ar", "48000", "-shortest", str(out)], check=True)
    raw.unlink()
    wav.unlink()
    return out


# ---------- zoom lent sur un passage déjà monté ----------

def zoom_segment(src, start, dur, out, z0=1.0, z1=1.07, fps=25):
    """Passage [start, start+dur] d'une vidéo 4K avec un zoom avant très lent et régulier (sous-pixel),
    son d'origine gardé. -> ProRes 422 HQ 4K + PCM."""
    n = round(dur * fps)
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-i", str(src), "-frames:v", str(n),
                            "-vf", f"fps={fps},scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb48le", "-"],
                           stdout=subprocess.PIPE)
    raw = Path(out).with_suffix(".video.mov")
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb48le", "-s", f"{W}x{H}",
                            "-r", str(fps), "-i", "-", "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le",
                            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", str(raw)],
                           stdin=subprocess.PIPE)
    for k in range(n):
        buf = dec.stdout.read(W * H * 6)
        if len(buf) < W * H * 6:
            break
        p = k / max(n - 1, 1)
        z = z0 + (z1 - z0) * p
        m = np.float32([[z, 0, (1 - z) * W / 2], [0, z, (1 - z) * H / 2]])
        img = np.frombuffer(buf, np.uint16).reshape(H, W, 3)
        enc.stdin.write(cv2.warpAffine(img, m, (W, H), flags=cv2.INTER_CUBIC).tobytes())
    dec.stdout.close()
    dec.wait()
    enc.stdin.close()
    enc.wait()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-ss", f"{start:.3f}", "-t", f"{n / fps:.3f}", "-i", str(src),
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "pcm_s24le", "-ar", "48000", "-ac", "2",
                    str(out)], check=True)
    raw.unlink()
    return out


def watermark_png(logo_png, out, width=0.11, margin=(0.028, 0.04), opacity=0.85):
    """Image 4K transparente avec le logo en haut à droite (filigrane de l'épisode), ombre douce pour
    rester lisible sur un fond clair."""
    logo = Image.open(logo_png)
    lw = int(W * width)
    logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
    x, y = W - lw - int(W * margin[0]), int(H * margin[1])
    canvas = Image.new("RGBA", (W, H))
    a = logo.getchannel("A")
    shadow = Image.new("RGBA", logo.size, (0, 0, 0, 0))
    shadow.putalpha(a.filter(ImageFilter.GaussianBlur(lw * 0.012)).point(lambda v: int(v * 0.45)))
    canvas.alpha_composite(shadow, (x + 3, y + 4))
    logo.putalpha(a.point(lambda v: int(v * opacity)))
    canvas.alpha_composite(logo, (x, y))
    canvas.save(out)
    return out
