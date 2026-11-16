// Sondage du serveur toutes les 1,5 s : vue de l'écran courant (accueil ou projet) ET activité.
// Ne redessine la page que si les données ont changé et si l'utilisateur n'est pas en train de saisir
// (champ texte focalisé, fenêtre ouverte, curseur glissé). Prévient quand une tâche se termine ou échoue.
import {api} from "./api.js";
import {route} from "./routeur.js";
import {toast} from "./ui.js";
import {jouer} from "./sons.js";

const PERIODE = 1500;
const etat = {route: route(), vue: null, erreurVue: null, activite: null, horsLigne: false};
let rendrePage = () => {}, rendreCoquille = () => {};
let cle = "", enRetard = false, gele = 0, minuterie = null, numero = 0;
let suivies = null;  // id -> titre des tâches actives au sondage précédent (null : premier sondage)

const SAISIE = "input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=button]),textarea,select," +
               "[contenteditable=true]";

function occupe() {
  if (gele > 0) return true;
  if (document.querySelector(".modal.on")) return true;
  const a = document.activeElement;
  return !!(a && a !== document.body && a.matches(SAISIE) && document.getElementById("page").contains(a));
}

function dessiner(forcer = false) {
  const c = JSON.stringify([etat.route, etat.vue, etat.erreurVue]);
  if (c === cle && !forcer) return;
  if (occupe() && !forcer) { enRetard = true; return; }
  cle = c;
  enRetard = false;
  rendrePage(etat);
}

function notifier(texte, ton) {
  toast(texte, ton, {son: false});
  jouer(ton === "ok" ? "fin" : "erreur");
  try {
    if ("Notification" in window && Notification.permission === "granted" && document.hidden) {
      new Notification(document.title, {body: texte});
    }
  } catch (e) { /* notifications du système indisponibles : le toast suffit */ }
}

// tâches passées de « active » à « terminée » ou « échec » entre deux sondages
function suivreFins(a) {
  const g = a.groupes || {};
  const actives = new Map([...(g.en_cours || []), ...(g.en_attente || [])].map(t => [t.id, t.titre]));
  if (suivies) {
    for (const [id, titre] of suivies) {
      if (actives.has(id)) continue;
      if ((g.echec || []).some(t => t.id === id)) notifier(`${titre} : ça n'a pas marché. Ouvre l'activité pour réessayer.`, "no");
      else if ((g.terminees || []).some(t => t.id === id && t.statut === "terminee")) notifier(`${titre} : c'est fini.`, "ok");
    }
  }
  suivies = actives;
}

async function sonder() {
  const n = ++numero, r = etat.route;
  const VUES = {projet: x => api.projet(x.projet), accueil: () => api.accueil(), packs: () => api.packs(),
                pack: x => api.pack(x.pack)};
  const pVue = VUES[r.ecran] ? VUES[r.ecran](r) : null;
  const [vue, act] = await Promise.all([pVue, api.activite()]);
  if (n !== numero) return;  // l'écran a changé pendant l'appel : on ignore cette réponse
  etat.horsLigne = !!(act.hors_ligne || (vue && vue.hors_ligne));
  if (!act.erreur) {
    etat.activite = act;
    suivreFins(act);
  }
  if (!etat.horsLigne) {
    if (r.ecran === "activite") { etat.vue = act.erreur ? null : act; etat.erreurVue = act.erreur ? act : null; }
    else if (vue.erreur) { etat.erreurVue = vue; }
    else { etat.vue = vue; etat.erreurVue = null; }
  }
  rendreCoquille(etat);
  dessiner();
}

// un seul sondage à la fois : un appel pendant un sondage en cours en relance un juste après
let enVol = false, encore = false;
async function boucle() {
  clearTimeout(minuterie);
  if (enVol) { encore = true; return; }
  enVol = true;
  try { await sonder(); } catch (e) { /* une erreur d'affichage ne doit pas arrêter le sondage */ console.warn(e); }
  enVol = false;
  if (encore) { encore = false; boucle(); return; }
  minuterie = setTimeout(boucle, PERIODE);
}

export const store = {
  get etat() { return etat; },

  demarrer({page, coquille}) {
    rendrePage = page;
    rendreCoquille = coquille;
    document.addEventListener("ui:libre", () => { if (enRetard) dessiner(); });
    document.addEventListener("focusout", () => setTimeout(() => { if (enRetard) dessiner(); }, 0));
    // la permission des notifications se demande au premier clic, jamais au chargement
    document.addEventListener("click", () => {
      if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    }, {once: true});
    boucle();
  },

  // l'écran change : on vide la vue et on sonde tout de suite
  changerRoute(r) {
    const memeProjet = r.ecran === "projet" && etat.route.ecran === "projet" && r.projet === etat.route.projet;
    etat.route = r;
    if (!memeProjet) { etat.vue = null; etat.erreurVue = null; }
    numero++;
    dessiner(true);
    boucle();
  },

  rafraichir() { boucle(); },

  // une action a renvoyé la vue à jour : on l'affiche sans attendre le sondage
  mettre(vue) {
    etat.vue = vue;
    etat.erreurVue = null;
    dessiner();
  },

  // pendant qu'on glisse un curseur : pas de redessin
  geler() { gele++; },
  degeler() { gele = Math.max(0, gele - 1); if (enRetard) dessiner(); },
};
