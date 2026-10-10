# Liga de bots: diseño multiagente (OpenClaw)

Regla base: **los números salen de código determinista; los agentes LLM orquestan,
platican y compiten.** Ningún agente calcula probabilidades "a ojo", salvo el
Reportero, cuyo trabajo es justo probar si leer noticias le gana al mercado, y se
mide con la misma vara (z pareado) que los demás.

## Roles

| Agente | Qué hace | Cómo | Permisos |
|---|---|---|---|
| **Claudio** (frente) | Habla contigo por Telegram: recibe tus picks, valida el formato, te avisa el deadline, explica por qué un bot puso 2-1 | LLM (Sonnet) | Sin red; solo lee los boletos y escribe tus picks a la cola del Notario |
| **Utilero** (datos) | Actualiza historial, fixtures y momios | GitHub Actions (`refresh-data`) + `git pull` en el VPS | Llave de deploy de solo lectura en el VPS |
| **Bots modeladores**: estadístico, calibrado, borrego | Arman su boleto: marcador, 1X2, Over/Under 2.5, ambos anotan, apuestas de valor (1X2, O/U, hándicap asiático) | Python: `pipeline.europa_live`, `pipeline.ligamx` | Sin red; solo lectura de `data/` |
| **Reportero** (bot LLM) | Lee lesiones, rotaciones por Champions y clima, y arma SU boleto con justificación | LLM + búsqueda web | El único con red, y solo para buscar; no toca el libro |
| **Notario** | Sella los boletos (SHA-256 encadenado) antes del primer partido y verifica la cadena | `liga.seal` (código) | El único que escribe `ledger.jsonl` |
| **Árbitro** | Al acabar la jornada califica a todos y manda la tabla | `liga.scoring` + `liga.markets` (código) | Solo lectura del libro y los resultados |

## Flujo de una jornada

1. **Jueves, Utilero**: datos frescos, con fixtures y momios previos.
2. **Jueves, bots modeladores**: `python -m wc_predictor.pipeline.europa_live --seal` y el equivalente de Liga MX; cada bot sella.
3. **Viernes, Reportero**: lee noticias, propone su boleto y el Notario lo sella.
4. **Antes del primer partido, tú**: le mandas a Claudio tus picks de los partidos top (Liga MX + top-3 de Europa) y el Notario los sella. Después del primer pitazo ya no se puede, y `sealed_before` lo comprueba.
5. **Lunes, Árbitro**: califica puntos de quiniela, Brier por mercado y bankroll ficticio por mercado, y Claudio te manda la tabla por Telegram.

## Por qué así

- **Reproducible**: si un bot gana, se puede volver a correr y sale lo mismo. Un LLM que "opina" probabilidades no es auditable.
- **Mínimo privilegio**: cada agente toca solo lo suyo, y el que tiene red no puede escribir el libro.
- **Comparación justa**: todos los bots, tú incluido, se miden en los MISMOS partidos con prueba pareada.

## Implementación actual (oct 2026)

Por ahora Claudio hace el trabajo de **operador** de los bots de código, el Notario y el Árbitro. Los corre él mismo dentro de su sandbox, con las skills `liga-jornada`, `liga-sellar` y `liga-tabla`, y sigue las automatizaciones de jueves, viernes y lunes. El Utilero es un timer del host sin LLM. Instalación y seguridad: `deploy/vps/README.md`.

## Reportero (implementado)

Claudio, con búsqueda web, investiga bajas, alineaciones y rotaciones de los partidos del boleto de Samuel. Su veredicto lo escribe como **multiplicadores de goles esperados** (`home_mult`, `away_mult`, acotados a 0.75–1.25) en `$LIGA_HOME/reportero/<jornada>.json`, junto con una nota y sus fuentes.

`liga.reportero` (código) parte del bot calibrado, aplica los multiplicadores, rearma la matriz de marcadores y sella el boleto como bot `reportero`. Un partido sin noticias queda idéntico al calibrado.

El Árbitro lo mide contra el calibrado en los mismos partidos (sección "Cada bot contra el calibrado"). Así se sabe si leer noticias le gana al mercado de ayer.

Corre el viernes a las 08:00. Las fuentes y notas quedan selladas con el boleto.

## Decisiones pendientes de infraestructura

- **Dónde vive el libro.** El VPS tiene llave de solo lectura al repo, así que no puede hacer push del ledger. Propuesta: un repo privado chiquito `quiniela-ledger` con llave de deploy de escritura, solo para `ledger.jsonl`. Si alguien comprometiera el VPS, no podría tocar el código.
- **Props de jugadores (fase 2).** Goleador y tarjetas necesitan alineaciones + momios históricos. Sin fuente gratis no se pueden medir.
