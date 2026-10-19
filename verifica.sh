#!/usr/bin/env bash
# Tabellone Carburanti — verifica completa in locale.
#   ./verifica.sh            prove + esecuzione sui campioni + controllo dei file
#   ./verifica.sh --servi    come sopra, poi avvia un server per il telefono
# Autore: Biagio Raucci — Licenza MIT.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1/3  Prove del motore"
python3 -m unittest discover -s motore -t . -p 'test_*.py'

echo "== 2/3  Esecuzione completa sul CSV ufficiale del 19/10/2026 (senza rete)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 -m motore.aggiorna --json "$tmp/prezzi.json" \
  --csv motore/campioni/MediaNazionaleAutostradale.csv --oggi 2026-10-19

echo "== 3/3  Validità di manifest e dati pubblicati"
python3 -m json.tool manifest.webmanifest > /dev/null
python3 -c "import json; from motore import core; core.controlla_invarianti(json.load(open('data/prezzi.json', encoding='utf-8')))"
echo "Tutto in ordine."

if [[ "${1:-}" == "--servi" ]]; then
  ip=$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1)
  echo
  echo "Apri dal telefono (stessa rete Wi-Fi):  http://${ip:-127.0.0.1}:8000"
  echo "Dal computer:                           http://localhost:8000"
  echo "Ctrl+C per fermare il server."
  python3 -m http.server 8000 --bind 0.0.0.0
fi
