// Retours sonores discrets, fabriqués en Web Audio (aucun fichier) : clic, validation, fin de tâche, erreur.
// Coupés par défaut ; l'interrupteur du bandeau les active, le choix est gardé sur cet ordinateur.
const CLE = "craie:sons";
let actifs = false, ctx = null;
try { actifs = localStorage.getItem(CLE) === "1"; } catch (e) { /* stockage indisponible : coupés */ }

// fréquence (Hz), départ (s), durée (s), volume, forme d'onde
const MOTIFS = {
  clic: [[1800, 0, 0.025, 0.04, "triangle"]],
  valide: [[660, 0, 0.09, 0.07, "sine"], [990, 0.08, 0.14, 0.07, "sine"]],
  fin: [[523, 0, 0.12, 0.07, "sine"], [659, 0.1, 0.12, 0.07, "sine"], [784, 0.2, 0.22, 0.08, "sine"]],
  erreur: [[220, 0, 0.16, 0.07, "triangle"], [175, 0.12, 0.2, 0.07, "triangle"]],
};

export const sonsActifs = () => actifs;

export function jouer(nom) {
  if (!actifs || !MOTIFS[nom]) return;
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") ctx.resume();
    const t0 = ctx.currentTime + 0.01;
    for (const [f, d, du, vol, forme] of MOTIFS[nom]) {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = forme;
      o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t0 + d);
      g.gain.exponentialRampToValueAtTime(vol, t0 + d + 0.008);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + d + du);
      o.connect(g).connect(ctx.destination);
      o.start(t0 + d);
      o.stop(t0 + d + du + 0.02);
    }
  } catch (e) { /* audio indisponible : silence */ }
}

const ICONE_ON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
  aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/></svg>`;
const ICONE_OFF = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
  aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="m22 9-6 6"/><path d="m16 9 6 6"/></svg>`;

function dessiner(b) {
  b.innerHTML = actifs ? ICONE_ON : ICONE_OFF;
  b.setAttribute("aria-pressed", String(actifs));
  const t = actifs ? "Sons de l'interface : activés (clic pour couper)" : "Sons de l'interface : coupés (clic pour activer)";
  b.title = t;
  b.setAttribute("aria-label", t);
}

// branche l'interrupteur du bandeau et le clic discret sur tous les boutons
export function brancherSons(b) {
  if (!b) return;
  dessiner(b);
  b.addEventListener("click", () => {
    actifs = !actifs;
    try { localStorage.setItem(CLE, actifs ? "1" : "0"); } catch (e) { /* pas mémorisé : tant pis */ }
    dessiner(b);
    jouer("valide");
  });
  document.addEventListener("pointerdown", e => {
    const x = e.target.closest && e.target.closest(".btn,.st,.lk,.seg button,.verdict button,.camb,.newcard");
    if (x && !x.disabled) jouer("clic");
  });
}
