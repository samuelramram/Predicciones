---
name: picks
description: >
  Generador de picks/predicciones/boleto para la quiniela del Mundial 2026.
  Úsalo automáticamente cada vez que el usuario pida picks, predicciones, boleto,
  quiniela, pronósticos o resultados de una jornada o ronda del Mundial — incluso
  si solo dice "dame los picks de J2" o "qué pones en cuartos". Siempre refresca
  la línea de cierre antes de generar. Si el usuario no especifica la jornada o
  ronda, pregúntale antes de correr nada.
---

# Picks — quiniela Mundial 2026

Genera picks EV-óptimos con el blend completo (Poisson + Dixon-Coles + Elo + odds de mercado).

## Paso 0 — Identificar la ronda

Si el usuario no especificó la jornada o ronda, **pregunta antes de continuar**.
No asumas "toda la fase de grupos".

| El usuario dice          | `--round`     | Partidos |
|--------------------------|---------------|----------|
| Jornada 1 / J1           | `j1`          | 24       |
| Jornada 2 / J2           | `j2`          | 24       |
| Jornada 3 / J3           | `j3`          | 24       |
| Toda la fase de grupos   | `group_stage` | 72       |
| Dieciseisavos            | `round_of_32` | 16       |
| Octavos                  | `round_of_16` | 8        |
| Cuartos                  | `quarter_final` | 4      |
| Semifinales              | `semi_final`  | 2        |
| Tercer lugar             | `third_place` | 1        |
| Final                    | `final`       | 1        |

## Paso 1 — Refrescar los datos del modelo (Elo + amistosos)

```bash
python -m wc_predictor.pipeline.refresh_data
```

Esto rebaja a un solo comando el ciclo completo: refetch del histórico martj42
(incluye los amistosos más recientes) → recalcular Elo → reajustar Poisson + DC.
`generate_picks` lee artefactos precalculados, no reentrena, así que **este paso
es obligatorio para que los picks usen el Elo actualizado**.

Si falla (red caída, fuente inalcanzable), **no abortes** — cada sub-paso degrada
solo y cae a los artefactos versionados más recientes (`elo_current.json`,
`team_strengths.json`). El error es informativo, no bloqueante.

## Paso 2 — Refrescar la línea de cierre

```bash
python -m wc_predictor.pipeline.snapshot_odds
```

Si falla (sin `THE_ODDS_API_KEY`, red caída, API no disponible), **no abortes** —
`generate_picks` usará el snapshot guardado más reciente. El error es informativo, no bloqueante.

## Paso 3 — Actualizar standings (brecha + horizonte)

Antes de generar, refresca `data/wc2026/pool_standings.json` con el leaderboard
más reciente que tenga el usuario (puntos + exactos por jugador; al menos la cima
de la tabla). Esto es lo que permite decidir **alcance vs colchón con matemáticas**:

- `you`: nombre del usuario en la quiniela (hoy `Claudio`).
- `players`: lista con `{name, points, exactos}` (la cima manda; captura lo que haya).
- `matches_resolved`: partidos ya calificados (fase de grupos jugada + KO jugados).
- `total_matches`: 104. `total_participants`: tamaño del pool. `field_baseline`:
  relleno para los no listados.

Si el usuario no tiene leaderboard nuevo, usa el archivo existente y avísale que
los números son de la última captura.

## Paso 4 — Generar los picks (objetivo pool por defecto)

```bash
python -m wc_predictor.pipeline.generate_picks --round <ROUND> --objective pool
```

Sustituye `<ROUND>` con el valor de la tabla de arriba. **Usa siempre
`--objective pool`**: con `pool_standings.json` presente, el optimizador maximiza
P(terminar 1.º del torneo) considerando tu brecha al líder y los partidos que
faltan, y de ahí decide cuánto arriesgar (no es corazonada). Si no existe el
archivo, degrada al objetivo de un solo round. Usa `--objective ev` solo si el
usuario pide explícitamente el boleto de máxima precisión sin estrategia de pool.

## Paso 4 — Reportar al usuario

Tras correr exitosamente:

1. Lee `data/wc2026/elo_snapshot.json` y extrae el campo `as_of` (fecha del último
   partido que entró al Elo, p. ej. el amistoso más reciente).
2. Lee `data/raw/odds_closing_line.json` y extrae el campo `captured_at`.
3. Lee el archivo de salida `outputs/picks_<round>.md` y muéstralo completo.
4. Informa al usuario:
   - **Ronda**: nombre legible (ej. "Jornada 2")
   - **Datos del modelo**: fecha `as_of` del Elo (o "sin actualizar, red caída" si falló el step 1)
   - **Línea de cierre**: fecha y hora de `captured_at` (o "snapshot local, sin actualizar" si falló el step 2)
   - **Archivos generados**: `outputs/picks_<round>.csv`, `.json`, `.md`

## Notas J3 — incentivos de clasificación

Para `--round j3`, el modelo aplica automáticamente ajustes de clasificación si ya
hay resultados de J1+J2 en `fixtures.json`:
- **Dead rubber**: ambos equipos ya clasificados → λ amortiguada
- **Equipo asegurado**: rota once titular → λ reducida
- **Empate de conveniencia**: si clasifica a ambos, la X vuelve a ser elegible

Antes del torneo o sin resultados cargados es un no-op transparente.
