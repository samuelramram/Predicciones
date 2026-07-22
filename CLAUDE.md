# CLAUDE.md

Modelo de quiniela del Mundial 2026 (Poisson + Dixon-Coles + Elo, picks
EV-óptimos). La documentación completa está en `README.md`.

## Proyecto activo: adaptación a Liga MX Apertura

Se está reusando este motor para el **Apertura de Liga MX** (ganar la quiniela
del pool privado + módulo de apuestas de valor). El **plan completo, el estado
por fases y los puntos de acoplamiento a refactorizar** están en
`docs/ligamx_apertura.md` — **léelo antes de tocar cualquier cosa de Liga MX.**

Estado: **Fase 1b** — ya hay pipeline Liga MX funcional y picks reales por
jornada. El `generate_picks` del Mundial sigue intacto (Liga MX corre por su
propio `pipeline/ligamx.py`, reusando el core). Las reglas de picks de abajo
aplican al Mundial; para Liga MX ver el runbook siguiente.

### Picks de Liga MX (runbook)

Perfil `LIGAMX_APERTURA_PROFILE` (`src/wc_predictor/leagues.py`), datos en
`data/ligamx/`. Cuando el usuario pida picks de Liga MX **sin jornada**,
pregúntale cuál (`j1`..`j17`). Flujo:

```bash
# 1) Refrescar datos (historial + calendario/resultados) — key premium en THESPORTSDB_API_KEY
python -m wc_predictor.ingest.ligamx --bootstrap
# 2) Re-fit (Elo replay + Poisson·DC) sobre el historial actualizado
python -m wc_predictor.pipeline.ligamx fit
# 3) Picks de la jornada
python -m wc_predictor.pipeline.ligamx picks --round j2
```

Salida en `outputs/ligamx_picks_{ronda}.{json,md}`. Atlante es cold-start
(franquicia comprada a Mazatlán) — cerca del promedio de liga hasta que junte
partidos. Pendiente: odds en el blend + backtest walk-forward (Fase 1b.2).

## Regla de interacción: picks por jornada

Cuando el usuario pida "picks", "boleto" o "predicciones" **sin especificar la
jornada o ronda**, pregúntale cuál antes de generar nada. La jornada es la
unidad real de decisión de la quiniela — no asumas "toda la fase de grupos".

Valores válidos de `--round`:

| El usuario dice | `--round` | Partidos |
|---|---|---|
| Jornada 1 / J1 | `j1` | 24 (1.ª de cada grupo) |
| Jornada 2 / J2 | `j2` | 24 (2.ª de cada grupo) |
| Jornada 3 / J3 | `j3` | 24 (3.ª de cada grupo) |
| Toda la fase de grupos | `group_stage` | 72 |
| Dieciseisavos | `round_of_32` | 16 |
| Octavos | `round_of_16` | 8 |
| Cuartos | `quarter_final` | 4 |
| Semifinales | `semi_final` | 2 |
| Tercer lugar | `third_place` | 1 |
| Final | `final` | 1 |

## Generar picks

Cuando el usuario pida correr el modelo para ver los picks de una jornada,
**siempre genera la predicción más certera posible en ese momento**: primero
refresca los datos del modelo (Elo + amistosos), luego la línea de cierre del
mercado, y al final corre `generate_picks`. No uses Elo ni odds viejos si se
pueden actualizar.

**Si el usuario comparte los CSV exportados de la app** (picks de todos los
participantes por ronda), ingiérelos ANTES de generar picks — actualizan
`fixtures.json` (resultados a 90', fuente de verdad para eliminatorias),
`pool_standings.json` (leaderboard con exactos) y `pool_picks.json` (boletos
reales que usa `--objective pool`):

```bash
python -m wc_predictor.ingest.pool_picks data/wc2026/pool_exports/*.csv \
    --you Claudio  # el 90' se infiere de los puntos de la app; --set-result solo si es ambiguo
```

```bash
# 1) Refrescar los datos del modelo (best-effort). Refetch del histórico
#    martj42 (incluye amistosos recientes) → recalcula Elo → reajusta Poisson+DC.
#    generate_picks lee artefactos precalculados (NO reentrena), así que este
#    paso es lo que hace que los picks usen el Elo actualizado. Si la red falla,
#    NO aborta: cada sub-paso cae a los artefactos versionados más recientes.
python -m wc_predictor.pipeline.refresh_data

# 2) Refrescar la línea de cierre (best-effort). Si no hay THE_ODDS_API_KEY,
#    falla la red o la API, NO aborta: generate_picks usará la línea guardada
#    más reciente. El comando degrada solo.
python -m wc_predictor.pipeline.snapshot_odds

# 3) Generar los picks de la ronda con el blend completo
#    (Poisson + Dixon-Coles + Elo + odds, e incentivos de clasificación si aplican)
python -m wc_predictor.pipeline.generate_picks --round j3
```

Salida en `outputs/picks_{ronda}.{csv,json,md}`. Tras correr, reporta de qué
fecha es el Elo (`as_of` en `data/wc2026/elo_snapshot.json`) y la línea de cierre
(`captured_at` en `data/raw/odds_closing_line.json`) para que el usuario sepa qué
tan frescos son los datos detrás del boleto.

## Estrategia de pool: alcance vs colchón (brecha + horizonte)

`generate_picks --objective pool` ya no maximiza P(ganar este round) sino
**P(terminar 1.º del torneo)**. Lee `data/wc2026/pool_standings.json` (leaderboard
del usuario) y, vía Monte Carlo (`model/pool_optimizer.py` + `model/standings.py`),
mete los factores que antes ignoraba:

- **Brecha real**: puntos actuales tuyos vs el líder y el resto del pool.
- **Desempate por exactos**: la victoria en la simulación es lexicográfica
  `(puntos, exactos)` — el colchón de exactos cuenta como ventaja real.
- **Picks reales de los rivales** (`pool_picks.json`, vía `ingest.pool_picks`):
  el campo se simula con los boletos capturados de la app, no con humanos
  sintéticos; la diferenciación se evalúa contra lo que de verdad picaron.
- **Horizonte**: partidos que faltan tras esta ronda (`total_matches − resueltos −
  pendientes de la ronda`); cada uno añade varianza futura.
- **Habilidad empírica** de cada jugador, pura estadística del marcador:
  `e = exactos/jugados`, `q = (puntos − exactos)/jugados`.
- **Multi-candidato**: por partido puede moverse del pick EV al mejor marcador
  de cualquier otro outcome (incluida la X, aunque esté vetada para el pick EV).

Con eso la decisión **emerge de la matemática**: vas atrás por margen alcanzable
+ pocos partidos → arriesga (swaps a contrarian); brecha chica o vas cómodo +
horizonte largo → EV puro (tu ventaja se compone sola). Sin los archivos, degrada
al objetivo de un solo round. Ingiere los exports (`ingest.pool_picks`) cada ronda.

## Eliminatorias (calibración específica)

- `ko_draw_allow_min_prob` (0.33): la quiniela sigue siendo a 90' en KO y ~25-35%
  de esos partidos terminan empatados; el gate de 0.42 de grupos era inalcanzable
  con odds en el blend, así que en eliminatorias la X se permite desde P(X) ≥ 0.33.
- `ko_modal_draw_min_prob` (0.30): segunda vía de desbloqueo de la X en KO — si
  el marcador MODAL del blend es un empate (0-0/1-1) y P(X) ≥ 0.30, la X entra al
  optimizador aunque no alcance el gate de arriba. Solo KO: en 204 partidos de
  grupos históricos (WC14/18/22 + Euro/Copa 24) la misma regla resta puntos.
- `ko_exacto_ev_bonus` (0.5): en KO los candidatos se rankean con EV inclinado al
  exacto (peso efectivo 2.5) porque el leaderboard desempata por exactos y, con
  scoring excluyente, el EV puro casi nunca aterriza en la X modal recién
  desbloqueada. El EV reportado sigue siendo el real. Backtest de los 13 R32
  resueltos a 90': 14 pts/4 exactos → 16/5.
- `ko_goal_env_ratio` (0.90): la inflación de goles (`wc_lambda_inflation`,
  `goal_env_mult`) se calibró con fase de grupos; en KO a 90' se anota menos y
  este ratio la amortigua para no picar marcadores un gol arriba.
- Los resultados de KO en `fixtures.json` vienen del export de la app (90'), no
  de martj42 (que registra el marcador con tiempo extra); `refresh_data` solo
  mergea marcadores de fase de grupos.
- Ojo: en KO decididos en prórroga la app puede MOSTRAR el marcador con tiempo
  extra aunque pague los puntos sobre el 90' (Bélgica-Senegal mostró 3-2 y pagó
  sobre 2-2). `ingest.pool_picks` valida cada "Resultado Real" contra los puntos
  pagados e infiere el 90' cuando no cuadran o cuando sigue "Pendiente" con
  puntos ya asignados — `--set-result` solo hace falta si la inferencia es
  ambigua (pocos jugadores puntuados).

## Incentivos de clasificación (jornada 3)

`model/qualification.py` calcula la tabla de cada grupo tras J1+J2 con los
desempates oficiales FIFA 2026 (puntos → duelo directo → diferencia de goles →
goles a favor) y clasifica cada partido de J3:

- **dead rubber** — la clasificación de ambos equipos al top-2 ya está
  decidida; el resultado es ruido (rotaciones, ritmo bajo).
- **equipo asegurado** — su λ se amortigua (`qual_rotation_lambda_mult`) porque
  suele rotar el once.
- **empate de conveniencia** — si un empate clasifica a los dos, el modelo
  vuelve a permitir la X (que normalmente está prohibida).

`generate_picks` lo aplica solo a J3 y solo cuando ya hay resultados de J1+J2
cargados en `fixtures.json`; antes del torneo es un no-op.
