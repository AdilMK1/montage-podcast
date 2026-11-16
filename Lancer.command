#!/bin/zsh
# Montage Podcast : lance l'app et l'ouvre dans le navigateur.
cd "$(dirname "$0")"
setopt NO_BG_NICE  # sinon zsh lance l’app en priorité basse (cœurs lents du Mac : rendus 3 à 5 fois plus lents)
[ -x .venv/bin/python ] || { echo "Lance d'abord « Installer.command »."; read; exit 1; }
PORT=8765
URL="http://localhost:$PORT"
repond() { curl -sf -m 1 "$URL/api/accueil" >/dev/null; }

if repond; then  # l'app tourne déjà (autre fenêtre) : on l'ouvre, c'est tout
  open "$URL"
  exit 0
fi

.venv/bin/python -m app.api.serveur $PORT &  # le serveur démarre et surveille l'atelier (qui fait les rendus)
SRV=$!
for i in {1..50}; do
  repond && break
  kill -0 $SRV 2>/dev/null || break
  sleep 0.3
done
if ! repond; then
  echo "L'app n'a pas pu démarrer (le port $PORT est peut-être pris par un autre programme)."
  echo "Ferme les autres fenêtres « Lancer » puis réessaie. Si ça recommence, envoie le fichier .atelier/serveur.log."
  kill $SRV 2>/dev/null
  read -k1 "?Appuie sur une touche pour fermer."
  exit 1
fi
open "$URL"
echo ""
echo "L'app est ouverte dans ton navigateur : $URL"
echo ""
echo "Garde cette fenêtre ouverte pendant que tu travailles."
echo "La fermer arrête l'interface, mais PAS les rendus en cours : ils continuent en fond,"
echo "et tu les retrouves à la prochaine ouverture (double-clic sur « Lancer »)."
wait $SRV
