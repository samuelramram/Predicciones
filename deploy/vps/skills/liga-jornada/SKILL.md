---
name: liga-jornada
description: Arma la jornada (Liga MX y Europa top-5) con los 3 bots, la sella y le manda a Samuel su boleto numerado.
---

# Jornada de la liga (Liga MX + Europa top-5)

Úsala cuando Samuel pida "la jornada", "el boleto", "qué pusieron los bots", o
cuando una automatización te lo pida.

Son dos boletos separados: Liga MX (`mx-AAAA-Jnn`, TODOS los partidos de la jornada)
y Europa (`eu-AAAA-Wnn`, solo los del top-3 de cada liga). Corre los dos:

1. Liga MX (segundos):
   `cd /workspace/predicciones && LIGA_HOME=/workspace/liga PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m wc_predictor.pipeline.ligamx_live --seal`
   Europa (~1 min, ajusta 5 ligas):
   `cd /workspace/predicciones && LIGA_HOME=/workspace/liga PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m wc_predictor.pipeline.europa_live --seal`
   - Si dice "ya selló … se queda como está", está bien: los bots no re-sellan.
   - Si falla porque no hay `fixtures.csv` o `fixtures_new.csv`, dile a Samuel que el
     Utilero (liga-sync) no ha corrido.
2. Lee los `.md` más recientes de `/workspace/liga/rounds/` (uno `mx-…`, uno `eu-…`).
3. Mándale a Samuel, corto:
   - la lista numerada de SUS partidos con día y hora (centro de México),
   - lo que puso `calibrado` en cada uno (su rival principal) y dónde los 3 bots no coinciden,
   - cómo contestar: por boleto, en orden (`2-1, 0-0, -, 1-3`) o con nombre
     (`Chivas 2-1, Bayern 2-0`); dile que te mande cada boleto en su propio mensaje,
   - la hora del primer partido = su deadline.

Reglas: no inventes probabilidades ni marcadores; todo sale del archivo. Si te
pregunta "¿por qué el bot puso X?", explica con los números del archivo
(probabilidades 1X2, Over 2.5, ambos anotan, apuestas de valor y su ventaja).
