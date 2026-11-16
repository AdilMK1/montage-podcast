// Écran Casting, les gestes : écouter un micro, vérifier une personne (sa caméra avec le son de SON micro), corriger
// (choisir la bonne caméra), glisser une pastille micro sur une carte, la placer au clavier, l'animation de validation.
import {api, media} from "../../api.js";
import {esc, lier, modale, toast} from "../../ui.js";
import {jouer} from "../../sons.js";
import {personneDe} from "./casting_vues.js";

const calme = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---- écoute d'un micro (8 s préparées par la pré-analyse)
let audio = null;
export function arreterEcoute(L, el) {
  if (audio) { audio.onended = audio.onerror = null; audio.pause(); audio = null; }
  const avant = L.joue;
  L.joue = null;
  if (avant && el) majEcoute(el, avant, false);
}

function majEcoute(el, micro, on) {
  for (const b of el.querySelectorAll(`.mpast[data-micro="${CSS.escape(micro)}"]`)) {
    b.classList.toggle("joue", on);
    const x = b.querySelector(".mplay");
    if (x && x.tagName === "BUTTON") { x.classList.toggle("on", on); x.textContent = on ? "■" : "▶"; x.title = on ? "Arrêter" : "Écouter 8 secondes"; }
  }
}

export function ecouter(L, el, c, micro) {
  const deja = L.joue === micro;
  arreterEcoute(L, el);
  const m = c.micros.find(x => x.id === micro);
  if (deja || !m || !m.extrait) return;
  audio = new Audio(media(L.projet, m.extrait));
  L.joue = micro;
  audio.onended = () => arreterEcoute(L, el);
  audio.onerror = () => { arreterEcoute(L, el); toast("Ce son ne se lit pas. Réessaie dans un instant.", "no"); };
  audio.play().catch(() => {});
  majEcoute(el, micro, true);
}

// ---- vérifier une personne : résout "oui", "non" ou "ferme"
export function verifier(L, c, micro, {rang = "", el = null} = {}) {
  arreterEcoute(L, el);
  const p = personneDe(c, micro);
  const cam = c.cameras.find(x => x.id === p?.camera);
  return new Promise(fin => {
    let rendu = false;
    const m = modale("", {classe: "player cverif", onFermer: () => {
      const v = m.el.querySelector("video");
      if (v) { v.pause(); v.removeAttribute("src"); v.load(); }
      if (!rendu) fin("ferme");
    }});
    const repondre = r => { rendu = true; m.fermer(); fin(r); };
    m.el.className = "cvm";
    m.el.style.cssText = p ? `--c:var(--p${(c.micros.findIndex(x => x.id === micro) % 6) + 1})` : "";
    m.el.innerHTML = `<button class="x" type="button" data-act="fermer" aria-label="Fermer">×</button>
      ${rang ? `<p class="eyebrow">Vérification ${esc(rang)}</p>` : ""}
      <h2><span class="qui-c">${esc(p ? p.nom : "")}</span> : les lèvres collent à la voix ?</h2>
      <div class="cvm-vid"><span class="spin"></span><span class="muted">Préparation de l'extrait…</span></div>
      <div class="cvm-acts"><button type="button" class="cvm-b oui" data-act="oui" disabled>✓ <span>Ça colle</span></button>
        <button type="button" class="cvm-b non" data-act="non" disabled>✗ <span>Pas lui/elle</span></button></div>
      <p class="muted small cvm-aide">Caméra ${esc(cam ? cam.nom : "")} avec le micro ${esc(c.micros.find(x => x.id === micro)?.nom || "")},
        au même instant. Clavier : O pour oui, N pour non, Échap pour fermer.</p>`;
    lier(m.el, {fermer: () => m.fermer(), oui: () => repondre("oui"), non: () => repondre("non")});
    const clavier = e => {
      if (!m.fond.isConnected) { document.removeEventListener("keydown", clavier); return; }
      const k = e.key.toLowerCase();
      if (k === "o" && !m.el.querySelector(".oui").disabled) { e.preventDefault(); repondre("oui"); }
      else if (k === "n" && !m.el.querySelector(".non").disabled) { e.preventDefault(); repondre("non"); }
    };
    document.addEventListener("keydown", clavier);
    api.verifier(L.projet, micro).then(r => {
      if (!m.fond.isConnected) return;
      const z = m.el.querySelector(".cvm-vid");
      if (r.erreur) { z.innerHTML = `<div class="errbox" style="margin:0"><b>${esc(r.erreur)}</b></div>`; return; }
      z.innerHTML = `<video src="${esc(media(L.projet, r.src))}" autoplay loop playsinline controls></video>`;
      const v = z.querySelector("video");
      v.addEventListener("error", () => toast("Cet extrait ne se lit pas. Réessaie dans un instant.", "no"));
      v.play().catch(() => {});
      for (const b of m.el.querySelectorAll(".cvm-b")) b.disabled = false;
      m.el.querySelector(".oui").focus();
    });
  });
}

// ---- corriger : choisir la caméra qui filme vraiment cette personne
export function corriger(L, c, micro, associer) {
  const p = personneDe(c, micro);
  const cams = c.cameras.filter(x => !x.large && x.id !== p?.camera);
  const m = modale("", {classe: "large"});
  m.el.innerHTML = `<h2>Sur quelle caméra est <span class="qui-c" style="--c:var(--p${(c.micros.findIndex(x => x.id === micro) % 6) + 1})">${esc(p?.nom || "")}</span> ?</h2>
    <p class="muted" style="margin:0">Choisis l'image où on la voit le mieux. Si quelqu'un y était déjà, vous échangez.</p>
    <div class="cchoix">${cams.map(x => {
      const qui = x.personne ? personneDe(c, x.personne) : null;
      return `<button type="button" class="cch" data-act="choisir" data-cam="${esc(x.id)}">
        ${x.image ? `<img src="${esc(media(L.projet, x.image))}" alt="">` : `<span class="cini">🎥</span>`}
        <span><b>${esc(x.nom)}</b>${qui ? `<small>aujourd'hui : ${esc(qui.nom)}</small>` : "<small>libre</small>"}</span></button>`;
    }).join("") || `<p class="muted">Aucune autre caméra serrée. Change le plan large si besoin.</p>`}</div>
    <div class="foot"><button type="button" class="btn ghost" data-act="aucune">Aucune caméra ne la filme</button>
      <button type="button" class="btn ghost" data-act="non">Annuler</button></div>`;
  return new Promise(fin => {
    lier(m.el, {
      non: () => { m.fermer(); fin(null); },
      aucune: async () => { m.fermer(); fin(await associer(micro, null)); },
      choisir: async b => { m.fermer(); fin(await associer(micro, b.dataset.cam)); },
    });
    m.el.querySelector(".cch")?.focus();
  });
}

// ---- glisser une pastille micro sur une carte (souris) ; la placer au clavier (Entrée, flèches, Entrée)
export function brancherGlisser(racine, {deposer, prendre}) {
  if (racine._glisser) return;
  racine._glisser = true;
  let micro = null;
  const fin = () => {
    micro = null;
    racine.classList.remove("glisse");
    racine.querySelectorAll(".ccard.survol,.ccard.refus").forEach(x => x.classList.remove("survol", "refus"));
  };
  racine.addEventListener("dragstart", e => {
    const p = e.target.closest && e.target.closest(".mpast[data-micro]");
    if (!p) return;
    micro = p.dataset.micro;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", micro);
    racine.classList.add("glisse");
    jouer("clic");
  });
  racine.addEventListener("dragover", e => {
    const k = micro && e.target.closest(".ccard");
    racine.querySelectorAll(".ccard.survol,.ccard.refus").forEach(x => { if (x !== k) x.classList.remove("survol", "refus"); });
    if (!k) return;
    if (k.classList.contains("large")) { k.classList.add("refus"); e.dataTransfer.dropEffect = "none"; return; }
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    k.classList.add("survol");
  });
  racine.addEventListener("drop", e => {
    const k = micro && e.target.closest(".ccard");
    const m = micro;
    fin();
    if (!k || k.classList.contains("large")) return;
    e.preventDefault();
    deposer(m, k.dataset.cam);
  });
  racine.addEventListener("dragend", fin);
  // au clavier : la poignée d'une pastille ; flèches pour choisir la carte, Entrée pour poser, Échap pour annuler
  racine.addEventListener("keydown", e => prendre(e));
}

// ---- validation : grand ✓ qui se dessine, son de validation, puis la suite
export function celebrer(texte) {
  jouer("valide");
  const o = document.createElement("div");
  o.className = "cvalide";
  o.setAttribute("role", "status");
  o.innerHTML = `<div><svg viewBox="0 0 120 120" aria-hidden="true"><circle cx="60" cy="60" r="52"/>
    <path d="M38 62 54 77 84 45"/></svg><b>Casting validé</b><span>${esc(texte)}</span></div>`;
  document.body.append(o);
  return new Promise(r => setTimeout(() => { o.classList.add("fin"); setTimeout(() => { o.remove(); r(); }, 250); },
    calme() ? 700 : 1400));
}
