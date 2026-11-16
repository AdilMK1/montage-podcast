// Étape Analyse : les sous-étapes cochées d'après la progression de la tâche « analyse », la barre réelle,
// un renvoi vers la couleur pendant l'attente, et à la fin les résultats en clair.
import {api} from "../../api.js";
import {barre, bouton, erreur, esc, lier} from "../../ui.js";
import {reessayer} from "../projet.js";

// dans l'ordre de la tâche : chaque sous-étape occupe un cinquième de la barre
const SOUS = ["Lecture du son des rushes", "Synchronisation des caméras", "Transcription de la conversation",
              "Nettoyage du son", "Repérage des visages"];
let phrases = {projet: null, n: null, enVol: false};
let cle = "";

// numéro de la sous-étape en cours, d'après le texte de la tâche, sinon d'après son pourcentage
export function sousEtape(t) {
  const i = SOUS.findIndex(s => (t.texte || "").startsWith(s));
  if (i >= 0) return i;
  return Math.min(SOUS.length - 1, Math.floor((t.pourcent || 0) / (100 / SOUS.length)));
}

// la synchro est faite : l'analyse est finie, ou sa tâche a dépassé la sous-étape « Synchronisation »
export function synchroFaite(v) {
  if (v.statuts.analyse === "valide") return true;
  const t = v.taches.find(x => x.type === "analyse" && x.actif);
  return !!t && sousEtape(t) > 1;
}

function compterPhrases(projet, refaire) {
  if (phrases.projet === projet && (phrases.n != null || phrases.enVol)) return;
  phrases = {projet, n: null, enVol: true};
  api.transcript(projet).then(r => {
    if (phrases.projet !== projet) return;
    phrases = {projet, n: r.erreur ? -1 : (r.phrases || []).length, enVol: false};
    refaire();
  });
}

function liste(t) {
  const i = t ? sousEtape(t) : -1;
  return `<div class="chk analyse-chk">${SOUS.map((s, k) =>
    `<div class="${k < i ? "fait" : k === i ? "en_cours" : ""}"><i>${k < i ? "✓" : ""}</i>${esc(s)}</div>`).join("")}</div>`;
}

function enCours(v, t) {
  return `<div class="stage"><h2>Analyse en cours</h2>
    <p class="intro">Tu n'as rien à faire.</p></div>
    <div class="card" style="margin-top:16px">${barre(t)}${liste(t.statut === "en_attente" ? null : t)}</div>
    <button type="button" class="bgtask" data-act="couleur" style="width:100%;text-align:left">
      <span class="dot"></span>
      <span><b>Pendant ce temps, règle la couleur.</b> Les images des caméras sont déjà prêtes.</span>
      <span class="go">Aller à la couleur →</span></button>`;
}

function fini(v) {
  const n = phrases.projet === v.id ? phrases.n : null;
  const txt = n == null ? "Transcription prête" : n < 0 ? "Transcription prête" : `${n} phrases transcrites`;
  const ligne = (ic, b, s) => `<div><span class="ic">${ic}</span><span><b>${esc(b)}</b><br>${esc(s)}</span></div>`;
  // micros qui ne sont pas un micro par personne (même son, micro silencieux) : dit en clair, l'analyse a continué
  const av = (v.avertissements || []).map(a =>
    `<div><span class="ic w">⚠</span><span><b>À savoir sur tes micros</b><br>${esc(a)}</span></div>`).join("");
  return `<div class="stage"><h2>Analyse terminée</h2>
    <p class="intro">${av ? "C'est prêt, avec un point à connaître sur tes micros." : "Tout est prêt."} Suite : la couleur, puis le son.</p></div>
    <div class="res" style="margin-top:16px">${av}
      ${ligne("🎥", `${v.cams.length} caméra${v.cams.length > 1 ? "s" : ""} synchronisée${v.cams.length > 1 ? "s" : ""}`,
              "Calées au centième de seconde sur les micros.")}
      ${ligne("💬", txt, "Toute la conversation, avec qui parle.")}
      ${ligne("🎙", `${v.mics.length} voix nettoyée${v.mics.length > 1 ? "s" : ""}`, "Volume égalisé, écho réduit.")}
      ${ligne("🙂", "Visages repérés", "Pour cadrer les shorts sur la bonne personne.")}</div>
    <div class="acts">${bouton({label: "Régler la couleur →", action: "couleur", style: "p lg"})}</div>`;
}

function attente(v, echec) {
  const relancer = !echec || !echec.actions || echec.actions.includes("reessayer");
  if (echec) return `<div class="stage"><h2>L'analyse s'est arrêtée</h2>
    <p class="intro">${relancer ? "Relance-la. Si ça recommence, envoie un rapport : on regardera ce qui coince."
      : "Voici ce qui coince et quoi faire."}</p></div><div data-err></div>`;
  if (v.casting && !v.casting.manuel && v.statuts.casting !== "valide") return `<div class="stage"><h2>L'analyse attend le casting</h2>
    <p class="intro">Elle démarre dès que tu valides qui est qui : les bons prénoms partout, dès la transcription.</p></div>
    <div class="acts">${bouton({label: "Aller au casting →", action: "casting", style: "p"})}</div>`;
  return `<div class="stage"><h2>L'analyse va démarrer</h2>
    <p class="intro">Elle se lance dès que le moteur de travail est prêt. Tu peux déjà régler la couleur.</p></div>
    <div class="acts">${bouton({label: "Aller à la couleur →", action: "couleur", style: "p"})}</div>`;
}

export function rendre(el, v, ctx) {
  const t = v.taches.find(x => x.type === "analyse" && (x.actif || x.statut === "en_attente"));
  const echec = !t && v.statuts.analyse !== "valide" ? v.taches.find(x => x.type === "analyse" && x.statut === "echec") : null;
  if (v.statuts.analyse === "valide") compterPhrases(v.id, () => { cle = ""; rendre(el, v, ctx); });
  const html = v.statuts.analyse === "valide" ? fini(v) : t ? enCours(v, t) : attente(v, echec);
  const k = v.id + html + (echec ? echec.id : "");
  if (k === cle && el.firstChild) return;
  cle = k;
  el.innerHTML = `<div class="fade">${html}</div>`;
  if (echec) {
    el.querySelector("[data-err]").append(erreur({erreur: echec.erreur || "L'analyse n'a pas abouti.",
      actions: echec.actions || ["reessayer", "rapport"]}, {projet: v.id, gestes: {reessayer: () => reessayer(v.id, echec.id)}}));
  }
  lier(el, {couleur: () => ctx.aller("couleur"), casting: () => ctx.aller("casting")});
}
