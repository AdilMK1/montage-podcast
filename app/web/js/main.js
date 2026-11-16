// Point d'entrée : coquille (bandeau, voyant d'activité, alerte du moteur), routeur et sondage.
import {api} from "./api.js";
import {store} from "./store.js";
import {aller, surChangement} from "./routeur.js";
import {$, esc, erreur} from "./ui.js";
import {rendreAccueil} from "./ecrans/accueil.js";
import {rendreProjet} from "./ecrans/projet.js";
import {rendreActivite} from "./ecrans/activite.js";
import {rendrePacks} from "./ecrans/packs.js";
import {rendrePack} from "./ecrans/pack.js";
import {brancherSons} from "./sons.js";

const page = $("#page");
const ECRANS = {accueil: rendreAccueil, projet: rendreProjet, activite: rendreActivite, packs: rendrePacks, pack: rendrePack};

function filAriane(etat) {
  const r = etat.route;
  let h = "";
  if (r.ecran === "projet") {
    const titre = etat.vue ? etat.vue.titre : "";
    h = `<a href="/" data-nav>Mes podcasts</a>${titre ? `<span>›</span><b>${esc(titre)}</b>` : ""}`;
  } else if (r.ecran === "activite") {
    h = `<a href="/" data-nav>Mes podcasts</a><span>›</span><b>Activité</b>`;
  } else if (r.ecran === "packs") {
    h = `<a href="/" data-nav>Mes podcasts</a><span>›</span><b>Packs de shorts</b>`;
  } else if (r.ecran === "pack") {
    const nom = etat.vue ? etat.vue.nom : "";
    h = `<a href="/" data-nav>Mes podcasts</a><span>›</span><a href="/?packs" data-nav>Packs de shorts</a>` +
        (nom ? `<span>›</span><b>${esc(nom)}</b>` : "");
  }
  $("#crumb").innerHTML = h;
}

function rendrePage(etat) {
  const r = etat.route;
  const ecran = r.ecran + ":" + (r.projet || r.pack || "");
  if (page.dataset.ecran !== ecran) {
    page.dataset.ecran = ecran;
    page.innerHTML = "";
    window.scrollTo(0, 0);
  }
  filAriane(etat);
  if (etat.erreurVue) {
    page.innerHTML = `<div class="empty fade"><div class="ill">🧭</div><h1>On ne trouve pas cette page</h1>
      <div id="err"></div><p style="margin-top:22px">${r.ecran === "pack"
        ? `<a class="btn p lg" href="/?packs" data-nav>Retour aux packs</a>`
        : `<a class="btn p lg" href="/" data-nav>Retour à mes podcasts</a>`}</p></div>`;
    const e = etat.erreurVue.code === 404 && r.ecran === "projet"
      ? {erreur: "Ce podcast est introuvable. Il a peut-être été renommé ou déplacé.", actions: []} : etat.erreurVue;
    page.querySelector("#err").append(erreur(e, {projet: r.ecran === "projet" && e === etat.erreurVue ? r.projet : null}));
    page.dataset.ecran = "";
    return;
  }
  if (!etat.vue) {
    if (!page.firstChild) page.innerHTML = `<p class="muted" style="display:flex;gap:10px;align-items:center">` +
      `<span class="spin"></span>Chargement…</p>`;
    return;
  }
  ECRANS[r.ecran](page, etat.vue, etat);
}

function rendreCoquille(etat) {
  const a = etat.activite;
  $("#hors").classList.toggle("on", etat.horsLigne);
  if (!a) return;
  const n = a.en_cours || 0;
  const v = $("#voyant");
  const g = a.groupes || {};
  const texte = !a.atelier.vivant ? "Moteur de travail arrêté"
    : n ? `${n} tâche${n > 1 ? "s" : ""} en cours`
    : (g.echec || []).length ? "Une tâche demande ton attention"
    : a.voyant === "rouge" ? "Disque presque plein"
    : a.voyant === "orange" ? "À surveiller" : "Tout est calme";
  v.className = "voyant " + (a.voyant === "vert" ? (n ? "actif" : "") : a.voyant);
  v.querySelector("span").textContent = texte;
  v.title = "Voir l'activité : ce qui tourne, ce qui attend, ce qui bloque";
  $("#alerte").classList.toggle("on", !a.atelier.vivant);
}

$("#voyant").addEventListener("click", () => aller({ecran: "activite"}));
brancherSons($("#sons"));

// le serveur relance le moteur de travail tout seul quand on l'interroge
$("#redemarrer").addEventListener("click", async e => {
  const b = e.currentTarget;
  b.disabled = true;
  b.textContent = "Redémarrage…";
  await api.activite();
  setTimeout(() => { b.disabled = false; b.textContent = "Redémarrer"; store.rafraichir(); }, 2500);
});

surChangement(r => store.changerRoute(r));
store.demarrer({page: rendrePage, coquille: rendreCoquille});
