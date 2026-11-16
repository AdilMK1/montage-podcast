// Shorts fabriqués : contrôle qualité rapide. Une carte vidéo par short ; si une coupe est douteuse, encadré
// orange avec « ▶ Début » / « ▶ Fin » (3 premières / 3 dernières secondes) puis « C'est bon » ; « Garder » /
// « Jeter » ; un short dont les réglages ont changé est « à refaire » avec son bouton « Refaire ». Un short jeté
// n'est jamais refabriqué ; « Repêcher » le remet en jeu.
import {media} from "../../api.js";
import {esc, lecteur} from "../../ui.js";
import {accrocheEdition, agir, lecteurShorts, textesHtml} from "./shorts_commun.js";

export const FABRIQUES = ["a_controler", "garde", "jete", "a_refaire"];
const ETATS = {a_controler: ["a_valider", "À contrôler"], garde: ["valide", "Gardé"], jete: ["a_faire", "Jeté"],
               a_refaire: ["a_refaire", "À refaire"]};

const etat = sh => `<span class="pastille ${ETATS[sh.statut][0]}"><i></i>${ETATS[sh.statut][1]}</span>`;
const aVerifier = sh => sh.alertes.length > 0 && !sh.alertes_ok;

function coupes(sh) {
  if (sh.statut === "a_refaire") return "";
  if (!sh.alertes.length) return `<span class="ctl ok">✓ Coupes vérifiées</span>`;
  if (sh.alertes_ok) return `<span class="ctl ok">✓ Coupes réécoutées</span>`;
  const mots = sh.alertes.map(a => `« ${esc(a)} »`).join(", ");
  return `<div class="att coupe"><div><b>${sh.alertes.length > 1 ? "Coupes" : "Coupe"} à vérifier : ${mots}</b>
    <span>Ces mots sont peut-être coupés. Réécoute le début et la fin.</span>
    <div class="mini-acts"><button type="button" class="btn sm" data-act="debut" data-id="${esc(sh.id)}">▶ Début</button>
      <button type="button" class="btn sm" data-act="fin" data-id="${esc(sh.id)}">▶ Fin</button>
      <button type="button" class="btn sm p" data-act="cbon" data-id="${esc(sh.id)}">C'est bon</button></div></div></div>`;
}

export function verdict(sh, {occupe = false, peutFabriquer = false, raisonFab = ""} = {}) {
  const id = esc(sh.id);
  if (sh.statut === "a_refaire") {
    const why = peutFabriquer ? "" : raisonFab;
    return `<div class="verdict"><button type="button" class="y" data-act="refaire" data-id="${id}"
      ${why ? `disabled title="${esc(why)}"` : ""}>↻ Refaire</button></div>
      ${why ? `<p class="why vwhy">${esc(why)}</p>` : `<p class="why vwhy">Tes réglages ont changé depuis sa fabrication.</p>`}`;
  }
  if (sh.statut === "jete") {
    return `<div class="verdict"><button type="button" class="no on" disabled title="Tu as jeté ce short.">✗ Jeté</button></div>
      <p class="why vwhy">Il ne partira pas dans la livraison.
        <button type="button" class="lnk" data-act="repecher" data-id="${id}" ${occupe ? "disabled" : ""}>Repêcher</button></p>`;
  }
  const bloque = aVerifier(sh) ? "Réécoute d'abord les coupes signalées." : "";
  return `<div class="verdict"><button type="button" class="y ${sh.statut === "garde" ? "on" : ""}" data-act="garder"
      data-id="${id}" ${bloque || occupe ? "disabled" : ""} ${bloque ? `title="${esc(bloque)}"` : ""}>✓ Garder</button>
    <button type="button" class="no ${sh.statut === "jete" ? "on" : ""}" data-act="jeter" data-id="${id}"
      ${occupe ? "disabled" : ""}>✗ Jeter</button></div>${bloque ? `<p class="why vwhy">${esc(bloque)}</p>` : ""}`;
}

export function carte(projet, sh, opts) {
  const id = esc(sh.id), src = sh.video ? media(projet, sh.video) : null;
  const cls = sh.statut === "garde" ? "ok" : sh.statut === "jete" ? "non" : "";
  return `<div class="clip ${cls}" data-id="${id}">
    <div class="thumb ${src ? "v" : ""}" ${src ? `data-act="voir_ctl" data-id="${id}"` : ""}>
      ${src ? `${sh.poster ? `<img src="${esc(media(projet, sh.poster))}" alt="">` : ""}
        <video muted loop preload="none" playsinline src="${esc(src)}"></video><div class="play"><i></i></div>`
        : `<div class="idea"><b>Vidéo indisponible</b><span>Refais ce short.</span></div>`}
      ${sh.num ? `<span class="tag num">${esc(sh.num)}</span>` : ""}<span class="tag dur">${sh.duree} s</span></div>
    <div class="meta"><div class="mh"><b>${esc(sh.titre)}</b>${etat(sh)}</div>
      ${sh.spec.accroche && sh.spec.accroche.length ? `<span class="hook">${textesHtml(sh)}</span>` : ""}
      ${coupes(sh)}
      ${opts && opts.pack ? opts.pack(sh) : ""}
      <details class="acc"><summary>Modifier l'accroche</summary>
        <textarea class="accr" rows="2" data-accroche="${id}">${esc(accrocheEdition(sh))}</textarea>
        <span class="muted small">Si tu la changes, ce short sera à refaire.</span></details></div>
    ${verdict(sh, opts)}</div>`;
}

// gestes des cartes et du lecteur ; ctx = {projet, opts: () => options du verdict}
function decider(projet, sh, decision) {
  return agir(projet, {type: "decider_short", id: sh.id, decision},
              decision === "garder" ? "Short gardé : il partira dans la livraison." : "Short jeté.");
}

const repecher = (projet, sh) => agir(projet, {type: "repecher_short", id: sh.id}, "Short repêché.");

function coteLecteur(ctx) {
  return sh => `<b style="font-size:19px">${esc(sh.titre)}</b> ${etat(sh)}
    ${sh.spec.accroche && sh.spec.accroche.length ? `<p>${textesHtml(sh)}</p>` : ""}
    <div style="margin:14px 0">${coupes(sh)}</div>
    ${verdict(sh, ctx.opts())}
    <p style="font-size:12px;margin-top:14px">← → pour passer au suivant · Échap pour fermer</p>`;
}

export function ouvrirLecteur(ctx, shorts, id) {
  const ids = shorts.filter(x => FABRIQUES.includes(x.statut) && x.video).map(x => x.id);
  const i = ids.indexOf(id);
  if (i < 0) return;
  const apres = L => r => { if (r) L.redessiner(); };
  lecteurShorts({
    ids, index: i, src: sh => (sh.video ? media(ctx.projet, sh.video) : null), cote: coteLecteur(ctx),
    gestes: {
      debut: (b, sh, L) => L.morceau(0, 3),
      fin: (b, sh, L) => L.morceau(-3, 3),
      cbon: async (b, sh, L) => { b.disabled = true; apres(L)(await agir(ctx.projet, {type: "confirmer_alertes", id: sh.id})); },
      garder: async (b, sh, L) => { b.disabled = true; apres(L)(await decider(ctx.projet, sh, "garder")); },
      jeter: async (b, sh, L) => { b.disabled = true; apres(L)(await decider(ctx.projet, sh, "jeter")); },
      refaire: async (b, sh, L) => { b.disabled = true; apres(L)(await ctx.fabriquer()); },
      repecher: async (b, sh, L) => { b.disabled = true; apres(L)(await repecher(ctx.projet, sh)); },
    },
  });
}

// gestes des cartes (dans la page)
export function gestes(ctx) {
  const sh = b => (ctx.vue().shorts || []).find(x => x.id === b.dataset.id);
  const morceau = (b, debut, titre) => {
    const s = sh(b);
    if (s && s.video) lecteur(media(ctx.projet, s.video), {debut, fin: debut >= 0 ? debut + 3 : null, titre: `${s.titre} · ${titre}`});
  };
  return {
    voir_ctl: b => ouvrirLecteur(ctx, ctx.vue().shorts, b.dataset.id),
    debut: b => morceau(b, 0, "les 3 premières secondes"),
    fin: b => morceau(b, -3, "les 3 dernières secondes"),
    cbon: async b => { b.disabled = true; if (!(await agir(ctx.projet, {type: "confirmer_alertes", id: b.dataset.id}, "Coupes validées."))) b.disabled = false; },
    garder: async b => { b.disabled = true; if (!(await decider(ctx.projet, sh(b), "garder"))) b.disabled = false; },
    jeter: async b => { b.disabled = true; if (!(await decider(ctx.projet, sh(b), "jeter"))) b.disabled = false; },
    refaire: async b => { b.disabled = true; if (!(await ctx.fabriquer())) b.disabled = false; },
    repecher: async b => { b.disabled = true; if (!(await repecher(ctx.projet, sh(b)))) b.disabled = false; },
  };
}
