#!/bin/bash
# Tabellone Carburanti — rimuove l'aggiornamento automatico dal Mac.
# Il registro (~/Library/Logs/TabelloneCarburanti.log) resta, per consultazione.
# Autore: Biagio Raucci — Licenza MIT.
set -euo pipefail

ETICHETTA="it.raucci.tabellone-carburanti"
SERVIZIO="tabellone-carburanti"
DEST="$HOME/Library/Application Support/TabelloneCarburanti"
PLIST="$HOME/Library/LaunchAgents/$ETICHETTA.plist"

launchctl bootout "gui/$(id -u)/$ETICHETTA" 2>/dev/null && echo "Pianificazione fermata." || echo "Pianificazione non attiva."
rm -f "$PLIST"
rm -rf "${DEST:?}"
echo "Motore rimosso da $DEST."

printf "Cancellare anche il token dal Portachiavi? [s/N] "
read -r risposta
case "$risposta" in
  s|S|si|sì|SI) security delete-generic-password -s "$SERVIZIO" >/dev/null 2>&1 \
                   && echo "Token cancellato. Revocalo anche su GitHub, se non serve più." \
                   || echo "Nessun token da cancellare." ;;
  *) echo "Token lasciato nel Portachiavi." ;;
esac
