// Étape Épisode : 1. passages retirés (voir episode_passages.js), 2. montage (calcul, se lance tout seul), 3. essai
// d'export de 3 minutes (rendu exactement comme l'export final, lancé tout seul après le montage ; autre départ ou
// autre format au choix) à valider, 4. export 1080p ou 4K avec la durée estimée d'après la vitesse mesurée de
// l'essai, puis la vidéo, « Ouvrir dans le Finder » et le fichier pour Premiere, 5. coupes rapides dans l'export
// (voir episode_coupes.js). Aucune logique de process : statuts, permissions et estimations viennent du serveur.
import {api, media} from "../../api.js";
import {barre, bouton, esc, lier, modale, toast} from "../../ui.js";
import {reessayer} from "../projet.js";
import * as coupes from "./episode_coupes.js";
import * as passages from "./episode_passages.js";
import {agir} from "./shorts_commun.js";

const S = {el: null, v: null, ctx: null, zones: {}, choix: null};
const tache = (v, type) => v.taches.find(t => t.type === type && (t.actif || t.statut === "en_attente"));
const echec = (v, type) => !tache(v, type) && v.taches.find(t => t.type === type && t.statut === "echec");
const finie = (v, type) => v.taches.find(t => t.type === type && t.statut === "terminee");
const FINDER = /Win/i.test(navigator.platform || "") ? "l'Explorateur" : "le Finder";
const FORMATS = {"1080p": "1080p", "4k": "4K"};
const ESSAI_S = 180;

// 540 -> « 9 min », 4500 -> « 1 h 15 »
export function dureeTexte(s) {
  if (s < 90) return "1 min";
  if (s < 3600) return `${Math.round(s / 60)} min`;
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`;
}

// 135 -> « 2:15 » (minute de l'épisode monté)
const mmss = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
// durée de l'épisode monté (lue dans le fichier de montage par le serveur)
const dureeEpisode = v => v.episode.duree || null;

const okchip = t => `<span class="okchip">✓ ${t}</span>`;
function echecHtml(t, quoi) {
  return `<div class="errbox"><div style="flex:1"><b>${quoi} n'a pas marché.</b>
    <span class="muted"> Relance-le. Si ça recommence, envoie un rapport depuis le panneau de droite.</span></div>
    <div class="acts">${bouton({label: "Réessayer", action: "reessayer", attrs: `data-id="${esc(t.id)}"`})}</div></div>`;
}

// ---- 2. montage
function raisonMontage(v) {
  if (!v.passages_revus) return "Vérifie d'abord les passages retirés, juste au-dessus.";
  return "Valide d'abord la couleur et le son.";
}

function montage(v) {
  const st = v.statuts.montage, t = tache(v, "montage"), e = echec(v, "montage");
  if (t) return `<p class="muted small" style="margin-bottom:12px">L'app calcule le montage : la caméra de celui qui
    parle, le plan large de temps en temps, des zooms lents. C'est rapide ; l'essai de 3 minutes suit tout seul.</p>${barre(t)}`;
  if (e) return echecHtml(e, "Le montage");
  if (st === "valide") return `<p class="small">${okchip("Épisode monté")} <span class="muted">${dureeEpisode(v)
    ? `Il dure ${dureeTexte(dureeEpisode(v))}. ` : ""}Regarde l'essai juste en dessous.</span></p>`;
  const reglages = v.statuts.couleur === "valide" && v.statuts.son === "valide";
  const liens = !reglages ? `<div class="acts" style="margin-top:10px">
      ${v.statuts.couleur !== "valide" ? bouton({label: "Aller à la couleur", action: "aller", style: "ghost sm", attrs: 'data-etape="couleur"'}) : ""}
      ${v.statuts.son !== "valide" ? bouton({label: "Aller au son", action: "aller", style: "ghost sm", attrs: 'data-etape="son"'}) : ""}</div>` : "";
  if (st === "a_refaire") {
    return `<div class="att" style="margin-top:0">Tes réglages ou tes passages ont changé depuis le montage :
      il faut remonter l'épisode.</div><div class="acts">${bouton({label: "Remonter l'épisode", action: "monter",
      style: "p", actif: !!v.peut.monter, raison: raisonMontage(v)})}</div>${liens}`;
  }
  if (!v.peut.monter) return `<p class="muted small">Le montage démarre tout seul dès que tout est prêt. ${esc(raisonMontage(v))}</p>${liens}`;
  return `<p class="muted small">Tout est prêt pour le montage.</p>
    <div class="acts">${bouton({label: "Monter l'épisode", action: "monter", style: "p"})}</div>`;
}

// ---- 3. essai d'export de 3 minutes
function cle(v, type) { const t = finie(v, type); return t ? `&t=${encodeURIComponent(t.fin || t.id)}` : ""; }

const estime = (v, quoi, fmt) => ((v.episode.estimations || {})[quoi] || {})[fmt];
const mesure = (v, fmt) => !!((v.episode.estimations || {}).mesure || {})[fmt];
const departMax = v => Math.max(0, (dureeEpisode(v) || 0) - ESSAI_S);

// le choix (départ, format) de l'essai suivant : celui du dernier essai, sinon le début en 1080p
function choix(v) {
  if (!S.choix || S.choix.projet !== v.id) {
    const e = v.episode.essai;
    S.choix = {projet: v.id, debut: e ? e.debut || 0 : 0, format: e ? e.format : "1080p"};
  }
  return S.choix;
}

function essaiVideo(v) {
  const e = v.episode.essai, src = e && e.video, t = tache(v, "essai"), err = echec(v, "essai");
  const st = v.statuts.apercu;
  let html = "";
  if (t) {
    html = `<p class="muted small" style="margin-bottom:12px">L'app rend 3 minutes de l'épisode exactement comme l'export
      final : rushes d'origine, pleine qualité, couleur, son traité et zooms.</p>${barre(t)}`;
  } else if (err) {
    html = echecHtml(err, "L'essai");
  } else if (!src) {
    const txt = st === "a_refaire" ? "L'épisode a changé : l'essai sera refait après le nouveau montage."
      : v.statuts.montage === "valide" ? "Aucun essai pour ce montage : lance-le juste en dessous."
        : "L'essai démarre tout seul dès que l'épisode est monté : 3 minutes rendues comme l'export final.";
    html = `<p class="muted small">${txt}</p>`;
  }
  if (src) {
    const fin = e.debut + e.duree;
    const rendu = e.rendu_s ? ` · rendu en ${dureeTexte(e.rendu_s)}` : "";
    html += `<div class="vid ep"${t ? ' style="margin-top:14px"' : ""}><video controls preload="metadata" playsinline
        src="${esc(media(v.id, src) + cle(v, "essai"))}"></video>
      <p><b style="color:var(--ink)">Regarde ces 3 minutes : c'est exactement le rendu final. Si c'est bon, lance
        l'export complet.</b><br>De ${mmss(e.debut)} à ${mmss(fin)} de l'épisode · ${FORMATS[e.format] || e.format}${rendu}</p></div>`;
  }
  return html;
}

// réglages de l'essai suivant : départ (curseur sur la durée de l'épisode), format, « Refaire l'essai »
function essaiReglages(v) {
  if (v.statuts.montage !== "valide" || tache(v, "essai")) return "";
  const max = departMax(v), deja = !!v.episode.essai;
  const depart = max > 0 ? `<label class="small" style="display:flex;flex-direction:column;gap:6px;flex:1;min-width:220px">
      <span>Départ de l'essai : <b data-o="depart"></b> <span class="muted" data-o="fin"></span></span>
      <input type="range" min="0" max="${Math.round(max)}" step="15" data-in="depart" aria-label="Minute de départ de l'essai"></label>`
    : `<span class="muted small" style="flex:1">L'épisode dure moins de 3 minutes : l'essai le montre en entier.</span>`;
  const seg = `<div class="seg" role="group" aria-label="Format de l'essai">${Object.entries(FORMATS).map(([k, nom]) =>
    `<button type="button" data-act="format_essai" data-format="${k}">${nom}</button>`).join("")}</div>`;
  return `<div class="epf" style="align-items:flex-end">${depart}${seg}
    ${bouton({label: deja ? "Refaire l'essai" : "Lancer l'essai", action: "essayer", style: deja ? "" : "p",
              actif: !!v.peut.essayer, raison: "Un essai est déjà en cours.", attrs: 'data-o="essayer"'})}</div>
    <p class="muted small" style="margin-top:6px" data-o="essai-duree"></p>`;
}

// le choix est appliqué aux champs après chaque dessin : le curseur n'est jamais redessiné pendant qu'on le tire
function appliquerChoix() {
  const v = S.v, el = S.el;
  if (!v || !el) return;
  const c = choix(v), max = departMax(v);
  c.debut = Math.min(Math.max(0, c.debut), max);
  const r = el.querySelector('[data-in="depart"]');
  if (r && document.activeElement !== r) r.value = String(c.debut);
  const o = n => el.querySelector(`[data-o="${n}"]`);
  if (o("depart")) o("depart").textContent = c.debut ? `à ${mmss(c.debut)}` : "le début (ce que le public voit en premier)";
  if (o("fin")) o("fin").textContent = c.debut ? `jusqu'à ${mmss(Math.min(c.debut + ESSAI_S, dureeEpisode(v) || 0))}` : "";
  el.querySelectorAll('[data-act="format_essai"]').forEach(b => b.classList.toggle("on", b.dataset.format === c.format));
  const t = estime(v, "essai", c.format);
  if (o("essai-duree")) o("essai-duree").textContent = t ? `Essai en ${FORMATS[c.format]} : compte environ ${dureeTexte(t)}${
    mesure(v, c.format) ? " (vitesse mesurée sur ton dernier rendu)" : ""}.` : "";
}

function essaiPied(v) {
  const e = v.episode.essai;
  if (!e || !e.video) return "";
  if (v.statuts.apercu === "valide") return `<div class="epf">${okchip("Essai validé")}<span class="muted small">Tu peux lancer l'export complet.</span></div>`;
  return `<div class="epf">${bouton({label: "Valider l'essai", action: "valider_apercu", style: "p",
    actif: v.statuts.apercu === "a_valider" && !tache(v, "essai"), raison: tache(v, "essai") ? "Un nouvel essai est en cours."
      : "Le montage n'est pas à jour : remonte l'épisode."})}
    <span class="muted small">Un plan ne va pas ? Change un passage, la couleur ou le son : l'épisode sera remonté et l'essai refait.</span></div>`;
}

// ---- 4. export
// durée de l'export recalée sur la vitesse de rendu mesurée (essai ou dernier export) x durée de l'épisode
function estimation(v, fmt, court = false) {
  const s = estime(v, "export", fmt), nom = FORMATS[fmt];
  const t = s == null ? "plusieurs fois la durée de l'épisode" : dureeTexte(s);
  return court ? `Compte environ ${t}.` : `En ${nom}, compte environ ${t}${mesure(v, fmt) ? ", d'après la vitesse mesurée sur ton dernier rendu" : ""}.`;
}

function raisonExport(v) {
  if (tache(v, "export")) return "Un export est déjà en cours.";
  return "Valide d'abord l'essai de 3 minutes.";
}

function exportActions(v) {
  const t = tache(v, "export"), e = echec(v, "export"), st = v.statuts.export, d = dureeEpisode(v);
  const actif = !!v.peut.exporter && !t, fait = st === "valide";
  // le bouton principal : le format de l'essai (c'est son rendu exact qu'on vient de voir)
  const principal = (v.episode.essai && v.episode.essai.format) || "1080p";
  const boutons = `<div class="acts">${Object.entries(FORMATS).map(([k, nom]) => bouton({
      label: fait ? `Exporter à nouveau en ${nom}` : `Exporter en ${nom}`, action: "exporter",
      style: !fait && k === principal ? "p big" : "big", actif, raison: raisonExport(v), attrs: `data-format="${k}"`,
      sous: estimation(v, k, true)})).join("")}</div>`;
  const intro = `<p class="muted small">L'export repart des rushes d'origine, en pleine qualité.
    ${d != null ? `L'épisode dure environ ${dureeTexte(d)}.` : ""} Tu peux continuer à travailler pendant ce temps.</p>`;
  const refaire = st === "a_refaire" && !t ? `<div class="att">L'épisode a changé depuis le dernier export.
    Valide le nouvel essai, puis exporte à nouveau.</div>` : "";
  const enCours = t ? `<div style="margin-top:14px">${barre(t)}</div><p class="muted small" style="margin-top:8px">
    Tu seras prévenu à la fin. Tu peux avancer sur les shorts en attendant.</p>` : "";
  if (fait && !t) return `<details class="acc"><summary>Exporter à nouveau, ou dans un autre format</summary>${boutons}</details>`;
  return intro + refaire + (e ? echecHtml(e, "L'export") : "") + (t ? enCours : boutons);
}

function exportVideo(v) {
  const src = v.episode.export, xml = v.episode.xml;
  const premiere = xml ? `<button type="button" class="lnk discret" data-act="premiere"
      title="Ouvre le dossier où se trouve le fichier de montage pour Premiere Pro">Fichier pour Premiere</button>` : "";
  if (!src) return premiere ? `<div class="epf">${premiere}</div>` : "";
  return `<div class="vid ep"><video controls preload="metadata" playsinline src="${esc(media(v.id, src) + cle(v, "export"))}"></video>
    <p>L'épisode complet, prêt à publier.</p></div>
    <div class="epf">${bouton({label: `Ouvrir dans ${FINDER}`, action: "finder", style: "ghost"})}${premiere}
      <span style="flex:1"></span>${bouton({label: "Continuer : Livraison →", action: "aller", style: "p", attrs: 'data-etape="livraison"'})}</div>`;
}

// ---- dessin
const section = (n, titre, nom) => `<div class="card epc"><div class="eph"><span class="epn">${n}</span><b>${titre}</b>
  <span data-z="chip-${nom}"></span></div><div data-z="${nom}"></div></div>`;

function construire() {
  S.el.innerHTML = `<div data-m="episode" class="fade"><div class="stage"><h2>Épisode</h2>
      <p class="intro">Vérifie les coupes, regarde 3 minutes rendues comme l'export final, exporte.</p></div>
    ${section(1, "Passages retirés", "passages")}${section(2, "Montage", "montage")}
    <div class="card epc"><div class="eph"><span class="epn">3</span><b>Essai de 3 minutes</b><span data-z="chip-apercu"></span></div>
      <div data-z="essai-video"></div><div data-z="essai-pied"></div><div data-z="essai-reglages"></div></div>
    <div class="card epc"><div class="eph"><span class="epn">4</span><b>Export de l'épisode</b><span data-z="chip-export"></span></div>
      <div data-z="export"></div><div data-z="export-video"></div></div>
    <div class="card epc"><div class="eph"><span class="epn">5</span><b>Couper dans l'épisode</b><span data-z="chip-coupes"></span></div>
      <div data-z="coupes-intro"></div><div data-z="coupes-video"></div><div data-z="coupes-liste"></div>
      <div data-z="coupes-pied"></div></div></div>`;
  S.zones = {};
}

function zone(n, html) {
  const z = S.el && S.el.querySelector(`[data-z="${n}"]`);
  if (z && S.zones[n] !== html) { S.zones[n] = html; z.innerHTML = html; }
}

const chipTache = t => `<span class="todochip">${t.statut === "en_attente" ? "En attente" : "En cours"}</span>`;
const CHIPS = {valide: '<span class="okchip">✓ Fait</span>', a_valider: '<span class="todochip">À valider</span>',
               a_refaire: '<span class="todochip">À refaire</span>', a_faire: ""};

function majZones() {
  const v = S.v;
  if (!v || !S.el.querySelector("[data-m=episode]")) return;
  const st = v.statuts;
  passages.phrases(v.id, majZones);  // transcript : ce qui se dit dans chaque passage
  zone("chip-passages", CHIPS[st.passages] || "");
  zone("passages", passages.carte(v));
  zone("chip-montage", tache(v, "montage") ? chipTache(tache(v, "montage")) : CHIPS[st.montage] || "");
  zone("montage", montage(v));
  zone("chip-apercu", tache(v, "essai") ? chipTache(tache(v, "essai")) : CHIPS[st.apercu] || "");
  zone("essai-video", essaiVideo(v));
  zone("essai-pied", essaiPied(v));
  zone("essai-reglages", essaiReglages(v));
  appliquerChoix();
  zone("chip-export", tache(v, "export") ? chipTache(tache(v, "export")) : CHIPS[st.export] || "");
  zone("export", exportActions(v));
  zone("export-video", exportVideo(v));
  const ok = st.export === "valide" && !!v.episode.export;
  zone("chip-coupes", tache(v, "coupes") ? chipTache(tache(v, "coupes"))
    : {valide: CHIPS.valide, a_faire: CHIPS.a_valider}[st.coupes] || "");
  zone("coupes-intro", ok ? `<p class="muted small" style="margin-bottom:12px">Un passage à enlever après l'export (hors antenne
    à la fin, une phrase ratée) ? Coupe-le ici : l'app ne réencode que quelques secondes autour de la coupe, pas tout l'épisode.</p>`
    : `<p class="muted small">Une fois l'épisode exporté, tu pourras couper dedans (la fin, un passage au milieu) sans tout réexporter.</p>`);
  zone("coupes-video", ok ? coupes.video(v) : "");
  zone("coupes-liste", ok ? coupes.liste(v) : "");
  zone("coupes-pied", ok ? coupes.pied(v) : "");
  coupes.brancher(S.el);
}

// ---- gestes
function exporter(fmt) {
  const v = S.v, nom = FORMATS[fmt], e = v.episode.essai;
  const autre = e && e.format !== fmt ? `<p class="muted">Ton essai a été rendu en ${esc(FORMATS[e.format] || e.format)} :
    l'export en ${nom} aura le même montage, mais pour voir son rendu exact, refais d'abord l'essai en ${nom}.</p>` : "";
  const m = modale(`<h2>Exporter l'épisode en ${nom} ?</h2>
    <p>${esc(estimation(v, fmt))} L'app travaille depuis les rushes d'origine. Tu peux continuer à travailler pendant ce temps.</p>
    ${autre}
    ${v.episode.export ? `<p class="muted">L'export précédent sera remplacé.</p>` : ""}
    <div class="foot">${bouton({label: "Pas maintenant", action: "non", style: "ghost"})}
      ${bouton({label: `Lancer l'export en ${nom}`, action: "oui", style: "p"})}</div>`);
  lier(m.el, {
    non: () => m.fermer(),
    oui: async b => {
      b.disabled = true;
      await agir(v.id, {type: "lancer_export", format: fmt}, `C'est parti : l'épisode s'exporte en ${nom}.`);
      m.fermer();
    },
  });
}

async function ouvrir(cible) {
  const r = await api.ouvrir(S.v.id, cible);
  if (r.erreur) toast(r.erreur, "no"); else toast(`Le dossier s'ouvre dans ${FINDER}.`, "ok");
}

const gestes = () => ({
  ...passages.gestes(S.v),
  ...coupes.gestes(S.v, S.el),
  aller: b => S.ctx.aller(b.dataset.etape),
  reessayer: b => { b.disabled = true; reessayer(S.v.id, b.dataset.id); },
  monter: async b => { b.disabled = true; if (!(await agir(S.v.id, {type: "lancer_montage"}, "Le montage de l'épisode démarre."))) b.disabled = false; },
  valider_apercu: async b => {
    b.disabled = true;
    if (!(await agir(S.v.id, {type: "valider_apercu"}, "Essai validé. Tu peux lancer l'export complet."))) b.disabled = false;
  },
  format_essai: b => { choix(S.v).format = b.dataset.format; appliquerChoix(); },
  essayer: async b => {
    const c = choix(S.v), nom = FORMATS[c.format];
    b.disabled = true;
    const ok = await agir(S.v.id, {type: "lancer_essai", format: c.format, debut: c.debut},
      `L'essai démarre : 3 minutes ${c.debut ? `à partir de ${mmss(c.debut)}` : "du début"}, en ${nom}.`);
    if (!ok) b.disabled = false;
  },
  exporter: b => exporter(b.dataset.format),
  finder: () => ouvrir("episode"),
  premiere: () => ouvrir("episode"),
});

function surCurseur(ev) {
  const r = ev.target.closest && ev.target.closest('[data-in="depart"]');
  if (!r || !S.v) return;
  choix(S.v).debut = Number(r.value) || 0;
  appliquerChoix();
}

export function rendre(el, v, ctx) {
  S.v = v;
  S.ctx = ctx;
  if (S.el !== el) { S.el = el; S.zones = {}; }
  if (!el._curseurEssai) { el._curseurEssai = true; el.addEventListener("input", surCurseur); }
  if (!el.querySelector("[data-m=episode]")) construire();
  lier(el, gestes());
  majZones();
}
