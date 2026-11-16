// Appels au serveur. Toute erreur devient {erreur, actions} : jamais d'exception non gérée dans l'interface.
const HORS_LIGNE = {erreur: "Impossible de joindre l'app. Relance « Lancer ».", actions: [], hors_ligne: true};

async function reponse(r) {
  let d = {};
  try { d = await r.json(); } catch (e) { d = {}; }
  return r.ok ? d : {erreur: d.erreur || "Erreur du serveur. Envoie un rapport.", actions: d.actions || [],
                     code: r.status};
}

async function appel(url, corps) {
  try {
    return await reponse(await fetch(url, corps ? {method: "POST", headers: {"Content-Type": "application/json"},
                                                   body: JSON.stringify(corps)} : {cache: "no-store"}));
  } catch (e) {
    return {...HORS_LIGNE};
  }
}

// un fichier envoyé tel quel (pack .zip, logo, police)
async function envoyer(url, fichier) {
  try {
    return await reponse(await fetch(url, {method: "POST", headers: {"Content-Type": "application/octet-stream"},
                                           body: fichier}));
  } catch (e) {
    return {...HORS_LIGNE};
  }
}

export const api = {
  accueil: () => appel("/api/accueil"),
  projet: id => appel("/api/projet?id=" + encodeURIComponent(id)),
  activite: () => appel("/api/activite"),
  transcript: id => appel("/api/transcript?projet=" + encodeURIComponent(id)),
  action: (projet, action) => appel("/api/action", {projet, action}),
  tache: (projet, id, geste) => appel("/api/tache", {projet, id, geste}),
  choisirDossier: () => appel("/api/choisir_dossier", {}),
  scanner: dossier => appel("/api/scanner", {dossier}),
  creer: corps => appel("/api/creer", corps),
  // nouveau début : le dossier seul (titre et brief facultatifs), puis la pré-analyse et le casting
  creerDossier: corps => appel("/api/creer_dossier", corps),
  casting: projet => appel("/api/casting?projet=" + encodeURIComponent(projet)),
  verifier: (projet, micro) => appel("/api/casting/verifier", {projet, micro}),
  boucle: (projet, camera) => appel("/api/casting/boucle", {projet, camera}),
  apercuPassage: (projet, id) => appel("/api/apercu_passage", {projet, id}),
  harmoniser: projet => appel("/api/harmoniser", {projet}),
  // cible : export, shorts, episode, livraison (avec le nom du dossier daté), rapports (sans podcast)
  ouvrir: (projet, cible, nom) => appel("/api/ouvrir", nom ? {projet, cible, nom} : {projet, cible}),
  rapport: projet => appel("/api/rapport", projet ? {projet} : {}),
  choisirLut: () => appel("/api/choisir_lut", {}),
  niveaux: projet => appel("/api/niveaux?projet=" + encodeURIComponent(projet)),
  ecoute: (projet, version) =>
    appel(`/api/ecoute?projet=${encodeURIComponent(projet)}&version=${encodeURIComponent(version)}`),
  // packs de shorts
  packs: () => appel("/api/packs"),
  pack: id => appel("/api/packs/pack?id=" + encodeURIComponent(id)),
  creerPack: (nom, depuis) => appel("/api/packs/creer", depuis ? {nom, depuis} : {nom}),
  renommerPack: (id, nom) => appel("/api/packs/renommer", {id, nom}),
  modifierPack: (id, reglages) => appel("/api/packs/modifier", {id, reglages}),
  supprimerPack: id => appel("/api/packs/supprimer", {id}),
  importerPack: fichier => envoyer("/api/packs/importer", fichier),
  fichierPack: (id, fichier) =>
    envoyer(`/api/packs/fichier?id=${encodeURIComponent(id)}&nom=${encodeURIComponent(fichier.name)}`, fichier),
};

// adresse d'un fichier du projet (vidéo, image) servi par le serveur
export const media = (projet, f) => `/api/media?projet=${encodeURIComponent(projet)}&f=${encodeURIComponent(f)}`;

// image d'une caméra avec des réglages de couleur
export const imageCouleur = (projet, cam, reglages) =>
  `/api/image_couleur?projet=${encodeURIComponent(projet)}&cam=${encodeURIComponent(cam)}` +
  `&p=${encodeURIComponent(JSON.stringify(reglages || {}))}`;

// image d'aperçu d'un pack : réglages en cours d'édition (facultatifs), fond = id d'un podcast ou vide (neutre),
// v = empreinte du pack enregistré (le navigateur garde l'image tant qu'elle ne change pas)
export const apercuPack = (id, reglages, fond, v) => `/api/packs/apercu?id=${encodeURIComponent(id)}` +
  (reglages ? `&r=${encodeURIComponent(JSON.stringify(reglages))}` : "") +
  (fond ? `&fond=${encodeURIComponent(fond)}` : "") + (v ? `&v=${encodeURIComponent(v)}` : "");

export const exportPack = id => `/api/packs/exporter?id=${encodeURIComponent(id)}`;

// un short habillé par son pack (cle : change quand le pack, l'accroche ou le passage changent)
export const habillage = (projet, short, cle) => `/api/packs/habillage?projet=${encodeURIComponent(projet)}` +
  `&short=${encodeURIComponent(short)}&v=${encodeURIComponent(cle || "")}`;
