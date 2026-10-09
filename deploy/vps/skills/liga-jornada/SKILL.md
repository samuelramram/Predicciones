---
name: liga-jornada
description: Arma la jornada de Europa con los 3 bots, la sella y le manda a Samuel su boleto numerado.
---

# Jornada de la liga (Europa top-5)

Úsala cuando Samuel pida "la jornada", "el boleto", "qué pusieron los bots", o
cuando una automatización te lo pida.

1. Corre (tarda ~1 min, ajusta 5 ligas):
   `cd /workspace/predicciones && LIGA_HOME=/workspace/liga PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m wc_predictor.pipeline.europa_live --seal`
   - Si dice "ya selló … se queda como está", está bien: los bots no re-sellan.
   - Si falla porque no hay `fixtures.csv`, dile a Samuel que el Utilero (liga-sync) no ha corrido.
2. Lee `/workspace/liga/rounds/<jornada>.md` (la más reciente).
3. Mándale a Samuel, corto:
   - la lista numerada de SUS partidos con día y hora (centro de México),
   - lo que puso `calibrado` en cada uno (su rival principal) y dónde los 3 bots no coinciden,
   - cómo contestar: `mis picks: 2-1, 0-0, -, 1-3` en ese orden (`-` salta uno),
   - la hora del primer partido = su deadline.

Reglas: no inventes probabilidades ni marcadores; todo sale del archivo. Si te
pregunta "¿por qué el bot puso X?", explica con los números del archivo
(probabilidades 1X2, Over 2.5, ambos anotan, apuestas de valor y su ventaja).
