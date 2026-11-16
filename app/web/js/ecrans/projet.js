// Écran d'un podcast : en-tête, fil d'étapes ([Casting →] Analyse → Couleur → Son → Shorts → Épisode → Livraison), l'étape
// ouverte au centre et, à droite, les tâches du podcast avec leur barre et les échecs avec leurs boutons.
// Les zones se mettent à jour séparément : une barre qui avance ne redessine ni les images ni les curseurs.
import {api} from "../api.js";
import {store} from "../store.js";
import {aller} from "../routeur.js";
import {barre, bouton, erreur, esc, lier, modale, pastille, teinte, toast} from "../ui.js";
import * as casting from "./etapes/casting.js";
import * as analyse from "./etapes/analyse.js";
import * as couleur from "./etapes/couleur.js";
import * as son from "./etapes/son.js";
import * as shorts from "./etapes/shorts.js";
import * as episode from "./etapes/episode.js";
import * as livraison from "./etapes/livraison.js";

export const ETAPES = [["casting", "Casting"], ["analyse", "Analyse"], ["couleur", "Couleur"], ["son", "Son"], ["shorts", "Shorts"],
                       ["episode", "Épisode"], ["livraison", "Livraison"]];
const MODULES = {casting, analyse, couleur, son, shorts, episode, livraison};
// étape de chaque type de tâche (pour la pastille « En cours » du fil)
const ETAPE_TACHE = {pre_analyse: "casting", analyse: "analyse", son: "son", proxys: "analyse", ia_shorts: "shorts", apercus: "shorts",
                     shorts: "shorts", ia_passages: "episode", montage: "episode", export: "episode",
                     livraison: "livraison"};
const GRAVITE = {valide: 0, a_faire: 1, a_valider: 2, a_refaire: 3};

let ouvert = {};      // projet -> étape choisie par l'utilisateur
const cles = {};      // zone -> dernier contenu dessiné

// statut d'une étape du fil ; Épisode = le pire statut entre passages, montage, aperçu et export
export function statutEtape(st, k) {
  if (k !== "episode") return st[k] || "a_faire";
  return ["passages", "montage", "apercu", "export"].map(x => st[x] || "a_faire")
    .reduce((a, b) => (GRAVITE[b] > GRAVITE[a] ? b : a), "valide");
}

// un podcast créé avec les noms choisis à la main n'a pas d'étape Casting
const etapesDe = v => ETAPES.filter(([k]) => k !== "casting" || (v.casting && !v.casting.manuel));
const castingAValider = v => v.casting && !v.casting.manuel && v.statuts.casting !== "valide";

function etapeParDefaut(v) {
  const es = etapesDe(v);
  const i = es.findIndex(([k]) => statutEtape(v.statuts, k) !== "valide");
  return es[i < 0 ? es.length - 1 : i][0];
}

function changer(zone, el, html) {
  if (cles[zone] === html) return;
  cles[zone] = html;
  el.innerHTML = html;
}

function entete(v) {
  return `<div class="phead fade"><div style="flex:1"><h1>${esc(v.titre)}</h1>
    <div class="chips">${castingAValider(v) ? `<span class="chip"><span class="av" style="background:var(--accent)">✋</span>` +
      `Casting à valider <small>qui est qui</small></span>` : v.personnes.map(p => `<span class="chip" style="${teinte(v, p.id)}"><span class="av">${esc(p.nom.charAt(0))}</span>` +
      `${esc(p.nom)} <small>${p.role === "animateur" ? "animateur·rice" : "invité·e"}</small></span>`).join("")}</div></div></div>`;
}

function fil(v, cur) {
  const actives = new Set(v.taches.filter(t => t.actif).map(t => ETAPE_TACHE[t.type]));
  return etapesDe(v).map(([k, nom], i) => {
    const s = statutEtape(v.statuts, k);
    const enCours = actives.has(k) && s !== "valide";
    return `${i ? '<span class="sep"></span>' : ""}<button type="button" class="st ${s}${enCours ? " en_cours" : ""}` +
      `${k === cur ? " cur" : ""}" data-act="etape" data-etape="${k}" aria-current="${k === cur ? "step" : "false"}">` +
      `<span class="n">${s === "valide" ? "✓" : i + 1}</span><span><b>${nom}</b>${pastille(enCours ? "en_cours" : s)}</span></button>`;
  }).join("");
}

function cote(v) {
  const actives = v.taches.filter(t => t.actif || t.statut === "en_attente");
  const echecs = v.taches.filter(t => t.statut === "echec");
  return `<h3><span class="pastille ${actives.length ? "en_cours" : "a_faire"}" style="padding:0;border:0;background:none"><i></i></span>Ce qui tourne</h3>
    ${actives.length ? actives.map(t => `<div class="tcote">${barre(t, {mini: true})}
      ${bouton({label: "Annuler", action: "annuler", style: "ghost sm", attrs: `data-id="${esc(t.id)}"`})}</div>`).join("")
      : `<p class="muted small">Rien ne tourne pour ce podcast.</p>`}
    ${echecs.length ? `<h3 style="margin-top:22px">À reprendre</h3>
      ${echecs.map(t => `<div class="echec" data-id="${esc(t.id)}" data-titre="${esc(t.titre)}"></div>`).join("")}` : ""}`;
}

// les encadrés d'échec (avec boutons « Réessayer » et « Envoyer un rapport »)
function remplirEchecs(el, v) {
  for (const z of el.querySelectorAll(".echec")) {
    const t = v.taches.find(x => x.id === z.dataset.id);
    if (!t) continue;
    const e = {erreur: `${t.titre} : ${t.erreur || "ça n'a pas marché."}`, actions: ["reessayer", "rapport"]};
    z.append(erreur(e, {projet: v.id, gestes: {reessayer: () => reessayer(v.id, t.id)}}));
  }
}

export async function reessayer(projet, id) {
  const r = await api.tache(projet, id, "reessayer");
  if (r.erreur) toast(r.erreur, "no");
  else { toast("C'est relancé.", "ok"); store.rafraichir(); }
}

function confirmerAnnulation(projet, id) {
  const t = (store.etat.vue?.taches || []).find(x => x.id === id);
  const m = modale(`<h2>Annuler « ${esc(t ? t.titre : "cette tâche")} » ?</h2>
    <p class="muted">Ce qui a déjà été fait est perdu pour cette tâche. Tu pourras la relancer plus tard.</p>
    <div class="foot">${bouton({label: "Continuer la tâche", action: "non", style: "ghost"})}
      ${bouton({label: "Oui, annuler", action: "oui", style: "danger"})}</div>`);
  lier(m.el, {
    non: () => m.fermer(),
    oui: async b => {
      b.disabled = true;
      const r = await api.tache(projet, id, "annuler");
      m.fermer();
      if (r.erreur) toast(r.erreur, "no"); else { toast("Annulation demandée.", "ok"); store.rafraichir(); }
    },
  });
}

export function rendreProjet(page, v, etat) {
  if (ouvert.projet !== v.id) ouvert = {projet: v.id, etape: null};
  const demandee = etat.route.etape;
  const cur = etapesDe(v).some(([k]) => k === demandee) ? demandee : (ouvert.etape || etapeParDefaut(v));
  ouvert.etape = cur;

  let racine = page.querySelector(`[data-projet]`);
  if (!racine || racine.dataset.projet !== v.id) {
    page.innerHTML = `<div data-projet="${esc(v.id)}"><div data-z="tete"></div>
      <nav class="stepper" data-z="fil" aria-label="Étapes"></nav>
      <div class="projet"><section data-z="etape"></section><aside class="cote" data-z="cote"></aside></div></div>`;
    racine = page.firstElementChild;
    for (const k of Object.keys(cles)) delete cles[k];
    lier(racine, {
      etape: b => {
        ouvert.etape = b.dataset.etape;
        aller({ecran: "projet", projet: v.id, etape: b.dataset.etape}, {remplacer: true});
      },
      annuler: b => confirmerAnnulation(store.etat.vue.id, b.dataset.id),
    });
  }
  const z = n => racine.querySelector(`[data-z="${n}"]`);
  changer("tete", z("tete"), entete(v));
  changer("fil", z("fil"), fil(v, cur));
  const c = cote(v) + JSON.stringify(v.taches.filter(t => t.statut === "echec").map(t => [t.id, t.erreur]));
  if (cles.cote !== c) { cles.cote = c; z("cote").innerHTML = cote(v); remplirEchecs(z("cote"), v); }

  const el = z("etape");
  if (el.dataset.etape !== cur) {
    el.dataset.etape = cur;
    el.innerHTML = "";
    for (const k of Object.keys(cles)) if (k.startsWith("etape:")) delete cles[k];
  }
  const ctx = {
    projet: v.id,
    aller: k => { ouvert.etape = k; aller({ecran: "projet", projet: v.id, etape: k}, {remplacer: true}); window.scrollTo(0, 0); },
  };
  MODULES[cur].rendre(el, v, ctx);
}
