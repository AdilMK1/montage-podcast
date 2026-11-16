// Écran Activité : l'état général (voyant + phrase), les tâches de tous les podcasts en 4 groupes (en cours,
// en attente, en échec, terminées) et la machine (processeur, mémoire, disque, encodeur, IA, veille).
// Les zones se mettent à jour séparément : une barre qui avance ne redessine pas les boutons d'à côté.
import {api} from "../api.js";
import {store} from "../store.js";
import {barre, bouton, depuis, envoyerRapport, esc, lier, modale, propre, toast} from "../ui.js";

const cles = {};
const pluriel = (n, mot) => `${n} ${mot}${n > 1 ? "s" : ""}`;

// la phrase du voyant, d'après la couleur décidée par le serveur
function etatGeneral(a) {
  const g = a.groupes, m = a.machine, n = g.en_cours.length;
  if (!a.atelier.vivant) return ["Le moteur de travail est arrêté",
    "Les rendus sont en pause. Il redémarre tout seul en quelques secondes. Sinon, clique sur « Redémarrer » en haut."];
  if (g.echec.length) return ["Une tâche demande ton attention",
    g.echec.length > 1 ? `${g.echec.length} tâches n'ont pas marché. Réessaie-les ou envoie un rapport.`
      : "Une tâche n'a pas marché. Réessaie-la ou envoie un rapport."];
  if (m.disque.niveau === "rouge") return ["Le disque est presque plein",
    "Les rendus sont bloqués. Vide la corbeille ou déplace d'anciens podcasts sur un autre disque."];
  if (g.en_cours.some(t => t.statut === "semble_bloquee")) return ["Une tâche semble ralentie",
    "On la surveille. Tu n'as rien à faire pour l'instant."];
  if (m.disque.niveau === "orange") return ["Le disque commence à se remplir",
    `Il reste ${m.disque.libre}. Pense à faire de la place avant les prochains rendus.`];
  return ["Tout tourne", n ? `${pluriel(n, "tâche")} en cours${g.en_attente.length
    ? `, ${g.en_attente.length} en attente` : ""}. Tu peux continuer à travailler.` : "Rien ne tourne en ce moment. Tout est à jour."];
}

function tete(a) {
  const [titre, sous] = etatGeneral(a);
  return `<div class="agen ${esc(a.voyant)}"><i></i><div><h1>${esc(titre)}</h1><p class="muted">${esc(sous)}</p></div>
    ${bouton({label: "Envoyer un rapport", action: "rapport", style: "ghost", attrs: 'data-projet=""'})}</div>`;
}

const lienPodcast = t => `<a class="apod" href="/?projet=${encodeURIComponent(t.projet)}" data-nav
  title="Ouvrir ce podcast">${esc(t.podcast || t.projet)}</a>`;
const annuler = t => bouton({label: "Annuler", action: "annuler", style: "ghost sm", attrs: `data-id="${esc(t.id)}" data-projet="${esc(t.projet)}"`});

// la partie vivante d'une tâche en cours (barre, temps), redessinée seule : les boutons ne bougent pas sous le curseur
function vivantEnCours(t, vivant) {
  const pause = vivant ? "" : `<div class="apause">En pause : elle reprend où elle en était dès que le moteur redémarre.</div>`;
  return `${barre(t)}${pause}<span class="muted small">${t.ecoule ? `Lancée il y a ${esc(t.ecoule)}` : "Vient de démarrer"}</span>`;
}

function enCours(t, vivant) {
  return `<div class="atache${vivant ? "" : " pause"}">${lienPodcast(t)}<div class="avif" data-b="${esc(t.id)}"></div>
    <div class="apied">${annuler(t)}</div></div>`;
}

function enAttente(t, vivant) {
  const raison = t.raison || (vivant ? "Attend une place : elle démarre dès qu'une autre tâche se termine."
    : "Attend que le moteur de travail redémarre.");
  return `<div class="atache attente">${lienPodcast(t)}<div class="tt"><b>${esc(t.titre)}</b></div>
    <div class="apied"><span class="muted small">${esc(raison)}</span>${annuler(t)}</div></div>`;
}

function enEchec(t) {
  const id = `data-id="${esc(t.id)}" data-projet="${esc(t.projet)}"`;
  return `<div class="atache echec">${lienPodcast(t)}<div class="tt"><b>${esc(t.titre)}</b></div>
    <p class="aerr">${esc(propre(t.erreur) || "Ça n'a pas marché.")}</p>
    <div class="acts">${bouton({label: "Réessayer", action: "reessayer", style: "p sm", attrs: id})}
      ${bouton({label: "Annuler", action: "annuler", style: "ghost sm", attrs: id})}
      ${bouton({label: "Envoyer un rapport", action: "rapport", style: "ghost sm", attrs: `data-projet="${esc(t.projet)}"`})}</div></div>`;
}

function terminee(t) {
  const ok = t.statut === "terminee";
  // à la minute près : la liste ne se redessine pas à chaque sondage
  const s = t.fin ? Date.now() / 1000 - t.fin : null;
  const quand = s == null ? "" : s < 60 ? "à l'instant" : depuis(Math.floor(s / 60) * 60);
  return `<li class="${ok ? "ok" : "non"}"><span class="ic">${ok ? "✓" : "–"}</span>
    <span><b>${esc(t.titre)}</b> · ${lienPodcast(t)}</span>
    <span class="muted small">${ok ? "Terminée" : "Annulée"}${quand ? ` ${esc(quand)}` : ""}</span></li>`;
}

function groupe(titre, ts, rendu, vide) {
  return `<section class="agrp"><h3>${esc(titre)} <span class="nb">${ts.length}</span></h3>
    ${ts.length ? `<div class="aliste">${ts.map(rendu).join("")}</div>` : `<p class="muted small">${esc(vide)}</p>`}</section>`;
}

function groupes(a) {
  const g = a.groupes, v = a.atelier.vivant;
  return groupe("En cours", g.en_cours, t => enCours(t, v), "Rien ne tourne en ce moment.") +
    groupe("En attente", g.en_attente, t => enAttente(t, v), "Aucune tâche n'attend.") +
    (g.echec.length ? groupe("En échec", g.echec, enEchec, "") : "") +
    `<section class="agrp"><h3>Terminées récemment</h3>${g.terminees.length
      ? `<ul class="afinies">${g.terminees.slice(0, 10).map(terminee).join("")}</ul>`
      : `<p class="muted small">Les tâches finies apparaîtront ici.</p>`}</section>`;
}

function jauge(nom, p) {
  const v = Math.round(p || 0);
  return `<div class="mj"><div class="tt"><span>${nom}</span><b>${v} %</b></div>
    <div class="jauge${v >= 90 ? " haute" : ""}" role="progressbar" aria-label="${nom}" aria-valuemin="0" aria-valuemax="100"
      aria-valuenow="${v}"><i style="width:${Math.max(2, Math.min(100, v))}%"></i></div></div>`;
}

function ligne(nom, valeur, aide = "", ton = "") {
  return `<div class="ml ${ton}"><span>${nom}</span><b>${esc(valeur)}</b>${aide ? `<small>${esc(aide)}</small>` : ""}</div>`;
}

function machine(a) {
  const m = a.machine, d = m.disque;
  const aideDisque = d.niveau === "rouge" ? "Presque plein : les rendus sont bloqués. Fais de la place."
    : d.niveau === "orange" ? "Moins de 30 Go : fais de la place bientôt." : "";
  const veille = m.eveille ? ["Oui", "Tant qu'une tâche tourne, l'ordinateur ne se met pas en veille. Garde le capot ouvert : fermé, " +
      "il s'endort quand même (le rendu reprend au réveil)."]
    : a.atelier.vivant ? ["Non", "Rien ne tourne : il peut se mettre en veille."]
    : ["Non", "Le moteur de travail est arrêté."];
  return `<h3>La machine</h3>${jauge("Processeur", m.processeur)}${jauge("Mémoire", m.memoire)}
    ${ligne("Disque libre", d.libre, aideDisque, d.niveau === "ok" ? "" : d.niveau)}
    ${ligne("Encodage vidéo", m.encodeur || "logiciel")}
    ${ligne("IA", m.ia ? "Disponible" : "Indisponible",
      m.ia ? "" : "Les propositions de l'IA ne se lancent pas. Tu peux choisir au transcript.", m.ia ? "" : "orange")}
    ${ligne("Ordinateur maintenu éveillé", veille[0], veille[1])}`;
}

function changer(racine, zone, html) {
  if (cles[zone] === html) return;
  cles[zone] = html;
  racine.querySelector(`[data-z="${zone}"]`).innerHTML = html;
}

function trouver(id) {
  const g = store.etat.activite?.groupes || {};
  return [...(g.en_cours || []), ...(g.en_attente || []), ...(g.echec || [])].find(t => t.id === id);
}

function confirmerAnnulation(projet, id) {
  const t = trouver(id);
  const echec = t && t.statut === "echec", attente = t && t.statut === "en_attente";
  const texte = echec ? "Elle disparaît de la liste. Tu pourras relancer cette étape depuis le podcast."
    : attente ? "Elle ne démarrera pas. Tu pourras la relancer plus tard depuis le podcast."
    : "Ce qui a déjà été fait est perdu pour cette tâche. Tu pourras la relancer plus tard depuis le podcast.";
  const m = modale(`<h2>Annuler « ${esc(t ? t.titre : "cette tâche")} » ?</h2>
    ${t ? `<p class="muted small">Podcast : ${esc(t.podcast || t.projet)}</p>` : ""}<p class="muted">${esc(texte)}</p>
    <div class="foot">${bouton({label: echec ? "Garder" : "Continuer la tâche", action: "non", style: "ghost"})}
      ${bouton({label: "Oui, annuler", action: "oui", style: "danger"})}</div>`);
  lier(m.el, {
    non: () => m.fermer(),
    oui: async b => {
      b.disabled = true;
      const r = await api.tache(projet, id, "annuler");
      m.fermer();
      if (r.erreur) toast(r.erreur, "no");
      else { toast(echec ? "C'est retiré de la liste." : "Annulation demandée.", "ok"); store.rafraichir(); }
    },
  });
}

async function reessayer(b) {
  b.disabled = true;
  const r = await api.tache(b.dataset.projet, b.dataset.id, "reessayer");
  if (r.erreur) { b.disabled = false; toast(r.erreur, "no"); }
  else { toast("C'est relancé.", "ok"); store.rafraichir(); }
}

export function rendreActivite(page, a) {
  let racine = page.querySelector("[data-activite]");
  if (!racine) {
    page.innerHTML = `<div data-activite class="fade"><div data-z="tete"></div>
      <div class="activite"><div data-z="groupes"></div><aside class="cote machine" data-z="machine"></aside></div></div>`;
    racine = page.firstElementChild;
    for (const k of Object.keys(cles)) delete cles[k];
    lier(racine, {
      annuler: b => confirmerAnnulation(b.dataset.projet, b.dataset.id),
      reessayer,
      rapport: b => envoyerRapport(b.dataset.projet || null, b),
    });
  }
  changer(racine, "tete", tete(a));
  changer(racine, "groupes", groupes(a));
  for (const t of a.groupes.en_cours) {
    const z = racine.querySelector(`[data-b="${CSS.escape(t.id)}"]`), h = vivantEnCours(t, a.atelier.vivant);
    if (z && z._h !== h) { z._h = h; z.innerHTML = h; }
  }
  changer(racine, "machine", machine(a));
}
