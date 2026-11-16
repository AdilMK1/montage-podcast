// Assistant « Nouveau podcast » en 4 écrans : 1 dossier des rushes, 2 qui est qui, 3 noms propres et brief,
// 4 lancement. Rien n'est créé avant le dernier bouton ; le double-clic ne crée pas deux projets.
import {api} from "../api.js";
import {aller} from "../routeur.js";
import {bouton, esc, lier, modale, nomFichier, propre, toast} from "../ui.js";
import {alertePrenom, arreterSon, ecouter, ecran1, ecran2, pluriel, prenomValable, preparerEcoutes, rappelsSon} from "./creation_rushes.js";

const NOMS_ETAPES = ["Les rushes", "Qui est qui", "Noms et brief", "Lancement"];
const EXEMPLE_BRIEF = "Exemple : mets en avant son parcours et l'anecdote de son premier concert. " +
  "Évite les passages sur sa famille. Ton léger, plutôt drôle. 5 shorts.";
let W = null, M = null;

export function ouvrirCreation() {
  W = {etape: 1, dossier: "", fichiers: [], identiques: [], ecoute: {}, joue: null, pers: {}, noms: [], retires: [],
       brief: "", titre: "", cherche: false, manuel: false, envoi: false, msg: null};
  M = modale("", {fermable: () => W && W.etape === 1 && !W.cherche, onFermer: () => { arreterSon(W); W = null; M = null; }});
  lier(M.el, gestes);
  M.el.addEventListener("input", saisie);
  M.el.addEventListener("change", changement);
  M.el.addEventListener("keydown", clavier);
  dessiner();
}

// « SARAH » -> « Sarah » ; « LEO_2 » -> « Léo 2 »
const joli = n => n.toLowerCase().replace(/_+/g, " ").trim().replace(/(^|\s)\S/g, c => c.toUpperCase());
const ident = v => v.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase().replace(/[^A-Z0-9_]+/g, "_").slice(0, 20);
const GENERIQUE = /^(rush(es)?|sd|carte ?sd|dcim|private|m4root|clip|vid[eé]os?|m[eé]dias?|sources?|import|untitled|sans titre|nouveau dossier|podcast|tournage|audio|son|cam[eé]ras?)?[ _-]*\d*$/i;

function lecture() {
  const on = W.fichiers.filter(f => f.on);
  const mics = on.filter(f => f.type === "micro"), cams = on.filter(f => f.type === "camera");
  const gens = mics.map((m, i) => {
    if (!W.pers[m.nom]) W.pers[m.nom] = {nom: joli(m.nom), fonction: "", role: i === 0 ? "animateur" : "invité"};
    return {id: m.nom, mic: m, cam: cams.find(c => c.nom === m.nom), ...W.pers[m.nom]};
  });
  const noms = mics.map(m => m.nom);
  const doublon = noms.find((n, i) => noms.indexOf(n) !== i);
  const orphelines = cams.filter(c => c.nom !== "LARGE" && !noms.includes(c.nom));
  return {mics, cams, gens, doublon, orphelines, large: cams.find(c => c.nom === "LARGE")};
}

function raison() {
  const L = lecture();
  if (W.etape === 1) {
    if (!W.fichiers.length) return "Choisis d'abord le dossier des rushes.";
    if (!L.mics.length) return "Il faut au moins un micro (fichier son).";
    if (!L.cams.length) return "Il faut au moins une caméra (fichier vidéo).";
    if (L.doublon) return `Deux micros s'appellent « ${L.doublon} » : renomme l'un des deux.`;
  }
  if (W.etape === 2 && L.gens.some(p => !p.nom.trim())) return "Indique le prénom de chaque personne.";
  if (W.etape === 4) {
    if (W.envoi) return "Création en cours, patiente quelques secondes.";
    if (!W.titre.trim()) return "Donne un titre au podcast.";
  }
  return "";
}

function entete() {
  return `<div class="wz">${NOMS_ETAPES.map((_, i) => `<div class="${i < W.etape ? "on" : ""}"></div>`).join("")}</div>
    <p class="muted" style="margin:-12px 0 14px;font-size:13px">Étape ${W.etape} sur 4 · ${NOMS_ETAPES[W.etape - 1]}</p>`;
}

function pied(suivant) {
  const r = raison();
  const gauche = W.envoi ? "<span></span>" : W.etape === 1 ? bouton({label: "Annuler", action: "fermer", style: "ghost"})
    : `<span style="display:flex;gap:8px">${bouton({label: "← Retour", action: "retour", style: "ghost"})}` +
      `${bouton({label: "Annuler", action: "fermer", style: "ghost"})}</span>`;
  return `<div class="foot">${gauche}${bouton({label: suivant, action: W.etape === 4 ? "creer" : "suivant",
    style: "p lg", actif: !r, raison: r, html: true})}</div>`;
}

function ecran3() {
  return `<h2>Noms propres et brief</h2><p class="muted" style="margin:0">Facultatif, mais ça aide l'IA à bien écrire et à bien choisir.</p>
    <label class="lbl">Noms à bien orthographier</label>
    <div class="tags">${W.noms.map((n, i) => `<span class="tagp">${esc(n)}<button type="button" data-act="retirer" data-i="${i}"
      title="Retirer">×</button></span>`).join("")}<input data-champ="nom-propre" placeholder="Invités, émission, marques, lieux… puis Entrée"></div>
    <p class="muted" style="font-size:12.5px;margin:6px 0 0">Ces mots seront écrits comme ça dans les sous-titres et les titres des shorts.</p>
    <label class="lbl">Brief pour l'IA</label>
    <textarea class="inp" data-champ="brief" placeholder="${esc(EXEMPLE_BRIEF)}">${esc(W.brief)}</textarea>
    <p class="muted" style="font-size:12.5px;margin:0">Sujets à mettre en avant, à éviter, ton, nombre de shorts.</p>`;
}

function ecran4() {
  const L = lecture();
  return `<h2>Tout est prêt 🚀</h2><p class="muted" style="margin:0">Vérifie le titre, puis lance. Tu pourras tout régler ensuite.</p>
    <label class="lbl">Titre du podcast</label><input class="tit" data-champ="titre" value="${esc(W.titre)}" placeholder="Ex. : Sarah × Léo">
    <div class="recap"><div><b>${L.cams.length}</b><span class="muted">${L.cams.length > 1 ? "caméras" : "caméra"}</span></div>
      <div><b>${L.mics.length}</b><span class="muted">${L.mics.length > 1 ? "micros" : "micro"}</span></div>
      <div><b style="font-size:17px">${esc(L.gens.map(p => p.nom).join(" · "))}</b><span class="muted">au micro</span></div></div>
    ${rappelsSon(W)}
    <p class="muted" style="font-size:13.5px;margin:12px 0 0">${W.noms.length ? pluriel(W.noms.length, "nom propre", "noms propres") : "Aucun nom propre"}
      · ${W.brief.trim() ? "brief pour l'IA rempli" : "pas de brief pour l'IA"}</p>
    <div class="chk" style="max-width:none;margin-top:18px">
      <div class="fait"><i>1</i>On synchronise les caméras sur les micros.</div>
      <div class="fait"><i>2</i>On transcrit toute la conversation et on nettoie le son.</div>
      <div class="fait"><i>3</i>On prépare des copies légères des vidéos, pour monter vite.</div></div>
    <p class="muted" style="font-size:13.5px;margin:14px 0 0">Ça tourne tout seul. Pendant ce temps, tu pourras régler la couleur.</p>
    ${W.msg ? `<div class="errbox"><b>${esc(W.msg)}</b></div>` : ""}`;
}

function dessiner() {
  if (!M) return;
  const corps = [() => ecran1(W, lecture()), () => ecran2(W, lecture()), ecran3, ecran4][W.etape - 1]();
  const suivant = W.etape === 4
    ? (W.envoi ? `<span class="spin"></span>Création en cours…` : "Créer et lancer l'analyse")
    : "Continuer →";
  M.el.innerHTML = entete() + corps + pied(suivant);
}

function recu(dossier, r) {
  arreterSon(W);
  W.dossier = dossier;
  W.fichiers = (r.fichiers || []).map(f => ({...f, on: true}));
  W.identiques = r.identiques || [];
  W.ecoute = {};
  // un dossier au nom passe-partout (« rushes », « DCIM »…) ne fait pas un titre : on proposera les prénoms
  const nom = nomFichier(dossier);
  W.titre = GENERIQUE.test(nom.trim()) ? "" : joli(nom);
  W.pers = {}; W.noms = []; W.retires = [];
  W.msg = W.fichiers.length ? null : "Aucun fichier son ou vidéo dans ce dossier. Choisis le dossier qui contient les rushes.";
  preparerEcoutes(W, () => M && M.el);
  dessiner();
}

// ajoute le nom tapé ; sans redessiner (« garder ») quand on quitte l'écran : le clic en cours n'est pas perdu
function ajouterNom(input, garder = false) {
  if (!input) return;
  const v = input.value.replace(/,/g, " ").trim();
  input.value = "";
  if (!v || W.noms.some(n => n.toLowerCase() === v.toLowerCase())) return;
  W.noms.push(v);
  if (garder) return;
  dessiner();
  focusNoms();
}
const nomEnCours = () => ajouterNom(M.el.querySelector('[data-champ="nom-propre"]'), true);

async function creer() {
  if (W.envoi || raison()) return;  // double-clic : le second clic ne fait rien
  W.envoi = true; W.msg = null;
  dessiner();
  const L = lecture();
  const personnes = Object.fromEntries(L.gens.map(p => [p.id, {nom: p.nom.trim(), fonction: p.fonction.trim(), role: p.role}]));
  const r = await api.creer({titre: W.titre.trim(), personnes, noms_propres: W.noms, brief: W.brief.trim(),
    fichiers: W.fichiers.filter(f => f.on).map(({chemin, type, nom}) => ({chemin, type, nom}))});
  if (!W) return;
  if (r.erreur) { W.envoi = false; W.msg = propre(r.erreur); dessiner(); return; }
  M.fermer();
  toast("C'est parti : l'analyse démarre.", "ok");
  aller({ecran: "projet", projet: r.projet});
}

const gestes = {
  fermer: () => M.fermer(),
  manuel: () => { W.manuel = true; dessiner(); M.el.querySelector('[data-champ="chemin"]').focus(); },
  changer: () => { arreterSon(W); W.fichiers = []; W.msg = null; dessiner(); },
  ecouter: b => ecouter(W, M.el, +b.dataset.i),
  async choisir() {
    if (W.cherche) return;
    W.cherche = true; W.msg = null;
    dessiner();
    const r = await api.choisirDossier();
    if (!W) return;
    W.cherche = false;
    if (r.erreur) { W.msg = propre(r.erreur); dessiner(); return; }
    if (!r.dossier) { dessiner(); toast("Aucun dossier choisi. Tu peux réessayer quand tu veux."); return; }
    recu(r.dossier, r);
  },
  async scanner() {
    const v = M.el.querySelector('[data-champ="chemin"]').value.trim().replace(/^['"]|['"]$/g, "");
    if (!v) { toast("Écris d'abord l'emplacement du dossier."); return; }
    const r = await api.scanner(v);
    if (!W) return;
    if (r.erreur) { W.msg = r.hors_ligne ? r.erreur : "Ce dossier est introuvable. Vérifie son emplacement."; dessiner(); return; }
    recu(v, r);
  },
  suivant: () => {
    if (raison()) return;
    nomEnCours();
    arreterSon(W);
    W.etape++;
    if (W.etape === 4 && !W.titre.trim()) W.titre = lecture().gens.map(p => p.nom.trim()).filter(prenomValable).join(" × ");
    if (W.etape === 3) {  // pré-remplir avec les vrais prénoms de l'écran 2 (pas « 1 » ni « MICRO_1 »)
      for (const p of lecture().gens) {
        const n = p.nom.trim();
        if (prenomValable(n) && !W.retires.includes(n) && !W.noms.some(x => x.toLowerCase() === n.toLowerCase())) W.noms.push(n);
      }
    }
    dessiner();
  },
  retour: () => { nomEnCours(); arreterSon(W); W.etape--; W.msg = null; dessiner(); },
  role: b => { W.pers[b.dataset.id].role = b.dataset.role; dessiner(); },
  retirer: b => { const [n] = W.noms.splice(+b.dataset.i, 1); W.retires.push(n); dessiner(); },
  creer,
};

// saisie au clavier : on garde la valeur sans redessiner (le curseur reste dans le champ)
function saisie(e) {
  const c = e.target.dataset.champ, id = e.target.dataset.id;
  if (c === "pnom") {
    W.pers[id].nom = e.target.value;
    const a = M.el.querySelector("[data-alerte-prenom]");
    if (a) a.textContent = alertePrenom(lecture());
  }
  else if (c === "pfonction") W.pers[id].fonction = e.target.value;
  else if (c === "brief") W.brief = e.target.value;
  else if (c === "titre") W.titre = e.target.value;
  else return;
  majPied();
}

// le bouton « Continuer » suit la saisie (actif ou non, avec sa raison) sans toucher aux champs
function majPied() {
  const f = M.el.querySelector(".foot");
  if (f) f.outerHTML = pied(W.etape === 4 ? "Créer et lancer l'analyse" : "Continuer →");
}

function changement(e) {
  const c = e.target.dataset.champ, f = W.fichiers[+e.target.dataset.i];
  if (c === "on") f.on = e.target.checked;
  else if (c === "type") f.type = e.target.value;
  else if (c === "nom") f.nom = ident(e.target.value) || f.nom;
  else return;
  dessiner();
}

function clavier(e) {
  const c = e.target.dataset.champ;
  if (c === "nom-propre") {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); ajouterNom(e.target); }
    else if (e.key === "Backspace" && !e.target.value && W.noms.length) { W.retires.push(W.noms.pop()); dessiner(); focusNoms(); }
  } else if (c === "chemin" && e.key === "Enter") { e.preventDefault(); gestes.scanner(); }
}

const focusNoms = () => M.el.querySelector('[data-champ="nom-propre"]').focus();
