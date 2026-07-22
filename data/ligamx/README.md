# data/ligamx — fuente de verdad Liga MX Apertura

Scaffolding de la Fase 0. Archivos versionados (fuente de verdad humana),
espejo de `data/wc2026/` pero para Liga MX (TheSportsDB league **4350**).

| Archivo | Estado | Quién lo llena | Notas |
|---|---|---|---|
| `teams.json` | ✅ del webapp | `quinielacartoimagen` | 18 equipos, nombres EXACTOS del webapp (`name_es` = clave canónica). Atlante marcado `cold_start`. |
| `venues.json` | ✅ | manual | Estadio + altitud. La altitud alimenta `altitude_penalty_per_1000m`; en Liga MX se lee en **cada** partido (localía por equipo). América y Cruz Azul en Azteca toda la temporada. |
| `matches_history.csv` | ✅ ingest | `ingest.ligamx` | 1028 partidos (3 temporadas + actual). Columnas idénticas al CSV internacional → fit y Elo lo consumen sin cambios. |
| `fixtures.json` | ✅ ingest | `ingest.ligamx` | Calendario Apertura 2026 (153 fixtures, 17 jornadas × 9). Se re-corre para traer resultados. |
| `rules.json` | **template — VERIFICAR** | usuario | Scoring del pool, desempate, premio. |
| `elo_current.json` | pendiente Fase 1b | replay local | Elo de clubes por replay sobre el historial (no clubelo). |
| `injuries.json` | pendiente | manual | Bajas por jornada. |

Regenerar historial + fixtures:

```bash
python -m wc_predictor.ingest.ligamx --bootstrap   # necesita THESPORTSDB_API_KEY premium
```

Ver el plan completo en `docs/ligamx_apertura.md`.
