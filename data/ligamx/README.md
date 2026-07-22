# data/ligamx — fuente de verdad Liga MX Apertura

Scaffolding de la Fase 0. Archivos versionados (fuente de verdad humana),
espejo de `data/wc2026/` pero para Liga MX (TheSportsDB league **4350**).

| Archivo | Estado | Quién lo llena | Notas |
|---|---|---|---|
| `venues.json` | **template — VERIFICAR** | usuario / Fase 1 | Estadio + altitud por equipo. La altitud alimenta `altitude_penalty_per_1000m`; en Liga MX se lee en **cada** partido (localía por equipo). |
| `teams.json` | **template — VERIFICAR** | usuario / Fase 1 | 18 equipos + su sede. Reconciliar nombres con el spelling de TheSportsDB 4350. |
| `rules.json` | **template — VERIFICAR** | usuario | Scoring del pool, desempate, premio, fuentes. |
| `fixtures.json` | pendiente Fase 1 | `ingest` 4350 | Calendario + resultados live. |
| `matches_history.csv` | pendiente Fase 1 | `ingest` 4350 + fbref | Histórico de entrenamiento (3-4 torneos atrás). |
| `elo_current.json` | pendiente Fase 1 | clubelo.com | Elo de clubes. |
| `injuries.json` | pendiente | manual | Bajas por jornada. |

**Todo lo marcado "VERIFICAR"** son valores plausibles de arranque, no verdad
confirmada — especialmente las altitudes y la sede de América/Cruz Azul (Azteca
está en obras post-Mundial). Revísalos antes de generar picks reales.

Ver el plan completo en `docs/ligamx_apertura.md`.
