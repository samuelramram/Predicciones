---
name: liga-jornada
description: Arma la jornada (Liga MX y Europa top-5) con los bots (estadístico, calibrado, borrego y aprendiz), la sella y le manda a Samuel su boleto numerado.
---

# Jornada de la liga (Liga MX + Europa top-5)

Úsala cuando Samuel pida "la jornada", "el boleto", "qué pusieron los bots", o
cuando una automatización te lo pida.

Son dos boletos separados e **independientes**: Liga MX (`mx-AAAA-Jnn`, TODOS los
partidos de la jornada) y Europa (`eu-AAAA-Wnn`, los del top-3 de cada liga **y sus
partidos de Champions / Europa League / Conference**). Corre los dos SIEMPRE, cada uno
con `--seal`; que uno no tenga partidos no detiene al otro:

1. Liga MX (segundos):
   `cd /workspace/predicciones && LIGA_HOME=/workspace/liga PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m wc_predictor.pipeline.ligamx_live --seal`
   Europa (~1 min, ajusta 5 ligas):
   `cd /workspace/predicciones && LIGA_HOME=/workspace/liga PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m wc_predictor.pipeline.europa_live --seal`
   - Si Football-Data aún no publica una liga, los scripts ya usan el respaldo solos
     (calendario de `data/ligamx/fixtures.json` y momios de The Odds API) y lo dicen en
     una línea; repítela tal cual.
   - Si aun así uno dice que no hay partidos próximos, di **exactamente** lo que dijo el
     script y **sigue con el otro**. **Nunca adivines la causa** ("fecha FIFA", "descanso"):
     para Liga MX revisa las fechas de la siguiente jornada en
     `predicciones/data/ligamx/fixtures.json` y dile a Samuel cuándo juega. Nunca corras
     Europa sin `--seal`.
   - Si dice "nada nuevo que sellar", está bien: los bots no re-sellan; si la jornada
     creció (copas el lunes, liga el jueves) sella solo lo nuevo como `…/2`.
   - Si falla porque no existe `fixtures.csv` o `fixtures_new.csv`, dile a Samuel que el
     Utilero (liga-sync) no ha corrido.
2. Lee los `.md` más recientes de `/workspace/liga/rounds/` (uno `mx-…`, uno `eu-…`).
3. Mándale a Samuel, corto:
   - la lista numerada de SUS partidos con día y hora (centro de México),
   - lo que puso `calibrado` en cada uno (su rival principal) y dónde los bots no coinciden,
   - la línea del **aprendiz** que viene arriba del `.md` (cuánto le cree al mercado esta
     semana y por qué); dila en una frase, sin adornarla,
   - cómo contestar: por boleto, en orden (`2-1, 0-0, -, 1-3`) o con nombre
     (`Chivas 2-1, Bayern 2-0`); dile que te mande cada boleto en su propio mensaje,
   - la hora del primer partido = su deadline.

Reglas: no inventes probabilidades ni marcadores; todo sale del archivo. Si te
pregunta "¿por qué el bot puso X?", explica con los números del archivo
(probabilidades 1X2, Over 2.5, ambos anotan, apuestas de valor y su ventaja).
