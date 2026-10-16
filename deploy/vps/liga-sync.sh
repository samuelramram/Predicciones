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
#    y una vez al día los partidos de copas UEFA con momios (uefa_fixtures.json)
#    y, si FD aún no publica una liga, sus partidos con momios (league_odds.json),
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
# Se reinstala solo: si main trae otra versión de este script, la copia a ~/bin y
# vuelve a arrancar con ella (una sola vez). La fuente es el clon de main, fuera del
# workspace, igual que el código Python que ya corre desde $REPO/src: Claudio no la toca.
NEW="$REPO/deploy/vps/liga-sync.sh"
SELF="$HOME/bin/liga-sync.sh"
if [ -z "${LIGA_SYNC_REEXEC:-}" ] && [ -f "$NEW" ] && ! cmp -s "$NEW" "$SELF"; then
  install -m 755 "$NEW" "$SELF"
  echo "liga-sync: script actualizado desde main; reinicio con la versión nueva"
  LIGA_SYNC_REEXEC=1 exec "$SELF" "$@"
fi
rsync -a --delete --exclude .git --exclude outputs "$REPO/" "$WS/predicciones/"
curl -fsSL --max-time 60 -o "$LIGA/fixtures.csv.tmp" https://www.football-data.co.uk/fixtures.csv
mv "$LIGA/fixtures.csv.tmp" "$LIGA/fixtures.csv"
curl -fsSL --max-time 60 -o "$LIGA/fixtures_new.csv.tmp" https://www.football-data.co.uk/new_league_fixtures.csv
mv "$LIGA/fixtures_new.csv.tmp" "$LIGA/fixtures_new.csv"
if [ -f "$HOME/.config/liga/thesportsdb.env" ]; then
  set -a; . "$HOME/.config/liga/thesportsdb.env"; set +a
fi
# Copas UEFA (Champions / Europa League / Conference) con momios de The Odds API.
# Llave en ~/.config/liga/odds.env (THE_ODDS_API_KEY=..., chmod 600). Se refresca una
# vez al día (cuida los 500 créditos/mes del plan gratis); sin llave se salta.
if [ -f "$HOME/.config/liga/odds.env" ]; then
  ( set -a; . "$HOME/.config/liga/odds.env"; set +a
    LIGA_HOME="$LIGA" PYTHONPATH="$REPO/src" PYTHONDONTWRITEBYTECODE=1 \
      python3 -m wc_predictor.ingest.uefa_odds ) || echo "aviso: copas UEFA fallaron (sigue sin ellas)"
  chmod a+r "$LIGA/uefa_fixtures.json" 2>/dev/null || true
  # Respaldo de ligas: Football-Data publica el fin de semana tarde (a veces el
  # viernes). Solo pide las ligas que FD no trae en los próximos 4 días, ≤1 vez/20 h.
  ( set -a; . "$HOME/.config/liga/odds.env"; set +a
    LIGA_HOME="$LIGA" PYTHONPATH="$REPO/src" PYTHONDONTWRITEBYTECODE=1 \
      python3 -m wc_predictor.ingest.uefa_odds --leagues ) || echo "aviso: respaldo de ligas falló (sigue con Football-Data)"
  chmod a+r "$LIGA/league_odds.json" 2>/dev/null || true
fi
LIGA_HOME="$LIGA" PYTHONPATH="$REPO/src" PYTHONDONTWRITEBYTECODE=1 \
  python3 -m wc_predictor.ingest.liga_results || echo "aviso: resultados rápidos fallaron (sigue con Football-Data)"
chmod a+r "$LIGA/results_live.csv" 2>/dev/null || true
mkdir -p "$HOME/liga-backups"
[ -f "$LIGA/ledger.jsonl" ] && cp "$LIGA/ledger.jsonl" "$HOME/liga-backups/ledger-$(date +%F).jsonl"
ls -1t "$HOME"/liga-backups/ledger-*.jsonl 2>/dev/null | tail -n +31 | xargs -r rm -f
echo "liga-sync ok $(date -Is)"
