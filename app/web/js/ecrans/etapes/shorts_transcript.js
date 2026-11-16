// Choisir un passage dans le transcript (port de openTr / selClick / drawSel / shortTexte v1) : clic sur la
// première phrase puis sur la dernière, résumé de la sélection, « Créer ce short » -> action ajouter_short (a, b).
// Le short créé est retenu d'office : c'est toi qui l'as choisi.
import {api} from "../../api.js";
import {store} from "../../store.js";
import {bouton, esc, lier, modale, teinte, toast} from "../../ui.js";
import {agir, duree, tc} from "./shorts_commun.js";

const cache = {projet: null, phrases: null};

function extrait(ph, lo, hi) {
  const mots = ph.slice(lo, hi + 1).map(p => p.t).join(" ").split(/\s+/);
  return mots.length <= 26 ? mots.join(" ") : `${mots.slice(0, 12).join(" ")} … ${mots.slice(-12).join(" ")}`;
}

export async function choisirAuTranscript(projet) {
  const m = modale(`<h2>Choisis un passage</h2>
    <p class="muted">Clique sur la première phrase du short, puis sur la dernière.</p>
    <input class="inp trs" type="search" placeholder="Chercher un mot dans la conversation" data-cherche>
    <div class="selp" data-liste><p class="muted small" style="display:flex;gap:8px;align-items:center;padding:10px">
      <span class="spin"></span>Chargement du transcript…</p></div>
    <div class="selbar" data-bas></div>`, {classe: "large"});
  const S = {a: null, b: null, ph: [], envoi: false};
  const liste = m.el.querySelector("[data-liste]"), bas = m.el.querySelector("[data-bas]");

  function dessinerBas() {
    const lo = S.a, hi = S.b == null ? S.a : S.b;
    let info;
    if (lo == null) info = `<span class="muted">Aucune phrase choisie.</span>`;
    else if (S.b == null) info = `<span><b>Début choisi.</b> Clique maintenant sur la dernière phrase du passage.</span>`;
    else {
      const d = S.ph[hi].b - S.ph[lo].a;
      const conseil = d > 75 ? " · un peu long pour un short" : d < 12 ? " · un peu court pour un short" : "";
      info = `<span><b>Passage de ${duree(d)}</b> à ${tc(S.ph[lo].a)}<span class="muted">${conseil}</span>
        <span class="selx">« ${esc(extrait(S.ph, lo, hi))} »</span></span>`;
    }
    const pret = S.a != null && S.b != null;
    bas.innerHTML = `<div style="flex:1">${info}</div><div class="acts" style="margin:0">
      ${bouton({label: "Fermer", action: "fermer", style: "ghost"})}
      ${lo != null ? bouton({label: "Effacer", action: "effacer"}) : ""}
      ${bouton({label: S.envoi ? "Création…" : "Créer ce short", action: "creer", style: "p", actif: pret && !S.envoi,
                raison: S.envoi ? "" : "Choisis d'abord la première puis la dernière phrase."})}</div>`;
    for (const el of liste.querySelectorAll(".ph")) {
      const i = +el.dataset.i;
      el.classList.toggle("edge", lo != null && (i === lo || i === hi));
      el.classList.toggle("in", lo != null && i > lo && i < hi);
    }
  }

  function clic(i) {
    if (S.a == null || S.b != null) { S.a = i; S.b = null; } else { S.b = i; if (S.b < S.a) [S.a, S.b] = [S.b, S.a]; }
    dessinerBas();
  }

  async function creer(b) {
    if (S.a == null || S.b == null || S.envoi) return;
    S.envoi = true;
    dessinerBas();
    const avant = new Set((store.etat.vue?.shorts || []).map(x => x.id));
    const v = await agir(projet, {type: "ajouter_short", a: S.ph[S.a].a, b: S.ph[S.b].b});
    if (!v) { S.envoi = false; dessinerBas(); return; }
    const nouveau = (v.shorts || []).find(x => !avant.has(x.id));
    if (nouveau) await agir(projet, {type: "retenir_short", id: nouveau.id, retenu: true});
    m.fermer();
    toast("Short ajouté et retenu. Son aperçu se prépare.", "ok");
  }

  lier(m.el, {fermer: () => m.fermer(), effacer: () => { S.a = S.b = null; dessinerBas(); }, creer});
  liste.addEventListener("click", e => { const p = e.target.closest(".ph"); if (p) clic(+p.dataset.i); });
  m.el.querySelector("[data-cherche]").addEventListener("input", e => {
    const q = e.target.value.trim().toLowerCase();
    let premier = null;
    for (const el of liste.querySelectorAll(".ph")) {
      const ok = q.length > 1 && el.dataset.t.includes(q);
      el.classList.toggle("trouve", ok);
      if (ok && !premier) premier = el;
    }
    if (premier) premier.scrollIntoView({block: "center"});
  });
  dessinerBas();

  if (cache.projet !== projet || !cache.phrases) {
    const r = await api.transcript(projet);
    if (r.erreur) { liste.innerHTML = `<p class="muted" style="padding:12px">${esc(r.erreur)}</p>`; return; }
    Object.assign(cache, {projet, phrases: r.phrases || []});
  }
  S.ph = cache.phrases;
  liste.innerHTML = S.ph.length ? S.ph.map((p, i) => `<div class="ph" data-i="${i}" data-t="${esc(p.t.toLowerCase())}">
      <span class="tcs">${tc(p.a)}</span><span class="qui" style="${teinte(store.etat.vue, p.qui)}">${esc(p.qui)}</span><span>${esc(p.t)}</span></div>`).join("")
    : `<p class="muted" style="padding:12px">Le transcript est vide.</p>`;
  dessinerBas();
}
