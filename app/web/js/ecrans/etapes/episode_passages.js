// Épisode, partie 1 : les passages que l'IA propose de retirer (port du bloc « coupes » et de voirCoupe v1).
// Chaque passage : ▶ pour le voir (extrait fabriqué à la demande), le moment, la durée, la raison, ce qui s'y dit,
// et le choix « Retirer » / « Garder dans l'épisode ». Puis « J'ai vérifié les passages ».
import {api, media} from "../../api.js";
import {barre, bouton, esc, lecteur, modale, toast} from "../../ui.js";
import {agir, tc} from "./shorts_commun.js";

const T = {projet: null, phrases: null, demande: false};
const virgule = x => String(x).replace(".", ",");
const secondes = s => (s < 10 ? `${virgule(Math.round(s * 10) / 10)} s` : s < 60 ? `${Math.round(s)} s`
  : `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, "0")}`);

// le transcript sert à montrer ce qui se dit dans chaque passage, et à estimer la durée de l'épisode
export function phrases(projet, redessiner) {
  if (T.projet !== projet) Object.assign(T, {projet, phrases: null, demande: false});
  if (!T.demande) {
    T.demande = true;
    api.transcript(projet).then(r => {
      if (T.projet !== projet) return;
      T.phrases = r.erreur ? [] : (r.phrases || []);
      redessiner();
    });
  }
  return T.phrases;
}

function texte(p) {
  if (!T.phrases) return null;
  const ph = T.phrases.filter(x => x.b > p.a + 0.05 && x.a < p.b - 0.05);
  return ph.map(x => x.t).join(" ").trim();
}

function ligne(p) {
  const id = esc(String(p.id)), tx = texte(p);
  const dit = tx == null ? "" : tx ? `« ${esc(tx)} »` : "Silence";
  return `<div class="cp ${p.garder ? "garder" : ""}">
    <button type="button" class="pl" data-act="voir_passage" data-id="${id}" title="Voir ce passage"
      aria-label="Voir ce passage">▶</button>
    <div><b>À ${tc(p.a)}</b> <span class="muted">· ${secondes(p.b - p.a)}${p.raison ? ` · ${esc(p.raison)}` : ""}</span>
      ${dit ? `<div class="tx" title="${tx ? esc(tx) : ""}">${dit}</div>` : ""}</div>
    <div class="seg" role="group" aria-label="Ce passage">
      <button type="button" class="${p.garder ? "" : "on"}" data-act="passage" data-id="${id}" data-garder="0">Retirer</button>
      <button type="button" class="${p.garder ? "on" : ""}" data-act="passage" data-id="${id}" data-garder="1">Garder dans l'épisode</button></div></div>`;
}

const tacheActive = (v, type) => v.taches.find(t => t.type === type && (t.actif || t.statut === "en_attente"));

// HTML de la carte « passages retirés »
export function carte(v) {
  const st = v.statuts.passages, ia = tacheActive(v, "ia_passages");
  if (st === "a_faire") {
    const pourquoi = v.statuts.analyse !== "valide"
      ? "L'IA repère les passages à retirer (blancs, hésitations, hors sujet) une fois l'analyse terminée."
      : ia ? "L'IA repère les passages à retirer : ils arrivent ici dans quelques minutes."
        : "L'IA va repérer les passages à retirer. Ils arrivent ici dès qu'ils sont prêts.";
    const t = ia || tacheActive(v, "analyse");
    return `<p class="muted small">${pourquoi}</p>${t ? `<div style="margin-top:12px">${barre(t, {mini: true})}</div>` : ""}`;
  }
  const n = v.passages.length, retires = v.passages.filter(p => !p.garder);
  const total = retires.reduce((s, p) => s + p.b - p.a, 0);
  const resume = !n ? "Rien n'est retiré : l'épisode est gardé en entier."
    : retires.length ? `${retires.length} passage${retires.length > 1 ? "s" : ""} retiré${retires.length > 1 ? "s" : ""} sur ${n}, soit ${secondes(total)} en moins.`
      : "Tout est gardé : l'épisode reste entier.";
  const revus = v.passages_revus, verif = v.a_verifier || [];
  // ce que l'IA signale sans le retirer (santé, mineurs, propos sur un tiers…) : aussi en marqueurs dans le XML
  const avert = verif.length ? `<div class="att" style="margin-top:12px;display:block">⚠ <b>À vérifier avant de publier</b>
      <span class="muted">(signalé par l'IA, rien n'est retiré)</span>
      ${verif.map(m => `<div class="small" style="margin-top:4px">À ${tc(m.a)} · ${esc(m.texte)}</div>`).join("")}</div>` : "";
  return `<p class="small"><b>${resume}</b></p>
    ${n ? `<p class="muted small" style="margin:4px 0 12px">Clique sur ▶ pour voir un passage. Garde-le s'il est utile à l'épisode.</p>
      <div class="cps">${v.passages.map(ligne).join("")}</div>` : ""}${avert}
    <div class="epf">${revus ? `<span class="okchip">✓ Passages vérifiés</span>
        <span class="muted small">${n ? "Tu peux encore changer un passage : il faudra remonter l'épisode." : ""}</span>`
      : bouton({label: n ? "J'ai vérifié les passages" : "C'est bon, on garde tout", action: "valider_passages", style: "p"})}</div>`;
}

// ---- gestes
async function voir(projet, id) {
  let ferme = false;
  const m = modale(`<div style="display:flex;gap:12px;align-items:center"><span class="spin"></span>
    <b>Préparation de l'extrait…</b></div><p class="muted small" style="margin-top:10px">Quelques secondes.</p>`,
  {onFermer: () => { ferme = true; }});
  const r = await api.apercuPassage(projet, id);
  if (ferme) return;  // fermée pendant la préparation : on n'ouvre pas le lecteur
  m.fermer();
  if (r.erreur) { toast(r.erreur, "no"); return; }
  const p = ((T.vue && T.vue.passages) || []).find(x => String(x.id) === String(id));
  lecteur(media(projet, r.src), {titre: p ? `Passage à ${tc(p.a)} · il dure ${secondes(p.b - p.a)}` : ""});
}

export function gestes(v) {
  T.vue = v;
  return {
    voir_passage: async b => { b.disabled = true; await voir(v.id, b.dataset.id); b.disabled = false; },
    passage: async b => {
      const p = v.passages.find(x => String(x.id) === b.dataset.id);
      if (!p || p.garder === (b.dataset.garder === "1")) return;
      b.disabled = true;
      const id = typeof p.id === "number" ? p.id : String(p.id);
      if (!(await agir(v.id, {type: "decider_passage", id, garder: b.dataset.garder === "1"}))) b.disabled = false;
    },
    valider_passages: async b => {
      b.disabled = true;
      const r = await agir(v.id, {type: "valider_passages"});
      if (!r) { b.disabled = false; return; }
      const pret = r.statuts.couleur === "valide" && r.statuts.son === "valide";
      toast(pret ? "Passages vérifiés : le montage de l'épisode démarre." : "Passages vérifiés. Valide la couleur et le son pour lancer le montage.", "ok");
    },
  };
}
