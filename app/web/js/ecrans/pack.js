// Éditeur d'un pack : les réglages à gauche, l'aperçu à droite (une image rendue par le vrai moteur des shorts,
// redessinée 0,25 s après chaque changement ; l'image d'avant reste affichée tant que la nouvelle n'est pas prête).
// Sur téléphone, l'aperçu passe en haut et une vignette flottante le garde en vue pendant qu'on règle plus bas.
// Rien n'est enregistré avant « Enregistrer » ; enregistrer un pack utilisé rend « à refaire » les shorts déjà
// fabriqués avec lui (le serveur le dit, l'écran l'annonce). Lot A : seulement ce que le moteur sait déjà faire.
import {api, apercuPack, exportPack} from "../api.js";
import {aller} from "../routeur.js";
import {store} from "../store.js";
import {bouton, esc, lier, modale, propre, toast} from "../ui.js";

const DELAI = 250;
const E = {id: null, vue: null, brouillon: null, sale: false, fond: "", minuterie: null, num: 0, url: null, el: null,
           obs: null};

const CHAMPS = [
  ["Sous-titres", "💬", [
    {cle: "sous_titres.police", type: "police", label: "Police", ajout: "police"},
    {cle: "sous_titres.casse", type: "choix", label: "Casse", choix: [["normale", "Normale"], ["majuscules", "MAJUSCULES"]]},
    {cle: "sous_titres.taille", type: "curseur", label: "Taille", min: 30, max: 120, pas: 1},
    {cle: "sous_titres.graisse", type: "curseur", label: "Graisse", min: 100, max: 900, pas: 100},
    {cle: "sous_titres.y_bas", type: "curseur", label: "Hauteur depuis le bas", min: 150, max: 1100, pas: 5, unite: " px"},
    {cle: "sous_titres.x", type: "curseur", label: "Décalage horizontal", min: -200, max: 200, pas: 1, unite: " px"},
    {cle: "sous_titres.echelle_cle", type: "curseur", label: "Taille du mot clé", min: 0.8, max: 2, pas: 0.05, fois: true},
    {cle: "sous_titres.graisse_cle", type: "curseur", label: "Graisse du mot clé", min: 100, max: 900, pas: 100},
  ]],
  ["Couleurs", "🎨", [
    {cle: "couleur", type: "couleur", label: "Accent", aide: "mot clé, accroche"},
    {cle: "teintes.clair", type: "couleur", label: "Teinte claire", aide: "textes sur fond"},
    {cle: "teintes.fond", type: "couleur", label: "Teinte de fond", aide: "cartons"},
  ]],
  ["Accroche", "⚡", [
    {cle: "police_accent", type: "police", label: "Police du mot clé de l'accroche", ajout: "police"},
    {cle: "accroche_y", type: "curseur", label: "Position verticale", min: 0.04, max: 0.5, pas: 0.002, pct: true},
    {cle: "defauts_short.accroche_duree", type: "curseur", label: "Durée à l'écran", min: 1, max: 8, pas: 0.1, unite: " s"},
  ]],
  ["Logo", "🏷️", [
    {cle: "logo", type: "case", label: "Afficher le logo"},
    {cle: "logo_fichier", type: "logo", label: "Fichier du logo", ajout: "logo"},
    {cle: "logo_position", type: "choix", label: "Emplacement", choix: [["haut", "En haut à droite"], ["bas", "En bas, au centre"]]},
    {cle: "logo_marge", type: "curseur", label: "Marge depuis le bord", min: 0, max: 0.15, pas: 0.005, pct: true},
  ]],
  ["Musique et fin", "🎵", [
    {cle: "defauts_short.sans_musique", type: "case", inverse: true, label: "Musique sous la voix"},
    {cle: "sans_fin", type: "case", inverse: true, label: "Écran de fin avec le logo"},
    {cle: "musique.fichier", type: "musique", label: "Morceau"},
    {cle: "musique.lufs", type: "curseur", label: "Volume de la musique", min: -36, max: -14, pas: 1, unite: " LUFS"},
  ]],
];
const TOUS = CHAMPS.flatMap(([, , cs]) => cs);

const lire = (o, cle) => cle.split(".").reduce((x, k) => (x == null ? x : x[k]), o);
function ecrire(o, cle, v) {
  const ks = cle.split("."), der = ks.pop();
  ks.reduce((x, k) => (x[k] = x[k] || {}), o)[der] = v;
}
const hex = c => "#" + (Array.isArray(c) ? c : [0, 0, 0]).map(x => Math.round(x).toString(16).padStart(2, "0")).join("");
const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const virgule = x => String(x).replace(".", ",");

function texteValeur(c, v) {
  if (v == null || Number.isNaN(Number(v))) return "";
  if (c.pct) return `${virgule(Math.round(v * 1000) / 10)} %`;
  if (c.fois) return `× ${virgule(Number(v).toFixed(2))}`;
  return `${virgule(Math.round(v * 10) / 10)}${c.unite || ""}`;
}

function liste(c, v, dis) {
  const options = [...(c.type === "police" ? E.vue.polices : c.type === "logo" ? E.vue.logos : E.vue.musiques) || []];
  if (v && !options.includes(v)) options.unshift(v);  // jamais de changement muet si le fichier manque
  const vide = c.type === "logo" ? `<option value="">(aucun fichier)</option>` : "";
  return `<select class="inp" data-cle="${c.cle}" data-type="${c.type === "logo" ? "fichier_vide" : "texte"}"
    aria-label="${esc(c.label)}"${dis}>${vide}${options.map(o =>
      `<option value="${esc(o)}"${o === v ? " selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
}

function controle(c, lecture) {
  const v = lire(E.brouillon, c.cle), dis = lecture ? " disabled" : "";
  if (c.type === "curseur") {
    return `<label class="lab" for="pk-${c.cle}">${esc(c.label)} <b data-val="${c.cle}">${texteValeur(c, v)}</b></label>
      <input type="range" id="pk-${c.cle}" data-cle="${c.cle}" data-type="nombre" min="${c.min}" max="${c.max}"
        step="${c.pas}" value="${esc(v)}"${dis}>`;
  }
  if (c.type === "couleur") {
    return `<label class="pk-coul"><input type="color" data-cle="${c.cle}" data-type="rgb" value="${hex(v)}"${dis}>
      <span>${esc(c.label)}<small data-hex="${c.cle}">${hex(v)} · ${esc(c.aide)}</small></span></label>`;
  }
  if (c.type === "case") {
    const on = c.inverse ? !v : !!v;
    return `<label class="pk-case"><input type="checkbox" data-cle="${c.cle}" data-type="${c.inverse ? "case_inverse" : "case"}"
      ${on ? "checked" : ""}${dis}> ${esc(c.label)}</label>`;
  }
  if (c.type === "choix") {
    return `<span class="lab">${esc(c.label)}</span><div class="tabs pk-seg" role="group" aria-label="${esc(c.label)}">${
      c.choix.map(([k, l]) => `<button type="button" data-act="choix" data-cle="${c.cle}" data-val="${esc(k)}"
        class="${k === v ? "on" : ""}" aria-pressed="${k === v}"${dis}>${esc(l)}</button>`).join("")}</div>`;
  }
  const ajout = c.ajout && !lecture ? `<div class="pk-ajout">${bouton({
    label: c.ajout === "logo" ? "＋ Ajouter un logo (.png)…" : "＋ Ajouter une police (.ttf, .otf)…",
    action: "ajouter", style: "lnk", attrs: `data-sorte="${c.ajout}" data-cible="${c.cle}"`})}</div>` : "";
  return `<label class="lab">${esc(c.label)}</label>${liste(c, v, dis)}${ajout}`;
}

function barreEnregistrer() {
  if (E.vue.integre) return "";
  return `<div class="pk-save${E.sale ? " sale" : ""}" data-save>
    <span class="etat">${E.sale ? "Changements pas encore enregistrés" : "Tout est enregistré"}</span>
    ${bouton({label: "Annuler", action: "annuler", style: "ghost", actif: E.sale})}
    ${bouton({label: "Enregistrer", action: "enregistrer", style: "p", actif: E.sale})}</div>`;
}

function majBarre() {
  const z = E.el && E.el.querySelector("[data-save]");
  if (z) z.outerHTML = barreEnregistrer();
}

function teinte() {
  const c = lire(E.brouillon, "couleur");
  if (E.el && Array.isArray(c)) E.el.style.setProperty("--pk", `rgb(${c.join(",")})`);
}

function avertissement(v) {
  if (v.integre) {
    return `<div class="att">« Aucun pack » est livré avec l'app : sous-titres blancs, sans logo ni musique.
      Duplique-le pour en faire un pack à toi.</div>`;
  }
  if (!v.utilise_par.length) return `<p class="muted small" style="margin-top:12px">Pas encore utilisé par un podcast.</p>`;
  return `<p class="muted small" style="margin-top:12px">Utilisé par ${v.utilise_par.map(t => `« ${esc(t)} »`).join(", ")}.
    Enregistrer rendra « à refaire » les shorts déjà fabriqués avec ce pack.</p>`;
}

function dessiner() {
  const v = E.vue, lecture = v.integre;
  const ancienne = E.url;  // l'image déjà rendue reste affichée pendant le nouveau rendu
  E.el.innerHTML = `<div class="fade">
    <div class="hero"><h1>${esc(v.nom)}</h1><span class="sp"></span>
      ${bouton({label: "← Tous les packs", action: "retour", style: "ghost"})}
      ${lecture ? bouton({label: "Dupliquer pour modifier", action: "dupliquer", style: "p"})
        : `<a class="btn ghost" href="${esc(exportPack(v.id))}" download="${esc(v.id)}.zip">Exporter</a>
           ${bouton({label: "Dupliquer", action: "dupliquer"})}`}</div>
    ${avertissement(v)}
    <div class="pk-edit">
      <div class="pk-form">${CHAMPS.map(([titre, ic, cs]) => `<section class="card pk-sect"><h3><i aria-hidden="true">${ic}</i>${esc(titre)}</h3>
        <div class="pk-grille">${cs.map(c => `<div class="pk-ch">${controle(c, lecture)}</div>`).join("")}</div></section>`).join("")}
        ${barreEnregistrer()}</div>
      <aside class="pk-apercu" aria-label="Aperçu">
        <div class="pk-cadre" data-cadre><img data-apercu alt="Aperçu du short habillé par ce pack"${ancienne ? ` src="${ancienne}"` : ""}>
          <span class="pk-rendu" data-attente hidden><span class="spin"></span>Rendu…</span>
          <p class="pk-msg" data-msg role="alert"></p></div>
        <div class="pk-fond"><label class="lab" for="pk-fond">Image de fond de l'aperçu</label>
          <select class="inp" id="pk-fond" data-fond><option value="">Fond neutre</option>${v.fonds.map(f =>
            `<option value="${esc(f.id)}"${f.id === E.fond ? " selected" : ""}>${esc(f.titre)}</option>`).join("")}</select>
          <p class="muted small">Rendu par le moteur des shorts : ce que tu vois, c'est ce qui sortira.</p></div>
      </aside></div>
    <button type="button" class="pk-mini" data-act="voir_apercu" aria-label="Revoir l'aperçu"><img data-mini alt=""${
      ancienne ? ` src="${ancienne}"` : ""}><span class="spin" data-attente-mini hidden></span></button>
    <input type="file" data-fichier hidden></div>`;
  teinte();
  observer();
  apercu();
}

// vignette flottante (téléphone) : visible quand le grand aperçu est sorti de l'écran
function observer() {
  if (E.obs) E.obs.disconnect();
  E.obs = null;
  const cadre = E.el.querySelector("[data-cadre]"), mini = E.el.querySelector(".pk-mini");
  if (!cadre || !mini || !("IntersectionObserver" in window)) return;
  E.obs = new IntersectionObserver(([e]) => mini.classList.toggle("on", !e.isIntersecting && !!E.url), {threshold: 0.15});
  E.obs.observe(cadre);
}

const planifier = () => { clearTimeout(E.minuterie); E.minuterie = setTimeout(apercu, DELAI); };

function attente(el, on) {
  el.querySelector("[data-attente]").hidden = !on;
  el.querySelector("[data-attente-mini]").hidden = !on;
}

async function apercu() {
  clearTimeout(E.minuterie);
  const n = ++E.num, el = E.el;
  if (!el) return;
  const img = el.querySelector("[data-apercu]"), mini = el.querySelector("[data-mini]");
  const msg = el.querySelector("[data-msg]"), cadre = el.querySelector("[data-cadre]");
  attente(el, true);
  let erreur = "";
  try {
    const r = await fetch(apercuPack(E.id, E.vue.integre ? null : E.brouillon, E.fond), {cache: "no-store"});
    if (n !== E.num || el !== E.el) return;
    if (!r.ok) {
      let d = {};
      try { d = await r.json(); } catch (x) { d = {}; }
      erreur = propre(d.erreur || "L'aperçu n'a pas pu être dessiné.");
      return;
    }
    const u = URL.createObjectURL(await r.blob());
    if (n !== E.num || el !== E.el) { URL.revokeObjectURL(u); return; }
    // on attend que la nouvelle image soit décodée avant de remplacer l'ancienne : pas de clignotement
    const pret = new Image();
    pret.src = u;
    try { await pret.decode(); } catch (x) { /* image illisible : on l'affiche quand même, le navigateur dira */ }
    if (n !== E.num || el !== E.el) { URL.revokeObjectURL(u); return; }
    const avant = E.url;
    E.url = u;
    img.src = u;
    mini.src = u;
    if (avant) setTimeout(() => URL.revokeObjectURL(avant), 1000);
  } catch (x) {
    if (n === E.num) erreur = "Impossible de joindre l'app. Relance « Lancer ».";
  } finally {
    if (n === E.num && el === E.el) {
      attente(el, false);
      msg.textContent = erreur;
      cadre.classList.toggle("ko", !!erreur);
    }
  }
}

function valeur(t) {
  switch (t.dataset.type) {
    case "nombre": return Number(t.value);
    case "rgb": return rgb(t.value);
    case "case": return t.checked;
    case "case_inverse": return !t.checked;
    case "fichier_vide": return t.value || null;
    default: return t.value;
  }
}

function changer(cle, v) {
  ecrire(E.brouillon, cle, v);
  if (!E.sale) { E.sale = true; majBarre(); }
  if (cle === "couleur") teinte();
  planifier();
}

function brancher(el) {
  el.addEventListener("input", e => {
    const t = e.target;
    if (!t.dataset.cle || t.matches("select")) return;
    changer(t.dataset.cle, valeur(t));
    const c = TOUS.find(x => x.cle === t.dataset.cle);
    const lab = el.querySelector(`[data-val="${CSS.escape(t.dataset.cle)}"]`);
    if (lab && c) lab.textContent = texteValeur(c, lire(E.brouillon, c.cle));
    const h = el.querySelector(`[data-hex="${CSS.escape(t.dataset.cle)}"]`);
    if (h && c) h.textContent = `${t.value} · ${c.aide}`;
  });
  el.addEventListener("change", e => {
    const t = e.target;
    if (t.matches("[data-fond]")) { E.fond = t.value; apercu(); }
    else if (t.matches("[data-fichier]")) envoyerFichier(t);
    else if (t.matches("select[data-cle]")) changer(t.dataset.cle, valeur(t));
  });
}

async function envoyerFichier(champ) {
  const f = champ.files && champ.files[0], cle = champ.dataset.cible;
  champ.value = "";
  if (!f) return;
  toast(`Envoi de « ${f.name} »…`);
  const r = await api.fichierPack(E.id, f);
  if (r.erreur) { toast(r.erreur, "no"); return; }
  E.vue = {...E.vue, polices: r.pack.polices, logos: r.pack.logos, musiques: r.pack.musiques, fichiers: r.pack.fichiers};
  ecrire(E.brouillon, cle, r.fichier);
  if (cle === "logo_fichier") ecrire(E.brouillon, "logo", true);
  E.sale = true;
  dessiner();
  toast(`« ${r.fichier} » ajouté au pack. Enregistre pour le garder dans tes réglages.`, "ok");
}

// quitter avec des changements pas enregistrés : on demande d'abord
function quitter(suite) {
  if (!E.sale) { suite(); return; }
  const m = modale(`<h2>Quitter sans enregistrer ?</h2>
    <p class="muted">Tes derniers réglages de « ${esc(E.vue.nom)} » seront perdus.</p>
    <div class="foot">${bouton({label: "Rester", action: "non", style: "ghost"})}
      ${bouton({label: "Quitter sans enregistrer", action: "oui", style: "danger"})}</div>`, {classe: "pk-petite"});
  lier(m.el, {non: () => m.fermer(), oui: () => { E.sale = false; m.fermer(); suite(); }});
}

const gestes = {
  retour: () => quitter(() => aller({ecran: "packs"})),
  voir_apercu: () => E.el.querySelector("[data-cadre]").scrollIntoView({behavior: "smooth", block: "center"}),
  choix: b => {
    changer(b.dataset.cle, b.dataset.val);
    b.parentElement.querySelectorAll("button").forEach(x => {
      x.classList.toggle("on", x === b);
      x.setAttribute("aria-pressed", String(x === b));
    });
  },
  annuler: () => { E.brouillon = structuredClone(E.vue.reglages); E.sale = false; dessiner(); },
  enregistrer: async () => {
    const r = await api.modifierPack(E.id, E.brouillon);
    if (r.erreur) {
      toast(r.erreur, "no");
      const msg = E.el.querySelector("[data-msg]");
      if (msg) { msg.textContent = propre(r.erreur); E.el.querySelector("[data-cadre]").classList.add("ko"); }
      return;
    }
    E.vue = r.pack;
    E.brouillon = structuredClone(r.pack.reglages);
    E.sale = false;
    majBarre();
    toast(r.podcasts ? `Pack enregistré. Les shorts déjà fabriqués avec ce pack sont à refaire (${r.podcasts} podcast${
      r.podcasts > 1 ? "s" : ""}).` : "Pack enregistré.", "ok");
    store.rafraichir();
  },
  dupliquer: () => quitter(async () => {
    const r = await api.creerPack(`${E.vue.nom} (copie)`.slice(0, 40), E.id);
    if (r.erreur) { toast(r.erreur, "no"); return; }
    toast("Pack dupliqué : tu règles maintenant la copie.", "ok");
    aller({ecran: "pack", pack: r.pack});
  }),
  ajouter: b => {
    const f = E.el.querySelector("[data-fichier]");
    f.dataset.cible = b.dataset.cible;
    f.accept = b.dataset.sorte === "logo" ? ".png,image/png" : ".ttf,.otf,font/ttf,font/otf";
    f.click();
  },
};

// liens internes (fil d'Ariane, logo) et fermeture de l'onglet pendant qu'un brouillon attend
const enEdition = () => E.sale && E.el && E.el.isConnected;
window.addEventListener("click", e => {
  const a = e.target.closest && e.target.closest("a[data-nav]");
  if (!a || !enEdition() || E.el.contains(a) || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
  e.preventDefault();
  e.stopPropagation();
  quitter(() => a.click());
}, true);
window.addEventListener("beforeunload", e => { if (enEdition()) { e.preventDefault(); e.returnValue = ""; } });

export function rendrePack(page, vue) {
  document.title = vue.nom;
  if (!page.querySelector(`[data-pack-ed="${CSS.escape(vue.id)}"]`)) {
    // nouvel écran (ou autre pack) : un conteneur à lui, les écouteurs meurent avec lui
    clearTimeout(E.minuterie);
    if (E.url) URL.revokeObjectURL(E.url);
    page.innerHTML = `<div class="pk-ed" data-pack-ed="${esc(vue.id)}"></div>`;
    Object.assign(E, {el: page.firstElementChild, id: vue.id, vue, brouillon: structuredClone(vue.reglages), sale: false,
                      url: null});
    if (!vue.fonds.some(f => f.id === E.fond)) E.fond = vue.fonds.length ? vue.fonds[0].id : "";
    brancher(E.el);
    lier(E.el, gestes);
    dessiner();
    return;
  }
  // sondage : le pack a changé ailleurs (autre onglet) ; un brouillon en cours n'est jamais écrasé
  if (!E.sale && JSON.stringify(vue) !== JSON.stringify(E.vue)) {
    E.vue = vue;
    E.brouillon = structuredClone(vue.reglages);
    dessiner();
  }
}
