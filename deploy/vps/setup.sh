#!/usr/bin/env bash
# Preparación única de la liga en el VPS. Correr como claw, DESPUÉS de clonar el
# repo en ~/predicciones (ver README.md de esta carpeta). Es idempotente.
set -euo pipefail
REPO="$HOME/predicciones"
WS="$HOME/.openclaw/workspace"
LIGA="$WS/liga"
HERE="$REPO/deploy/vps"
[ -d "$REPO/.git" ] || { echo "Falta el clon en $REPO (paso 1 del README)"; exit 1; }
command -v rsync >/dev/null || { echo "Instala rsync: sudo apt install -y rsync"; exit 1; }

echo "== 1/6 carpetas de la liga"
mkdir -p "$LIGA/rounds" "$LIGA/tabla" "$WS/predicciones" "$HOME/bin" "$HOME/.config/systemd/user"
# Semilla: el libro y las jornadas que ya se sellaron en el repo (solo si no hay libro aún).
if [ ! -f "$LIGA/ledger.jsonl" ] && [ -f "$REPO/data/liga/ledger.jsonl" ]; then
  cp "$REPO/data/liga/ledger.jsonl" "$LIGA/ledger.jsonl"
  cp -n "$REPO"/data/europa/rounds/*.json "$REPO"/data/europa/rounds/*.md "$LIGA/rounds/" 2>/dev/null || true
  echo "   libro sembrado desde el repo"
fi

echo "== 2/6 Utilero (liga-sync) fuera del workspace + timer cada 3 h"
install -m 755 "$HERE/liga-sync.sh" "$HOME/bin/liga-sync.sh"
install -m 644 "$HERE/liga-sync.service" "$HERE/liga-sync.timer" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now liga-sync.timer
"$HOME/bin/liga-sync.sh"

echo "== 3/6 imagen del sandbox con numpy/scipy"
docker build -q -t openclaw-sandbox-liga:bookworm-slim -f "$HERE/Dockerfile.sandbox" "$HERE"

echo "== 4/6 skills e instrucciones de Claudio"
mkdir -p "$WS/skills"
cp -r "$HERE"/skills/liga-* "$WS/skills/"
touch "$WS/AGENTS.md"
grep -q "## Liga de bots" "$WS/AGENTS.md" || cat "$HERE/AGENTS-liga.md" >> "$WS/AGENTS.md"

echo "== 5/6 permisos para el usuario del sandbox"
SB_UID=$(docker run --rm openclaw-sandbox-liga:bookworm-slim id -u)
if [ "$SB_UID" != "$(id -u)" ]; then
  echo "   uid sandbox=$SB_UID ≠ claw=$(id -u): la liga queda escribible para ambos"
  chmod -R a+rwX "$LIGA"
  chmod -R a+rX "$WS/predicciones" "$WS/skills"
fi

echo "== 6/6 prueba dentro de la imagen (sin red, como Claudio)"
docker run --rm --network none -v "$WS:/workspace" -e LIGA_HOME=/workspace/liga \
  -e PYTHONPATH=/workspace/predicciones/src -e PYTHONDONTWRITEBYTECODE=1 \
  openclaw-sandbox-liga:bookworm-slim python3 -m wc_predictor.liga.notario \
  --round "$(ls -1t "$LIGA"/rounds/*.json | head -1 | xargs -n1 basename | sed 's/.json$//')" --status

echo
echo "Listo. Falta el paso de config de OpenClaw del README (workspaceAccess rw + imagen)."
