#!/bin/bash
# Tabellone Carburanti — aggiornamento automatico dal Mac.
#
# Installa un "LaunchAgent" (il pianificatore di macOS, launchd) che più volte
# al giorno legge le medie ufficiali MIMIT dalla connessione di casa e, se ci
# sono dati nuovi, li pubblica nel repository GitHub. GitHub poi rimette online
# il sito da solo.
#
# Uso, dalla cartella del progetto:   bash strumenti/macos/installa.sh
# Per sostituire il token salvato:    bash strumenti/macos/installa.sh --nuovo-token
#
# Compatibile con il bash 3.2 di macOS. Autore: Biagio Raucci — Licenza MIT.
set -euo pipefail

ETICHETTA="it.raucci.tabellone-carburanti"
REPO="braucci/tabellone-carburanti"
SERVIZIO="tabellone-carburanti"                       # voce nel Portachiavi
DEST="$HOME/Library/Application Support/TabelloneCarburanti"
PLIST="$HOME/Library/LaunchAgents/$ETICHETTA.plist"
LOG="$HOME/Library/Logs/TabelloneCarburanti.log"
SORGENTE="$(cd "$(dirname "$0")/../.." && pwd)"

if [ "$(uname)" != "Darwin" ]; then
  echo "Questo script è per macOS."; exit 1
fi
if [ ! -f "$SORGENTE/motore/aggiorna.py" ]; then
  echo "Non trovo motore/aggiorna.py: esegui lo script dalla cartella del progetto."; exit 1
fi

echo "== 1/6  Python (serve la versione 3.10 o successiva)"
PY=""
candidati="/Library/Frameworks/Python.framework/Versions/Current/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3"
if command -v python3 >/dev/null 2>&1; then candidati="$candidati $(command -v python3)"; fi
if xcode-select -p >/dev/null 2>&1; then candidati="$candidati /usr/bin/python3"; fi
for c in $candidati; do
  if [ -x "$c" ] && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "   Nessun Python adatto. Installalo da https://www.python.org/downloads/macos/ e riprova."; exit 1
fi
echo "   $PY ($("$PY" --version 2>&1))"

echo "== 2/6  Connessioni HTTPS da Python"
if ! "$PY" -c "import urllib.request; urllib.request.urlopen('https://api.github.com', timeout=20)" 2>/dev/null; then
  echo "   Python non riesce ad aprire https://api.github.com."
  echo "   Se sei connesso a Internet, mancano i certificati del Python di python.org:"
  for f in /Applications/Python\ 3.*/Install\ Certificates.command; do
    [ -e "$f" ] && echo "     open \"$f\""
  done
  echo "   Esegui il comando qui sopra, poi rilancia questo script."; exit 1
fi
echo "   ok"

echo "== 3/6  Copia del motore in ~/Library/Application Support"
# Fuori da Scrivania, Documenti e Download: macOS non lascia leggere quelle
# cartelle ai programmi che partono da soli in background.
mkdir -p "$DEST"
rm -rf "${DEST:?}/motore"
cp -R "$SORGENTE/motore" "$DEST/"
find "$DEST/motore" -name __pycache__ -type d -prune -exec rm -rf {} +
( cd "$DEST" && "$PY" -m unittest discover -s motore -t . -p 'test_*.py' >/dev/null 2>&1 ) \
  || { echo "   Le prove del motore non passano con $PY: installazione interrotta."; exit 1; }
echo "   $DEST/motore  (prove superate)"

echo "== 4/6  Token GitHub nel Portachiavi"
if [ "${1:-}" = "--nuovo-token" ]; then
  security delete-generic-password -s "$SERVIZIO" >/dev/null 2>&1 || true
fi
if security find-generic-password -s "$SERVIZIO" >/dev/null 2>&1; then
  echo "   già presente (per sostituirlo: bash strumenti/macos/installa.sh --nuovo-token)"
else
  echo "   Incolla il token (inizia con github_pat_). Non verrà mostrato mentre lo incolli;"
  echo "   premi Invio, poi incollalo una seconda volta per conferma e premi di nuovo Invio."
  security add-generic-password -a "$USER" -s "$SERVIZIO" -l "Tabellone Carburanti (GitHub)" -w
fi
( cd "$DEST" && "$PY" -m motore.aggiorna --github "$REPO" --verifica-github ) \
  || { echo "   Il token non funziona: controlla repository e permessi, poi usa --nuovo-token."; exit 1; }

echo "== 5/6  Pianificazione con launchd"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
ETICHETTA="$ETICHETTA" PY="$PY" DEST="$DEST" REPO="$REPO" LOG="$LOG" PLIST="$PLIST" "$PY" - <<'FINE'
import os, plistlib
orari = [(9, 40), (11, 40), (15, 10), (19, 10)]      # ora locale; più passaggi coprono i ritardi
dati = {
    "Label": os.environ["ETICHETTA"],
    "ProgramArguments": [os.environ["PY"], "-u", "-m", "motore.aggiorna", "--github", os.environ["REPO"]],
    "WorkingDirectory": os.environ["DEST"],
    "StartCalendarInterval": [{"Hour": h, "Minute": m} for h, m in orari],
    "RunAtLoad": True,                                # anche all'accensione e all'accesso
    "StandardOutPath": os.environ["LOG"],
    "StandardErrorPath": os.environ["LOG"],
}
with open(os.environ["PLIST"], "wb") as f:
    plistlib.dump(dati, f)
FINE
plutil -lint "$PLIST" >/dev/null
UTENTE_ID="$(id -u)"
launchctl bootout "gui/$UTENTE_ID/$ETICHETTA" 2>/dev/null || true
echo "=== installazione del $(date '+%d/%m/%Y %H:%M') ===" >> "$LOG"
PRIMA=$(wc -l < "$LOG")                               # righe del registro prima dell'avvio
launchctl bootstrap "gui/$UTENTE_ID" "$PLIST"
echo "   attivo: ogni giorno alle 9:40, 11:40, 15:10, 19:10 e a ogni accesso"

echo "== 6/6  Prima esecuzione"
for i in $(seq 1 45); do
  if tail -n +$((PRIMA + 1)) "$LOG" | grep -q -E "Nessun dato nuovo|Pubblicato su GitHub|Nessuna fonte|GitHub:|Invariante"; then break; fi
  sleep 2
done
tail -n +$((PRIMA + 1)) "$LOG"
echo
echo "Fatto. Registro completo: $LOG  (si apre anche con l'app Console)"
echo "Esecuzione manuale:      launchctl kickstart -k gui/$UTENTE_ID/$ETICHETTA"
