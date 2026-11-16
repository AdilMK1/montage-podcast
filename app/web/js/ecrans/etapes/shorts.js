// Étape Shorts. Le choix se fait SUR APERÇU : chaque proposition se regarde tout de suite (survol = lecture muette,
// clic = plein écran avec le son), son accroche se modifie sur place, une case la retient. Puis « Fabriquer » ;
// ensuite un contrôle qualité rapide des coupes (voir shorts_controle.js). Aucune logique de process ici : les
// statuts viennent du serveur, chaque geste part en action.
import {habillage, media} from "../../api.js";
import {store} from "../../store.js";
import {barre, bouton, esc, lier, modale} from "../../ui.js";
import {accrocheEdition, accrocheLignes, agir, choixPack, lecteurShorts, pourquoi, shortCourant, tc, textesHtml} from "./shorts_commun.js";
import {FABRIQUES, carte as carteControle, gestes as gestesControle} from "./shorts_controle.js";
import {choisirAuTranscript} from "./shorts_transcript.js";

const S = {el: null, v: null, ctx: null, zones: {}};
const tache = (v, type) => v.taches.find(t => t.type === type && (t.actif || t.statut === "en_attente"));
const iaDispo = () => { const a = store.etat.activite; return !a || !a.machine || a.machine.ia !== false; };
const reglagesOk = v => v.statuts.couleur === "valide" && v.statuts.son === "valide";

function raisonFabrication(v) {
  if (tache(v, "shorts")) return "La fabrication est déjà en cours.";
  if (!reglagesOk(v)) return "Valide d'abord la couleur et le son.";
  return "Retiens au moins une proposition.";
}

// pack du podcast (en tête de l'étape) et lien vers la bibliothèque
function choixPodcast(v) {
  if (!(v.packs || []).length) return "";
  return `<label class="pk-podcast"><i aria-hidden="true">🎨</i>Pack du podcast <select class="inp" data-pack-projet
    aria-label="Pack du podcast">${v.packs.map(p =>
      `<option value="${esc(p.id)}"${v.pack && p.id === v.pack.id ? " selected" : ""}>${esc(p.nom)}</option>`).join("")}
    </select><a class="lnk" href="/?packs" data-nav>Gérer les packs</a></label>`;
}

// ---- en-tête : résumé, actions, barres des tâches de l'étape
function tete(v) {
  const sh = v.shorts, n = sh.filter(x => ["retenu", "a_refaire"].includes(x.statut)).length;
  const props = sh.filter(x => !FABRIQUES.includes(x.statut)).length, ret = sh.filter(x => x.statut === "retenu").length;
  const ia = tache(v, "ia_shorts"), fab = tache(v, "shorts"), ap = tache(v, "apercus");
  const resume = sh.length ? `<b>${props} proposition${props > 1 ? "s" : ""} · ${ret} retenue${ret > 1 ? "s" : ""}</b>`
    : `<b>Pas encore de propositions</b>`;
  const serie = v.series.length > 1 ? `<span class="muted small">Les propositions précédentes sont rangées à part.</span>` : "";
  const label = n ? `Fabriquer ${n} short${n > 1 ? "s" : ""}` : "Fabriquer les shorts";
  return `<div class="card shead"><div class="shl">${resume}${serie}${choixPodcast(v)}</div><div class="acts" style="margin:0">
      ${bouton({label: "Choisir un passage dans le transcript", action: "transcript"})}
      ${bouton({label: "Nouvelles propositions de l'IA", action: "ia", actif: iaDispo() && !ia,
                raison: ia ? "L'IA prépare déjà des propositions." : "L'IA n'est pas disponible sur cet ordinateur."})}
      ${fab ? "" : bouton({label, action: "fabriquer", style: "p", actif: !!v.peut.fabriquer, raison: raisonFabrication(v)})}
    </div></div>
    ${!reglagesOk(v) ? `<div class="att">Pour fabriquer, valide d'abord la couleur et le son. Tu peux déjà choisir tes shorts.
      <span class="lien">${v.statuts.couleur !== "valide" ? bouton({label: "Aller à la couleur", action: "aller", style: "ghost sm", attrs: 'data-etape="couleur"'}) : ""}
      ${v.statuts.son !== "valide" ? bouton({label: "Aller au son", action: "aller", style: "ghost sm", attrs: 'data-etape="son"'}) : ""}</span></div>` : ""}
    ${ia ? `<div class="card" style="margin-top:14px">${barre(ia)}</div>` : ""}
    ${ap ? `<div class="card" style="margin-top:14px">${barre(ap, {mini: true})}</div>` : ""}
    ${fab ? `<div class="card" style="margin-top:14px"><p class="small" style="margin:0 0 10px">Compte environ 1 min par short.
      Chaque short apparaît ci-dessous dès qu'il est prêt.</p>${barre(fab)}</div>` : ""}`;
}

// ---- propositions (propose, retenu)
function carteProposition(v, sh, prep) {
  const id = esc(sh.id), src = sh.apercu ? media(v.id, sh.apercu) : null, retenu = sh.statut === "retenu";
  const p = pourquoi(sh), hab = habillage(v.id, sh.id, sh.habillage);
  return `<div class="clip ${retenu ? "ok" : ""}" data-id="${id}">
    <div class="thumb ${src ? "v" : ""}" ${src ? `data-act="voir" data-id="${id}"` : ""}>
      ${src ? `<video muted loop preload="metadata" playsinline src="${esc(src)}" poster="${esc(hab)}"></video><div class="play"><i></i></div>`
        : `<div class="idea"><b>${sh.spec.accroche && sh.spec.accroche.length ? textesHtml(sh) : esc(sh.titre)}</b></div>
          <img data-hab src="${esc(hab)}" alt="Le short habillé par le pack « ${esc(sh.pack_nom)} »">
          <span class="tag prep">${prep ? '<span class="spin"></span> Aperçu vidéo en préparation' : "Aperçu vidéo indisponible"}</span>`}
      ${sh.num ? `<span class="tag num">${esc(sh.num)}</span>` : ""}<span class="tag dur">${sh.duree} s</span></div>
    <div class="meta"><b>${esc(sh.titre)}</b><span class="muted small">À ${tc(sh.debut)} dans la conversation</span>
      ${p ? `<span class="hook">${esc(p)}</span>` : ""}
      <label class="lab">Accroche</label>
      <textarea class="accr" rows="2" data-accroche="${id}" placeholder="Écris l'accroche affichée en haut du short">${
        esc(accrocheEdition(sh))}</textarea>
      ${choixPack(v, sh)}</div>
    <label class="retenir ${retenu ? "on" : ""}"><input type="checkbox" data-retenir="${id}" ${retenu ? "checked" : ""}
> ${retenu ? "Retenu" : "Retenir ce short"}</label></div>`;
}

function propositions(v) {
  const sh = v.shorts.filter(x => !FABRIQUES.includes(x.statut));
  const prep = !!tache(v, "apercus");
  if (!v.shorts.length) {
    return `<div class="card" style="margin-top:22px"><b>Pas encore de propositions.</b>
      <p class="muted" style="margin:6px 0 0">${tache(v, "ia_shorts") ? "L'IA les prépare : elles arrivent ici dans quelques minutes."
        : "Demande des propositions à l'IA, ou choisis toi-même un passage dans le transcript."}</p></div>`;
  }
  if (!sh.length) return "";
  return `<div class="sect"><h3>Propositions</h3><p class="muted small">Survol : aperçu muet. Clic : avec le son.
      Accroche : une ligne = une ligne à l'écran, *mot* = en couleur.</p></div>
    <div class="clips">${sh.map(x => carteProposition(v, x, prep)).join("")}</div>`;
}

const optsControle = v => ({peutFabriquer: !!v.peut.fabriquer && !tache(v, "shorts"), raisonFab: raisonFabrication(v),
                            pack: sh => choixPack(v, sh)});

function controle(v) {
  const sh = v.shorts.filter(x => FABRIQUES.includes(x.statut));
  if (!sh.length) return "";
  const reste = sh.filter(x => x.statut === "a_controler").length;
  const opts = optsControle(v);
  return `<div class="sect"><h3>Tes shorts fabriqués</h3><p class="muted small">${reste
      ? `${reste} à contrôler : regarde-les, réécoute les coupes signalées, puis garde ou jette.`
      : "Tout est contrôlé. Les shorts gardés partiront dans la livraison."}</p></div>
    <div class="clips">${sh.map(x => carteControle(v.id, x, opts)).join("")}</div>`;
}

// ---- gestes
async function fabriquer() {
  return agir(S.v.id, {type: "lancer_fabrication"}, "C'est parti : les shorts se fabriquent.");
}

function proposerIA() {
  const v = S.v, gardes = v.shorts.filter(x => x.statut === "garde").length;
  const lancer = () => agir(v.id, {type: "proposer_shorts_ia"}, "L'IA prépare de nouvelles propositions.");
  if (!v.shorts.length) { lancer(); return; }
  const m = modale(`<h2>Nouvelles propositions de l'IA ?</h2>
    <p class="muted">Les propositions actuelles seront rangées à part : tu repartiras d'une nouvelle liste.
      ${gardes ? `Les ${gardes} short${gardes > 1 ? "s" : ""} que tu as gardé${gardes > 1 ? "s" : ""} ne partiront plus dans la livraison.` : ""}</p>
    <div class="foot">${bouton({label: "Garder mes propositions", action: "non", style: "ghost"})}
      ${bouton({label: "Oui, demander à l'IA", action: "oui", style: "p"})}</div>`);
  lier(m.el, {non: () => m.fermer(), oui: async b => { b.disabled = true; await lancer(); m.fermer(); }});
}

function voirApercu(id) {
  const ids = S.v.shorts.filter(x => !FABRIQUES.includes(x.statut) && x.apercu).map(x => x.id);
  lecteurShorts({
    ids, index: Math.max(0, ids.indexOf(id)), src: sh => (sh.apercu ? media(S.v.id, sh.apercu) : null),
    cote: sh => `<b style="font-size:19px">${esc(sh.titre)}</b>
      ${sh.spec.accroche && sh.spec.accroche.length ? `<p>${textesHtml(sh)}</p>` : ""}
      ${pourquoi(sh) ? `<p>${esc(pourquoi(sh))}</p>` : ""}
      <div class="verdict" style="padding:0"><button type="button" class="y ${sh.statut === "retenu" ? "on" : ""}"
        data-act="retenir">${sh.statut === "retenu" ? "✓ Retenu" : "Retenir ce short"}</button></div>
      <img class="pk-habille" src="${esc(habillage(S.v.id, sh.id, sh.habillage))}" alt="Le short habillé par son pack">
      <p style="font-size:12px;margin-top:14px">Vidéo : aperçu brut. Image : l'habillage du pack « ${esc(sh.pack_nom)} ».
        ← → pour passer au suivant · Échap pour fermer</p>`,
    gestes: {retenir: async (b, sh, L) => {
      b.disabled = true;
      if (await agir(S.v.id, {type: "retenir_short", id: sh.id, retenu: sh.statut !== "retenu"})) L.redessiner();
      else b.disabled = false;
    }},
  });
}

async function retenir(input) {
  input.disabled = true;  // la carte est redessinée avec la réponse
  const v = await agir(S.v.id, {type: "retenir_short", id: input.dataset.retenir, retenu: input.checked});
  if (!v) { input.checked = !input.checked; input.disabled = false; }
}

async function accroche(ta) {
  const sh = shortCourant(ta.dataset.accroche);
  if (!sh) return;
  const lignes = accrocheLignes(ta.value);
  if (JSON.stringify(lignes) === JSON.stringify(sh.spec.accroche || [])) return;
  const refaire = FABRIQUES.includes(sh.statut);
  await agir(S.v.id, {type: "modifier_short", id: sh.id, spec: {...sh.spec, accroche: lignes}},
             refaire ? "Accroche enregistrée. Refais ce short pour l'appliquer." : "Accroche enregistrée.");
}

// pack du podcast : les shorts fabriqués sans pack à eux passent « à refaire »
async function choisirPackPodcast(sel) {
  const v = S.v, fab = v.shorts.some(x => FABRIQUES.includes(x.statut) && x.statut !== "jete" && !x.pack);
  sel.blur();
  sel.disabled = true;
  const ok = await agir(v.id, {type: "choisir_pack", pack: sel.value},
    fab ? "Pack du podcast changé. Les shorts déjà fabriqués sont à refaire." : "Pack du podcast changé.");
  if (!ok) { sel.value = v.pack ? v.pack.id : ""; sel.disabled = false; }
}

// pack d'un short : vide = celui du podcast (le champ disparaît de la spec)
async function changerPackShort(sel) {
  const sh = shortCourant(sel.dataset.packShort);
  if (!sh) return;
  const spec = {...sh.spec};
  if (sel.value) spec.pack = sel.value; else delete spec.pack;
  sel.blur();
  sel.disabled = true;
  const ok = await agir(S.v.id, {type: "modifier_short", id: sh.id, spec},
    FABRIQUES.includes(sh.statut) && sh.statut !== "jete" ? "Pack changé. Refais ce short pour l'appliquer." : "Pack changé.");
  if (!ok) { sel.value = sh.pack || ""; sel.disabled = false; }
}

function brancher(el) {
  el.addEventListener("change", e => {
    if (e.target.dataset.retenir) retenir(e.target);
    else if (e.target.dataset.accroche) accroche(e.target);
    else if (e.target.dataset.packShort) changerPackShort(e.target);
    else if (e.target.matches("[data-pack-projet]")) choisirPackPodcast(e.target);
  });
  // image habillée pas encore prête ou en erreur : on la cache, l'idée (accroche) reste en dessous
  el.addEventListener("error", e => { if (e.target.matches && e.target.matches("img[data-hab]")) e.target.hidden = true; }, true);
  // survol d'une vignette : lecture muette
  el.addEventListener("mouseover", e => {
    const t = e.target.closest(".thumb.v");
    const vid = t && t.querySelector("video");
    if (vid && vid.paused) { vid.style.zIndex = 1; vid.play().catch(() => {}); }
  });
  el.addEventListener("mouseout", e => {
    const t = e.target.closest(".thumb.v");
    if (!t || t.contains(e.relatedTarget)) return;
    const vid = t.querySelector("video");
    if (vid) { vid.pause(); vid.style.zIndex = 0; }
  });
}

function zone(n, html) {
  const z = S.el.querySelector(`[data-z="${n}"]`);
  if (z && S.zones[n] !== html) { S.zones[n] = html; z.innerHTML = html; }
}

function attente(v) {
  const t = tache(v, "analyse");
  return `<div class="stage"><h2>Shorts</h2><p class="intro">Les shorts se choisissent une fois l'analyse terminée :
    l'app a besoin du transcript. Règle la couleur en attendant.</p></div>
    ${t ? `<div class="card" style="margin-top:20px">${barre(t)}</div>` : ""}
    <div class="acts">${bouton({label: "Aller à la couleur →", action: "aller", style: "p", attrs: 'data-etape="couleur"'})}</div>`;
}

export function rendre(el, v, ctx) {
  S.v = v;
  S.ctx = ctx;
  if (S.el !== el) { S.el = el; S.zones = {}; brancher(el); }
  const cctx = {projet: v.id, vue: () => S.v, fabriquer, opts: () => optsControle(store.etat.vue || S.v)};
  lier(el, {
    aller: b => ctx.aller(b.dataset.etape),
    transcript: () => choisirAuTranscript(v.id),
    ia: proposerIA,
    fabriquer: async b => { b.disabled = true; if (!(await fabriquer())) b.disabled = false; },
    voir: b => voirApercu(b.dataset.id),
    ...gestesControle(cctx),
  });
  if (v.statuts.analyse !== "valide") {
    if (!el.querySelector("[data-m=attente]")) S.zones = {};
    const h = attente(v);
    if (S.zones.attente !== h) { el.innerHTML = `<div data-m="attente" class="fade">${h}</div>`; S.zones = {attente: h}; }
    return;
  }
  if (!el.querySelector("[data-m=shorts]")) {
    el.innerHTML = `<div data-m="shorts" class="fade"><div class="stage"><h2>Shorts</h2>
      <p class="intro">Retiens tes préférés, ajuste l'accroche, fabrique. Puis garde les meilleurs.</p></div>
      <div data-z="tete"></div><div data-z="controle"></div><div data-z="props"></div></div>`;
    S.zones = {};
  }
  zone("tete", tete(v));
  zone("controle", controle(v));
  zone("props", propositions(v));
}
