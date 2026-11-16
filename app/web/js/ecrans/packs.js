// Packs de shorts : la bibliothèque commune (habillage des shorts : sous-titres, couleurs, accroche, logo, musique).
// Une carte par pack avec son aperçu (rendu par le vrai moteur des shorts) et les gestes : nouveau, modifier,
// dupliquer, renommer, exporter, importer, supprimer. « Aucun pack » est livré avec l'app : il se duplique seulement.
import {api, apercuPack, exportPack} from "../api.js";
import {aller} from "../routeur.js";
import {store} from "../store.js";
import {bouton, esc, lier, modale, toast} from "../ui.js";

let structure = "";

const usage = p => !p.utilise_par.length ? "Pas encore utilisé"
  : p.utilise_par.length === 1 ? `Utilisé par « ${p.utilise_par[0]} »` : `Utilisé par ${p.utilise_par.length} podcasts`;

function pilule(p, dernier) {
  if (p.integre) return `<span class="pill neutre"><i></i>Livré avec l'app</span>`;
  if (p.id === dernier) return `<span class="pill ok"><i></i>Dernier choisi</span>`;
  return "";
}

// pack dont le fichier pack.json est abîmé ou manquant : pas d'aperçu, on peut seulement le supprimer
function carteIllisible(p) {
  return `<div class="pcard pk-carte pk-ko">
    <div class="im pk-im"><div class="pk-casse"><span aria-hidden="true">🧩</span><b>Pack illisible</b>
      <small>Ses réglages sont abîmés ou manquants. Réimporte-le depuis un export, ou supprime-le.</small></div></div>
    <div class="bd"><b>${esc(p.nom)}</b>
      <div class="pk-acts">${bouton({label: "Supprimer", action: "supprimer", style: "ghost sm", attrs: `data-id="${esc(p.id)}"`})}</div>
    </div></div>`;
}

function carte(p, dernier) {
  if (p.illisible) return carteIllisible(p);
  const id = esc(p.id), at = `data-id="${id}"`;
  return `<div class="pcard pk-carte">
    <div class="im pk-im" data-act="${p.integre ? "dupliquer" : "modifier"}" ${at}
      title="${p.integre ? "Dupliquer pour en faire un pack à toi" : "Modifier ce pack"}">
      <img src="${esc(apercuPack(p.id, null, "", p.empreinte))}" alt="Aperçu du pack ${esc(p.nom)}" loading="lazy">
      ${pilule(p, dernier)}<span class="pk-usage">${p.integre ? "Sous-titres blancs, sans logo ni musique" : esc(usage(p))}</span></div>
    <div class="bd"><b>${esc(p.nom)}</b>
      <div class="pk-acts">
        ${p.integre ? "" : bouton({label: "Modifier", action: "modifier", style: "p sm", attrs: at})}
        ${bouton({label: "Dupliquer", action: "dupliquer", style: p.integre ? "p sm" : "sm", attrs: at})}
        ${p.integre ? "" : bouton({label: "Renommer", action: "renommer", style: "ghost sm", attrs: at})}
        ${p.integre ? "" : `<a class="btn ghost sm" href="${esc(exportPack(p.id))}" download="${id}.zip"
          title="Un fichier .zip à garder ou à envoyer sur un autre ordinateur">Exporter</a>`}
        ${p.integre ? "" : bouton({label: "Supprimer", action: "supprimer", style: "ghost sm", attrs: at})}
      </div></div></div>`;
}

export function rendrePacks(page, vue) {
  document.title = "Packs de shorts";
  const s = JSON.stringify(vue);
  if (s === structure && page.querySelector("[data-packs]")) return;
  structure = s;
  page.innerHTML = `<div data-packs>
    <div class="hero fade"><h1>Packs de shorts</h1><span class="nb">${vue.packs.length}</span><span class="sp"></span>
      ${bouton({label: "Importer un pack…", action: "importer"})}
      ${bouton({label: "＋ Nouveau pack", action: "nouveau", style: "p"})}</div>
    <p class="muted fade pk-intro" style="margin-top:14px">Un pack, c'est l'habillage de tes shorts : sous-titres,
      couleurs, accroche, logo, musique. Choisis-le pour un podcast (à la création ou à l'étape Shorts), ou short par short.</p>
    <div class="grid pk-grid fade">
      <button class="newcard pk-new" type="button" data-act="nouveau"><span>＋</span><b>Nouveau pack</b>
        <small>à partir d'un pack existant</small></button>
      ${vue.packs.map(p => carte(p, vue.dernier)).join("")}</div>
    <input type="file" accept=".zip,application/zip" data-fichier hidden></div>`;
  const champ = page.querySelector("[data-fichier]");
  champ.addEventListener("change", () => importer(champ));
  const trouver = b => vue.packs.find(p => p.id === b.dataset.id);
  lier(page, {
    nouveau: () => nouveau(vue.packs, vue.dernier),
    importer: () => champ.click(),
    modifier: b => aller({ecran: "pack", pack: b.dataset.id}),
    dupliquer: b => dupliquer(trouver(b)),
    renommer: b => renommer(trouver(b)),
    supprimer: b => supprimer(trouver(b)),
  });
}

// petite fenêtre « nom du pack » (et « partir de » pour un nouveau pack) ; résout {nom, depuis} ou null
function demanderNom({titre, valeur = "", ok, packs = null, depuis = "neutre"}) {
  return new Promise(resolve => {
    let fini = false;
    const fin = r => { if (!fini) { fini = true; resolve(r); } };
    const m = modale(`<h2>${esc(titre)}</h2>
      <label class="lbl" for="pk-nom">Nom du pack</label>
      <input class="tit" id="pk-nom" maxlength="40" value="${esc(valeur)}" placeholder="Ex. : Mon émission" autocomplete="off">
      ${packs ? `<label class="lbl" for="pk-depuis">Partir de</label><select class="inp" id="pk-depuis">${packs.map(p =>
        `<option value="${esc(p.id)}"${p.id === depuis ? " selected" : ""}>${esc(p.nom)}</option>`).join("")}</select>` : ""}
      <div class="foot">${bouton({label: "Annuler", action: "non", style: "ghost"})}${bouton({label: ok, action: "oui", style: "p"})}</div>`,
      {classe: "pk-petite", onFermer: () => fin(null)});
    const champ = m.el.querySelector("#pk-nom");
    champ.focus();
    champ.select();
    const valider = () => {
      const nom = champ.value.trim();
      if (!nom) { toast("Donne un nom au pack.", "no"); champ.focus(); return; }
      const sel = m.el.querySelector("#pk-depuis");
      fin({nom, depuis: sel ? sel.value : null});
      m.fermer();
    };
    champ.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); valider(); } });
    lier(m.el, {non: () => m.fermer(), oui: valider});
  });
}

async function nouveau(tous, dernier) {
  const packs = tous.filter(p => !p.illisible);
  const depuis = dernier || (packs.some(p => p.id === "neutre") ? "neutre" : (packs[0] || {}).id);
  const r = await demanderNom({titre: "Nouveau pack", ok: "Créer et régler →", packs, depuis});
  if (!r) return;
  const c = await api.creerPack(r.nom, r.depuis);
  if (c.erreur) { toast(c.erreur, "no"); return; }
  aller({ecran: "pack", pack: c.pack});
}

async function dupliquer(p) {
  if (!p) return;
  const r = await demanderNom({titre: `Dupliquer « ${p.nom} »`, valeur: `${p.nom} (copie)`.slice(0, 40), ok: "Dupliquer et régler →"});
  if (!r) return;
  const c = await api.creerPack(r.nom, p.id);
  if (c.erreur) { toast(c.erreur, "no"); return; }
  toast("Pack dupliqué.", "ok");
  aller({ecran: "pack", pack: c.pack});
}

async function renommer(p) {
  if (!p) return;
  const r = await demanderNom({titre: "Renommer le pack", valeur: p.nom, ok: "Renommer"});
  if (!r || r.nom === p.nom) return;
  const c = await api.renommerPack(p.id, r.nom);
  if (c.erreur) { toast(c.erreur, "no"); return; }
  toast("Pack renommé.", "ok");
  store.rafraichir();
}

function supprimer(p) {
  if (!p) return;
  const m = modale(`<h2>Supprimer « ${esc(p.nom)} » ?</h2>
    <p class="muted">Le pack et ses fichiers (logo, polices) seront supprimés. Exporte-le d'abord si tu veux le garder.</p>
    <div class="foot">${bouton({label: "Garder", action: "non", style: "ghost"})}${bouton({label: "Supprimer", action: "oui", style: "danger"})}</div>`,
    {classe: "pk-petite"});
  lier(m.el, {
    non: () => m.fermer(),
    oui: async () => {
      const r = await api.supprimerPack(p.id);
      m.fermer();
      if (r.erreur) { toast(r.erreur, "no"); return; }
      toast("Pack supprimé.", "ok");
      store.rafraichir();
    },
  });
}

async function importer(champ) {
  const f = champ.files && champ.files[0];
  champ.value = "";
  if (!f) return;
  toast(`Import de « ${f.name} »…`);
  const r = await api.importerPack(f);
  if (r.erreur) { toast(r.erreur, "no"); return; }
  toast("Pack importé.", "ok");
  store.rafraichir();
}
