// Écran Casting, le dessin : pré-analyse (vu-mètre et étapes en clair), messages sur les micros, une carte par
// caméra (boucle muette, badge plan large, personne placée), une pastille par micro (forme d'onde, écoute).
// Fonctions pures : elles reçoivent la vue du casting et l'état local, et renvoient du HTML échappé.
import {media} from "../../api.js";
import {barre, bouton, esc, pastille} from "../../ui.js";

// étapes de la tâche « pre_analyse », en clair ; le texte du serveur (ou son pourcentage) dit où on en est
const ETAPES = [
  ["Lecture du son", ["Lecture du son"], 0],
  ["Synchro des caméras", ["Synchronisation"], 35],
  ["Repérage des visages", ["Qui est sur quelle caméra"], 50],
  ["Écoute du début", ["Écoute du début", "Prénoms et rôles"], 85],
  ["Préparation des extraits", ["Préparation"], 97],
];

export function etapeEnCours(t) {
  const i = ETAPES.findIndex(([, debuts]) => debuts.some(d => (t.texte || "").startsWith(d)));
  if (i >= 0) return i;
  const p = t.pourcent || 0;
  return ETAPES.reduce((n, [, , seuil], k) => (p >= seuil ? k : n), 0);
}

export function preAnalyse(c, echec) {
  const t = c.tache;
  if (echec) {
    return `<div class="stage"><h2>La pré-analyse s'est arrêtée</h2>
      <p class="intro">Relance-la. Si ça recommence, envoie un rapport : on regardera ce qui coince.</p></div><div data-err></div>`;
  }
  const actif = t && (t.actif || t.statut === "en_attente");
  const i = actif && t.statut !== "en_attente" ? etapeEnCours(t) : -1;
  return `<div class="stage"><h2>L'app cherche qui est qui</h2>
    <p class="intro">Elle écoute les micros, regarde les caméras et lit le début de la conversation. Tu n'as rien à faire :
      dans quelques minutes, tout sera placé.</p></div>
    <div class="card cprea">${actif ? barre(t) : `<div class="bar"><div class="tt"><b>Pré-analyse des rushes</b></div>
      <div class="jauge indet"><i></i></div><div class="txt">Ça démarre dès que le moteur de travail est prêt.</div></div>`}
      <div class="chk analyse-chk">${ETAPES.map(([nom], k) =>
        `<div class="${k < i ? "fait" : k === i ? "en_cours" : ""}"><i>${k < i ? "✓" : ""}</i>${esc(nom)}</div>`).join("")}</div></div>`;
}

// ---- petits morceaux
const teinteMicro = (c, micro) => {
  const i = c.micros.findIndex(m => m.id === micro);
  return i < 0 ? "" : `--c:var(--p${(i % 6) + 1})`;
};
export const personneDe = (c, micro) => c.personnes.find(p => p.micro === micro) || null;
const micro = (c, id) => c.micros.find(m => m.id === id) || {};
const camera = (c, id) => c.cameras.find(x => x.id === id) || null;
const verifie = (L, p) => p && p.camera && L.verifies.has(`${p.micro}:${p.camera}`);

// forme d'onde : ~200 valeurs entre 0 et 1, une barre verticale par valeur, dessinée en un seul tracé SVG
export function onde(vals, {h = 28} = {}) {
  const v = (vals || []).length ? vals : Array(60).fill(0.04);
  const d = v.map((x, i) => {
    const y = Math.max(0.05, Math.min(1, +x || 0)) * h;
    return `M${i + 0.5} ${((h - y) / 2).toFixed(1)}v${y.toFixed(1)}`;
  }).join("");
  return `<svg class="onde" viewBox="0 0 ${v.length} ${h}" preserveAspectRatio="none" aria-hidden="true">` +
    `<path d="${d}"/></svg>`;
}

const CONFIANCE = {
  sure: ["sure", "Sûr", "La voix colle au mouvement des lèvres."],
  a_verifier: ["warn", "À vérifier", "L'app hésite : regarde et écoute pour confirmer."],
  impossible: ["no", "Impossible à deviner", "Les micros ne permettent pas de savoir qui est où. Vérifie d'après le visage."],
  choisi: ["choisi", "Choisi par toi", "Tu as placé ce micro toi-même."],
};

function confiance(L, p) {
  if (verifie(L, p)) return `<span class="conf sure"><i></i>Vérifié</span>`;
  const k = CONFIANCE[p.confiance];
  if (!k) return "";
  const score = p.score != null ? ` Accord voix et lèvres : ${String(Math.round(p.score * 100) / 100).replace(".", ",")}.` : "";
  return `<span class="conf ${k[0]}" title="${esc(k[2] + score)}"><i></i>${k[1]}</span>` +
    (p.confiance === "impossible" ? `<span class="conf-why">${esc(k[2])}</span>` : "");
}

// pastille d'un micro : à glisser sur une carte (souris) ou à prendre au clavier (Entrée puis flèches)
export function pastilleMicro(c, L, m, {mini = false} = {}) {
  const p = personneDe(c, m.id);
  const nom = p ? p.nom : m.nom;
  const cam = p && p.camera ? camera(c, p.camera) : null;
  const tags = [m.muet ? "Muet" : "", m.identique ? "Même son" : "", m.bas && !m.muet ? "Très bas" : ""].filter(Boolean);
  const aide = `Placer le micro ${m.nom}${p ? ` de ${p.nom}` : ""} sur une caméra : Entrée, puis flèches et Entrée.`;
  const joue = L.joue === m.id;
  const lecture = m.extrait
    ? `<button type="button" class="mplay${joue ? " on" : ""}" data-act="ecouter" data-micro="${esc(m.id)}"
        aria-label="${joue ? "Arrêter" : `Écouter le micro ${esc(m.nom)}`}" title="${joue ? "Arrêter" : "Écouter 8 secondes"}">${joue ? "■" : "▶"}</button>`
    : `<span class="mplay off" title="Extrait pas encore prêt">♪</span>`;
  return `<div class="mpast${mini ? " mini" : ""}${joue ? " joue" : ""}${L.pris && L.pris.micro === m.id ? " pris" : ""}"
      style="${teinteMicro(c, m.id)}" draggable="true" data-micro="${esc(m.id)}" title="Glisse ce micro sur la caméra de la personne">
    ${lecture}<span class="mtxt"><b>${esc(mini ? m.nom : nom)}</b>${mini ? "" : `<small>${esc(m.nom)}${m.niveau_db != null
      ? ` · <span class="mono">${Math.round(m.niveau_db)} dB</span>` : ""}</small>`}</span>
    ${onde(m.onde, {h: mini ? 20 : 28})}
    ${mini ? "" : `<span class="msur">${cam ? `sur ${esc(cam.nom)}` : "sans caméra"}</span>`}
    ${tags.map(t => `<span class="mtag">${t}</span>`).join("")}<button type="button" class="mgrip" data-act="prendre"
      data-micro="${esc(m.id)}" aria-label="${esc(aide)}" title="Placer ce micro : clique puis choisis la caméra">⠿</button></div>`;
}

function personne(c, L, p, cam) {
  const role = r => `<button type="button" class="${p.role === r ? "on" : ""}" data-act="role" data-role="${r}"
    data-micro="${esc(p.micro)}" aria-pressed="${p.role === r}">${r === "animateur" ? "Anime" : "Invité·e"}</button>`;
  const autres = c.personnes.filter(x => x.micro !== p.micro && x.camera);
  const echange = L.echange && L.echange !== p.micro
    ? bouton({label: `⇄ Échanger avec ${personneDe(c, L.echange)?.nom || ""}`, action: "echanger_ici", style: "p sm",
              attrs: `data-micro="${esc(p.micro)}"`}) : "";
  return `<div class="cpers" style="${teinteMicro(c, p.micro)}">
    <div class="cligne">${pastilleMicro(c, L, micro(c, p.micro), {mini: true})}${confiance(L, p)}</div>
    <input class="cnom" data-champ="nom" data-micro="${esc(p.micro)}" value="${esc(p.nom)}" maxlength="30"
      aria-label="Prénom de la personne filmée par ${esc(cam.nom)}" placeholder="Prénom" autocomplete="off" spellcheck="false">
    <div class="cligne"><div class="seg crole" role="group" aria-label="Rôle">${role("animateur")}${role("invité")}</div></div>
    <div class="cacts">${echange || `${bouton({label: "▶ Vérifier", action: "verifier", style: "sm", attrs: `data-micro="${esc(p.micro)}"`})}
      ${autres.length ? bouton({label: "⇄ Échanger", action: "echanger", style: "ghost sm", attrs: `data-micro="${esc(p.micro)}"`}) : ""}
      ${bouton({label: "Plan large ?", action: "large", style: "ghost sm", attrs: `data-cam="${esc(cam.id)}"`})}`}</div></div>`;
}

export function carte(c, L, cam, i) {
  const p = cam.personne ? personneDe(c, cam.personne) : null;
  const doute = cam.large && c.large_confiance === "a_verifier";
  const morceaux = cam.morceaux > 1 ? ` · ${cam.morceaux} morceaux` : "";
  const img = cam.image ? `<img src="${esc(media(L.projet, cam.image))}" alt="" loading="lazy">` : `<span class="cini">🎥</span>`;
  const ok = verifie(L, p);
  const corps = p ? personne(c, L, p, cam)
    : cam.large ? `<p class="cnote">Filme tout le monde. Pas de micro ici.</p>`
    : `<div class="cvide">Glisse un micro ici<br><small>ou ${bouton({label: "c'est le plan large", action: "large", style: "lnk",
        attrs: `data-cam="${esc(cam.id)}"`})}</small></div>`;
  return `<article class="ccard${cam.large ? " large" : ""}${p ? "" : " libre"}${ok ? " ok" : ""}${L.cible === i ? " survol" : ""}"
      data-cam="${esc(cam.id)}" data-i="${i}" tabindex="-1" style="${p ? teinteMicro(c, p.micro) : ""}"
      aria-label="Caméra ${esc(cam.nom)}${cam.large ? ", plan large" : p ? `, ${esc(p.nom)}` : ", sans personne"}">
    <div class="cvid" data-vid="${esc(cam.id)}">${img}
      <span class="ctag">${esc(cam.nom)}${morceaux}</span>
      ${cam.large ? `<span class="clarge${doute ? " doute" : ""}">${doute ? "Plan large ?" : "Plan large"}</span>` : ""}
      ${ok ? `<span class="cok" aria-hidden="true">✓</span>` : ""}
      ${p ? `<button type="button" class="cplay" data-act="verifier" data-micro="${esc(p.micro)}"
        aria-label="Vérifier ${esc(p.nom)} : sa caméra avec le son de son micro"><i></i></button>` : ""}
      <span class="cdepot" aria-hidden="true">${cam.large ? "Plan large : pas de micro" : "Poser ici"}</span></div>
    <div class="cbd">${corps}</div></article>`;
}

export function messages(c) {
  return (c.messages || []).map(m => `<div class="att cmsg"><span aria-hidden="true">⚠</span><span>${esc(m)}</span></div>`).join("");
}

export function entete(c, L) {
  const avec = c.personnes.filter(p => p.camera);
  const n = avec.filter(p => verifie(L, p)).length;
  const sous = c.statut === "valide"
    ? "Casting validé. Si tu changes quelque chose, valide de nouveau : l'analyse sera refaite."
    : "Tout est déjà placé. Clique sur une personne : tu vois sa caméra avec le son de son micro. Si les lèvres collent à la voix, c'est bon.";
  return `<div class="stage"><h2>Casting</h2>${pastille(c.statut)}
    ${c.statut !== "valide" && c.personnes.some(p => /^Personne \d+$/.test(p.nom)) ? `<span class="todochip">Prénoms à écrire</span>` : ""}
    <p class="intro">${esc(sous)}</p></div>
    <div class="cbarre"><span class="cprog"><b class="mono">${n}/${avec.length}</b> vérifiée${n > 1 ? "s" : ""}</span>
      <span class="cjauge" aria-hidden="true"><i style="width:${avec.length ? Math.round(100 * n / avec.length) : 0}%"></i></span>
      ${bouton({label: "▶ Tout vérifier", action: "tout", actif: avec.length > 0, raison: "Aucune personne n'a de caméra."})}
      ${c.statut === "valide" ? `<span class="okchip">✓ Casting validé</span>`
        : bouton({label: "Valider le casting", action: "valider", style: "p", actif: c.peut_valider, raison: c.raison || ""})}</div>`;
}

export function micros(c, L) {
  return `<div class="sect"><h3>Les micros</h3><p class="muted small">▶ pour écouter. Glisse un micro sur la caméra de sa
    personne, ou prends-le au clavier : Entrée, flèches, Entrée.</p></div>
    <div class="mlist">${c.micros.map(m => pastilleMicro(c, L, m)).join("")}</div>`;
}
