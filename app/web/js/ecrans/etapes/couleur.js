// Étape Couleur (port de blocImage v1) : une image par caméra, looks, curseurs, LUT, comparateur avant / après,
// harmonisation des caméras. Chaque changement part au serveur (regler_couleur) 400 ms après le dernier geste.
// Les réglages en cours vivent ici : un sondage ne les écrase jamais pendant qu'un envoi est en attente.
import {api, imageCouleur} from "../../api.js";
import {store} from "../../store.js";
import {bouton, esc, lier, nomFichier, teinte, toast} from "../../ui.js";
import {synchroFaite} from "./analyse.js";

const LOOKS = {  // mêmes valeurs que app/services/couleur.py (LOOKS)
  naturel: {lumiere: 0, contraste: 0, saturation: 0, temperature: 0},
  chaud: {lumiere: 0.05, contraste: 0.1, saturation: 0.1, temperature: 0.45},
  contraste: {lumiere: 0, contraste: 0.4, saturation: 0.2, temperature: 0},
  doux: {lumiere: 0.2, contraste: -0.25, saturation: -0.1, temperature: 0.1},
  cinema: {lumiere: -0.05, contraste: 0.3, saturation: -0.25, temperature: 0.2},
};
const LOOKNOM = {naturel: "Naturel", chaud: "Chaud", contraste: "Contrasté", doux: "Doux", cinema: "Cinéma"};
const SLNOM = {lumiere: "Lumière", contraste: "Contraste", saturation: "Saturation", temperature: "Température"};
const VIDE = {look: "", lumiere: 0, contraste: 0, saturation: 0, temperature: 0, lut: null, equilibre: null};

// projet, réglages en cours, caméra affichée, n° du dernier changement et du dernier enregistré
const S = {projet: null, reg: {}, cam: null, version: 0, envoyee: 0, tEnvoi: null, tImg: null, aRefaire: true,
           calme: 0, gele: false, v: null, ctx: null, el: null, zones: {}};

const stable = o => JSON.stringify(o, (k, x) => (x && typeof x === "object" && !Array.isArray(x)
  ? Object.fromEntries(Object.keys(x).sort().map(c => [c, x[c]])) : x));
const fmt = x => { x = +x || 0; return (x > 0 ? "+" : "") + Math.round(x * 100); };
const enAttente = () => S.version !== S.envoyee || !!S.tEnvoi;

function cams(v) {
  return [...v.cams].sort((a, b) => (a !== "LARGE") - (b !== "LARGE"));
}

function nomCam(v, c) {
  if (c === "LARGE") return "Plan large";
  const p = v.personnes.find(x => x.id === c);
  return p ? p.nom : c.charAt(0) + c.slice(1).toLowerCase();
}

function normaliser(v, reg) {
  return Object.fromEntries(cams(v).map(c => [c, {...VIDE, ...((reg || {})[c] || {})}]));
}

// ---- dessin
function vignettes(v) {
  return cams(v).map(c => `<button type="button" class="camb${c === S.cam ? " on" : ""}" data-act="cam" data-cam="${esc(c)}"
    style="${teinte(v, c)}">
    <img data-th="${esc(c)}" src="${esc(imageCouleur(S.projet, c, S.reg[c]))}" alt=""><span>${esc(nomCam(v, c))}</span></button>`).join("");
}

function reglages(r) {
  return `<label class="lab first">Look</label><div class="looks">${Object.keys(LOOKS).map(l =>
      `<button type="button" class="lk${r.look === l ? " on" : ""}" data-act="look" data-look="${l}">${LOOKNOM[l]}</button>`).join("")}</div>
    <label class="lab">Ajuster</label>${Object.keys(SLNOM).map(k => `<label class="sl"><span>${SLNOM[k]}</span>
      <input type="range" min="-1" max="1" step="0.05" value="${+r[k] || 0}" data-sl="${k}" aria-label="${SLNOM[k]}">
      <em data-val="${k}">${fmt(r[k])}</em></label>`).join("")}
    <label class="lab">LUT (facultatif)</label>${r.lut
      ? `<div class="lut"><span>🎞 ${esc(nomFichier(r.lut))}</span><button type="button" class="lnk" data-act="sanslut">Retirer</button></div>`
      : bouton({label: "Importer un fichier .cube", action: "lut", attrs: 'style="width:100%"'})}
    <div class="rgtools" data-z="outils"></div>`;
}

function construire(v) {
  const r = S.reg[S.cam];
  S.el.innerHTML = `<div data-m="couleur" class="fade"><div class="stage"><h2>Couleur</h2>
      <p class="intro">Choisis un look, ajuste, compare. La même couleur sur toutes les caméras.</p></div>
    <div class="rg card"><div class="rgh"><div><span class="rgi">🎨</span><b>Image</b>
      <span class="muted">· ${esc(nomCam(v, S.cam))}</span></div><span data-z="chip"></span></div>
    <div class="camstrip">${vignettes(v)}</div>
    <div class="rgbody"><div><div class="cmp">
        <img src="${esc(imageCouleur(S.projet, S.cam, {}))}" alt="Avant">
        <div class="cmpa" style="clip-path:inset(0 0 0 50%)"><img data-apres src="${esc(imageCouleur(S.projet, S.cam, r))}" alt="Après"></div>
        <div class="cmpl" style="left:50%"></div><span class="cmpt l">Avant</span><span class="cmpt r">Après</span>
        <input type="range" class="cmpr" min="0" max="100" value="50" aria-label="Comparer avant et après" data-cmp></div>
      <p class="muted small" style="margin-top:8px">Glisse sur l'image pour comparer avant et après.</p></div>
      <div>${reglages(r)}</div></div>
    <div class="rgf" data-z="pied"></div></div></div>`;
  S.zones = {};
  S.aRefaire = false;
}

function zone(nom, html) {
  const z = S.el.querySelector(`[data-z="${nom}"]`);
  if (z && S.zones[nom] !== html) { S.zones[nom] = html; z.innerHTML = html; }
}

function majZones() {
  const v = S.v;
  if (!v || !S.el.querySelector("[data-m=couleur]")) return;
  const valide = v.statuts.couleur === "valide" && !enAttente();
  zone("chip", valide ? '<span class="okchip">✓ Validée</span>' : '<span class="todochip">À valider</span>');
  const sync = synchroFaite(v);
  zone("outils", bouton({label: "✨ Harmoniser les caméras", action: "harmo", actif: sync,
      raison: "Attends la synchro : l'analyse cale d'abord les caméras."}) +
    bouton({label: "Appliquer ces réglages à toutes les caméras", action: "toutes", style: "ghost"}));
  zone("pied", `<span class="muted">${enAttente() ? "Enregistrement de tes réglages…"
      : "Une base propre et homogène. Un étalonnage plus fin reste possible dans ton logiciel de montage."}</span>` +
    bouton({label: valide ? "✓ Couleur validée" : "Valider la couleur", action: "valider", style: valide ? "" : "p",
            actif: !valide, raison: "Déjà validée. Change un réglage pour la revalider."}));
}

// ---- envois
function planifierEnvoi() {
  S.version++;
  clearTimeout(S.tEnvoi);
  S.tEnvoi = setTimeout(envoyer, 400);
  majZones();
}

async function envoyer() {
  clearTimeout(S.tEnvoi);
  S.tEnvoi = null;
  const n = S.version, projet = S.projet;
  const r = await api.action(projet, {type: "regler_couleur", reglages: JSON.parse(JSON.stringify(S.reg))});
  if (projet !== S.projet) return r;
  if (r.erreur) { toast(r.erreur, "no"); S.envoyee = S.version; majZones(); return r; }
  if (n === S.version) S.envoyee = n;
  S.calme = Date.now() + 2500;  // un sondage parti avant l'envoi ne doit pas remettre les anciens réglages
  store.mettre(r.projet);
  return r;
}

function rafraichirImage() {
  clearTimeout(S.tImg);
  S.tImg = setTimeout(() => {
    const src = imageCouleur(S.projet, S.cam, S.reg[S.cam]);
    const a = S.el.querySelector("[data-apres]");
    if (a) a.src = src;
    const t = S.el.querySelector(`[data-th="${CSS.escape(S.cam)}"]`);
    if (t) t.src = src;
  }, 180);
}

function refaire() {
  S.aRefaire = true;
  construire(S.v);
  majZones();
}

async function valider(b) {
  b.disabled = true;
  if (enAttente()) {
    const r = await envoyer();
    if (r.erreur) { b.disabled = false; return; }
  }
  const r = await api.action(S.projet, {type: "valider_couleur"});
  if (r.erreur) { toast(r.erreur, "no"); b.disabled = false; return; }
  store.mettre(r.projet);
  const sonOk = r.projet.statuts.son === "valide";
  toast(sonOk ? "Couleur validée." : "Couleur validée. Passe maintenant au son.", "ok");
  if (!sonOk) S.ctx.aller("son");
}

const GESTES = {
  cam: b => { S.cam = b.dataset.cam; refaire(); },
  look: b => { Object.assign(S.reg[S.cam], LOOKS[b.dataset.look], {look: b.dataset.look}); refaire(); planifierEnvoi(); },
  sanslut: () => { S.reg[S.cam].lut = null; refaire(); planifierEnvoi(); },
  lut: async b => {
    b.disabled = true;
    toast("La fenêtre de choix du fichier s'ouvre…");
    const r = await api.choisirLut();
    b.disabled = false;
    if (r.erreur) return toast(r.erreur, "no");
    if (!r.lut) return toast("Aucun fichier choisi.");
    S.reg[S.cam].lut = r.lut;
    refaire();
    planifierEnvoi();
  },
  harmo: async b => {
    b.disabled = true;
    toast("Analyse des couleurs de chaque caméra…");
    const r = await api.harmoniser(S.projet);
    b.disabled = false;
    if (r.erreur) return toast(r.erreur, "no");
    Object.entries(r.gains || {}).forEach(([c, g]) => { if (S.reg[c]) S.reg[c].equilibre = g; });
    refaire();
    planifierEnvoi();
    toast("Couleurs des caméras harmonisées sur le plan large.", "ok");
  },
  toutes: () => {
    const r = S.reg[S.cam];
    for (const c of Object.keys(S.reg)) if (c !== S.cam) S.reg[c] = {...r, equilibre: S.reg[c].equilibre};
    refaire();
    planifierEnvoi();
    toast("Réglages appliqués à toutes les caméras.", "ok");
  },
  valider,
};

function degeler() {
  if (S.gele) { S.gele = false; store.degeler(); }
}

function ecouter(el) {
  el.addEventListener("input", e => {
    const t = e.target;
    if (t.matches("[data-cmp]")) {
      const box = t.closest(".cmp");
      box.querySelector(".cmpa").style.clipPath = `inset(0 0 0 ${t.value}%)`;
      box.querySelector(".cmpl").style.left = t.value + "%";
    } else if (t.dataset.sl) {
      const r = S.reg[S.cam];
      r[t.dataset.sl] = +t.value;
      r.look = "";
      el.querySelector(`[data-val="${t.dataset.sl}"]`).textContent = fmt(t.value);
      el.querySelectorAll(".lk.on").forEach(x => x.classList.remove("on"));
      rafraichirImage();
      planifierEnvoi();
    }
  });
  // pendant qu'on glisse un curseur, la page ne se redessine pas
  el.addEventListener("pointerdown", e => {
    if (e.target.matches("input[type=range]") && !S.gele) { S.gele = true; store.geler(); }
  });
  for (const ev of ["pointerup", "pointercancel", "change"]) el.addEventListener(ev, degeler);
  el.addEventListener("error", e => {
    if (e.target.tagName === "IMG") (e.target.closest(".cmp, .camb") || e.target).classList.add("ko");
  }, true);
}

export function rendre(el, v, ctx) {
  S.v = v;
  S.ctx = ctx;
  if (S.el !== el) { S.el = el; ecouter(el); }
  if (S.projet !== v.id) {
    Object.assign(S, {projet: v.id, version: 0, envoyee: 0, reg: normaliser(v, v.couleur.reglages), aRefaire: true});
    clearTimeout(S.tEnvoi);
    S.tEnvoi = null;
    S.cam = cams(v)[0];
  } else if (!enAttente() && !S.gele && Date.now() > S.calme) {
    const serveur = normaliser(v, v.couleur.reglages);
    if (stable(serveur) !== stable(S.reg)) { S.reg = serveur; S.aRefaire = true; }  // changé ailleurs
  }
  if (!cams(v).includes(S.cam)) { S.cam = cams(v)[0]; S.aRefaire = true; }
  if (!S.cam) {
    el.innerHTML = `<div class="stage"><h2>Couleur</h2><p class="intro">Ce podcast n'a pas de caméra : rien à régler ici.</p></div>`;
    return;
  }
  if (S.aRefaire || !el.querySelector("[data-m=couleur]")) construire(v);
  lier(el, GESTES);
  majZones();
}
