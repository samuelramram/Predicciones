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

## Paso 1 — Refrescar la línea de cierre

```bash
python -m wc_predictor.pipeline.snapshot_odds
```

Si falla (sin `THE_ODDS_API_KEY`, red caída, API no disponible), **no abortes** —
`generate_picks` usará el snapshot guardado más reciente. El error es informativo, no bloqueante.

## Paso 2 — Generar los picks

```bash
python -m wc_predictor.pipeline.generate_picks --round <ROUND>
```

Sustituye `<ROUND>` con el valor de la tabla de arriba.

## Paso 3 — Reportar al usuario

Tras correr exitosamente:

1. Lee `data/raw/odds_closing_line.json` y extrae el campo `captured_at`.
2. Lee el archivo de salida `outputs/picks_<round>.md` y muéstralo completo.
3. Informa al usuario:
   - **Ronda**: nombre legible (ej. "Jornada 2")
   - **Línea de cierre**: fecha y hora de `captured_at` (o "snapshot local, sin actualizar" si falló el step 1)
   - **Archivos generados**: `outputs/picks_<round>.csv`, `.json`, `.md`

## Notas J3 — incentivos de clasificación

Para `--round j3`, el modelo aplica automáticamente ajustes de clasificación si ya
hay resultados de J1+J2 en `fixtures.json`:
- **Dead rubber**: ambos equipos ya clasificados → λ amortiguada
- **Equipo asegurado**: rota once titular → λ reducida
- **Empate de conveniencia**: si clasifica a ambos, la X vuelve a ser elegible

Antes del torneo o sin resultados cargados es un no-op transparente.
