// Composants de l'interface : chaque fonction renvoie du HTML échappé ou un élément prêt à l'emploi.
import {api} from "./api.js";
import {jouer} from "./sons.js";

export const $ = s => document.querySelector(s);
export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

// un message du serveur ne doit jamais montrer de chemin technique (/Users/…, C:\…)
export function propre(msg) {
  return String(msg || "")
    .replace(/\s*:?\s*(?:\/(?:Users|Volumes|private|tmp|home|var|opt|mnt|media)\/|~\/|[A-Za-z]:\\)[^]*?\.[A-Za-z0-9]{2,5}(?=[.,;\s]|$)/g, "")
    .trim();
}

// nom de fichier seul, sans le dossier
export const nomFichier = f => String(f || "").split(/[\\/]/).filter(Boolean).pop() || "";

export function depuis(s) {
  if (s == null) return "";
  if (s < 5) return "à l'instant";
  if (s < 60) return `il y a ${Math.round(s)} s`;
  if (s < 3600) return `il y a ${Math.round(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.round(s / 3600)} h`;
  const j = Math.round(s / 86400);
  return j > 1 ? `il y a ${j} jours` : "hier";
}

export function dateFr(t) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(t || "");
  if (!m) return "";
  const mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
                "novembre", "décembre"][+m[2] - 1];
  return `${+m[3]} ${mois} ${m[1]}`;
}

// barre de progression réelle d'une tâche (vue « tache » du serveur)
export function barre(t, {mini = false} = {}) {
  if (!t) return "";
  const attente = t.statut === "en_attente", lente = t.statut === "semble_bloquee";
  const p = t.pourcent;
  const jauge = p == null || attente
    ? `<div class="jauge${attente ? "" : " indet"}"><i${attente ? ' style="width:100%"' : ""}></i></div>`
    : `<div class="jauge" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${p}">` +
      `<i style="width:${Math.max(2, Math.min(100, p))}%"></i></div>`;
  const texte = attente ? "En attente : ça démarre dès qu'une place se libère." : (t.texte || "Ça démarre…");
  const restant = attente ? "" : (t.restant ? `Reste ${esc(t.restant)}` : "Temps restant : on calcule…");
  const vie = t.depuis_vie != null ? `<span class="vie">Dernière avancée ${depuis(t.depuis_vie)}</span>` : "";
  const alerte = lente ? `<div class="lent">Ça semble ralenti. On surveille, tu n'as rien à faire pour l'instant.</div>` : "";
  return `<div class="bar${mini ? " mini" : ""}${lente ? " lente" : ""}${attente ? " attente" : ""}">
    <div class="tt"><b>${esc(t.titre)}</b><span class="pct">${p == null || attente ? "" : p + " %"}</span></div>
    ${jauge}<div class="txt">${esc(texte)}</div>
    ${restant || vie ? `<div class="ss"><span>${restant}</span>${vie}</div>` : ""}${alerte}</div>`;
}

const STATUTS = {a_faire: "À faire", a_valider: "À valider", valide: "Validé", a_refaire: "À refaire",
                 en_cours: "En cours"};
export function pastille(statut) {
  const s = STATUTS[statut] ? statut : "a_faire";
  return `<span class="pastille ${s}"><i></i>${STATUTS[s]}</span>`;
}

// bouton ; désactivé, il dit pourquoi (au survol ET en petit dessous)
export function bouton({label, action, actif = true, raison = "", style = "", sous = "", html = false, attrs = ""}) {
  const titre = !actif && raison ? ` title="${esc(raison)}"` : "";
  const b = `<button type="button" class="btn ${style}" data-act="${esc(action)}" ${attrs}` +
    `${actif ? "" : ' disabled aria-disabled="true"'}${titre}>${html ? label : esc(label)}` +
    `${sous ? `<small>${esc(sous)}</small>` : ""}</button>`;
  return actif || !raison ? b : `<span class="bw"${titre}>${b}<span class="why">${esc(raison)}</span></span>`;
}

// clics sur [data-act] dans un conteneur : un seul écouteur, les gestionnaires peuvent changer à chaque rendu
export function lier(el, gestionnaires) {
  el._gest = gestionnaires;
  if (el._lie) return;
  el._lie = true;
  el.addEventListener("click", e => {
    const b = e.target.closest("[data-act]");
    if (!b || !el.contains(b) || b.disabled) return;
    const f = el._gest[b.dataset.act];
    if (!f) return;
    e.preventDefault();
    const r = f(b, e);
    // geste qui attend le serveur : le bouton montre qu'il travaille (rotor), jusqu'à la réponse
    if (r && typeof r.then === "function" && b.classList.contains("btn")) {
      b.setAttribute("aria-busy", "true");
      const fin = () => b.removeAttribute("aria-busy");
      r.then(fin, fin);
    }
  });
}

// couleur propre à chaque personne du podcast (ordre des personnes), réutilisée partout : style="--c:…"
const TEINTES = 6;
export function teinte(v, cle) {
  const ps = (v && v.personnes) || [];
  const i = ps.findIndex(p => p.id === cle || p.nom === cle);
  return i < 0 ? "" : `--c:var(--p${(i % TEINTES) + 1})`;
}

export function toast(msg, ton = "", {son = true} = {}) {
  const e = $("#toast");
  if (!e) return;
  if (son) jouer(ton === "ok" ? "valide" : ton === "no" ? "erreur" : "");
  e.textContent = propre(msg);
  e.className = "toast on " + ton;
  clearTimeout(e._t);
  e._t = setTimeout(() => e.classList.remove("on"), ton === "no" ? 5000 : 3000);
}

// fenêtre par-dessus la page ; la page ne se redessine pas tant qu'elle est ouverte
export function modale(contenu, {classe = "", fermable = true, onFermer} = {}) {
  const fond = document.createElement("div");
  fond.className = "modal on " + classe;
  const box = document.createElement("div");
  box.className = "box";
  if (contenu instanceof Node) box.append(contenu); else box.innerHTML = contenu || "";
  fond.append(box);
  document.body.append(fond);
  const peut = () => (typeof fermable === "function" ? fermable() : fermable);
  const dessus = () => [...document.querySelectorAll(".modal.on")].pop() === fond;
  const clavier = e => { if (e.key === "Escape" && dessus() && peut()) fermer(); };
  function fermer() {
    if (!fond.isConnected) return;
    fond.remove();
    document.removeEventListener("keydown", clavier);
    if (onFermer) onFermer();
    document.dispatchEvent(new Event("ui:libre"));
  }
  fond.addEventListener("click", e => { if (e.target === fond && peut()) fermer(); });
  document.addEventListener("keydown", clavier);
  return {el: box, fond, fermer};
}

// lecteur vidéo plein écran ; debut / fin (secondes) pour réécouter un morceau précis.
// debut négatif : compté depuis la fin (-3 = les 3 dernières secondes)
export function lecteur(src, {debut = 0, fin = null, titre = ""} = {}) {
  const m = modale("", {classe: "player"});
  m.el.className = "";
  m.el.innerHTML = `<button class="x" type="button" aria-label="Fermer">×</button>
    <video class="hvid" src="${esc(src)}" controls autoplay playsinline></video>
    ${titre ? `<p style="color:#fff;text-align:center;margin:10px 0 0">${esc(titre)}</p>` : ""}`;
  const v = m.el.querySelector("video");
  m.el.querySelector(".x").onclick = m.fermer;
  v.addEventListener("loadedmetadata", () => {
    if (debut) v.currentTime = debut < 0 ? Math.max(0, (v.duration || 0) + debut) : debut;
  });
  v.addEventListener("timeupdate", () => { if (fin != null && v.currentTime >= fin) v.pause(); });
  v.addEventListener("error", () => { toast("Cette vidéo ne se lit pas. Elle est peut-être encore en préparation.", "no"); });
  const fermer = m.fermer;
  m.fermer = () => { v.pause(); fermer(); };
  return m;
}

const LIBELLES = {reessayer: "Réessayer", rapport: "Envoyer un rapport",
                  choisir_au_transcript: "Choisir dans le transcript", liberer_disque: "Libérer de la place"};

// encadré d'erreur : message en clair + boutons d'action (gestes = {reessayer: fn, choisir_au_transcript: fn})
export function erreur(e, {projet = null, gestes = {}} = {}) {
  const el = document.createElement("div");
  el.className = "errbox";
  const acts = (e.actions || []).filter(a => LIBELLES[a]);
  el.innerHTML = `<div style="flex:1"><b>${esc(propre(e.erreur || e))}</b></div>
    ${acts.length ? `<div class="acts">${acts.map(a => bouton({label: LIBELLES[a], action: a})).join("")}</div>` : ""}`;
  lier(el, {
    reessayer: () => gestes.reessayer && gestes.reessayer(),
    choisir_au_transcript: () => gestes.choisir_au_transcript && gestes.choisir_au_transcript(),
    liberer_disque: () => toast("Vide la corbeille ou déplace d'anciens podcasts sur un autre disque, puis réessaie.", "warn"),
    rapport: b => envoyerRapport(projet, b),
  });
  return el;
}

const FINDER = /Win/i.test(navigator.platform || "") ? "l'Explorateur" : "le Finder";

// rapport de dépannage (journaux et états, jamais de vidéo) puis fenêtre « Rapport prêt » avec « Ouvrir le dossier »
export async function envoyerRapport(projet, b) {
  const texte = b ? b.innerHTML : "";
  if (b) { b.disabled = true; b.innerHTML = `<span class="spin"></span>Préparation…`; }
  const r = await api.rapport(projet);
  if (b) { b.disabled = false; b.innerHTML = texte; }
  if (r.erreur) { toast(r.erreur, "no"); return; }
  const m = modale(`<h2>Rapport prêt</h2>
    <p>Il s'appelle « ${esc(nomFichier(r.fichier))} ». Envoie-le à la personne qui t'aide, par mail ou par message.</p>
    <p class="muted small">Il contient l'état des tâches et du podcast, jamais tes vidéos ni tes sons.</p>
    <div class="foot">${bouton({label: "Fermer", action: "non", style: "ghost"})}
      ${bouton({label: "Ouvrir le dossier", action: "ouvrir", style: "p"})}</div>`);
  lier(m.el, {
    non: () => m.fermer(),
    ouvrir: async () => {
      const o = await api.ouvrir(null, "rapports");
      if (o.erreur) toast(o.erreur, "no");
      else { toast(`Le dossier des rapports s'ouvre dans ${FINDER}.`, "ok"); m.fermer(); }
    },
  });
}
