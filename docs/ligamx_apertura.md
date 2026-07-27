# Plan: adaptar el modelo a Liga MX Apertura

Documento de diseño para reusar este motor de quiniela (hoy cableado al Mundial
2026) en el **Apertura de Liga MX**. Objetivo del proyecto, según el usuario:

1. **Ganar la quiniela** del pool privado (webapp existente, league TheSportsDB `4350`).
2. **Sugerencias de apuestas de valor** — diversión y recuperar lo invertido en
   Claude, sin ludopatía: staking conservador, disciplina, medición honesta (CLV).

> Este doc es la fuente de verdad del plan. Cuando una corrección futura toque
> Liga MX, empieza por aquí: enumera qué se reusa, qué cambia, y los **puntos de
> acoplamiento** exactos que el refactor debe tocar.

---

## 1. Estado del proyecto (fases)

| Fase | Entregable | Estado |
|---|---|---|
| **0** | Doc de diseño + capa de perfil de liga + scaffolding de datos + `.md` | ✅ |
| **1a** | Datos alineados al webapp + **ingest real** (TheSportsDB 4350) → 1028 partidos de historial + calendario Apertura 2026 (153 fixtures) | ✅ |
| **1b** | Elo por replay + fit Poisson+DC + **picks por jornada** (`pipeline/ligamx.py`, localía por equipo + altitud diferencial) | ✅ este commit |
| **1b.2** | Odds de Liga MX en el blend (3 vías) + **backtest walk-forward** | ✅ este commit |
| **1c** | Liguilla a doble partido (marcador global + desempate) + proyección MC + **output HTML** | ✅ |
| **2** | Optimizador de pool con rivales reales (`--objective pool` + `ingest.ligamx_pool`) | ✅ este commit |
| **3** | Módulo de apuestas de valor (1X2 + O/U, ¼ Kelly, line-shopping) | ✅ este commit |

### Fase 1b.2 — odds + backtest (implementado)

- `ingest.ligamx_odds`: The Odds API `soccer_mexico_ligamx` (activo, ~23 casas,
  h2h + totals). Produce `odds_h2h.json` (1X2 devigado → 3.ª fuente del blend,
  55% mercado) y `odds_markets.json` (fair + mejor precio por casa para 1X2 y
  O/U → módulo de apuestas). Odds efímeras, gitignored; regenerar por jornada.
- `pipeline.ligamx_backtest`: walk-forward, refit por semana, sin look-ahead.
  **Resultado (347 partidos out-of-sample, calibración afinada): 0.646
  pts/partido vs 0.562 del baseline trivial "1-0" = +14.9%.** Es SIN odds — mide
  la skill base; en producción el mercado (55%) lo sube. El backtest ahora
  perfila rho por semana (misma ruta que producción) y puntúa los baselines
  sobre los MISMOS partidos que el modelo (antes se comparaba contra un conjunto
  desalineado, lo que inflaba/deflactaba el edge sin querer).
- **Calibración re-fiteada (Fase 1b.2)** contra el histórico real vía el
  backtest walk-forward (687 partidos oos, dos ventanas anuales disjuntas para
  descartar sobreajuste):
  - `goal_env_mult=1.0` — se confirma neutral: la liga rinde 2.84 g/partido y el
    fit predice ~2.86, se autocalibra (el 1.20 del Mundial corregía el
    sub-conteo de fase de grupos; aquí sobra). **TODO cerrado.**
  - `elo_home_bonus=100` (vs 80 default) y blend **60/40 Poisson/Elo** (vs
    70/30): la localía de Liga MX es fuerte (~47% gana el local + altitud) y más
    peso de Elo ayuda. 441 vs 434 pts / 72 vs 70 exactos oos. Re-correr el
    backtest tras nuevas jornadas para confirmar.
- **Bug corregido:** `ligamx picks` construía la matriz de marcadores con el rho
  default (−0.10) en vez del rho perfilado por `ligamx fit` (−0.05), degradando
  el componente de exacto (los 2 puntos). Ahora adopta el rho ajustado igual que
  `generate_picks` del Mundial (`effective_model_config`).

### Fase 1c — liguilla + proyección + output HTML (implementado)

- **Formato Apertura 2026** (cambió: desapareció el Play-In). Top-8 directo;
  cuartos 1-8/2-7/3-6/4-5; **semis resembradas por posición en la tabla general**
  (mejor vs peor, 2.º vs 3.º); todo ida y vuelta. Global empatado → avanza el
  mejor sembrado en cuartos y semis (sin extras); en la **final** hay tiempos
  extra y penales. El local mejor sembrado cierra en casa (vuelta).
- `model/liguilla.py` (puro): `compute_table` (tabla general con desempates
  puntos→DG→GF), siembra + cruces, `series_advance_prob` (convolución de las dos
  legs → distribución del global + regla de desempate), y `project_liguilla`
  (Monte-Carlo: simula el resto del rol → tabla → siembra → bracket → P(llegar a
  cada ronda)). 8 tests en `tests/test_liguilla.py`.
- **El pool puntúa cada leg a 90'**, así que una serie son dos picks normales
  (ida + vuelta) del mismo optimizador — no hubo que inventar scoring de global
  para los picks; el global solo decide el avance (contexto + proyección).
- Comandos: `ligamx picks --round quarter_final|semi_final|final` (bracket real
  de `data/ligamx/liguilla.json` si existe, si no el proyectado desde la tabla),
  y `ligamx liguilla --sims N` (proyección). Rutas de salida `.json/.md/.html`.
- **Output HTML** (`pipeline/ligamx_html.py`): página self-contained, theme-aware
  y mobile-first — el boleto como "ticket" impreso, medidor de EV, barra 1X2,
  chips de abstain/contrarian, barra de avance por serie, tabla de proyección con
  barras. Se publica como Artifact para que el usuario lo vea en claude.ai (el
  markdown de GitHub no le sirve). Es la pieza que faltaba de "verlo por acá".

### Mejoras de modelo de este ciclo (evidencia, no corazonada)

- **Half-life del fit**: se expuso `ModelConfig.half_life_days` y se barrió en el
  backtest walk-forward {365, 540, 730, 1095}d. **730d gana** (224 pts / +14.9%)
  sobre 365/540/1095 (222 / +13.8%). La intuición "planteles rotan → acorta" es
  falsa aquí: con ~1000 partidos de histórico, más data pesa más que la frescura.
  Se dejó 730d, documentado en el perfil. Re-barrer cuando entren más temporadas.
- **Contrarian**: antes maximizaba EV/p_outcome y **colapsaba al empate (1-1) en
  casi todos los partidos** (P(X) es el marginal más chico → siempre ganaba el
  ratio) — columna inútil. Ahora es el **mejor outcome alternativo real**
  (runner-up por EV): el resultado distinto más probable, con su sacrificio de EV
  como criterio de accionable. El leverage del empate sigue vivo donde importa: el
  optimizador de pool usa `alt_picks` (con la X incluida), no `contra_pick`.
- **xG**: evaluado y **descartado por ahora**. fbref da 403 tras el proxy; y con
  el mercado al 55% del blend (que ya es un modelo xG), el margen de xG sobre un
  modelo de goles bien calibrado es chico/redundante. Goles+odds gana en ROI. Vía
  futura si se quiere: API-Football como experimento medido con CLV, en su PR.

### Fase 2 — objetivo de pool (implementado)

`pipeline.ligamx picks --round jN --objective pool` optimiza el boleto para
**P(quedar 1.º del torneo)** en vez del EV por partido, reusando el optimizador
genérico (`model/pool_optimizer` + `model/standings`, los mismos del Mundial).

- Lee `data/ligamx/pool_standings.json` (brecha al líder, exactos, habilidad
  empírica) y, si existe, `data/ligamx/pool_picks.json` (picks REALES de los
  rivales → el campo se simula con sus boletos, no con humanos sintéticos).
- `total_matches` = partidos que la quiniela **realmente puntúa**, no el
  calendario entero. `ingest.ligamx_pool` lo calcula con `--start-round`
  (default 3: este pool arrancó en J3, así que J1-J2 nunca dan puntos) +
  `--liguilla-matches` (default 17: 3 reclasificación + 8 QF + 4 SF + 2 final).
  Contar los 153 del calendario completo (bug anterior) sobreestimaba el
  horizonte y sesgaba al optimizador a jugar demasiado conservador cerca del
  cierre. Con horizonte largo + brecha chica juega **EV** (tu ventaja se
  compone); con brecha grande + pocos partidos **arriesga** (swaps a
  contrarian). La decisión emerge de la mate.
- Sin los archivos degrada al objetivo de un solo round (igual que el WC).

**Datos del pool (RLS):** la tabla `predictions` del webapp revela las picks de
un rival **solo cuando el partido termina** — así que las picks de la jornada
que estás por jugar no son visibles para nadie hasta el cierre/reveal (correcto).
El leaderboard (de partidos ya jugados) sí es derivable. Flujo actual: exportar
los CSV por jornada de la app e ingerirlos con `ingest.ligamx_pool` (desacoplado
de Supabase, como el WC). Un pull directo del leaderboard de Supabase es una
mejora futura posible (solo lectura).

### Hechos confirmados en Fase 1a (leer antes de corregir)

- **Fuente de verdad de equipos/nombres** = el webapp `samuelramram/quinielacartoimagen`
  (`src/data/ligaMxApertura2026.ts` + migración Supabase). `data/ligamx/teams.json`
  usa esos nombres exactos (`name_es` como clave canónica).
- **Acceso a datos disponible**: el entorno tiene `THESPORTSDB_API_KEY` premium,
  `THE_ODDS_API_KEY` y `API_FOOTBALL_KEY`. El ingest (`ingest.ligamx`) ya corre
  contra la key premium y produce `matches_history.csv` + `fixtures.json`.
- **Elo NO viene de clubelo** — clubelo.com es HTTP puro y el proxy solo pasa
  HTTPS (connection reset). El Elo de clubes se computa por **replay** sobre
  `matches_history.csv` (reusa `ratings/elo.py`). `profile.elo_source =
  "replay_ligamx"`.
- **fbref/xG**: aún no cableado; el fit base arranca con goles de TheSportsDB.
  xG es una mejora de Fase 1b+.

### Atlante cold-start (decisión del usuario)

El Apertura 2026 mete a **Atlante** en lugar de Mazatlán. No es un ascenso
normal: es la **misma franquicia comprada a Mazatlán, que desaparece**, y
**arranca de cero** (sin continuidad de rating). En los datos:

- El historial (`matches_history.csv`) tiene a **Mazatlán** como oponente de
  temporadas pasadas y a **Atlante con 1 solo partido** (su J1 2026-2027).
- El fit debe tratar a Atlante como **equipo nuevo**: prior de fuerza =
  media de liga (o media − pequeño castigo de recién llegado), **varianza
  amplia**, para que las primeras jornadas lo muevan rápido. NO heredar el
  rating de Mazatlán. Implementar en Fase 1b (shrinkage con prior explícito
  para `cold_start=true` en `teams.json`).

Decisiones ya cerradas con el usuario:

- **Quiniela** = pool privado webapp (mismo scoring exacto/1X2 que el WC).
- **Apuestas** = módulo de **medición/valor** (no automatiza apuestas). Núcleo:
  Over/Under 2.5 + doble oportunidad. Books: Caliente / Betway. Referencia
  afilada: Pinnacle / línea de cierre.
- **Estructura** = perfil de liga sobre un **core común** (no duplicar paquete).

---

## 2. Qué se reusa y qué cambia

El motor es ~80% agnóstico al torneo. Cambia **dato y calibración**, no la mates.

| Se reusa casi intacto | Cambia para Liga MX |
|---|---|
| `model/poisson_dc.py` (MLE bivariate Poisson + DC) | Fuente: histórico de **clubes** (100+ partidos/equipo), no 3 de selecciones |
| `scoring/quiniela.py` (optimizador EV exacto+1X2) | Elo de **clubes** (clubelo.com) en vez de internacional |
| `model/pool_optimizer.py` + `pool_sim.py` (P(1.º) por MC) | Localía **por equipo** + altitud fuerte, no host-only |
| `model/blend.py` (log-pool Poisson+Elo+odds) | Formato: 17 jornadas + **liguilla** (ida/vuelta) en vez de grupos+bracket |
| `ingest/pool_picks.py` + `standings.py` (endgame del pool) | xG **sí** disponible (fbref) — el WC casi no lo tenía |
| `config.py` (dataclasses, fingerprint) | Sin host/mismatch/qual-J3 internacionales; sí home advantage por club |

**Ventaja estructural de Liga MX:** ~100+ partidos por equipo por torneo (vs 3
del WC) ⇒ el Poisson+DC se calibra muchísimo mejor. Y el legado
`legacy/ligamx_2026/` ya tenía shrinkage, bajas por rol y xG resueltos —
recuperar esos parámetros en Fase 1 en vez de empezar de cero.

---

## 3. Capa de perfil de liga (implementada en Fase 0)

`src/wc_predictor/leagues.py` — `LeagueProfile` bundlea todo lo que diverge:
ids, rutas, fuente de Elo, modo de localía, sport key de odds, tokens de ronda,
rondas a doble partido, y el `ModelConfig`/`QuinielaRules` calibrados.

Dos perfiles:

- `WC2026_PROFILE` — reproduce hoy byte-a-byte (usa los defaults intactos).
- `LIGAMX_APERTURA_PROFILE` — **neutraliza los knobs WC-only** vía
  `dataclasses.replace`:

  | Knob | WC | Liga MX | Por qué |
  |---|---|---|---|
  | `host_advantage_*` | 1.10–1.18 | **1.0** | Localía es por-equipo (entra vía gamma), no host |
  | `wc_lambda_inflation` | 1.12 | **1.0** | Liga MX ~2.53 g/partido, no ~2.81 de grupos WC |
  | `goal_env_mult` | 1.20 | **1.0** *(placeholder)* | Re-fit en Fase 1 al goal env real de Liga MX |
  | `mismatch_*` | activo | **off** *(placeholder)* | Calibrado con goleadas de selecciones; gaps intra-liga son menores |
  | `qual_rotation_lambda_mult` | 0.90 | **1.0** | Concepto de grupos; jornada regular no tiene tabla de grupo |
  | `altitude_penalty_per_1000m` | 0.04 | **0.04** *(mantener)* | Pesa **más** en Liga MX (Toluca 2660 m, Pachuca 2400 m) |

  Los marcados *(placeholder)* se **re-fitean en Fase 1** contra histórico real.

---

## 4. Datos Liga MX

| Qué | Fuente | Notas |
|---|---|---|
| Fixtures + live | TheSportsDB **4350** | Misma que la webapp → `match_id`/nombres consistentes |
| Histórico (fit) | TheSportsDB 4350 + fbref | 3-4 torneos atrás |
| xG | fbref | Mejora fuerte de λ; el legado tenía `fetch_fbref_stats.py` |
| Elo de clubes | **replay local** sobre `matches_history.csv` | clubelo es HTTP-only, inalcanzable tras el proxy; se computa con `ratings/elo.py` |
| Odds | The Odds API `soccer_mexico_ligamx` | Comparar Caliente/Betway; Pinnacle como precio justo |
| Bajas | manual + perplexity | Impactos por rol del legado |

Scaffolding versionado en `data/ligamx/` (`venues.json` con altitudes,
`teams.json`, `rules.json`, todos **template a verificar**).

---

## 5. Puntos de acoplamiento a refactorizar (Fase 1)

`pipeline/generate_picks.py` está cableado al WC. El refactor a core común +
perfil debe tocar exactamente esto (enumerado para eficientar la corrección):

1. **Rutas de datos** — `WC_DIR`, `_load_venues`, `_load_fixtures` hardcodean
   `data/wc2026/`. → leer de `profile.data_dir`.
2. **`resolve_round_filter`** — tokens `j1..j3`/`md1..md17`/KO del WC. → para
   Liga MX `j1..j17` + liguilla (`play_in`, `quarter_final` … a doble partido).
3. **Localía** — `_host_role` deriva host del país de la sede (venues neutrales).
   → Liga MX: el local es el equipo de casa siempre (`neutral_venues=False`,
   `home_advantage_mode="per_team"`); el boost entra vía la gamma del fit y la
   altitud de `venues.json` por equipo local.
4. **`apply_wc_lambdas`** (mismatch + wc_inflation) y el bloque `goal_env` — usar
   los valores del `profile.model` (neutralizados/placeholder para Liga MX).
5. **`build_j3_contexts` / `model/qualification.py`** — no aplica a jornada
   regular; el perfil lo deja inerte (`qual_rotation_lambda_mult=1.0`).
6. **Liguilla a doble partido** (`two_legged_rounds`) — NUEVO: modelar el
   marcador **global** (ida+vuelta) y la regla de desempate (gol de visitante si
   aplica / penales) para el scoring a 90'. Reusar el gate de empate KO del WC
   como base (`ko_draw_allow_min_prob`, `ko_exacto_ev_bonus`).
7. **Elo** — `pipeline/fit_elo` hace replay internacional; añadir ingest
   `clubelo` seleccionado por `profile.elo_source`.
8. **Rename físico** — mover `wc_predictor/{model,scoring,ratings}` a
   `core/` y `pipeline` a consumir `profile`. Hacerlo en su **propio commit**,
   con los 166+ tests como red, para no mezclar el rename con lógica nueva.

---

## 6. Módulo de apuestas de valor (Fase 3)

El modelo es un **modelo de goles** (λ_local, λ_visita → matriz Poisson
completa), así que cualquier mercado se deriva de ahí. Alcance v1, ordenado por
qué tan bien lo predice el modelo y qué tan blando suele estar el book:

| Mercado | Veredicto v1 | Por qué |
|---|---|---|
| **Over/Under 2.5** | ✅ núcleo | Directo de la matriz; el mejor calibrado; books blandos en Liga MX |
| **Doble oportunidad (1X/X2)** | ✅ núcleo | Baja varianza, hit-rate alto — ideal para "recuperar sin ludopatear" |
| **1X2** | ✅ selectivo | Ya lleva odds en el blend; edge fino, solo con edge >4% |
| Ambos anotan (BTTS) | 🟡 opcional | Correlaciona con Over; no apostar ambos a la vez |
| Hándicap asiático | 🟡 v2 | Derivable; menos vig, pero avanzado |
| Marcador exacto | 🟡 mini-stake | Edge real pero vig ~15-20%; solo simbólico |
| Combinadas / goleador / en vivo | ❌ evitar | Vig compuesto; requieren modelos que no tenemos |

**Disciplina (no negociable):**

- **Line-shopping** Caliente vs Betway; apostar en la que pague más.
- **Precio justo** = Pinnacle/línea de cierre sin vig. Si el edge desaparece
  contra la línea afilada, es error mío → no se apuesta.
- **Staking** = ¼ Kelly, tope duro 2% del bankroll por apuesta. Bankroll = costo
  de Claude; se **para al recuperarlo**.
- **CLV tracking** — cada sugerencia se registra vs la línea de cierre. CLV
  promedio positivo ⇒ el edge es real; si no, concentrarse en la quiniela (ahí
  compites contra 30 humanos, no contra un book con vig — tu ventaja real).

Diseño técnico: módulo `betting/value.py` (puro) + `pipeline/ligamx_bets.py`.
Compara la probabilidad **independiente** del modelo (Poisson+Elo, SIN odds en
el blend — si no, el modelo solo haría eco del mercado) vs el precio devigado
del book, y marca +EV con ¼-Kelly topado. Line-shopping: muestra el mejor
precio y la casa. Mercados: 1X2 + O/U 2.5 (los que el feed cotiza densamente).

**Honestidad de calibración (crítico):** el backtest dice que el modelo solo le
gana ~8% a un baseline trivial → **NO es más afilado que el mercado** (Brier del
mercado ≈0.23 vs modelo ≈0.55). Por eso un edge grande (≥8%) casi siempre es
**error del modelo, no valor** — el output lo advierte. El valor real del módulo
es la **medición** (registrar CLV a lo largo de la temporada para descubrir
empíricamente si algún mercado tiene edge), no apostar los edges crudos. La
ventaja de verdad está en la quiniela (30 humanos), no contra el book.

**Integración al boleto + ledger de CLV (hecho).** El boleto HTML incluye la
sección de apuestas partida en dos bandas: **valor jugable** (edge 3-8%) y **solo
medición ⚠** (edge ≥8%, casi siempre error del modelo). `betting/clv.py` +
`pipeline/ligamx_clv.py` implementan el ledger de closing-line-value (`log` →
`close` → `settle` → `report`, versionado en `data/ligamx/clv_ledger.json`):
- **CLV primario** = `precio_entrada / precio_cierre − 1` (ambos reales; mezclar
  precio vigado con prob. devigada sesga negativo siempre — bug evitado).
- **EV vs justa** (secundario) = `precio × prob_justa_cierre − 1`.
- Veredicto tras ≥10 cierres: CLV promedio > 0 ⇒ edge real; si no, a la quiniela.

**Mercados disponibles (hallazgo empírico):** el feed de Liga MX de The Odds API
(este plan) **solo cotiza `h2h` y `totals`**. `double_chance` y `btts` responden
`422 INVALID_MARKET` — requerirían el endpoint por-evento (más quota, cobertura
pobre). Así que el valor apostable vive en **1X2 y O/U 2.5**; la doble
oportunidad queda documentada como no disponible vía esta API.

---

## 7. Riesgos / notas

- **Realismo de apuestas:** el modelo le gana ~6% a un baseline trivial en
  quiniela; el edge sobre un book afilado es fino. Tratar apuestas como
  **medición**, no ingreso. La ventaja de verdad está en la quiniela.
- **Liguilla ida/vuelta** es la pieza genuinamente nueva (el WC es a partido
  único). No subestimar el modelado del global + desempate.
- **Verificar datos template** de `data/ligamx/` antes de picks reales.

---

## 8. Auditoría "¿algo mejorable para ganar?" (jul 2026)

Revisión del motor contra el reglamento REAL del pool y contra los datos. Tres
cosas cambiaron, una se probó y se descartó.

### 8.1 El bote paga 80/20 — el objetivo era el equivocado

`src/lib/ligaMxPricing.ts` reparte **80% al 1.º y 20% al 2.º**, pero
`pool_optimizer` maximizaba P(rank=1) y trataba el 2.º como **cero** (literal en
su docstring: *"want when you only get paid for rank 1"*). Dos consecuencias
reales, ambas caras:

- Yendo atrás al final, el optimizador cambiaba un 2.º casi seguro por un 1.º
  improbable — negativo en dinero.
- Con el 1.º ya inalcanzable, P(1.º) es **plana en cero**: sin gradiente, el
  boleto quedaba a merced del desempate por exactos. En un escenario de prueba
  hacía **5 swaps arbitrarios**; con premio esperado hace 1, dirigido.

Ahora el objetivo es `sum_r prize_shares[r]·P(rank=r+1)`
(`QuinielaRules.prize_shares`, Liga MX `(0.8, 0.2)`, Mundial `(1.0,)`). La sim
guarda las **top-K puntuaciones distintas del campo con su multiplicidad** — lo
justo para ubicarte exacto entre los lugares que pagan, empates incluidos
(`_placement_share`). Con `(1.0,)` el objetivo ES P(1.º), así que la ruta del
Mundial no se mueve. Tests en `tests/test_prize_objective.py`.

También: sin `pool_standings.json` el campo sintético se dimensionaba con 29
rivales (número del Mundial). Ahora sale de `rules.pool_participants` (15).

### 8.2 La liguilla corría con calibración de rol regular

`pipeline/ligamx.py` aplicaba solo `draw_allow_min_prob`; los tres knobs de
eliminatoria vivían únicamente en `generate_picks.py` (Mundial). Antes de
copiarlos por fe, se midieron con datos de Liga MX — para lo cual hubo que
arreglar el ingest, que **tiraba el `intRound`** de TheSportsDB.

Con `round` + `stage` en `matches_history.csv` (y `annotate_stages` rellenando
las liguillas que el feed manda sin ronda — sin eso solo se recuperan 44 de 99):

| | n | goles/partido | empates | local gana |
|---|---|---|---|---|
| rol regular | 936 | 2.860 | 23.9% | 46.8% |
| **liguilla** | 99 | **2.576** | **32.3%** | 49.5% |

Ratio de goles **0.9006**, prácticamente idéntico al `ko_goal_env_ratio=0.90` que
el Mundial calibró por su cuenta. Los legs de liguilla ahora corren con
`liguilla=True` (λ amortiguada + gate `ko_draw_allow_min_prob` + desbloqueo por
marcador modal + tilt de exactos), y la proyección Monte-Carlo usa matrices de
playoff para el bracket y de rol regular para lo que queda de temporada.

**A/B out-of-sample (honesto): la ganancia en puntos es ruido.** Con
`ligamx_backtest --since 2024-07-01 [--no-liguilla-calibration]`, sobre los 65
partidos de playoff que caen en la ventana:

| calibración de los legs | pts | p/p | exactos |
|---|---|---|---|
| rol regular (antes) | 43 | 0.662 | 9 |
| playoff (nueva) | **44** | 0.677 | 9 |

**+1 punto en 65 partidos** — dentro del ruido, no una mejora demostrada. Lo que
justifica el cambio es la **medición del entorno** (2.576 vs 2.860 goles y 32.3%
vs 23.9% de empates son diferencias grandes sobre 99 partidos), no este delta. La
calibración es correcta por construcción y no cuesta nada, pero **no esperes que
mueva la aguja del marcador**. Re-correr el A/B cuando haya más liguillas en la
ventana: 65 partidos no alcanzan para distinguir +1 de 0.

### 8.3 `rules.json` dejó de ser plantilla

Verificado contra la app: scoring 2/1 excluyente ✓, desempate por exactos ✓,
arranque en J3 ✓, $200 + $50/jornada, reparto 80/20. Queda por confirmar el
deadline de captura y **si la liguilla puntúa en la misma tabla `ligamx`** — eso
define el horizonte real que consume `--liguilla-matches`.

### 8.4 Descartado con evidencia: el gate de empate del rol regular

`draw_allow_min_prob = 0.42` (heredado de fase de grupos del Mundial) parecía un
bug obvio: el P(X) del blend **nunca pasa de 0.298** en los 135 partidos
pendientes, o sea la X es inalcanzable, y el **1-1 es el marcador más común de
Liga MX** (12.2%, arriba del 1-0 con 10.1%).

Pero no cuesta nada: bajando el gate a 0.38/0.34/0.32/0.30/0.28 el backtest
walk-forward da **229 pts / 35 exactos idénticos en los seis casos**, y el boleto
de los 135 pendientes no cambia ni un partido. La X nunca gana por EV contra el
lado ganador, y `alt_picks` ya se la ofrece al optimizador de pool aunque esté
vetada para el pick EV. **No tocar** — el gate solo importa en liguilla, donde
ya se bajó por la vía de 8.2.

### 8.5 Lo que queda sin explotar

- **`pool_standings.json` / `pool_picks.json` no existen.** Toda la Fase 2 está
  construida y sin combustible: `--objective pool` degrada al objetivo de un
  round. Ahora mismo empata con EV (el pool arranca en J3, todos en cero), pero
  las tasas empíricas `e`/`q` necesitan historial — hay que exportar e ingerir
  **cada jornada desde la J3**, no a mitad de temporada.
- **Alineaciones y bajas.** `API_FOOTBALL_KEY` está en el entorno y la app ya
  tiene cron de lineups, pero el modelo ignora la disponibilidad de jugadores.
  Es la única fuente que el mercado (55% del blend) podría no tener incorporada
  a la hora de capturar. Proyecto, no parche, y con payoff incierto.
