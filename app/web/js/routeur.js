// Adresse de la page : « / » (accueil), « ?projet=ID&etape=couleur » (un podcast), « ?activite » (activité),
// « ?packs » (packs de shorts), « ?pack=ID » (un pack).
// Le bouton retour du navigateur est géré : il ramène à l'écran précédent.
const ecouteurs = [];

export function route() {
  const q = new URLSearchParams(location.search);
  if (q.has("activite")) return {ecran: "activite"};
  if (q.get("pack")) return {ecran: "pack", pack: q.get("pack")};
  if (q.has("packs")) return {ecran: "packs"};
  const projet = q.get("projet");
  if (projet) return {ecran: "projet", projet, etape: q.get("etape") || null};
  return {ecran: "accueil"};
}

export function adresse(r) {
  if (!r || r.ecran === "accueil") return "/";
  if (r.ecran === "activite") return "/?activite";
  if (r.ecran === "packs") return "/?packs";
  if (r.ecran === "pack") return "/?" + new URLSearchParams({pack: r.pack}).toString();
  const q = new URLSearchParams({projet: r.projet});
  if (r.etape) q.set("etape", r.etape);
  return "/?" + q.toString();
}

function prevenir() {
  const r = route();
  ecouteurs.forEach(f => f(r));
}

// changer d'écran ; « remplacer » ne crée pas d'entrée dans l'historique (ex. changer d'étape)
export function aller(r, {remplacer = false} = {}) {
  const url = adresse(r);
  if (url !== location.pathname + location.search) history[remplacer ? "replaceState" : "pushState"](null, "", url);
  prevenir();
}

export function surChangement(f) {
  ecouteurs.push(f);
}

window.addEventListener("popstate", prevenir);

// liens internes <a data-nav href="/?projet=X"> : navigation sans recharger la page
document.addEventListener("click", e => {
  const a = e.target.closest("a[data-nav]");
  if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
  e.preventDefault();
  const u = new URL(a.href, location.href);
  if (u.pathname + u.search !== location.pathname + location.search) history.pushState(null, "", u.pathname + u.search);
  prevenir();
});
