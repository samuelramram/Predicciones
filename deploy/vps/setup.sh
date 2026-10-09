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
# Semilla / avance rápido del libro desde el repo: se copia solo si en el VPS no hay
# libro o si el del VPS es un PREFIJO exacto del del repo (el repo solo agregó sellos).
# Si divergen, el del VPS manda y no se toca.
if [ -f "$REPO/data/liga/ledger.jsonl" ]; then
  python3 - "$REPO/data/liga/ledger.jsonl" "$LIGA/ledger.jsonl" <<'PY'
import sys, pathlib, shutil
repo, vps = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
r = repo.read_text().splitlines()
v = vps.read_text().splitlines() if vps.exists() else []
if v == r[:len(v)] and len(r) > len(v):
    shutil.copyfile(repo, vps); print(f"   libro: +{len(r) - len(v)} sellos desde el repo")
elif v != r[:len(v)]:
    print("   libro: el del VPS ya tiene sellos propios; se queda como está")
PY
  cp -n "$REPO"/data/europa/rounds/*.json "$REPO"/data/europa/rounds/*.md "$LIGA/rounds/" 2>/dev/null || true
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
# Reemplaza la sección de la liga (entre marcadores, o la versión vieja sin marcadores
# que iba al final del archivo) por la actual; el resto de AGENTS.md no se toca.
python3 - "$WS/AGENTS.md" "$HERE/AGENTS-liga.md" <<'PY'
import sys, re, pathlib
dst, src = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]).read_text()
cur = dst.read_text()
if "<!-- liga:start -->" in cur:
    cur = re.sub(r"\n?<!-- liga:start -->.*?<!-- liga:end -->\n?", "", cur, flags=re.S)
elif "## Liga de bots" in cur:
    cur = cur[:cur.index("## Liga de bots")].rstrip("\n") + "\n"
dst.write_text(cur.rstrip("\n") + "\n" + src)
PY

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
