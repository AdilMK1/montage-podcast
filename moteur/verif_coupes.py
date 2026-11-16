"""Contrôle des coupes d'un lot de shorts : retranscrit chaque clip rendu et le compare au texte attendu.

Signale : mots du texte source absents du clip (coupe en plein mot / phrase amputée), et montre
les premiers et derniers mots réellement entendus (un clip doit commencer et finir sur une phrase complète).

Usage : python verif_coupes.py sessions/clips_x.json [début de nom …]
"""
import difflib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import whisper_local
import travail

ROOT = Path(__file__).parent


def norm(t):
    t = t.lower().replace("’", "'")
    t = re.sub(r"\s+'", "'", t)          # « qu 'on » (transcript découpé) -> « qu'on »
    t = re.sub(r"\s+-(?=\w)", "-", t)     # « est -ce » -> « est-ce »
    t = t.replace("'", "").replace("-", " ")
    return [w for w in re.split(r"[^a-zàâäéèêëîïôöùûüç0-9]+", t) if w]


def main(spec_path, names):
    spec = json.loads(Path(spec_path).read_text())
    cfg = json.loads((ROOT / spec["session"]).read_text())
    sents = json.loads((travail.dossier(cfg["name"]) / "transcript.json").read_text())
    words = sorted(((w["w"], w["start"]) for s in sents if not s.get("traduction") for w in s["words"]), key=lambda x: x[1])
    bilan = []
    for sh in spec["shorts"]:
        if names and not any(sh["nom"].startswith(n) for n in names):
            continue
        f = Path(spec["dossier"]) / f'{sh["nom"]}.mp4'
        if not f.exists():
            continue
        exp = []
        for ex in sh["extraits"]:
            a, b = ex["rush"]
            exp += norm(" ".join(w for w, s in words if a - 0.02 <= s < b - 0.05))
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                   capture_output=True, text=True).stdout)
        fin = 0.0 if spec.get("sans_fin") else 2.2  # carton de fin sans voix : Whisper y invente du texte
        with tempfile.TemporaryDirectory() as tmpd:  # (Windows : un fichier ouvert ne peut pas être réécrit par ffmpeg)
            wav = str(Path(tmpd) / "clip.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(f), "-t", f"{dur - fin:.2f}", "-ac", "1", "-ar", "16000", wav], check=True)
            r = whisper_local.transcrire(wav, temperatures=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0))
        got = norm(r["text"])
        sm = difflib.SequenceMatcher(a=exp, b=got, autojunk=False)
        manques = []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op in ("delete", "replace") and i2 - i1 >= 2:
                manques.append(" ".join(exp[i1:i2]))
        ratio = sm.ratio()
        print(f'\n== {sh["nom"]}  (accord {ratio:.0%})')
        print("   début entendu :", " ".join(got[:8]))
        print("   fin entendue  :", " ".join(got[-8:]))
        if manques:
            print("   ⚠️ absents du clip :", " | ".join(manques[:6]))
        bilan.append((sh["nom"], ratio, manques))
        res = {"accord": round(ratio, 3), "debut": " ".join(got[:8]), "fin": " ".join(got[-8:]), "absents": manques[:6],
               "date": __import__("time").strftime("%Y-%m-%d %H:%M")}
        vp = Path(spec_path).parent / "verif_coupes.json"
        allv = json.loads(vp.read_text()) if vp.exists() else {}
        allv[sh["nom"]] = res
        vp.write_text(json.dumps(allv, ensure_ascii=False, indent=1))
    return bilan


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
