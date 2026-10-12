---
name: liga-tablero
description: Arma el tablero de la liga (puntos de todos + feria ficticia de cada bot y por qué) y se lo manda a Samuel como archivo HTML por Telegram.
---

# Tablero de la liga

Úsala cuando la automatización diaria lo pida, o cuando Samuel diga "el tablero",
"¿cuánta feria traen?", "¿cómo nos fue?".

1. Corre (la automatización usa `--auto`; si Samuel lo pide a mano, quítalo):
   `cd /workspace/predicciones && LIGA_HOME=/workspace/liga PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m wc_predictor.liga.tablero --auto`
2. Si imprime `SIN NOVEDAD`, termina sin mandar nada a Samuel (responde solo `NO_REPLY`).
3. Si imprime `TABLERO: <ruta>`:
   - Si también imprime `IMAGEN: <ruta.png>`, manda ESE `.png` a Samuel como imagen por
     Telegram (herramienta `message` con el archivo, o una línea `MEDIA:<ruta.png>`).
     **Nunca adjuntes el `.html`**: OpenClaw lo rechaza ("local attachment allowlist").
     Si no salió `IMAGEN:` (falta matplotlib en el sandbox), no mandes archivo; solo el texto.
   - Junto, un mensaje corto con lo que imprimió el comando. **Sin tablas markdown ni
     bloques de código**: Telegram las rompe en el teléfono. Una línea por bot:
     - Puntos: quién va arriba y el mano a mano de Samuel con su z
       (|z| < 2 = "todavía puede ser suerte"; dilo así).
     - Feria: `bot: saldo (±última jornada, N apuestas, ROI)` y el "por qué" en una frase,
       usando el veredicto que trae el texto (CLV y suerte). No inventes razones.
     - Pendientes de resultado si los hay.
4. Si dice "Libro corrupto", NO lo arregles: avísale a Samuel tal cual.

Recuerda: la feria es ficticia (1,000 por bot, 10 por apuesta). Una jornada que "gana"
casi siempre es varianza; el veredicto serio es el CLV (si le gana a la línea de cierre).
