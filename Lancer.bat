@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Montage Podcast
set PYTHONUTF8=1
if not exist .venv\Scripts\python.exe (
  echo Lance d'abord Installer.bat
  pause
  exit /b 1
)
set PORT=8765
set "URL=http://localhost:%PORT%"

rem deja ouverte (autre fenetre) : on ouvre juste le navigateur
curl -sf -m 1 "%URL%/api/accueil" >nul 2>nul
if not errorlevel 1 (
  start "" "%URL%"
  exit /b 0
)

rem nouvelle version ? installee avant d'ouvrir (jamais pendant un rendu)
.venv\Scripts\python.exe -m app.mise_a_jour

rem le navigateur s'ouvre des que l'app repond
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 80;$i++){try{Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 '%URL%/api/accueil' | Out-Null; Start-Process '%URL%'; break}catch{Start-Sleep -Milliseconds 500}}"

echo L'app s'ouvre dans ton navigateur : %URL%
echo.
echo Garde cette fenetre ouverte pendant que tu travailles.
echo La fermer arrete l'interface, mais PAS les rendus en cours : ils continuent en fond,
echo et tu les retrouves a la prochaine ouverture (double-clic sur Lancer.bat).
echo.
.venv\Scripts\python.exe -m app.api.serveur %PORT%
echo.
echo L'app s'est arretee. Si elle n'a pas demarre (port %PORT% pris par un autre programme ?),
echo ferme les autres fenetres Lancer puis reessaie. Sinon envoie le fichier .atelier\serveur.log
pause
