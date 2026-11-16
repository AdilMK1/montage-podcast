// Outils partagés de l'étape Shorts : envoi d'une action, mise en forme (minute, accroche, « pourquoi »),
// et le lecteur plein écran des shorts (port de openPL / drawPL v1) : la vidéo avec le son, à côté le titre,
// l'accroche et la décision ; ← → pour passer au suivant, Échap pour fermer.
import {api} from "../../api.js";
import {store} from "../../store.js";
import {esc, lier, modale, toast} from "../../ui.js";

// envoie une action ; en cas de refus, le message du serveur s'affiche en toast. Renvoie la vue à jour ou null.
export async function agir(projet, action, ok = "") {
  const r = await api.action(projet, action);
  if (r.erreur) { toast(r.erreur, "no"); return null; }
  store.mettre(r.projet);
  if (ok) toast(ok, "ok");
  return r.projet;
}

// 754 -> « 12:34 », 3723 -> « 1:02:03 »
export function tc(s) {
  s = Math.max(0, Math.round(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

export const duree = s => (s >= 60 ? `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, "0")}` : `${Math.round(s)} s`);

// l'accroche telle qu'on la modifie : une ligne par ligne d'écran, les *mots en couleur* gardent leurs étoiles
export const accrocheEdition = sh => ((sh.spec && sh.spec.accroche) || []).join("\n");
export const accrocheLignes = txt => String(txt || "").split("\n").map(l => l.replace(/\s+/g, " ").trim()).filter(Boolean);

// « pourquoi » de l'IA, sans les phrases qui parlent de fichiers internes
export function pourquoi(sh) {
  const t = String(sh.pourquoi || "");
  if (/^choisi à la main/i.test(t)) return "Choisi par toi dans le transcript.";
  return t.split(/(?<=[.!?])\s+/).filter(p => !/\b[\w-]+\.(json|py|txt|log|wav|mp4)\b/i.test(p)).join(" ");
}

// le short à jour dans la dernière vue reçue
export const shortCourant = id => ((store.etat.vue && store.etat.vue.shorts) || []).find(x => x.id === id) || null;

// Lecteur plein écran d'une liste de shorts. src(sh) -> adresse de la vidéo (ou null : sauté) ;
// cote(sh) -> HTML du panneau de droite ; gestes : {act: (bouton, sh, lecteur) => …} sur les [data-act] du panneau.
export function lecteurShorts({ids, index, src, cote, gestes}) {
  const lisibles = () => ids.map(shortCourant).filter(sh => sh && src(sh));
  let id = ids[index];
  let clavier = null;
  const m = modale("", {classe: "player", onFermer: () => { v.pause(); document.removeEventListener("keydown", clavier); }});
  m.el.className = "";
  m.el.innerHTML = `<button class="x" type="button" aria-label="Fermer">×</button>
    <div class="plw"><button type="button" class="nav" data-act="prec" aria-label="Short précédent">‹</button>
      <video controls autoplay playsinline></video>
      <button type="button" class="nav" data-act="suiv" aria-label="Short suivant">›</button>
      <div class="side" data-cote></div></div>`;
  const v = m.el.querySelector("video"), zc = m.el.querySelector("[data-cote]");
  let fin = null;
  v.addEventListener("timeupdate", () => { if (fin != null && v.currentTime >= fin) { v.pause(); fin = null; } });
  v.addEventListener("error", () => { if (v.getAttribute("src")) toast("Cette vidéo ne se lit pas pour l'instant.", "no"); });
  const L = {
    video: v,
    // joue un morceau : debut négatif = compté depuis la fin
    morceau(debut, duree_s) {
      const go = () => { v.currentTime = debut < 0 ? Math.max(0, v.duration + debut) : debut; fin = v.currentTime + duree_s; v.play().catch(() => {}); };
      if (v.readyState >= 1) go(); else v.addEventListener("loadedmetadata", go, {once: true});
    },
    redessiner() { const sh = shortCourant(id); if (sh) zc.innerHTML = cote(sh); },
  };
  function montrer(nid) {
    const sh = shortCourant(nid);
    if (!sh || !src(sh)) return;
    id = nid;
    fin = null;
    v.src = src(sh);
    v.play().catch(() => {});
    L.redessiner();
    const l = lisibles();
    m.el.querySelectorAll(".nav").forEach(b => { b.disabled = l.length < 2; });
  }
  function pas(d) {
    const l = lisibles(), i = l.findIndex(x => x.id === id);
    if (l.length > 1) montrer(l[(i + d + l.length) % l.length].id);
  }
  clavier = e => {
    if ([...document.querySelectorAll(".modal.on")].pop() !== m.fond) return;
    if (e.target.matches && e.target.matches("input,textarea")) return;
    if (e.key === "ArrowRight") pas(1);
    if (e.key === "ArrowLeft") pas(-1);
  };
  document.addEventListener("keydown", clavier);
  m.el.querySelector(".x").onclick = m.fermer;
  const g = {prec: () => pas(-1), suiv: () => pas(1)};
  for (const [k, f] of Object.entries(gestes)) g[k] = b => f(b, shortCourant(id), L);
  lier(m.el, g);
  montrer(id);
  return L;
}

export function textesHtml(sh) {
  const a = (sh.spec && sh.spec.accroche) || [];
  return a.map(l => esc(l).replace(/\*([^*]+)\*/g, "<em>$1</em>")).join("<br>");
}

// choix du pack d'un short : « celui du podcast » (pas de champ pack), « Aucun pack » ou un pack de la bibliothèque
export function choixPack(v, sh) {
  const packs = v.packs || [];
  const opts = packs.map(p =>
    `<option value="${esc(p.id)}"${sh.pack === p.id ? " selected" : ""}>${esc(p.nom)}</option>`).join("");
  const inconnu = sh.pack && !packs.some(p => p.id === sh.pack)
    ? `<option value="${esc(sh.pack)}" selected>${esc(sh.pack_nom || sh.pack)}</option>` : "";
  return `<label class="lab" for="pk-${esc(sh.id)}">Pack</label><select class="inp pk-short" id="pk-${esc(sh.id)}"
    data-pack-short="${esc(sh.id)}"><option value=""${sh.pack ? "" : " selected"}>Pack du podcast (${
      esc(v.pack ? v.pack.nom : "")})</option>${opts}${inconnu}</select>`;
}
