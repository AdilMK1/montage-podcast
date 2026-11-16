// Assistant de création, écrans 1 et 2 : les rushes trouvés, avec une image de chaque caméra et l'écoute de chaque
// micro ; les morceaux d'une même caméra regroupés ; les sons identiques et les sons très bas signalés.
import {bouton, esc, nomFichier, toast} from "../ui.js";

const taille = mo => mo >= 1000 ? `${(mo / 1000).toFixed(1).replace(".", ",")} Go` : `${mo} Mo`;
export const pluriel = (n, un, plusieurs = un + "s") => `${n} ${n > 1 ? plusieurs : un}`;
const q = f => encodeURIComponent(f.chemin);
const sansExt = c => nomFichier(c).replace(/\.[^.]+$/, "").trim();
const liste = ns => ns.length > 1 ? `${ns.slice(0, -1).join(", ")} et ${ns[ns.length - 1]}` : ns[0] || "";

// un vrai prénom : pas un chiffre (« 1 »), pas le nom technique d'un fichier (« MICRO_1 », « Track 2 », « ZOOM0001 »)
const TECHNIQUE = /^(micro|mic|cam[eé]ra|cam|audio|piste|track|tr|zoom|rec|son|voix|lav)?[\s_-]*\d*[\s_-]*[a-z]?$/i;
export const prenomValable = n => /\p{L}.*\p{L}/u.test(n || "") && !TECHNIQUE.test(String(n).trim());
const ALERTE_PRENOM = "Donne son prénom à chaque personne : il sert aux sous-titres et au montage.";
export const alertePrenom = L => L.gens.some(p => !prenomValable(p.nom)) ? `⚠ ${ALERTE_PRENOM}` : "";

// ---- écoute des micros : niveau et extrait préparés par le serveur dès que la liste s'affiche
let son = null;

export function preparerEcoutes(W, el) {
  for (const f of W.fichiers.filter(x => x.type === "micro")) {
    W.ecoute[f.chemin] = {etat: "calcul"};
    fetch(`/api/micro_rush?f=${q(f)}`, {cache: "no-store"})
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(a => { W.ecoute[f.chemin] = {etat: "pret", bas: a.bas}; })
      .catch(() => { W.ecoute[f.chemin] = {etat: "erreur"}; })
      .finally(() => majEcoutes(W, el()));
  }
}

function boutonEcoute(W, f) {
  const e = W.ecoute[f.chemin] || {};
  const i = W.fichiers.indexOf(f);
  if (!e.etat || e.etat === "erreur") return `<span class="ec" data-ec="${i}"></span>`;
  if (e.etat !== "pret") {
    return `<span class="ec" data-ec="${i}"><button type="button" class="lect" disabled title="On cherche un moment où ce micro parle">` +
      `<span class="spin"></span></button></span>`;
  }
  const joue = W.joue === f.chemin;
  return `<span class="ec" data-ec="${i}"><button type="button" class="lect${joue ? " on" : ""}" data-act="ecouter" data-i="${i}"
    title="${joue ? "Arrêter" : "Écouter 8 secondes de ce micro"}" aria-label="${joue ? "Arrêter" : "Écouter"}">${joue ? "■" : "▶"}</button></span>`;
}

const noteBas = (W, f) => f.type === "micro" && (W.ecoute[f.chemin] || {}).bas
  ? "Le son est très bas, vérifie que c'est la bonne piste." : "";

// mise à jour ciblée (sans redessiner l'écran : un nom en cours de saisie n'est pas perdu)
function majEcoutes(W, el) {
  if (!el) return;
  for (const s of el.querySelectorAll("[data-ec]")) {
    const f = W.fichiers[+s.dataset.ec];
    if (!f) continue;
    s.outerHTML = boutonEcoute(W, f);
  }
  for (const n of el.querySelectorAll("[data-note]")) {
    const f = W.fichiers[+n.dataset.note];
    n.textContent = f ? noteBas(W, f) : "";
  }
}

export function ecouter(W, el, i) {
  const f = W.fichiers[i];
  const deja = W.joue === f.chemin;
  arreterSon(W);
  if (!deja) {
    son = new Audio(`/api/son_rush?f=${q(f)}`);
    W.joue = f.chemin;
    son.onended = () => { W.joue = null; majEcoutes(W, el); };
    son.onerror = () => { W.joue = null; majEcoutes(W, el); toast("Ce son ne se lit pas. Réessaie dans un instant.", "no"); };
    son.play().catch(() => {});
  }
  majEcoutes(W, el);
}

export function arreterSon(W) {
  if (son) { son.onended = son.onerror = null; son.pause(); son = null; }
  if (W) W.joue = null;
}

// ---- écran 1
const vignette = f => `<span class="vg" title="Image prise au milieu de la vidéo">🎥` +
  `<img src="/api/image_rush?f=${q(f)}" alt="" loading="lazy" onerror="this.remove()"></span>`;

function ligne(W, f) {
  const i = W.fichiers.indexOf(f);
  return `<div class="fi" style="${f.on ? "" : "opacity:.5"}">
    <input type="checkbox" data-champ="on" data-i="${i}" ${f.on ? "checked" : ""} title="Garder ce fichier">
    ${f.type === "camera" ? vignette(f) : boutonEcoute(W, f)}
    <span class="fn" title="${esc(nomFichier(f.chemin))}">${esc(nomFichier(f.chemin))} <span class="muted">· ${taille(f.taille_mo)}</span></span>
    <select data-champ="type" data-i="${i}" title="Micro ou caméra"><option value="micro" ${f.type === "micro" ? "selected" : ""}>micro</option>
      <option value="camera" ${f.type === "camera" ? "selected" : ""}>caméra</option></select>
    <input type="text" data-champ="nom" data-i="${i}" value="${esc(f.nom)}" title="Nom (le même pour le micro et la caméra d'une personne)"></div>
    ${f.type === "micro" ? `<div class="fnote" data-note="${i}">${noteBas(W, f)}</div>` : ""}`;
}

// caméras : les morceaux qui portent le même nom sont mis bout à bout, on le montre en un seul bloc
function cameras(W, fs) {
  const noms = [...new Set(fs.map(f => f.nom))];
  return noms.map(n => {
    const m = fs.filter(f => f.nom === n);
    const on = m.filter(f => f.on).length;
    if (m.length < 2) return m.map(f => ligne(W, f)).join("");
    return `<div class="grp"><div class="grp-t">🔗 <b>${on > 1 ? `${on} fichiers mis bout à bout` : "Morceaux d'une même caméra"}</b> :
      la caméra « ${esc(n)} ». Pour les séparer, donne un autre nom à l'un d'eux.</div>${m.map(f => ligne(W, f)).join("")}</div>`;
  }).join("");
}

// micros cochés au contenu identique (même enregistrement copié) ; micros au son très bas
export function alertesSon(W) {
  const mics = new Set(W.fichiers.filter(f => f.on && f.type === "micro").map(f => f.chemin));
  const memes = (W.identiques || []).map(g => g.filter(c => mics.has(c))).filter(g => g.length > 1).map(g => liste(g.map(sansExt)));
  const bas = W.fichiers.filter(f => mics.has(f.chemin) && (W.ecoute[f.chemin] || {}).bas).map(f => sansExt(f.chemin));
  return {memes, bas};
}

const texteMemes = n => `${esc(n)} contiennent exactement le même son : ce n'est pas un micro par personne.
  Récupère les pistes séparées de chaque micro (export de la table de mixage ou de Reaper).`;

export function ecran1(W, L) {
  if (!W.fichiers.length) {
    const choix = W.cherche
      ? `<button class="btn p lg" type="button" disabled><span class="spin"></span>La fenêtre de choix est ouverte…</button>
         <p class="muted" style="margin:12px 0 0;font-size:13px">Elle peut être derrière ton navigateur.</p>`
      : `${bouton({label: "Choisir le dossier…", action: "choisir", style: "p lg"})}
         <p class="muted" style="margin:14px 0 0;font-size:13px">ou ${bouton({label: "écrire l'emplacement du dossier",
           action: "manuel", style: "lnk"})}</p>`;
    return `<h2>Où sont les rushes ?</h2><p class="muted" style="margin:0">Choisis le dossier qui contient les fichiers son
      des micros et les vidéos des caméras de l'épisode.</p>
      <div class="drop"><div class="ill">📁</div>${choix}
      ${W.manuel && !W.cherche ? `<div style="display:flex;gap:8px;margin:14px auto 0;max-width:520px">
        <input class="inp" style="margin:0" data-champ="chemin" placeholder="Glisse le dossier ici ou colle son emplacement">
        ${bouton({label: "OK", action: "scanner"})}</div>` : ""}</div>
      ${W.msg ? `<div class="att">⚠ ${esc(W.msg)}</div>` : ""}`;
  }
  const alertes = [];
  if (!L.mics.length) alertes.push("Aucun micro trouvé. Si un fichier est mal reconnu, change son type ci-dessous.");
  if (!L.cams.length) alertes.push("Aucune caméra trouvée. Si un fichier est mal reconnu, change son type ci-dessous.");
  if (L.doublon) alertes.push(`Deux micros s'appellent « ${L.doublon} ». Donne un nom différent à chacun.`);
  const {memes} = alertesSon(W);
  const col = (titre, corps, aide, vide) => `<div><h3>${titre}</h3><p class="muted" style="margin:0;font-size:12.5px">${aide}</p>
    ${vide ? `<p class="muted" style="font-size:13.5px">Aucun.</p>` : corps}</div>`;
  const mics = W.fichiers.filter(f => f.type === "micro"), cams = W.fichiers.filter(f => f.type === "camera");
  return `<h2>Voici ce qu'on a trouvé</h2>
    <p class="muted" style="margin:0">Dans « ${esc(nomFichier(W.dossier))} » : <b>${pluriel(L.mics.length, "micro")}</b> et
      <b>${pluriel(L.cams.length, "caméra")}</b>. ${bouton({label: "Changer de dossier", action: "changer", style: "lnk"})}</p>
    ${memes.map(n => `<div class="att">⚠ <span>${texteMemes(n)}</span></div>`).join("")}
    ${alertes.map(a => `<div class="att">⚠ ${esc(a)}</div>`).join("")}
    <div class="trouve">${col("🎙 Micros", mics.map(f => ligne(W, f)).join(""), "Un fichier son par personne. ▶ pour écouter qui parle.", !mics.length)}
      ${col("🎥 Caméras", cameras(W, cams), "Une image du milieu de chaque vidéo.", !cams.length)}</div>
    <p class="aide">💡 Donne le même nom au micro et à la caméra d'une même personne (son prénom).
      La caméra qui filme tout le monde s'appelle LARGE.</p>`;
}

// ---- écran 2 : une carte par micro, avec l'image de la caméra du même nom
const image = cam => cam ? `<img src="/api/image_rush?f=${q(cam)}" alt="" onerror="this.remove()">` : "";
const morceaux = (L, cam) => {
  const n = L.cams.filter(c => c.nom === cam.nom).length;
  return n > 1 ? ` <span class="muted">+ ${pluriel(n - 1, "morceau", "morceaux")}</span>` : "";
};

export function ecran2(W, L) {
  const carte = p => `<div class="pc"><div class="im"><span class="ini">${esc((p.nom || p.id).charAt(0).toUpperCase())}</span>${image(p.cam)}</div>
    <div class="bd"><div class="src"><span class="srcl">${boutonEcoute(W, p.mic)}🎙 ${esc(nomFichier(p.mic.chemin))}</span>
      ${p.cam ? `🎥 ${esc(nomFichier(p.cam.chemin))}${morceaux(L, p.cam)}` : "Pas de caméra à son nom"}</div>
      <input class="inp nm" data-champ="pnom" data-id="${esc(p.id)}" value="${esc(p.nom)}" placeholder="Prénom Nom">
      <input class="inp" data-champ="pfonction" data-id="${esc(p.id)}" value="${esc(p.fonction)}" placeholder="Fonction (facultatif)">
      <div class="seg">${[["invité", "Invité·e"], ["animateur", "Animateur·rice"]].map(([r, l]) =>
        `<button type="button" class="${p.role === r ? "on" : ""}" data-act="role" data-id="${esc(p.id)}" data-role="${r}">${l}</button>`).join("")}</div>
    </div></div>`;
  return `<h2>Qui est qui ?</h2><p class="muted" style="margin:0">Une carte par micro. Indique le prénom de chacun et qui anime.</p>
    <div class="att" data-alerte-prenom>${alertePrenom(L)}</div>
    <div class="pers">${L.gens.map(carte).join("")}
      ${L.large ? `<div class="pc"><div class="im"><span class="ini">▣</span>${image(L.large)}</div><div class="bd"><b>Plan large</b>
        <div class="src">🎥 ${esc(nomFichier(L.large.chemin))}${morceaux(L, L.large)}</div><p class="muted" style="font-size:13px;margin:0">Filme tout le monde. Rien à remplir.</p></div></div>` : ""}</div>
    ${L.orphelines.length ? `<div class="att">⚠ ${L.orphelines.map(c => esc(nomFichier(c.chemin))).join(", ")} : caméra sans micro du même nom.
      Si elle filme une personne, reviens à l'étape 1 et donne-lui le nom de son micro.</div>` : ""}`;
}

// ---- écran 4 : rappel des alertes sur le son, on peut quand même lancer
export function rappelsSon(W) {
  const {memes, bas} = alertesSon(W);
  return memes.map(n => `<div class="att">⚠ <span>Rappel : ${texteMemes(n)} Tu peux lancer quand même, mais le montage
      ne saura pas qui parle.</span></div>`).join("") +
    (bas.length ? `<div class="att">⚠ <span>Le son de ${esc(liste(bas))} est très bas, vérifie que c'est la bonne piste.</span></div>` : "");
}
