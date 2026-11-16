// « Nouveau podcast » : on choisit seulement le dossier des rushes (titre et brief facultatifs), puis l'app crée le
// podcast et lance la pré-analyse ; on arrive sur l'étape Casting. L'ancien assistant (fichiers et noms choisis à
// la main) ne s'ouvre que si cette création échoue : il permet de corriger un fichier mal reconnu.
import {api} from "../api.js";
import {aller} from "../routeur.js";
import {bouton, esc, lier, modale, nomFichier, propre, toast} from "../ui.js";
import {ouvrirCreation} from "./creation.js";

let W = null, M = null;
const pluriel = (n, un, plusieurs = un + "s") => `${n} ${n > 1 ? plusieurs : un}`;

export function ouvrirNouveau() {
  W = {dossier: "", micros: 0, cameras: 0, titre: "", brief: "", cherche: false, manuel: false, envoi: false,
       msg: null, echec: false, pack: null, packs: [], packChoisi: false};
  M = modale("", {fermable: () => W && !W.cherche && !W.envoi, onFermer: () => { W = null; M = null; }});
  lier(M.el, gestes);
  M.el.addEventListener("input", e => {
    const c = e.target.dataset.champ;
    if (c === "titre") W.titre = e.target.value;
    else if (c === "brief") W.brief = e.target.value;
    else if (c === "pack") { W.pack = e.target.value; W.packChoisi = true; }
  });
  M.el.addEventListener("keydown", e => {
    if (e.target.dataset.champ === "chemin" && e.key === "Enter") { e.preventDefault(); gestes.scanner(); }
  });
  dessiner();
  // packs de la bibliothèque, pré-rempli avec le dernier utilisé (sinon le neutre). Tant que la personne n'y touche
  // pas, rien n'est envoyé : le serveur prend son pack par défaut (le même, sauf réglage particulier de config.json)
  api.packs().then(r => {
    if (!W || r.erreur) return;
    W.packs = (r.packs || []).filter(p => !p.illisible);
    W.pack = W.pack || r.defaut || r.dernier || ((W.packs.find(p => p.id === "neutre") || W.packs[0] || {}).id ?? null);
    if (M && W.dossier) dessiner();
  });
}

function raison() {
  if (!W.dossier) return "Choisis d'abord le dossier des rushes.";
  if (!W.micros) return "Aucun fichier son dans ce dossier : il faut au moins un micro.";
  if (!W.cameras) return "Aucune vidéo dans ce dossier : il faut au moins une caméra.";
  if (W.envoi) return "Création en cours, patiente quelques secondes.";
  return "";
}

function choix() {
  if (W.cherche) {
    return `<button class="btn p lg" type="button" disabled><span class="spin"></span>La fenêtre de choix est ouverte…</button>
      <p class="muted" style="margin:12px 0 0;font-size:13px">Elle peut être derrière ton navigateur.</p>`;
  }
  return `${bouton({label: W.dossier ? "Choisir un autre dossier…" : "Choisir le dossier…", action: "choisir",
    style: W.dossier ? "" : "p lg"})}
    <p class="muted" style="margin:14px 0 0;font-size:13px">ou ${bouton({label: "écrire l'emplacement du dossier",
      action: "manuel", style: "lnk"})}</p>
    ${W.manuel ? `<div class="nv-chemin"><input class="inp" data-champ="chemin" aria-label="Emplacement du dossier"
      placeholder="Glisse le dossier ici ou colle son emplacement">${bouton({label: "OK", action: "scanner"})}</div>` : ""}`;
}

function trouve() {
  if (!W.dossier) return "";
  const ok = W.micros && W.cameras;
  return `<div class="nv-trouve ${ok ? "ok" : "ko"}"><span class="nv-ic" aria-hidden="true">${ok ? "✓" : "!"}</span>
    <span><b>« ${esc(nomFichier(W.dossier))} »</b><br>${pluriel(W.micros, "micro")} · ${pluriel(W.cameras, "caméra")}
    ${ok ? "" : `<br><span class="muted">Si un fichier est mal reconnu, ${bouton({label: "choisis les fichiers à la main",
      action: "ancien", style: "lnk"})}.</span>`}</span></div>`;
}

function dessiner() {
  if (!M) return;
  const r = raison();
  M.el.innerHTML = `<h2>Nouveau podcast</h2>
    <p class="muted" style="margin:0">Donne le dossier des rushes. L'app trouve seule qui est qui, tu n'as plus qu'à confirmer.</p>
    <div class="drop nv-drop"><div class="ill" aria-hidden="true">📁</div>${choix()}</div>
    ${trouve()}
    ${W.dossier ? `<label class="lbl" for="nv-titre">Titre <span class="muted" style="font-weight:500">(facultatif)</span></label>
      <input class="tit" id="nv-titre" data-champ="titre" value="${esc(W.titre)}" placeholder="${esc(nomFichier(W.dossier))}">
      <details class="adv"${W.brief ? " open" : ""}><summary>Ajouter un brief pour l'IA (facultatif)</summary>
        <textarea class="inp" style="margin-top:8px" data-champ="brief" aria-label="Brief pour l'IA"
          placeholder="Sujets à mettre en avant ou à éviter, ton, nombre de shorts.">${esc(W.brief)}</textarea></details>
      ${W.packs.length ? `<label class="lbl" for="nv-pack">Pack de shorts</label>
        <div class="nv-pack"><select class="inp" id="nv-pack" data-champ="pack">${W.packs.map(p =>
          `<option value="${esc(p.id)}"${p.id === W.pack ? " selected" : ""}>${esc(p.nom)}</option>`).join("")}</select></div>
        <p class="muted" style="margin:0;font-size:12.5px">L'habillage des shorts : sous-titres, couleurs, logo.
          Tu pourras le changer à l'étape Shorts.</p>` : ""}` : ""}
    ${W.msg ? `<div class="errbox"><div style="flex:1"><b>${esc(W.msg)}</b>${W.echec ? `<br><span class="muted small">Tu peux
      choisir les fichiers et les noms à la main.</span>` : ""}</div>${W.echec ? `<div class="acts">${bouton({label:
      "Choisir les fichiers à la main", action: "ancien"})}</div>` : ""}</div>` : ""}
    <div class="foot">${bouton({label: "Annuler", action: "fermer", style: "ghost"})}
      ${bouton({label: W.envoi ? `<span class="spin"></span>Création…` : "Lancer la pré-analyse →", action: "creer",
        style: "p lg", actif: !r, raison: r, html: true})}</div>`;
}

function recu(dossier, r) {
  const fs = r.fichiers || [];
  W.dossier = dossier;
  W.micros = fs.filter(f => f.type === "micro").length;
  W.cameras = new Set(fs.filter(f => f.type === "camera").map(f => f.nom)).size;
  W.manuel = false; W.msg = null; W.echec = false;
  dessiner();
}

async function creer() {
  if (raison()) return;
  W.envoi = true; W.msg = null;
  dessiner();
  const corps = {dossier: W.dossier};
  if (W.titre.trim()) corps.titre = W.titre.trim();
  if (W.brief.trim()) corps.brief = W.brief.trim();
  if (W.pack && W.packChoisi) corps.pack = W.pack;
  const r = await api.creerDossier(corps);
  if (!W) return;
  W.envoi = false;
  if (r.erreur) { W.msg = propre(r.erreur); W.echec = !r.hors_ligne; dessiner(); return; }
  M.fermer();
  toast("C'est parti : l'app cherche qui est qui.", "ok");
  aller({ecran: "projet", projet: r.projet, etape: "casting"});
}

const gestes = {
  fermer: () => M.fermer(),
  manuel: () => { W.manuel = true; dessiner(); M.el.querySelector('[data-champ="chemin"]').focus(); },
  ancien: () => { M.fermer(); ouvrirCreation(); },
  creer,
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
    const v = (M.el.querySelector('[data-champ="chemin"]')?.value || "").trim().replace(/^['"]|['"]$/g, "");
    if (!v) { toast("Écris d'abord l'emplacement du dossier."); return; }
    const r = await api.scanner(v);
    if (!W) return;
    if (r.erreur) { W.msg = r.hors_ligne ? r.erreur : "Ce dossier est introuvable. Vérifie son emplacement."; dessiner(); return; }
    recu(v, r);
  },
};
