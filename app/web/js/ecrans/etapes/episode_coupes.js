// Épisode, partie 5 : couper dans l'épisode exporté sans le réexporter. On marque le début et la fin d'une coupe sur
// la vidéo exportée (au dixième près, ±0,2 s / ±1 s), « Couper jusqu'à la fin » pour le hors antenne final ; chaque
// coupe se vérifie tout de suite (« Écouter la jointure » : 3 s avant, saut, 3 s après, dans l'export lui-même), puis
// « Appliquer les coupes » : l'app ne réencode que quelques secondes autour de chaque coupe. L'export d'origine est
// gardé ; la livraison prend la version coupée. Aucune logique de process : statuts et permissions viennent du serveur.
import {media} from "../../api.js";
import {barre, bouton, esc, toast} from "../../ui.js";
import {agir} from "./shorts_commun.js";

const K = {projet: null, debut: null, joint: null};
const AUTOUR = 3;  // secondes écoutées de part et d'autre d'une jointure

// 754.36 -> « 12:34,4 » (au dixième : on coupe à l'image près)
export function tcf(s) {
  s = Math.max(0, s || 0);
  const d = Math.round(s * 10) / 10, h = Math.floor(d / 3600), m = Math.floor(d / 60) % 60;
  const ss = (d % 60).toFixed(1).replace(".", ",").padStart(4, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}
const duree = s => s < 60 ? `${String(Math.round(s * 10) / 10).replace(".", ",")} s`
  : `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, "0")}`;

const tache = (v, type) => v.taches.find(t => t.type === type && (t.actif || t.statut === "en_attente"));
const echec = (v, type) => !tache(v, type) && v.taches.find(t => t.type === type && t.statut === "echec");
const finie = (v, type) => v.taches.find(t => t.type === type && t.statut === "terminee");
const cle = (v, type) => { const t = finie(v, type); return t ? `&t=${encodeURIComponent(t.fin || t.id)}` : ""; };

function etat(v) {
  if (K.projet !== v.id) Object.assign(K, {projet: v.id, debut: null, joint: null});
  return K;
}

// la vidéo de travail : toujours l'export d'origine (les heures des coupes sont les siennes)
export function video(v) {
  const src = v.episode.export;
  if (!src) return "";
  return `<div class="vid ep"><video controls preload="metadata" playsinline data-coupe-video
      src="${esc(media(v.id, src) + cle(v, "export"))}"></video></div>
    <div class="cbar">
      <div class="seg" role="group" aria-label="Avancer ou reculer">
        <button type="button" data-act="decaler" data-d="-1" title="Reculer d'une seconde">−1 s</button>
        <button type="button" data-act="decaler" data-d="-0.2" title="Reculer de 0,2 s">−0,2</button>
        <button type="button" data-act="decaler" data-d="0.2" title="Avancer de 0,2 s">+0,2</button>
        <button type="button" data-act="decaler" data-d="1" title="Avancer d'une seconde">+1 s</button></div>
      <b class="ctc" data-o="coupe-tc">0:00,0</b>
      <span style="flex:1"></span>
      ${bouton({label: "Début de la coupe ici", action: "coupe_debut", style: "sm"})}
      ${bouton({label: "Fin de la coupe ici", action: "coupe_fin", style: "sm", attrs: 'data-o="coupe-fin"'})}
      ${bouton({label: "Couper jusqu'à la fin", action: "coupe_tout_fin", style: "ghost sm"})}
    </div>
    <p class="muted small" data-o="coupe-attente" style="margin-top:8px"></p>`;
}

function ligne(c) {
  return `<div class="cp">
    <button type="button" class="pl" data-act="jointure" data-id="${c.id}" title="Écouter la jointure"
      aria-label="Écouter la jointure de cette coupe">▶</button>
    <div><b>${tcf(c.a)} → ${tcf(c.b)}</b> <span class="muted">· ${duree(c.b - c.a)} en moins</span>
      <div class="tx" style="font-style:normal">▶ : ${AUTOUR} s avant, la coupe sautée, ${AUTOUR} s après</div></div>
    ${bouton({label: "Enlever", action: "coupe_retirer", style: "ghost sm", attrs: `data-id="${c.id}"`})}</div>`;
}

export function liste(v) {
  const c = v.episode.coupes || [];
  if (!c.length) return `<p class="muted small" style="margin-top:12px">Aucune coupe. Mets la vidéo au bon endroit,
    « Début de la coupe ici », avance, « Fin de la coupe ici ».</p>`;
  const total = c.reduce((s, x) => s + x.b - x.a, 0);
  return `<p class="small" style="margin:14px 0 8px"><b>${c.length} coupe${c.length > 1 ? "s" : ""}, ${duree(total)} en moins</b></p>
    <div class="cps">${[...c].sort((x, y) => x.a - y.a).map(ligne).join("")}</div>`;
}

export function pied(v) {
  const t = tache(v, "coupes"), e = echec(v, "coupes"), st = v.statuts.coupes;
  if (t) return `<div style="margin-top:14px">${barre(t)}</div><p class="muted small" style="margin-top:8px">
    L'app ne réencode que quelques secondes autour de chaque coupe : le reste est recopié tel quel.</p>`;
  const err = e ? `<div class="errbox" style="margin-top:14px"><div style="flex:1"><b>Les coupes n'ont pas marché.</b>
      <span class="muted"> ${esc(e.erreur || "")}</span></div>
      <div class="acts">${bouton({label: "Réessayer", action: "reessayer", attrs: `data-id="${esc(e.id)}"`})}</div></div>` : "";
  if (st === "valide") {
    return `${err}<div class="epf">${'<span class="okchip">✓ Coupes appliquées</span>'}
      <span class="muted small">C'est cette version qui sera livrée. L'export d'origine est gardé à côté.</span></div>
      <div class="vid ep" style="margin-top:12px"><video controls preload="metadata" playsinline
        src="${esc(media(v.id, v.episode.coupe) + cle(v, "coupes"))}"></video><p>L'épisode coupé, prêt à publier.</p></div>`;
  }
  if (st !== "a_faire") return err;
  return `${err}<div class="epf">${bouton({label: "Appliquer les coupes", action: "coupes_appliquer", style: "p",
      actif: !!v.peut.couper, raison: "Attends la fin de l'export en cours."})}
    <span class="muted small">Environ 1 minute, sans repasser par les rushes. L'export d'origine est gardé.</span></div>`;
}

// ---- lecteur : heure affichée, saut de la jointure
function lecteurCoupe(el) { return el.querySelector("[data-coupe-video]"); }

export function brancher(el) {
  const vid = lecteurCoupe(el);
  if (!vid || vid._branche) return;
  vid._branche = true;
  vid.addEventListener("timeupdate", () => {
    const o = el.querySelector('[data-o="coupe-tc"]');
    if (o) o.textContent = tcf(vid.currentTime);
    const j = K.joint;
    if (!j || j.video !== vid) return;
    if (!j.saute && vid.currentTime >= j.a) { j.saute = true; vid.currentTime = j.b; }
    else if (j.saute && vid.currentTime >= j.b + AUTOUR) { vid.pause(); K.joint = null; }
  });
  vid.addEventListener("seeking", () => {  // un saut de la main annule l'écoute de la jointure
    const j = K.joint;
    if (j && j.video === vid && !j.attendu.some(t => Math.abs(vid.currentTime - t) < 0.3)) K.joint = null;
  });
  majAttente(el);
}

function majAttente(el) {
  const o = el.querySelector('[data-o="coupe-attente"]');
  if (o) o.innerHTML = K.debut == null ? "" : `Début de la coupe à <b>${tcf(K.debut)}</b> : avance jusqu'à la fin du
    passage à couper, puis « Fin de la coupe ici ».`;
}

async function ajouter(v, a, b) {
  if (b - a < 0.04) { toast("La fin de la coupe doit être après son début.", "no"); return; }
  const r = await agir(v.id, {type: "ajouter_coupe", a: Math.round(a * 100) / 100, b: Math.round(b * 100) / 100},
    `Coupe ajoutée : ${duree(b - a)} en moins. Écoute la jointure avec ▶.`);
  if (r) K.debut = null;
}

export function gestes(v, el) {
  etat(v);
  const vid = () => lecteurCoupe(el);
  return {
    decaler: b => { const x = vid(); if (x) x.currentTime = Math.max(0, x.currentTime + Number(b.dataset.d)); },
    coupe_debut: () => { const x = vid(); if (!x) return; K.debut = x.currentTime; majAttente(el); },
    coupe_fin: async () => {
      const x = vid();
      if (!x) return;
      if (K.debut == null) { toast("Marque d'abord le début de la coupe.", "no"); return; }
      await ajouter(v, K.debut, x.currentTime);
      majAttente(el);
    },
    coupe_tout_fin: async () => {
      const x = vid();
      if (!x) return;
      const a = K.debut ?? x.currentTime, fin = x.duration || v.episode.duree || a;
      await ajouter(v, a, Math.max(fin, a) + 1);  // au-delà de la fin : l'app coupe jusqu'au bout
      majAttente(el);
    },
    coupe_retirer: async b => { b.disabled = true; if (!(await agir(v.id, {type: "retirer_coupe", id: Number(b.dataset.id)}))) b.disabled = false; },
    jointure: b => {
      const c = (v.episode.coupes || []).find(x => x.id === Number(b.dataset.id)), x = vid();
      if (!c || !x) return;
      K.joint = {video: x, a: c.a, b: c.b, saute: false, attendu: [Math.max(0, c.a - AUTOUR), c.b]};
      x.currentTime = Math.max(0, c.a - AUTOUR);
      x.scrollIntoView({block: "nearest", behavior: "smooth"});
      x.play().catch(() => {});
    },
    coupes_appliquer: async b => {
      b.disabled = true;
      if (!(await agir(v.id, {type: "lancer_coupes"}, "C'est parti : l'épisode se coupe (environ 1 minute)."))) b.disabled = false;
    },
  };
}
