#!/usr/bin/env bash
# Utilero (sin LLM). Corre en el HOST, con red, como el usuario claw.
#
# Seguridad: este script vive FUERA del workspace de Claudio (~/bin) y el clon
# con .git también (~/predicciones). Claudio solo recibe una COPIA sin .git. Así
# nada que el agente escriba en su workspace llega a ejecutarse en el host
# (ni un script editado, ni un hook o config de git).
#
# 1) deja ~/predicciones idéntico a origin/main,
# 2) copia el código y los datos al workspace (borra cualquier edición local),
# 3) baja los próximos partidos con momios (fixtures.csv),
# 4) respalda el libro sellado (copia diaria, se guardan 30).
set -euo pipefail
WS="${WS:-$HOME/.openclaw/workspace}"
LIGA="$WS/liga"
REPO="$HOME/predicciones"
git -C "$REPO" fetch -q origin main
git -C "$REPO" reset -q --hard origin/main
rsync -a --delete --exclude .git --exclude outputs "$REPO/" "$WS/predicciones/"
curl -fsSL --max-time 60 -o "$LIGA/fixtures.csv.tmp" https://www.football-data.co.uk/fixtures.csv
mv "$LIGA/fixtures.csv.tmp" "$LIGA/fixtures.csv"
mkdir -p "$HOME/liga-backups"
[ -f "$LIGA/ledger.jsonl" ] && cp "$LIGA/ledger.jsonl" "$HOME/liga-backups/ledger-$(date +%F).jsonl"
ls -1t "$HOME"/liga-backups/ledger-*.jsonl 2>/dev/null | tail -n +31 | xargs -r rm -f
echo "liga-sync ok $(date -Is)"
