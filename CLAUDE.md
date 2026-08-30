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
# 1b) Odds de mercado (1X2 devigado para el blend + mercados para apuestas)
python -m wc_predictor.ingest.ligamx_odds
# 2) Re-fit (Elo replay + Poisson·DC) sobre el historial actualizado
python -m wc_predictor.pipeline.ligamx fit
# 3) Picks de la jornada (EV por partido)
python -m wc_predictor.pipeline.ligamx picks --round j2

# 3c) Liguilla — picks por leg (ida y vuelta a 90') de una ronda del playoff.
#     Antes de que termine el rol regular usa el bracket PROYECTADO desde la
#     tabla actual; cuando se definan los cruces, fíjalos en
#     data/ligamx/liguilla.json y se recalcula solo. Rondas: quarter_final |
#     semi_final | final.
python -m wc_predictor.pipeline.ligamx picks --round quarter_final

# 3d) Proyección del torneo (Monte-Carlo): simula el resto de la temporada →
#     tabla final → siembra → bracket, y da P(cada equipo llega a liguilla,
#     semis, final, campeón). Útil desde ya para ver rumbo.
python -m wc_predictor.pipeline.ligamx liguilla --sims 10000

# 3b) Picks optimizados para P(quedar 1.º) — requiere pool_standings.json
#     (ingiere primero los exports de la app; sin ellos degrada a EV)
#     --start-round 3: el pool puntúa desde J3 (J1-J2 no cuentan); --liguilla-matches
#     ancla el horizonte real (regular + liguilla), no el calendario completo.
python -m wc_predictor.ingest.ligamx_pool data/ligamx/pool_exports/*j*.csv --you Samuel \
    --start-round 3 --liguilla-matches 17
python -m wc_predictor.pipeline.ligamx picks --round j2 --objective pool

# 4) Apuestas de valor. Por DEFAULT cotiza solo en TUS casas (data/ligamx/books.json)
#    y parte el boleto por CLV, no por edge: la prueba es si el precio le gana a la
#    línea justa afilada, no si el modelo le gana al mercado (no le gana).
#    Caliente no está en The Odds API → sus precios se capturan a mano en books.json.
python -m wc_predictor.pipeline.ligamx_bets --round j2 --bankroll 500
python -m wc_predictor.pipeline.ligamx_bets --round j2 --require-clv   # solo lo apostable
python -m wc_predictor.pipeline.ligamx_bets --round j2 --all-books     # medir el modelo, NO apostar
#    El BOLETO DISCIPLINADO: --require-clv + --min-stake 20 (default). Los
#    stakes de ¼-Kelly caen en $3–$10, bajo el mínimo de la casa; se redondean a
#    múltiplos de $20 para que el boleto sea copy-paste. --min-stake 0 = Kelly crudo.
python -m wc_predictor.pipeline.ligamx_bets --round j2 --require-clv --min-stake 20
#    El BOLETO DE DESPLIEGUE (experimento): --budget 0.9 pone ~90% del roll a
#    trabajar con UN pick 1X2 por partido, peso mixto (base igual + bonus por CLV+
#    + bonus por ventaja del modelo). Acción medida sobre el roll, NO boleto +EV:
#    la mayoría de los picks empiezan con CLV negativo. El CLV de cada uno se
#    registra igual para medir al modelo a lo largo del torneo.
python -m wc_predictor.pipeline.ligamx_bets --round j2 --budget 0.9
#    El BOLETO POR CASA (lo que apuesta el usuario de verdad): despliega el
#    presupuesto de CADA casa por separado, a SU precio, un pick 1X2 por partido,
#    mínimo $20/predicción en unidades de $20. --log-boleto lo registra en el
#    ledger con la casa + precio REALES (no la medición all-books).
python -m wc_predictor.pipeline.ligamx_bets --round j2 \
    --budget-betway 300 --budget-caliente 200 --log-boleto
#    --house-totals: además del pick 1X2 por partido, agrega una pierna Over/Under
#    (al precio de la casa) SOLO cuando el modelo ve valor real ahí (edge>0 y +EV).
#    Así el boleto lleva la acción de totals, no solo el 1X2. Ojo: si el feed de
#    odds no trae los totals de una casa (p.ej. Betway en algunas jornadas), esa
#    casa se queda 1X2 — no se inventa un precio.
python -m wc_predictor.pipeline.ligamx_bets --round j2 \
    --budget-betway 300 --budget-caliente 200 --house-totals --log-boleto

# 4b) Ledger de CLV — mide si el edge de apuestas es REAL a lo largo del torneo.
#     log al apostar → close cerca del kickoff (tras refrescar odds) → settle con
#     resultados → report (CLV promedio, % que le gana al cierre, ROI + HTML).
#     El ledger se versiona en data/ligamx/clv_ledger.json (es el registro).
python -m wc_predictor.pipeline.ligamx_clv log --round j2 --bankroll 500
python -m wc_predictor.pipeline.ligamx_clv close     # cerca del kickoff
python -m wc_predictor.pipeline.ligamx_clv settle    # con resultados
python -m wc_predictor.pipeline.ligamx_clv report    # → outputs/ligamx_clv.html

# 5) Backtest walk-forward (validación out-of-sample, sin odds)
python -m wc_predictor.pipeline.ligamx_backtest --since 2025-07-01

# 6) Tracker de fuentes — ¿le gana el BLEND (55% mercado) al modelo solo y al
#    mercado solo? El peso del mercado NO se puede backtestear (no hay feed
#    histórico de odds de Liga MX), así que se MIDE en vivo: log por jornada →
#    settle con resultados → report acumulado. En ~5-6 jornadas dice si conviene
#    mover blend_odds_weight. También mide la congestión (ver abajo).
#
#    OJO: el `log` YA NO se corre a mano — `ligamx picks --round jN` lo dispara
#    solo. El tracker lee el snapshot VIVO de odds, que solo trae partidos sin
#    patear; loguear después del kickoff pierde esas filas PARA SIEMPRE (no hay
#    feed histórico). Por eso se registra al generar los picks: único momento con
#    odds frescas y garantizado pre-kickoff. Si el log avisa "⚠ N partidos SIN
#    línea", la ronda se logueó tarde y esa muestra ya no se recupera.
#    (Medido: J5 registró 2 de 9 partidos e imprimía un éxito engañoso.)
python -m wc_predictor.pipeline.ligamx_source_tracker log --round j4   # solo backfill manual
python -m wc_predictor.pipeline.ligamx_source_tracker settle
python -m wc_predictor.pipeline.ligamx_source_tracker report
```

### Calibración: qué se probó y por qué NO se cambió (disciplina)

La quiniela puntúa **decisiones discretas** (el pick es un argmax), así que afinar
una probabilidad continua casi nunca cruza el umbral que cambia el pick. Medido en
el backtest walk-forward (354 partidos OOS): **bajar el veto al empate (0.30→0.50),
subir el ambiente de goles (1.00→1.08) y el tilt de exactos (+0.25→+1.5) dan CERO
cambio de puntos.** El 1X2 ya está casi perfectamente calibrado (local/empate/visita
dentro de ±1pp) y los exactos (~9-10%) van a la par del campo. **No metas knobs de
calibración: no encienden nada.** La ganancia fina vive en señal nueva, no en tuning:

- **Peso del mercado (0.55):** el predictor más fuerte y lo único que corrige la
  sobreconfianza del modelo en el rango medio (el modelo solo sobrevalora a los
  cold-start como Atlante). No es backtesteable → se mide con el `source_tracker`.
- **Congestión (Leagues Cup):** el efecto de descanso corto en el histórico de Liga
  MX midió **~0** (prueba pareada por equipo: Δ −0.014 PPG, Δ −0.07 goles, t≈−0.2).
  Por eso **no se cablea ninguna penalización de λ**; se marcan los equipos con carga
  en `data/ligamx/congestion.json` y el `source_tracker` mide si de verdad rinden por
  debajo de su predicción a lo largo de J4-J6. Si aparece señal, se calibra CON
  evidencia — igual que el peso del mercado.

### Diagnóstico tras J5 — leer antes de "arreglar" el modelo

`docs/ligamx_diagnostico_j5.md` tiene la auditoría completa (656 partidos OOS +
62 apuestas liquidadas). Los tres resultados que cambian cómo se habla del
modelo:

1. **El techo de Liga MX es ~53% de acierto 1X2** y el modelo entrega 53.2% con
   55.1% de confianza media. No está descalibrado (±1.5pp en los tres
   resultados). El contraste con el Mundial **no** es de afinación: la
   distribución cruda de resultados es idéntica (entropía 1.524 vs 1.526), pero
   el Mundial tiene el doble de dispersión de fuerza (|ΔElo| mediana 193 vs 113;
   47% de partidos con brecha >200 vs 21%). El acierto sube de 46.6% a 63.8%
   conforme crece la brecha — Liga MX simplemente vive en el extremo parejo.
2. **El modelo no le gana al mercado apostando, y el selector es adverso.** En
   las 62 apuestas liquidadas: modelo 48.8%, mercado 40.9%, realidad 40.3%. El
   mercado clava la realidad dentro de ~1pp en TODOS los cortes (1X2, totals,
   favoritos, longshots) y el modelo se pasa 6-10pp en todos. Brier 0.2354 vs
   0.2156. Apostar "donde el modelo > mercado" es un filtro para los errores del
   modelo. Con las líneas de cierre de J4+J5 (47 entradas): **CLV global −3.43%,
   21% le gana al cierre** (J4 −5.56%, J5 −1.71%).
3. **Los empates apostados son el peor corte del ledger**: 9 apuestas, modelo
   28.1%, real 11.1%, **−90.3% ROI**. Fuera del boleto hasta nuevo aviso.

Decisiones vigentes: **boleto de despliegue por casa retirado** (−EV por
construcción, costó $291 en J5); toda apuesta pasa por `--require-clv`; sin
empates; totals antes que 1X2. La quiniela no se toca.

Esto encaja con el shrinkage de abajo: el pool no tiene habilidad detectable
todavía (dispersión observada < la que produce la suerte), así que ni la tabla
ni una jornada mala son evidencia de que el modelo esté roto.

### Habilidad del pool: shrinkage empírico-Bayes (medido, NO es un knob)

El simulador proyecta la habilidad de cada jugador (`q_rate`, `e_rate`) sobre el
horizonte restante. Usaba la **media muestral cruda**, y eso rompía el objetivo:

- Tras 18 partidos, la dispersión OBSERVADA del pool era **0.126 pts/partido**,
  MENOR que la que produce la pura suerte (**0.156**) → no hay habilidad
  detectable; toda la tabla era varianza. (Arturo 0.722 vs Claudio 0.333: z=1.76,
  p=0.08, **no significativo**.)
- Pero la cruda extrapolaba ese ruido a 134 partidos → el líder terminaba ~60 pts
  arriba → **P(1.º)=0.0%** → objetivo plano en cero → el desempate por exactos
  tomaba el volante y picaba el marcador modal global (1-1) en TODOS lados.

`standings.shrink_rates` encoge las tasas hacia la media del pool por la fracción
de varianza que sobrevive restarle la suerte (James-Stein). Si la dispersión
observada ≤ suerte, encoge al 100%. **Efecto medido en J6: P(1.º) 0.0% → 3.1%**
(coincide con simulación independiente 2.5-3.8%) y los swaps arbitrarios
desaparecen. Cuando SÍ haya habilidad real (muestra larga), la conserva.

Dos guardas relacionadas en `pool_optimizer`:
- `objective_live`: si el premio simulado del boleto EV es ~0, el desempate por
  exactos NO se activa (rankear por P(exacto) sola tira el punto del 1X2). En J4
  ese camino cambió 4 favoritos a 1-1: **0 puntos ganados, 1 perdido.**
- Un swap que de verdad mueve el premio sigue pasando por la rama `better`.

### Regla de interacción: apuestas por casa (cada jornada)

Cuando vayas a generar el boleto de apuestas de una jornada, **pregúntale al
usuario cuánto va a apostar en Betway y cuánto en Caliente** (puede ser una,
otra, o ambas). Tú **destinas ese presupuesto COMPLETO** en cada casa con
`--budget-betway`/`--budget-caliente`: un pick 1X2 por partido, al precio de esa
casa, **mínimo $20 por predicción** (en unidades de $20 — es el mínimo real de
ambas casas). Corre siempre con `--log-boleto` para que el ledger registre lo que
DE VERDAD apostó (casa + precio + stake reales), no la medición all-books. Esto
requiere `ingest.ligamx_odds` fresco (los precios caducan por jornada, y Caliente
se captura a mano en `books.json`).

**Honestidad del boleto por casa:** es acción medida sobre el roll, NO un boleto
+EV. Casi todos los picks arrancan con CLV ≤ 0 (el mercado les gana); el valor de
esto es medir el CLV real a lo largo del torneo, no ganar cada jornada. Si una
jornada "gana", casi siempre es varianza de un par de longshots, no edge — díselo
al usuario con esas palabras y remite al CLV promedio del ledger como el veredicto.

**J3 (medido): los empates NO son un ajuste de calibración pendiente.** En J3 el
modelo quedó abajo de la media por no picar 2 empates (San Luis 0-0 lo cazó medio
pool). Se probó bajar el `draw_allow_min_prob` y agregar un *modal-draw unlock* de
rol regular (como el de liguilla) en el backtest walk-forward: **cero cambio de
puntos incluso con umbral 0.22** — el EV ya prefiere el lado ganador por décimas,
así que levantar el veto del empate nunca cambia el pick. Picar esos empates
habría sido una desviación −EV que solo se ve bien en retrospectiva. La skill
base del modelo es +14.9% OOS y su tasa de exactos (~10%) va a la par del campo;
**no metas un cambio de calibración por una jornada de varianza.**

Salida en `outputs/ligamx_picks_{ronda}.{json,md,html}` (+ `ligamx_liguilla.*`
para la proyección). Atlante es cold-start (franquicia comprada a Mazatlán) —
cerca del promedio de liga hasta que junte partidos. La calibración está
re-fiteada contra el histórico real (localía Elo 100, blend 60/40, rho perfilado,
`goal_env_mult` neutral, half-life 730d confirmado por sweep): +14.9% vs baseline
"1-0" en el backtest walk-forward.

**Output para el usuario (importante): cada corrida emite un `.html`
self-contained y theme-aware.** El usuario NO ve bien el markdown en GitHub, así
que **siempre que generes picks o la proyección, publica ese `.html` como
Artifact** (`outputs/ligamx_picks_{ronda}.html` o `ligamx_liguilla.html`) para
que lo vea en claude.ai. Es el boleto/serie/tabla renderado bonito, no el ASCII.

**Calibración de liguilla (medida con datos de Liga MX).** El ingest ahora guarda
la ronda de TheSportsDB en `matches_history.csv` (`round` + `stage`), lo que
permitió aislar **99 partidos de playoff (2023-2026)** y medirlos contra el rol
regular:

| | goles/partido | empates a 90' |
|---|---|---|
| rol regular (936) | 2.860 | 23.9% |
| liguilla (99) | **2.576** | **32.3%** |

Ratio de goles **0.90** — coincide con el `ko_goal_env_ratio` del Mundial, ahora
sobre evidencia local. Así que los legs de liguilla corren con la calibración de
playoff (`predict_fixture(..., liguilla=True)`): λ amortiguada, gate de empate
`ko_draw_allow_min_prob` con el desbloqueo por marcador modal, y el tilt de
exactos. Un tercio de los legs termina empatado — el gate de rol regular no puede
expresar eso. Ojo: TheSportsDB **omite `intRound` en liguillas enteras**, así que
`annotate_stages` las rellena por fecha (todo lo posterior a la última jornada
fechada del torneo es playoff); sin ese backfill solo se recuperaban 44 de 99.
El A/B está en `ligamx_backtest --no-liguilla-calibration`.

**Liguilla (Fase 1c, hecha).** Formato Apertura 2026: sin Play-In, top-8 directo,
cuartos 1-8/2-7/3-6/4-5, semis resembradas por posición en la tabla general,
todo ida y vuelta; global empatado avanza el mejor sembrado en cuartos/semis y en
la final hay tiempos extra + penales. `model/liguilla.py` calcula tabla+siembra,
el avance por global (convolución de las dos legs + regla de desempate) y la
proyección Monte-Carlo. El pool puntúa **cada leg a 90'** como cualquier partido,
así que los picks por leg salen del mismo optimizador.

**xG vs goles (decisión):** se evaluó cablear xG (fbref) y **se descartó por
ahora** — fbref responde 403 detrás del proxy, y con el **mercado al 55% del
blend (que ya ES un modelo xG)** el margen de xG sobre un modelo de goles bien
calibrado es chico y en parte redundante. Goles + odds gana en ROI. Si algún día
se quiere xG, la vía es API-Football (`API_FOOTBALL_KEY`) como experimento medido
con CLV/backtest, en su propio PR — no fbref.

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

## Reglamento real del pool de Liga MX (verificado, no plantilla)

Todo esto salió del código de la webapp (`samuelramram/quinielacartoimagen`) y
está fijado en `data/ligamx/rules.json` + `LIGAMX_APERTURA_PROFILE.rules`:

- **Scoring**: 2 pts marcador exacto, 1 pt el 1X2, **excluyente** (`get_leaderboard`
  cuenta exactos como `points_awarded = 2`). Desempate por **exactos**
  (`ORDER BY total_points DESC, exact_results DESC`).
- **Dinero**: $200 de inscripción + $50 por jornada jugada. El bote se reparte
  **80% al 1.º y 20% al 2.º** (`src/lib/ligaMxPricing.ts`).
- **Arranca en la J3**: J1 y J2 quedan como historial con 0 puntos
  (`counts_for_leaderboard = false`). Por eso `ingest.ligamx_pool --start-round 3`.

**Que el bote pague dos lugares cambia el objetivo.** El optimizador ya no
maximiza P(1.º) sino el **premio esperado** `0.8·P(1.º) + 0.2·P(2.º)`
(`QuinielaRules.prize_shares`, `model/pool_optimizer.py`). Importa de verdad: con
el 1.º fuera de alcance, maximizar P(1.º) es una función **plana en cero** — el
boleto se vuelve arbitrario — mientras que el 20% del bote sigue vivo y se puede
defender. El Mundial sigue en `(1.0,)` (winner-takes-all), así que su ruta no
cambia. El pool sin standings dimensiona el campo con `rules.pool_participants`
(15 en Liga MX), no con la constante de 30 del Mundial.

## Estrategia de pool: alcance vs colchón (brecha + horizonte)

`generate_picks --objective pool` ya no maximiza P(ganar este round) sino
**P(terminar 1.º del torneo)** (en Liga MX, el premio esperado — ver arriba). Lee `data/wc2026/pool_standings.json` (leaderboard
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
