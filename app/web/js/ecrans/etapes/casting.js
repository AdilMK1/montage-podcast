// Étape Casting : pendant la pré-analyse, sa progression en clair ; ensuite qui est qui, déjà placé. On vérifie
// chaque personne (sa caméra avec le son de SON micro), on corrige en glissant une pastille micro, on renomme, on
// choisit qui anime, puis on valide : l'analyse démarre avec les bons noms. Données : GET /api/casting (contrat dans
// docs/superpowers/plans/2026-11-15-casting-serveur.md) ; gestes : actions du casting par /api/action.
import {api, media} from "../../api.js";
import {store} from "../../store.js";
import {erreur, lier, toast} from "../../ui.js";
import {jouer} from "../../sons.js";
import {reessayer} from "../projet.js";
import * as V from "./casting_vues.js";
import * as G from "./casting_gestes.js";

let L = null;  // état local de l'écran, pour un podcast
const calme = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// qui a été vérifié (micro:caméra) : la vue du serveur ne le garde pas, on le garde sur cet ordinateur
const cleVerif = p => `craie:casting:verifies:${p}`;
function lireVerifies(p) {
  try { return new Set(JSON.parse(localStorage.getItem(cleVerif(p)) || "[]")); } catch (e) { return new Set(); }
}
function marquer(micro, cam) {
  L.verifies.add(`${micro}:${cam}`);
  try { localStorage.setItem(cleVerif(L.projet), JSON.stringify([...L.verifies])); } catch (e) { /* gardé pour cette page */ }
}

function neuf(projet) {
  return {projet, c: null, enVol: false, encore: false, verifies: lireVerifies(projet), joue: null, pris: null, cible: null,
          echange: null, videos: new Map(), boucles: new Map(), demandes: new Set(), cles: {}, racine: null, ctx: null};
}

function charger() {
  if (L.enVol) { L.encore = true; return; }
  L.enVol = true;
  const projet = L.projet;
  api.casting(projet).then(c => {
    if (!L || L.projet !== projet) return;
    L.enVol = false;
    if (!c.erreur) { L.c = c; dessiner(); }
    if (L.encore) { L.encore = false; charger(); }
  });
}

export function rendre(el, v, ctx) {
  if (!L || L.projet !== v.id) { if (L) G.arreterEcoute(L, null); L = neuf(v.id); }
  L.ctx = ctx;
  if (!L.racine || !el.contains(L.racine)) {
    el.innerHTML = `<div class="cst fade" data-cst><div data-cz="tete"><p class="muted" style="display:flex;gap:10px;align-items:center">
      <span class="spin"></span>Chargement du casting…</p></div><div data-cz="msgs"></div>
      <div class="ccams" data-cz="cams"></div><div data-cz="mics"></div><p class="sr" aria-live="polite" data-annonce></p></div>`;
    L.racine = el.querySelector("[data-cst]");
    L.cles = {};
    brancher(L.racine);
  }
  dessiner();
  charger();
}

function zone(nom, html, cle = html) {
  if (L.cles[nom] === cle) return false;
  L.cles[nom] = cle;
  L.racine.querySelector(`[data-cz="${nom}"]`).innerHTML = html;
  return true;
}

function dessiner() {
  const c = L && L.c;
  if (!c || !L.racine) return;
  // un prénom en cours de saisie n'est jamais écrasé : on redessine quand le champ est quitté
  const a = document.activeElement;
  if (a && a.classList.contains("cnom") && L.racine.contains(a)) { L.retard = true; return; }
  L.retard = false;
  if (c.manuel) { zone("tete", `<p class="muted">Ce podcast a été créé avec les noms choisis à la main : pas de casting à faire.</p>`); return; }
  if (!c.pret) {
    const echec = c.tache && c.tache.statut === "echec" ? c.tache : null;
    const html = V.preAnalyse(c, echec);
    if (zone("tete", html, html + (echec ? echec.id + echec.erreur : "")) && echec) {
      L.racine.querySelector("[data-err]").append(erreur({erreur: echec.erreur || "La pré-analyse n'a pas abouti.",
        actions: echec.actions || ["reessayer", "rapport"]}, {projet: L.projet, gestes: {reessayer: () => reessayer(L.projet, echec.id)}}));
    }
    ["msgs", "cams", "mics"].forEach(z => zone(z, ""));
    return;
  }
  zone("tete", V.entete(c, L));
  zone("msgs", V.messages(c));
  if (zone("cams", c.cameras.map((cam, i) => V.carte(c, L, cam, i)).join(""))) videos();
  zone("mics", V.micros(c, L));
}

// ---- boucles vidéo : un élément <video> par caméra, gardé d'un dessin à l'autre (pas de rechargement)
function videos() {
  for (const z of L.racine.querySelectorAll(".cvid[data-vid]")) {
    const cam = L.c.cameras.find(x => x.id === z.dataset.vid);
    if (!cam) continue;
    let v = L.videos.get(cam.id);
    if (!v) {
      const src = cam.boucle || L.boucles.get(cam.id);
      if (!src) { demanderBoucle(cam.id); continue; }
      v = document.createElement("video");
      Object.assign(v, {muted: true, loop: true, playsInline: true, preload: "auto"});
      v.setAttribute("aria-hidden", "true");
      v.addEventListener("loadeddata", () => v.classList.add("on"));
      v.addEventListener("error", () => v.remove());
      v.src = media(L.projet, src);
      L.videos.set(cam.id, v);
    }
    z.insertBefore(v, z.children[1] || null);
    if (!calme()) v.play().catch(() => {});
  }
}

function demanderBoucle(cam) {
  if (L.demandes.has(cam)) return;
  L.demandes.add(cam);
  const projet = L.projet;
  api.boucle(projet, cam).then(r => {
    if (!L || L.projet !== projet || r.erreur) return;
    L.boucles.set(cam, r.src);
    videos();
  });
}

// ---- actions
async function agir(action, ok = "") {
  const r = await api.action(L.projet, action);
  if (!L) return null;
  if (r.erreur) { toast(r.erreur, "no"); return null; }
  if (r.casting) L.c = r.casting;
  dessiner();
  if (r.projet) store.mettre(r.projet);
  if (ok) toast(ok, "ok");
  return r;
}

const nomDe = micro => V.personneDe(L.c, micro)?.nom || "";
const camDe = id => L.c.cameras.find(x => x.id === id);

function associer(micro, cam) {
  const avant = cam ? camDe(cam)?.personne : null;
  const ok = !cam ? `${nomDe(micro)} n'a plus de caméra.`
    : avant && avant !== micro ? `${nomDe(micro)} et ${nomDe(avant)} ont échangé leur caméra.`
    : `${nomDe(micro)} est sur ${camDe(cam)?.nom || "cette caméra"}.`;
  return agir({type: "associer_micro", micro, camera: cam}, ok);
}

async function verifierUn(micro, rang = "") {
  const r = await G.verifier(L, L.c, micro, {rang, el: L.racine});
  if (!L) return r;
  const p = V.personneDe(L.c, micro);
  if (r === "oui" && p && p.camera) { marquer(micro, p.camera); jouer("valide"); L.cles.tete = L.cles.cams = null; dessiner(); }
  if (r === "non") {
    const fait = await G.corriger(L, L.c, micro, associer);
    if (fait && V.personneDe(L.c, micro)?.camera) return verifierUn(micro, rang);
  }
  return r;
}

async function toutVerifier() {
  const ps = L.c.personnes.filter(p => p.camera);
  for (let i = 0; i < ps.length; i++) {
    if (await verifierUn(ps[i].micro, `${i + 1} / ${ps.length}`) !== "oui") return;
  }
  toast("Tout le monde est vérifié. Tu peux valider le casting.", "ok");
}

async function valider() {
  G.arreterEcoute(L, L.racine);
  const r = await api.action(L.projet, {type: "valider_casting"});
  if (!L) return;
  if (r.erreur) { toast(r.erreur, "no"); return; }
  if (r.casting) L.c = r.casting;
  await G.celebrer("L'analyse démarre, avec les bons prénoms.");
  if (r.projet) store.mettre(r.projet);
  L.ctx.aller("analyse");
}

function role(micro, r) {
  const p = V.personneDe(L.c, micro);
  if (!p || p.role === r) return;
  if (r === "animateur") return agir({type: "definir_animateur", micro}, `${p.nom} anime.`);
  const autres = L.c.personnes.filter(x => x.micro !== micro);
  if (autres.length === 1) return agir({type: "definir_animateur", micro: autres[0].micro}, `${autres[0].nom} anime.`);
  toast("Choisis qui anime : clique « Anime » sur sa carte.");
}

function echanger(micro) {
  const autres = L.c.personnes.filter(x => x.micro !== micro && x.camera);
  if (autres.length === 1) {
    return agir({type: "echanger_personnes", a: micro, b: autres[0].micro, quoi: "cameras"},
      `${nomDe(micro)} et ${autres[0].nom} ont échangé leur caméra.`);
  }
  L.echange = micro;
  annoncer(`Choisis avec qui ${nomDe(micro)} échange sa caméra. Échap pour annuler.`);
  L.cles.cams = null;
  dessiner();
}

// ---- placer un micro au clavier (ou clic sur la poignée, puis clic sur une carte)
function annoncer(t) { const a = L.racine.querySelector("[data-annonce]"); if (a) a.textContent = t; }

function surligner() {
  const cards = [...L.racine.querySelectorAll(".ccard")];
  cards.forEach((k, i) => {
    k.classList.toggle("survol", i === L.cible && !k.classList.contains("large"));
    k.classList.toggle("refus", i === L.cible && k.classList.contains("large"));
  });
  L.racine.querySelectorAll(".mpast").forEach(p => p.classList.toggle("pris", !!L.pris && p.dataset.micro === L.pris.micro));
  L.racine.classList.toggle("glisse", !!L.pris);
}

function prendre(micro) {
  if (L.pris && L.pris.micro === micro) { lacher(); return; }
  const cards = [...L.racine.querySelectorAll(".ccard")];
  const ici = cards.findIndex(k => k.dataset.cam === V.personneDe(L.c, micro)?.camera);
  L.pris = {micro};
  L.cible = ici >= 0 ? ici : Math.max(0, cards.findIndex(k => !k.classList.contains("large")));
  surligner();
  cards[L.cible]?.focus();
  annoncer(`Micro de ${nomDe(micro) || "cette personne"} pris. Flèches pour choisir la caméra, Entrée pour le poser, Échap pour annuler.`);
}

function lacher() {
  L.pris = null; L.cible = null;
  surligner();
}

function poser(micro, cam) {
  lacher();
  const k = camDe(cam);
  if (!k) return;
  if (k.large) { toast("Le plan large filme tout le monde : il n'a pas de micro.", "warn"); return; }
  if (V.personneDe(L.c, micro)?.camera === cam) return;
  return associer(micro, cam);
}

function clavier(e) {
  if (e.key === "Escape" && (L.pris || L.echange)) {
    e.preventDefault();
    if (L.echange) { L.echange = null; L.cles.cams = null; dessiner(); }
    lacher();
    annoncer("Annulé.");
    return;
  }
  if (e.key === "Enter" && e.target.classList.contains("cnom")) { e.preventDefault(); e.target.blur(); return; }
  if (!L.pris) return;
  const cards = [...L.racine.querySelectorAll(".ccard")];
  const d = {ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1}[e.key];
  if (d) {
    e.preventDefault();
    L.cible = ((L.cible ?? 0) + d + cards.length) % cards.length;
    surligner();
    cards[L.cible].focus();
    const k = camDe(cards[L.cible].dataset.cam);
    annoncer(k.large ? `${k.nom} : plan large, pas de micro.` : `${k.nom}${k.personne ? `, aujourd'hui ${nomDe(k.personne)}` : ", libre"}.`);
  } else if (e.key === "Enter" && e.target.classList.contains("ccard")) {
    e.preventDefault();
    poser(L.pris.micro, cards[L.cible].dataset.cam);
  }
}

function renommer(input) {
  const p = V.personneDe(L.c, input.dataset.micro);
  const nom = input.value.trim().replace(/\s+/g, " ");
  if (!p || nom === p.nom) { if (L.retard) dessiner(); return; }
  if (!nom) { input.value = p.nom; toast("Donne un prénom : il sert aux sous-titres et au montage.", "warn"); return; }
  agir({type: "renommer_personne", micro: p.micro, nom}, `C'est noté : ${nom}.`);
}

function brancher(r) {
  lier(r, {
    ecouter: b => G.ecouter(L, L.racine, L.c, b.dataset.micro),
    verifier: b => { verifierUn(b.dataset.micro); },
    tout: () => { toutVerifier(); },
    valider,
    role: b => role(b.dataset.micro, b.dataset.role),
    echanger: b => echanger(b.dataset.micro),
    echanger_ici: b => {
      const a = L.echange;
      L.echange = null;
      return agir({type: "echanger_personnes", a, b: b.dataset.micro, quoi: "cameras"},
        `${nomDe(a)} et ${nomDe(b.dataset.micro)} ont échangé leur caméra.`);
    },
    large: b => agir({type: "designer_large", camera: b.dataset.cam}, `${camDe(b.dataset.cam)?.nom} est le plan large.`),
    prendre: b => prendre(b.dataset.micro),
  });
  // micro pris : un clic sur une carte le pose
  r.addEventListener("click", e => {
    const k = L.pris && e.target.closest(".ccard");
    if (k && !e.target.closest("button,input")) poser(L.pris.micro, k.dataset.cam);
  });
  r.addEventListener("change", e => { if (e.target.classList.contains("cnom")) renommer(e.target); });
  r.addEventListener("focusout", e => {
    if (e.target.classList.contains("cnom")) setTimeout(() => { if (L && L.retard) dessiner(); }, 0);
  });
  G.brancherGlisser(r, {deposer: (m, cam) => poser(m, cam), prendre: clavier});
}
