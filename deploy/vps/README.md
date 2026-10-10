# Liga en el VPS: Claudio (OpenClaw) como operador

Quién hace qué:
- **Utilero** (`liga-sync`, timer del host, sin LLM): repo + fixtures (Europa y Liga MX) + respaldo, cada 3 h.
- **Claudio** (OpenClaw, en su sandbox sin red): corre los bots, sella, califica y te platica.
- **Código** (bots, Notario, Árbitro): decide los números. Claudio solo los opera y explica.

Seguridad: el clon con `.git` y el script del Utilero viven FUERA del workspace;
Claudio recibe una copia sin `.git` que se pisa cada 3 h. Nada que él escriba llega
a ejecutarse en el host. El libro se respalda a diario en `~/liga-backups/`.

## 1. Clonar el repo (llave de deploy de SOLO lectura)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/predicciones_deploy -N "" -C "vps-predicciones-ro"
cat ~/.ssh/predicciones_deploy.pub
```
GitHub → repo Predicciones → Settings → Deploy keys → Add deploy key: pega la llave,
**sin** marcar "Allow write access".

```bash
cat >> ~/.ssh/config <<'CFG'
Host github-predicciones
  HostName github.com
  User git
  IdentityFile ~/.ssh/predicciones_deploy
  IdentitiesOnly yes
CFG
git clone git@github-predicciones:samuelramram/Predicciones.git ~/predicciones
sudo apt install -y rsync
```

## 2. Preparar la liga

```bash
~/predicciones/deploy/vps/setup.sh
```

## 3. Darle a Claudio su carpeta y la imagen con Python científico

```bash
openclaw config patch --stdin <<'JSON'
{ "agents": { "defaults": { "sandbox": {
    "workspaceAccess": "rw",
    "docker": {
      "image": "openclaw-sandbox-liga:bookworm-slim",
      "env": { "LIGA_HOME": "/workspace/liga",
               "PYTHONPATH": "/workspace/predicciones/src",
               "PYTHONDONTWRITEBYTECODE": "1" } } } } } }
JSON
systemctl --user stop openclaw-gateway
openclaw sandbox recreate --all --force
systemctl --user start openclaw-gateway
openclaw sandbox explain
openclaw skills list | grep liga
```
`explain` debe decir workspace `rw` y la imagen `openclaw-sandbox-liga`; red sigue en none.

## 4. Que Claudio chambee solo (automatizaciones)

Verifica la sintaxis con `openclaw automations add --help` (cambia entre versiones).

```bash
# Jueves 20:00: arma y sella la jornada, te manda tu boleto
openclaw automations add --name "liga-jornada" --agent claudio --cron "0 20 * * 4" --tz America/Mexico_City \
  --session isolated --message "Usa la skill liga-jornada y mándame mi boleto." \
  --announce --channel telegram --to "1305320146"
# Viernes 09:00: qué te falta por sellar
openclaw automations add --name "liga-recordatorio" --agent claudio --cron "0 9 * * 5" --tz America/Mexico_City \
  --session isolated --message "Con la skill liga-sellar revisa (--status) qué me falta de la jornada y recuérdame el deadline." \
  --announce --channel telegram --to "1305320146"
# Viernes 08:00: el Reportero investiga y sella su boleto (antes del primer partido)
openclaw automations add --name "liga-reportero" --agent claudio --cron "0 8 * * 5" --tz America/Mexico_City \
  --session isolated --message "Usa la skill liga-reportero para las jornadas de esta semana y avísame qué moviste." \
  --announce --channel telegram --to "1305320146"
# Jueves 09:00: tabla rápida antes de la jornada nueva
openclaw automations add --name "liga-tabla" --agent claudio --cron "0 9 * * 4" --tz America/Mexico_City \
  --session isolated --message "Usa la skill liga-tabla y cuéntame cómo voy." \
  --announce --channel telegram --to "1305320146"
# Diario 10:00: tablero (puntos + feria ficticia y por qué). Solo manda algo cuando una
# jornada ya tiene TODOS sus resultados, y los lunes aunque falte alguno.
openclaw automations add --name "liga-tablero" --agent claudio --cron "0 10 * * *" --tz America/Mexico_City \
  --session isolated --message "Usa la skill liga-tablero (con --auto). Si no hay novedad no me mandes nada." \
  --announce --channel telegram --to "1305320146"
```

## Búsqueda web para el Reportero

El Reportero necesita buscar noticias. La búsqueda de OpenClaw corre del lado del gateway;
el sandbox sigue sin red. Actívala con un proveedor sin llave (DuckDuckGo):

```bash
openclaw configure --section web     # elige DuckDuckGo (o Brave si tienes BRAVE_API_KEY)
openclaw gateway restart
```

Riesgo conocido: lo que el Reportero lee en internet puede traer texto que intente darle
órdenes. Está contenido así: sus notas pasan por código que recorta todo a 0.75–1.25, no
tiene red en el sandbox, no puede tocar el host, y el libro sellado detecta cualquier edición.

## Cómo le hablas a Claudio (Telegram o dashboard)

- "Pásame la jornada" · "¿qué pusieron los bots en el Liverpool–City y por qué?"
- "mis picks: 2-1, 0-2, -, 1-3" · "¿qué me falta?"
- "¿cómo voy?" · "¿ya le gano al borrego o es suerte?" · "pásame el tablero" · "¿cuánta feria traen?"
- "corre al reportero" · "¿qué noticias movió el reportero?"

En el dashboard (túnel SSH) ves cada comando que corrió y lo que leyó.

## Actualizar (cuando cambie algo de `deploy/vps/`)

```bash
git -C ~/predicciones pull && ~/predicciones/deploy/vps/setup.sh
```
`setup.sh` es idempotente: reinstala el Utilero y las skills, no toca el libro.
Las skills se copian de nuevo; `AGENTS.md` no se duplica.
