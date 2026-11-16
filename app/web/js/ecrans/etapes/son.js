// Étape Son (port de blocSon v1) : écoute avant / après, volume de chaque voix, force de l'anti-écho,
// réduction du souffle par micro. Un changement part au serveur (regler_son) qui recalcule le son en tâche :
// la validation attend la fin du recalcul, avec la raison affichée.
import {api, media} from "../../api.js";
import {store} from "../../store.js";
import {barre, bouton, esc, lier, teinte, toast} from "../../ui.js";
import {reessayer} from "../projet.js";

const AMIX = {leger: "Le micro de celui qui se tait baisse un peu. Le plus naturel quand la pièce ne résonne pas.",
              normal: "Conseillé : l'écho d'un micro dans l'autre disparaît, les voix restent naturelles.",
              fort: "Pour une pièce qui résonne : le micro de celui qui se tait baisse beaucoup."};
const FORCES = [["leger", "Léger"], ["normal", "Normal"], ["fort", "Fort"]];

const S = {projet: null, reg: null, version: 0, envoyee: 0, tEnvoi: null, calme: 0, ver: "apres", el: null, v: null,
           niveaux: null, cleNiveaux: null, cleEcoute: null, zones: {}};
const enAttente = () => S.version !== S.envoyee || !!S.tEnvoi;
const virgule = x => String(x).replace(".", ",");

function normaliser(r) {
  return {automix: (r && r.automix) || "normal", debruitage: [...((r && r.debruitage) || [])].sort()};
}

const nom = (v, id) => (v.personnes.find(p => p.id === id) || {nom: id}).nom;

// ---- dessin
function controles(v) {
  const r = S.reg;
  return `<label class="lab first">Écho entre les micros</label><div class="seg">${FORCES.map(([k, l]) =>
      `<button type="button" class="${r.automix === k ? "on" : ""}" data-act="force" data-force="${k}">${l}</button>`).join("")}</div>
    <p class="muted small" style="margin-top:8px">${esc(AMIX[r.automix] || "")}</p>
    <label class="lab">Réduire le souffle</label>${v.mics.map(m => `<label class="tog"><input type="checkbox" data-deb="${esc(m)}"
      ${r.debruitage.includes(m) ? "checked" : ""}> <span class="qui-c" style="${teinte(v, m)}">Micro de ${esc(nom(v, m))}</span></label>`).join("")}
    <p class="muted small">À cocher seulement si tu entends un souffle continu sur ce micro.</p>`;
}

function niveaux(v) {
  const n = S.niveaux;
  if (v.son_a_recalculer) return `<p class="muted small">Les volumes seront mesurés à la fin du recalcul.</p>`;
  if (!n) return `<p class="muted small" style="display:flex;gap:8px;align-items:center"><span class="spin"></span>Mesure des voix…</p>`;
  const nv = v.mics.filter(m => n[m] != null).map(m => [nom(v, m), n[m]]);
  if (!nv.length) return `<p class="muted small">Les volumes ne sont pas encore mesurables.</p>`;
  const tri = [...nv].sort((a, b) => a[1] - b[1]);
  const ecart = tri.length > 1 ? tri[tri.length - 1][1] - tri[0][1] : 0;
  const verdict = ecart < 2 ? `<p class="verd ok">✓ Les voix sont au même niveau.</p>`
    : `<p class="verd w">⚠ ${esc(tri[0][0])} est ${virgule(ecart.toFixed(1))} dB plus bas que ${esc(tri[tri.length - 1][0])}.</p>`;
  return nv.map(([nm, x]) => `<div class="lv" style="${teinte(v, nm)}"><span>${esc(nm)}</span><div class="lvm"><i style="left:${
    Math.max(0, Math.min(100, (x + 30) / 20 * 100))}%"></i></div><em>${virgule(x)} LUFS</em></div>`).join("") + verdict;
}

function recalcul(v) {
  if (!v.son_a_recalculer && !enAttente()) return "";
  const t = v.taches.find(x => x.type === "son" && (x.actif || x.statut === "en_attente"));
  if (enAttente()) return `<div class="bgtask"><span class="dot"></span><span>Envoi de ton réglage…</span></div>`;
  if (t) return `<div class="card" style="margin-top:16px"><p style="margin:0 0 10px"><b>Nouveau réglage : le son se recalcule.</b>
    Tu pourras réécouter et valider dès que c'est fini.</p>${barre(t)}</div>`;
  const echec = v.taches.find(x => x.type === "son" && x.statut === "echec");
  if (echec) return `<div class="errbox"><div style="flex:1"><b>Le recalcul du son n'a pas marché.</b>
    <span class="muted"> Relance-le. Si ça recommence, envoie un rapport.</span></div>
    <div class="acts">${bouton({label: "Réessayer", action: "reessayer", attrs: `data-id="${esc(echec.id)}"`})}</div></div>`;
  return `<div class="errbox" style="background:var(--warn-soft);border-color:transparent"><div style="flex:1">
    <b style="color:var(--warn)">Ton dernier réglage n'est pas encore appliqué.</b></div>
    <div class="acts">${bouton({label: "Recalculer le son", action: "recalculer", style: "p"})}</div></div>`;
}

function pied(v) {
  const valide = v.statuts.son === "valide" && !enAttente();
  const bloque = v.son_a_recalculer || enAttente();
  return `<span class="muted">${bloque ? "Le son se recalcule (environ 1 min). Réécoute ensuite avant de valider."
      : "Ce son sert aux shorts et à l'épisode."}</span>` +
    bouton({label: valide ? "✓ Son validé" : "Valider le son", action: "valider", style: valide ? "" : "p",
            actif: !valide && !bloque,
            raison: bloque ? "Attends la fin du recalcul du son : réécoute-le avant de valider."
              : "Déjà validé. Change un réglage pour le revalider."});
}

function construire(v) {
  S.el.innerHTML = `<div data-m="son" class="fade"><div class="stage"><h2>Son</h2>
      <p class="intro">Écoute, ajuste si besoin, puis valide.</p></div>
    <div class="rg card"><div class="rgh"><div><span class="rgi">🔊</span><b>Son</b>
      <span class="muted">· ${v.mics.length} micro${v.mics.length > 1 ? "s" : ""}</span></div><span data-z="chip"></span></div>
    <div data-z="recalcul" style="padding:0 22px"></div>
    <div class="rgbody2"><div><label class="lab first">Écouter</label>
        <div class="ab"><button type="button" class="abplay" data-act="jouer" aria-label="Lecture">▶</button>
          <div style="flex:1"><div class="seg" data-z="versions"></div><div class="abbar"><i data-prog></i></div>
          <p class="muted small">16 s de conversation, au même volume dans les deux versions. Compare au casque.</p></div></div>
        <audio preload="none" data-audio></audio>
        <label class="lab">Volume de chaque voix</label><div data-z="niveaux"></div></div>
      <div data-z="controles"></div></div>
    <div class="rgf" data-z="pied"></div></div></div>`;
  S.zones = {};
  const a = S.el.querySelector("[data-audio]");
  a.addEventListener("timeupdate", () => {
    const p = S.el.querySelector("[data-prog]");
    if (p) p.style.width = (100 * a.currentTime / (a.duration || 16)) + "%";
  });
  a.addEventListener("pause", () => { bouton_jouer("▶"); });
  a.addEventListener("playing", () => { bouton_jouer("❚❚"); });
  a.addEventListener("error", () => { bouton_jouer("▶"); if (a.getAttribute("src")) toast("Cet extrait ne se lit pas pour l'instant.", "no"); });
}

function bouton_jouer(t) {
  const b = S.el.querySelector("[data-act=jouer]");
  if (b) b.textContent = t;
}

function zone(n, html) {
  const z = S.el.querySelector(`[data-z="${n}"]`);
  if (z && S.zones[n] !== html) { S.zones[n] = html; z.innerHTML = html; }
}

function majZones() {
  const v = S.v;
  if (!v || !S.el.querySelector("[data-m=son]")) return;
  const valide = v.statuts.son === "valide" && !enAttente();
  zone("chip", valide ? '<span class="okchip">✓ Validé</span>' : '<span class="todochip">À valider</span>');
  zone("recalcul", recalcul(v));
  zone("versions", [["avant", "Avant"], ["apres", "Après traitement"]].map(([k, l]) =>
    `<button type="button" class="${S.ver === k ? "on" : ""}" data-act="version" data-v="${k}">${l}</button>`).join(""));
  zone("niveaux", niveaux(v));
  zone("controles", controles(v));
  zone("pied", pied(v));
}

// ---- niveaux des voix : mesurés après chaque recalcul
function chargerNiveaux(v) {
  const cle = v.id + ":" + v.son.applique;
  if (v.son_a_recalculer || S.cleNiveaux === cle) return;
  S.cleNiveaux = cle;
  S.niveaux = null;
  api.niveaux(v.id).then(r => {
    if (S.cleNiveaux !== cle) return;
    S.niveaux = r.erreur ? {} : (r.niveaux || {});
    majZones();
  });
}

// ---- écoute A/B
async function charger(a, ver) {
  const r = await api.ecoute(S.projet, ver);
  if (r.erreur) { toast(r.erreur, "no"); return false; }
  a.preload = "auto";  // sinon, sans lecture, les métadonnées (et la reprise au même moment) n'arrivent jamais
  a.src = media(S.projet, r.src);
  a.dataset.v = ver + ":" + S.cleEcoute;
  return true;
}

async function jouer() {
  const a = S.el.querySelector("[data-audio]");
  if (!a.paused) { a.pause(); return; }
  if (a.dataset.v !== S.ver + ":" + S.cleEcoute) {
    bouton_jouer("…");
    if (!(await charger(a, S.ver))) { bouton_jouer("▶"); return; }
  }
  try { await a.play(); } catch (e) { bouton_jouer("▶"); }
}

async function version(ver) {
  S.ver = ver;
  majZones();
  const a = S.el.querySelector("[data-audio]");
  if (!a.getAttribute("src")) return;
  const t = a.currentTime, jouait = !a.paused;
  a.pause();
  if (!(await charger(a, ver))) return;
  a.addEventListener("loadedmetadata", () => { a.currentTime = t; if (jouait) a.play().catch(() => {}); }, {once: true});
}

// ---- envois
function planifierEnvoi() {
  S.version++;
  clearTimeout(S.tEnvoi);
  S.tEnvoi = setTimeout(envoyer, 600);
  majZones();
}

async function envoyer() {
  clearTimeout(S.tEnvoi);
  S.tEnvoi = null;
  const n = S.version, projet = S.projet;
  const r = await api.action(projet, {type: "regler_son", reglages: normaliser(S.reg)});
  if (projet !== S.projet) return;
  if (r.erreur) { toast(r.erreur, "no"); S.envoyee = S.version; majZones(); return; }
  if (n === S.version) S.envoyee = n;
  S.calme = Date.now() + 2500;
  store.mettre(r.projet);
}

const GESTES = {
  force: b => { S.reg.automix = b.dataset.force; planifierEnvoi(); },
  jouer,
  version: b => version(b.dataset.v),
  recalculer: b => { b.disabled = true; S.version++; envoyer(); },
  reessayer: b => { b.disabled = true; reessayer(S.projet, b.dataset.id); },
  valider: async b => {
    b.disabled = true;
    const r = await api.action(S.projet, {type: "valider_son"});
    if (r.erreur) { toast(r.erreur, "no"); b.disabled = false; return; }
    store.mettre(r.projet);
    const couleurOk = r.projet.statuts.couleur === "valide";
    toast(couleurOk ? "Son validé. Passe maintenant aux shorts." : "Son validé. Il reste à valider la couleur.", "ok");
    S.ctx.aller(couleurOk ? "shorts" : "couleur");
  },
};

function attente(v) {
  const t = v.taches.find(x => x.type === "analyse" && (x.actif || x.statut === "en_attente"));
  return `<div class="stage"><h2>Son</h2><p class="intro">Le son se règle une fois l'analyse terminée :
    l'app doit d'abord nettoyer les voix. Règle la couleur en attendant.</p></div>
    ${t ? `<div class="card" style="margin-top:20px">${barre(t)}</div>` : ""}
    <div class="acts">${bouton({label: "Aller à la couleur →", action: "couleur", style: "p"})}</div>`;
}

export function rendre(el, v, ctx) {
  S.v = v;
  S.ctx = ctx;
  if (S.el !== el) {
    S.el = el;
    el.addEventListener("change", e => {
      const d = e.target.dataset && e.target.dataset.deb;
      if (!d || !S.reg) return;
      S.reg.debruitage = S.reg.debruitage.filter(x => x !== d).concat(e.target.checked ? [d] : []).sort();
      planifierEnvoi();
    });
  }
  if (S.projet !== v.id) {
    Object.assign(S, {projet: v.id, reg: normaliser(v.son.reglages), version: 0, envoyee: 0, cleNiveaux: null, ver: "apres"});
    clearTimeout(S.tEnvoi);
    S.tEnvoi = null;
  } else if (!enAttente() && Date.now() > S.calme) {
    S.reg = normaliser(v.son.reglages);  // changé ailleurs, ou enregistré
  }
  if (v.statuts.analyse !== "valide") {
    const h = attente(v);
    if (S.zones.attente !== h || !el.querySelector("[data-m=attente]")) {
      el.innerHTML = `<div data-m="attente" class="fade">${h}</div>`;
      S.zones = {attente: h};
    }
    lier(el, {couleur: () => ctx.aller("couleur")});
    return;
  }
  S.cleEcoute = v.son.applique;  // l'extrait « après » change à chaque recalcul
  if (!el.querySelector("[data-m=son]")) construire(v);
  chargerNiveaux(v);
  lier(el, GESTES);
  majZones();
}
