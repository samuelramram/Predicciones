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
| **1c** | Liguilla a doble partido (marcador global + desempate) | pendiente |
| **2** | Optimizador de pool con rivales reales (`--objective pool` + `ingest.ligamx_pool`) | ✅ este commit |
| **3** | Módulo de apuestas de valor (O/U + doble oportunidad, ¼ Kelly, CLV) | pendiente |

### Fase 1b.2 — odds + backtest (implementado)

- `ingest.ligamx_odds`: The Odds API `soccer_mexico_ligamx` (activo, ~23 casas,
  h2h + totals). Produce `odds_h2h.json` (1X2 devigado → 3.ª fuente del blend,
  55% mercado) y `odds_markets.json` (fair + mejor precio por casa para 1X2 y
  O/U → módulo de apuestas). Odds efímeras, gitignored; regenerar por jornada.
- `pipeline.ligamx_backtest`: walk-forward, refit por semana, sin look-ahead.
  **Resultado (347 partidos out-of-sample): 0.611 pts/partido vs 0.565 del
  baseline trivial "1-0" = +8.2%** (comparable al +6% del Mundial). Es SIN odds
  — mide la skill base; en producción el mercado (55%) lo sube.
- Calibración a datos LMX (`goal_env_mult`, gate de empate): pendiente de afinar
  con más jornadas jugadas; los defaults del perfil son un punto de arranque.

### Fase 2 — objetivo de pool (implementado)

`pipeline.ligamx picks --round jN --objective pool` optimiza el boleto para
**P(quedar 1.º del torneo)** en vez del EV por partido, reusando el optimizador
genérico (`model/pool_optimizer` + `model/standings`, los mismos del Mundial).

- Lee `data/ligamx/pool_standings.json` (brecha al líder, exactos, habilidad
  empírica) y, si existe, `data/ligamx/pool_picks.json` (picks REALES de los
  rivales → el campo se simula con sus boletos, no con humanos sintéticos).
- `total_matches` = tamaño del calendario (153 en regular). Con horizonte largo
  + brecha chica juega **EV** (tu ventaja se compone); con brecha grande + pocos
  partidos **arriesga** (swaps a contrarian). La decisión emerge de la mate.
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

Diseño técnico: módulo nuevo `betting/` (sin dependencia del pipeline de
quiniela): `devig()`, `edge()`, `kelly_fraction()`, `bankroll.py`, `clv.py`.
Reusa la matriz de marcadores que ya produce `scoring/quiniela.build_score_matrix`.

---

## 7. Riesgos / notas

- **Realismo de apuestas:** el modelo le gana ~6% a un baseline trivial en
  quiniela; el edge sobre un book afilado es fino. Tratar apuestas como
  **medición**, no ingreso. La ventaja de verdad está en la quiniela.
- **Liguilla ida/vuelta** es la pieza genuinamente nueva (el WC es a partido
  único). No subestimar el modelado del global + desempate.
- **Verificar datos template** de `data/ligamx/` antes de picks reales.
