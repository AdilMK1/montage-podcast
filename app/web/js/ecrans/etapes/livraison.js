// Étape Livraison : ce qui part (shorts gardés et épisode exporté, à jour), « Préparer la livraison » avec sa
// barre, les rappels avant de publier (repris de PROCESS.md) et les livraisons déjà faites, dossier par dossier.
import {api} from "../../api.js";
import {barre, bouton, dateFr, esc, lier, modale, toast} from "../../ui.js";
import {reessayer} from "../projet.js";
import {agir} from "./shorts_commun.js";

const S = {el: null, v: null, ctx: null, zones: {}};
const tache = v => v.taches.find(t => t.type === "livraison" && (t.actif || t.statut === "en_attente"));
const echec = v => !tache(v) && v.taches.find(t => t.type === "livraison" && t.statut === "echec");
const FINDER = /Win/i.test(navigator.platform || "") ? "l'Explorateur" : "le Finder";

const RAPPELS = [
  ["accords", "Les invités sont d'accord pour la publication (et pour leur logo s'il apparaît)."],
  ["photos", "Chaque photo qui n'est pas à vous est en licence libre, avec son crédit dans la description."],
  ["traduction", "Les sous-titres traduits ont été relus par quelqu'un qui parle la langue."],
  ["date", "À l'écran, les dates sont écrites en toutes lettres : jamais « demain » ni « la semaine prochaine »."],
];

// cases cochées : un confort de cette personne sur cet ordinateur, rien de bloquant
const cleCases = () => `livraison:${S.v.id}`;
function cases() { try { return JSON.parse(localStorage.getItem(cleCases()) || "{}"); } catch (e) { return {}; } }
function cocher(k, oui) {
  const c = cases();
  c[k] = oui;
  try { localStorage.setItem(cleCases(), JSON.stringify(c)); } catch (e) { /* stockage indisponible : tant pis */ }
}

// « 2026-11-14 16h30 » -> « 14 novembre 2026 à 16h30 »
function quand(nom) {
  const h = /(\d{1,2}h\d{2})/.exec(nom || "");
  const d = dateFr(nom);
  return d ? `${d}${h ? ` à ${h[1]}` : ""}` : nom;
}

function raisonLivrer(v) {
  if (tache(v)) return "La livraison est en cours.";
  const liv = v.livrables;
  if (!liv.shorts.length && !liv.episode) return "Garde au moins un short ou exporte l'épisode.";
  return "Tout est déjà livré. Garde un autre short ou refais l'export pour livrer à nouveau.";
}

function episodeLigne(v) {
  if (v.livrables.episode) return `<li class="ok">✓ L'épisode complet</li>`;
  const st = v.statuts.export;
  const pourquoi = st === "a_refaire" ? "L'épisode a changé depuis son export : exporte-le à nouveau."
    : "L'épisode n'est pas encore exporté.";
  return `<li class="non">${esc(pourquoi)} ${bouton({label: "Aller à l'épisode", action: "aller", style: "ghost sm", attrs: 'data-etape="episode"'})}</li>`;
}

function recap(v) {
  const gardes = v.shorts.filter(x => v.livrables.shorts.includes(x.id));
  const t = tache(v), e = echec(v), fait = v.statuts.livraison === "valide";
  const shorts = gardes.length
    ? gardes.map(x => `<li class="ok">✓ Short ${x.num ? `${esc(x.num)} · ` : ""}${esc(x.titre)}</li>`).join("")
    : `<li class="non">Aucun short gardé. ${bouton({label: "Aller aux shorts", action: "aller", style: "ghost sm", attrs: 'data-etape="shorts"'})}</li>`;
  const pied = e ? "" : t ? `<div style="margin-top:14px">${barre(t)}</div>`
    : `<div class="epf">${fait ? `<span class="okchip">✓ Livré</span>` : ""}
        ${bouton({label: "Préparer la livraison", action: "livrer", style: "p", actif: !!v.peut.livrer, raison: raisonLivrer(v)})}
        ${fait && v.livraisons.length ? bouton({label: `Ouvrir la dernière livraison dans ${FINDER}`, action: "finder",
          style: "ghost", attrs: `data-nom="${esc(v.livraisons[0].nom)}"`}) : ""}</div>`;
  const erreur = e ? `<div class="errbox"><div style="flex:1"><b>La livraison n'a pas marché.</b>
      <span class="muted"> Relance-la. Si ça recommence, envoie un rapport depuis le panneau de droite.</span></div>
      <div class="acts">${bouton({label: "Réessayer", action: "reessayer", attrs: `data-id="${esc(e.id)}"`})}</div></div>` : "";
  return `<ul class="livl">${shorts}${episodeLigne(v)}</ul>
    <p class="muted small">Les shorts sont mis au bon volume pour les réseaux. Tout est rangé dans un dossier daté.</p>
    ${erreur}${pied}`;
}

function rappels() {
  const c = cases();
  return `<p class="muted small" style="margin-bottom:10px">Avant de publier, vérifie ces points. Personne d'autre ne le fera.</p>
    ${RAPPELS.map(([k, t]) => `<label class="tog"><input type="checkbox" data-rappel="${k}" ${c[k] ? "checked" : ""}> ${esc(t)}</label>`).join("")}`;
}

function passees(v) {
  if (!v.livraisons.length) return `<p class="muted small">Aucune livraison pour l'instant. Elles apparaîtront ici, chacune dans son dossier daté.</p>`;
  return v.livraisons.map(l => `<div class="livp"><div style="flex:1"><b>${esc(quand(l.nom))}</b>
      <span class="muted small">${l.fichiers.length} fichier${l.fichiers.length > 1 ? "s" : ""}</span>
      <ul>${l.fichiers.map(f => `<li>${esc(f)}</li>`).join("")}</ul></div>
      ${bouton({label: "Ouvrir", action: "finder", style: "ghost sm", attrs: `data-nom="${esc(l.nom)}"`})}</div>`).join("") +
    `<div class="acts">${bouton({label: "Ouvrir le dossier des livraisons", action: "finder", style: "ghost"})}</div>`;
}

function zone(n, html) {
  const z = S.el.querySelector(`[data-z="${n}"]`);
  if (z && S.zones[n] !== html) { S.zones[n] = html; z.innerHTML = html; }
}

async function livrer(b) {
  const v = S.v;
  const go = async () => agir(v.id, {type: "livrer"}, "C'est parti : la livraison se prépare.");
  if (!v.livraisons.length) { b.disabled = true; if (!(await go())) b.disabled = false; return; }
  const m = modale(`<h2>Préparer une nouvelle livraison ?</h2>
    <p class="muted">Elle sera rangée dans un nouveau dossier daté. Les livraisons d'avant restent où elles sont.</p>
    <div class="foot">${bouton({label: "Pas maintenant", action: "non", style: "ghost"})}
      ${bouton({label: "Préparer la livraison", action: "oui", style: "p"})}</div>`);
  lier(m.el, {non: () => m.fermer(), oui: async x => { x.disabled = true; await go(); m.fermer(); }});
}

export function rendre(el, v, ctx) {
  S.v = v;
  S.ctx = ctx;
  if (S.el !== el) {
    S.el = el;
    S.zones = {};
    el.addEventListener("change", e => { const k = e.target.dataset && e.target.dataset.rappel; if (k) cocher(k, e.target.checked); });
  }
  if (!el.querySelector("[data-m=livraison]")) {
    el.innerHTML = `<div data-m="livraison" class="fade"><div class="stage"><h2>Livraison</h2>
        <p class="intro">Tout ce qui est prêt à publier, rangé au même endroit.</p></div>
      <div class="card epc"><div class="eph"><b>Ce qui part</b></div><div data-z="recap"></div></div>
      <div class="card epc"><div class="eph"><b>Avant de publier</b></div><div data-z="rappels"></div></div>
      <div class="card epc"><div class="eph"><b>Livraisons faites</b></div><div data-z="passees"></div></div></div>`;
    S.zones = {};
  }
  lier(el, {
    aller: b => ctx.aller(b.dataset.etape),
    livrer,
    reessayer: b => { b.disabled = true; reessayer(v.id, b.dataset.id); },
    // un dossier daté précis (data-nom), sinon le dossier de toutes les livraisons
    finder: async b => {
      const r = b.dataset.nom ? await api.ouvrir(v.id, "livraison", b.dataset.nom) : await api.ouvrir(v.id, "export");
      if (r.erreur) toast(r.erreur, "no"); else toast(`Le dossier s'ouvre dans ${FINDER}.`, "ok");
    },
  });
  zone("recap", recap(v));
  zone("rappels", rappels());
  zone("passees", passees(v));
}
