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
# 3) baja los próximos partidos con momios: Europa (fixtures.csv) y Liga MX
#    (new_league_fixtures.csv → fixtures_new.csv),
# 4) baja resultados rápidos de TheSportsDB para lo sellado (results_live.csv),
# 5) respalda el libro sellado (copia diaria, se guardan 30).
#
# La llave de TheSportsDB vive en ~/.config/liga/thesportsdb.env (chmod 600), fuera
# del workspace: Claudio nunca la ve. Sin ese archivo se usa la llave pública.
set -euo pipefail
WS="${WS:-$HOME/.openclaw/workspace}"
LIGA="$WS/liga"
REPO="$HOME/predicciones"
git -C "$REPO" fetch -q origin main
git -C "$REPO" reset -q --hard origin/main
rsync -a --delete --exclude .git --exclude outputs "$REPO/" "$WS/predicciones/"
curl -fsSL --max-time 60 -o "$LIGA/fixtures.csv.tmp" https://www.football-data.co.uk/fixtures.csv
mv "$LIGA/fixtures.csv.tmp" "$LIGA/fixtures.csv"
curl -fsSL --max-time 60 -o "$LIGA/fixtures_new.csv.tmp" https://www.football-data.co.uk/new_league_fixtures.csv
mv "$LIGA/fixtures_new.csv.tmp" "$LIGA/fixtures_new.csv"
if [ -f "$HOME/.config/liga/thesportsdb.env" ]; then
  set -a; . "$HOME/.config/liga/thesportsdb.env"; set +a
fi
LIGA_HOME="$LIGA" PYTHONPATH="$REPO/src" PYTHONDONTWRITEBYTECODE=1 \
  python3 -m wc_predictor.ingest.liga_results || echo "aviso: resultados rápidos fallaron (sigue con Football-Data)"
chmod a+r "$LIGA/results_live.csv" 2>/dev/null || true
mkdir -p "$HOME/liga-backups"
[ -f "$LIGA/ledger.jsonl" ] && cp "$LIGA/ledger.jsonl" "$HOME/liga-backups/ledger-$(date +%F).jsonl"
ls -1t "$HOME"/liga-backups/ledger-*.jsonl 2>/dev/null | tail -n +31 | xargs -r rm -f
echo "liga-sync ok $(date -Is)"
