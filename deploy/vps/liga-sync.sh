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
# Bots sin LLM (opt-in: existe ~/.config/liga/autoseal). Sellar es puro código; no hace
# falta pagarle tokens a Claudio para correr dos comandos. Corre en la MISMA imagen del
# sandbox de Claudio y sin red (--network none): mismo entorno, mismos permisos sobre el
# libro. Solo re-corre cuando cambian los partidos o los momios que bajó este script (y
# como red de seguridad cada 12 h), para no reajustar 5 ligas cada hora. Los bots no
# re-sellan: lo nuevo entra como "<jornada>/2" (p.ej. calibrado cuando llega el momio).
# Tablero: una vez al día (10:00 CDMX en adelante); a Telegram solo si hay novedad y
# existe ~/.config/liga/telegram.env (TELEGRAM_BOT_TOKEN=..., TELEGRAM_CHAT_ID=...).
if [ -f "$HOME/.config/liga/autoseal" ]; then
  liga_py() {
    if python3 -c "import numpy, scipy" 2>/dev/null; then
      ( cd "$WS/predicciones" && LIGA_HOME="$LIGA" PYTHONPATH="$WS/predicciones/src" \
          PYTHONDONTWRITEBYTECODE=1 python3 "$@" )
    else
      docker run --rm --network none \
        -v "$LIGA:/workspace/liga" -v "$WS/predicciones:/workspace/predicciones:ro" \
        -w /workspace/predicciones -e LIGA_HOME=/workspace/liga \
        -e PYTHONPATH=/workspace/predicciones/src -e PYTHONDONTWRITEBYTECODE=1 \
        openclaw-sandbox-liga:bookworm-slim python3 "$@"
    fi
  }
  STAMP="$LIGA/.autoseal.sha"
  SHA=$( { cat "$LIGA"/fixtures.csv "$LIGA"/fixtures_new.csv "$LIGA"/uefa_fixtures.json \
            "$LIGA"/league_odds.json "$WS/predicciones/data/ligamx/fixtures.json" 2>/dev/null \
            || true; } | sha256sum | cut -c1-16)
  if [ "$SHA" != "$(cat "$STAMP" 2>/dev/null)" ] || [ -n "$(find "$STAMP" -mmin +720 2>/dev/null)" ]; then
    ok=1
    for job in ligamx_live europa_live; do
      # "No hay partidos próximos" no es una falla: semana sin partidos de esa liga.
      if OUT=$(liga_py -m "wc_predictor.pipeline.$job" --seal 2>&1) \
         || echo "$OUT" | grep -q "No hay partidos próximos"; then
        echo "$OUT" | grep -E "^(sellado|No hay|Football-Data)" | head -6 || true
      else
        ok=0; echo "aviso: $job no selló"; echo "$OUT" | tail -3
      fi
    done
    [ "$ok" = 1 ] && echo "$SHA" > "$STAMP"
  fi
  TODAY=$(TZ=America/Mexico_City date +%F)
  if [ "$(TZ=America/Mexico_City date +%H)" -ge 10 ] && [ "$(cat "$LIGA/.tablero.day" 2>/dev/null)" != "$TODAY" ]; then
    OUT=$(liga_py -m wc_predictor.liga.tablero --auto 2>&1) && echo "$TODAY" > "$LIGA/.tablero.day"
    echo "$OUT" | head -2
    if [ -f "$HOME/.config/liga/telegram.env" ] && echo "$OUT" | grep -q "^TABLERO:"; then
      ( set -a; . "$HOME/.config/liga/telegram.env"; set +a
        TG="https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN"
        IMG=$(echo "$OUT" | sed -n 's/^IMAGEN: //p' | sed 's#^/workspace/liga#'"$LIGA"'#')
        [ -n "$IMG" ] && [ -f "$IMG" ] && curl -fsS -m 60 -o /dev/null "$TG/sendPhoto" \
          -F chat_id="$TELEGRAM_CHAT_ID" -F photo=@"$IMG"
        echo "$OUT" | grep -v '^\(TABLERO\|IMAGEN\):' | head -c 4000 \
          | curl -fsS -m 60 -o /dev/null "$TG/sendMessage" \
              --data-urlencode chat_id="$TELEGRAM_CHAT_ID" --data-urlencode text@- \
      ) || echo "aviso: Telegram falló (el tablero quedó en $LIGA/tablero/)"
    fi
  fi
fi
mkdir -p "$HOME/liga-backups"
[ -f "$LIGA/ledger.jsonl" ] && cp "$LIGA/ledger.jsonl" "$HOME/liga-backups/ledger-$(date +%F).jsonl"
ls -1t "$HOME"/liga-backups/ledger-*.jsonl 2>/dev/null | tail -n +31 | xargs -r rm -f
echo "liga-sync ok $(date -Is)"
