// Accueil : « Mes podcasts », carte « Nouveau podcast », une carte par projet (vignette, titre, personnes,
// étape en cours, barre réduite de la tâche qui tourne). Les barres se mettent à jour sans recharger les vignettes.
import {media} from "../api.js";
import {barre, dateFr, esc, lier, propre} from "../ui.js";
import {ouvrirNouveau} from "./nouveau.js";
import {ETAPES, statutEtape} from "./projet.js";

let structure = "";

function pilule(p) {
  if (p.erreur) return `<span class="pill"><i style="background:var(--no)"></i>À vérifier</span>`;
  if (p.tache) return `<span class="pill cours"><i></i>${esc(p.tache.titre)}</span>`;
  if (p.etape === "Terminé") return `<span class="pill ok"><i></i>Terminé</span>`;
  return `<span class="pill"><i></i>Étape : ${esc(p.etape)}</span>`;
}

function carte(p) {
  const href = "/?" + new URLSearchParams({projet: p.id}).toString();
  const image = p.vignette ? `<img src="${esc(media(p.id, p.vignette))}" alt="" loading="lazy">`
    : `<div class="ini">${esc((p.titre || "?").charAt(0).toUpperCase())}</div>`;
  // « Sarah · Léo » : chaque personne avec sa couleur, comme dans le podcast
  // avant la validation du casting, les personnes n'ont que des noms techniques (Mic_1…) : on ne les montre pas
  const casting = p.statuts && ["a_faire", "a_valider"].includes(p.statuts.casting);
  const gens = casting ? `<span class="qui-c" style="--c:var(--accent)">Casting à valider</span>`
    : p.personnes ? p.personnes.split(" · ").map((n, i) =>
      `<span class="qui-c" style="--c:var(--p${(i % 6) + 1})">${esc(n)}</span>`).join("") : "Personnes à indiquer";
  return `<a class="pcard" href="${esc(href)}" data-nav>
    <div class="im">${image}${pilule(p)}</div>
    <div class="bd"><b>${esc(p.titre)}</b>
      <div class="who">${gens}</div>
      ${p.statuts && Object.keys(p.statuts).length ? `<div class="minifil" aria-hidden="true" style="grid-template-columns:repeat(${ETAPES.length},minmax(0,1fr))">${ETAPES.map(([k, nom]) =>
        `<i class="${statutEtape(p.statuts, k)}" title="${esc(nom)}"></i>`).join("")}</div>` : ""}
      ${p.cree ? `<div class="date">Créé le ${esc(dateFr(p.cree))}</div>` : ""}
      ${p.erreur ? `<div class="err">${esc(propre(p.erreur))}</div>` : ""}
      <div class="zone-barre" data-projet="${esc(p.id)}">${barre(p.tache, {mini: true})}</div>
    </div></a>`;
}

function vide() {
  return `<div class="empty fade"><div class="ill">🎙</div><h1>Monte ton premier podcast</h1>
    <p class="muted" style="margin:0 0 22px">Donne le dossier des rushes. L'app synchronise, transcrit, propose les shorts
    et monte l'épisode. Toi, tu valides.</p>
    <button class="btn p lg" type="button" data-act="nouveau">＋ Nouveau podcast</button>
    <p class="muted" style="margin:16px 0 0"><a class="lnk" href="/?packs" data-nav>Régler l'habillage de tes shorts
      (packs de shorts)</a></p></div>`;
}

// mise à jour : installée au lancement (Lancer), ou disponible si l'app est restée ouverte
function noteMaj(m) {
  if (!m) return "";
  if (m.disponible) return `<p class="maj fade">Nouvelle version <b>${esc(m.distante)}</b> disponible (tu as la ${esc(m.locale)}).
    Pour l'installer : ferme la fenêtre « Lancer » puis relance l'app. Les rendus en cours ne sont pas touchés.</p>`;
  if (m.faite) return `<p class="maj ok fade">App mise à jour : version <b>${esc(m.locale)}</b>.</p>`;
  return "";
}

export function rendreAccueil(page, vue) {
  const projets = vue.projets || [];
  document.title = vue.nom || document.title;
  // ce qui change la mise en page ; la barre (pourcentage, signe de vie) se met à jour à part
  const s = JSON.stringify([vue.maj, projets.map(p => ({...p, tache: p.tache ? p.tache.id + p.tache.titre : null}))]);
  if (s === structure && page.querySelector("[data-accueil]")) {
    for (const p of projets) {
      const z = page.querySelector(`.zone-barre[data-projet="${CSS.escape(p.id)}"]`);
      if (z) z.innerHTML = barre(p.tache, {mini: true});
    }
    return;
  }
  structure = s;
  page.innerHTML = `<div data-accueil>${noteMaj(vue.maj)}${projets.length ? `
    <div class="hero fade"><h1>Mes podcasts</h1><span class="nb">${projets.length}</span><span class="sp"></span>
      <a class="btn" href="/?packs" data-nav><span aria-hidden="true">🎨</span> Packs de shorts</a>
      <button class="btn p" type="button" data-act="nouveau">＋ Nouveau podcast</button></div>
    <div class="grid fade">
      <button class="newcard" type="button" data-act="nouveau"><span>＋</span><b>Nouveau podcast</b>
        <small>à partir du dossier des rushes</small></button>
      ${projets.map(carte).join("")}</div>` : vide()}</div>`;
  lier(page, {nouveau: () => ouvrirNouveau()});
}
