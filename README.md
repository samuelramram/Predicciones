# Predicciones Mundial 2026 — Modelo de Quiniela

Modelo probabilístico para ganar una quiniela del **Mundial FIFA 2026** (USA · Canadá · México).
Scoring de la quiniela: **2 puntos por marcador exacto, 1 por resultado 1X2** (excluyente, solo 90 min).

> Estado: **rebuild en marcha (mayo 2026)**. Modelo base Poisson + Dixon-Coles del proyecto Liga MX
> archivado en `legacy/ligamx_2026/` y reusado donde aplica.
>
> **Nuevo (Fase 0):** este motor se está adaptando para el **Apertura de Liga MX**
> (quiniela + apuestas de valor). Plan completo y estado por fases en
> [`docs/ligamx_apertura.md`](docs/ligamx_apertura.md). La capa de perfil de liga
> vive en `src/wc_predictor/leagues.py` y el scaffolding de datos en `data/ligamx/`.

---

## Objetivo y restricción de optimización

La quiniela paga `2 pts` por acertar el marcador exacto **o** `1 pt` por acertar 1X2 (sin sumar
ambos). No paga el modal — paga lo que maximiza esperanza de puntos. El modelo no elige el
marcador más probable: elige el par `(1X2, exacto)` con mayor **valor esperado de puntos**:

```
EV(pick) = points_exact · P(exacto) + points_1x2 · (P(1X2) − P(exacto))    # caso excluyente
```

donde `P(exacto)` y `P(1X2)` salen de una grilla bivariada Poisson + corrección Dixon-Coles
para empates de marcador bajo. Si el gap entre el mejor y el segundo mejor candidato es chico,
el modelo levanta una bandera **ABSTAIN** (señal de que la diferencia entre picks no es informativa).

El bloque que define todo esto vive en `src/wc_predictor/scoring/quiniela.py` y está
parametrizado por `QuinielaRules` — si cambian las reglas del pool, se cambia un dataclass.

---

## Arquitectura

```
src/wc_predictor/
├── config.py           # Hiperparámetros + reglas del pool (single source of truth)
├── ingest/
│   ├── fixtures.py     # Calendario 2026 (104 partidos)
│   ├── matches.py      # Histórico internacional 2014→hoy (martj42/international_results)
│   ├── elo.py          # Snapshots eloratings.net
│   ├── squads.py       # Convocatorias 26 jugadores
│   └── odds.py         # Scrape best-effort de cierre de bookmakers
├── ratings/
│   └── elo.py          # Update Elo internacional (K por etapa, GD multiplier)
├── model/
│   ├── poisson_dc.py   # MLE bivariate Poisson + Dixon-Coles
│   ├── blend.py        # Log-pool de Poisson + Elo + odds
│   └── adjustments.py  # Host advantage, altitud (CDMX), fatiga, bajas
├── scoring/
│   └── quiniela.py     # EV optimizer + scorer pool-of-truth
├── pipeline/
│   └── generate_picks.py  # Entry-point por ronda
└── utils.py            # Hashes, git introspection
```

### Diferencias vs el modelo Liga MX (lo que cambia)

| Componente | Liga MX (viejo) | Mundial 2026 (nuevo) |
|---|---|---|
| Cobertura de partidos | 1 liga, 18 equipos | 48 selecciones, ~10 confederaciones |
| Datos por equipo | 100+ partidos por torneo | 3 de grupos, luego 1+ por ronda |
| Calibración cross-equipos | Misma liga, fácil | Cross-confederation — requiere Elo internacional |
| Home advantage | Por equipo | Solo aplica a anfitriones (USA/MEX/CAN) y altitud CDMX |
| xG | xgscore.io | Solo en torneos top (Euro, WC). Friendlies y qualifiers pocas veces |
| Bajas | Manual por jornada | Manual + Transfermarkt scrape post-roster announcement |
| Mercado | No usado | **Sí** — odds de cierre como tercer source del blend |
| Rondas | 17 jornadas regulares | 8 rondas (3 grupos + 5 eliminatorias) |

### Lo que se mantiene del modelo Liga MX

- **Grilla Poisson adaptativa** (target captured mass 99.5%, grilla 5-12).
- **Dixon-Coles ρ = -0.10** para empates bajos.
- **EV optimizer** con candidato por outcome (1, X, 2) y elección por max EV + flag de gap.
- **Shrinkage bayesiano** (re-parametrizado para internacionales: prior = Elo + confederación;
  data = últimos N partidos del equipo).
- **Fingerprint SHA-256** de inputs/outputs y `config_hash` para reproducibilidad por corrida.

---

## Datos (fuente de verdad humana, versionados)

Todo en `data/wc2026/` y `data/historical/`. El usuario llena los campos `TBD`; los scrapers
llenan el resto. Ver `data/wc2026/rules.json` para las reglas exactas del pool + las APIs.

| Archivo | Quién lo llena | Fuente | Cuándo |
|---|---|---|---|
| `wc2026/rules.json` | Usuario | manual | Una vez (al definir el pool) |
| `wc2026/teams.json` | Scraper | openfootball/worldcup.json | Una vez (post-draw) |
| `wc2026/venues.json` | Manual | FIFA | Una vez |
| `wc2026/fixtures.json` | **`ingest.openfootball`** | openfootball + martj42 (scores) | Bootstrap + cada ronda |
| `wc2026/squads.json` | Scraper + usuario | Transfermarkt | ~7 días antes del torneo |
| `wc2026/injuries.json` | Usuario | Perplexity + manual | Antes de cada ronda |
| `historical/international_matches.csv` | **`ingest.martj42`** | martj42/international_results | Bootstrap + semanal |
| `historical/elo_history.csv` | TODO Phase 2 | replay propio sobre martj42 | Bootstrap |

### Cómo correr el pipeline

**Un solo comando (recomendado)** — orquesta ingesta → Elo → fit → picks:

```bash
python -m wc_predictor.pipeline.run --round md1
python -m wc_predictor.pipeline.run --round round_of_32 --skip-fetch
```

`--round` acepta: `all`, `group_stage`, `md1`..`md17`, `round_of_32`, `round_of_16`,
`quarter_final`, `semi_final`, `third_place`, `final`. `--skip-fetch` omite la descarga
de red (re-corre con los datos ya en `data/raw/`).

**Por etapas (debug / desarrollo):**

```bash
python -m wc_predictor.ingest.martj42 --bootstrap --refetch       # histórico training
python -m wc_predictor.ingest.openfootball --bootstrap --refetch  # 104 fixtures WC2026
python -m wc_predictor.ingest.fetch_odds                          # odds: snapshot único (opcional)
python -m wc_predictor.pipeline.snapshot_odds                     # odds: closing line (recomendado, ver abajo)
python -m wc_predictor.ingest.api_football                        # lesiones API-Football (opcional, requiere plan Pro)
python -m wc_predictor.pipeline.fit_elo                           # replay Elo internacional
python -m wc_predictor.pipeline.fit_model                         # fit Poisson + DC (perfila rho; --no-fit-rho para el viejo -0.10)
python -m wc_predictor.pipeline.generate_picks --round group_stage
python -m wc_predictor.pipeline.backtest                          # validación 5 torneos
python -m wc_predictor.pipeline.simulate_pool                     # simulación de pool 30 personas
python -m wc_predictor.pipeline.tune_odds_weight --round j1       # afina blend_odds_weight tras una jornada jugada
```

**Odds de bookmakers (opcional pero recomendado):** el mercado es el predictor individual
más fuerte. API recomendada: **The Odds API, v4** (sport key `soccer_fifa_world_cup`,
mercado `h2h` = 1X2, regiones `eu,uk` para libros afilados como Pinnacle). Es la única
con buena cobertura de **selecciones** — football-data.co.uk es solo clubes. Consigue una
key gratis en [the-odds-api.com](https://the-odds-api.com/) (500 créditos/mes, sin tarjeta),
ponla en `.env` como `THE_ODDS_API_KEY=...`. El modelo pasa automáticamente a un blend de
3 vías (Poisson + Elo + odds). Sin key, cae al blend de 2 vías — backtesteado y funcional.

Dos modos de captura:

- **`ingest.fetch_odds`** — snapshot único de las cuotas *actuales*. Rápido para probar.
- **`pipeline.snapshot_odds`** (recomendado) — captura la **closing line**, el predictor de
  verdad. El endpoint solo da la cuota del momento, así que este comando se corre en un cron
  ~10 min antes del primer kickoff de cada jornada y, por partido, guarda el último snapshot
  tomado *antes* del arranque (lo congela una vez empieza). `generate_picks` prefiere esta
  tienda de closing line sobre el snapshot único de forma automática.

```bash
# cron Jun–Jul 2026: 10 min antes de los kickoffs típicos 12:00Z y 19:00Z
50 11 * 6,7 *  cd /ruta/Predicciones && python -m wc_predictor.pipeline.snapshot_odds
50 18 * 6,7 *  cd /ruta/Predicciones && python -m wc_predictor.pipeline.snapshot_odds
```

> Nota: el odds blend NO está backtesteado — no existe un dataset gratuito de odds
> históricas de selecciones. El peso de las odds (55%) es un default basado en literatura
> (las cuotas de cierre son casi eficientes). Se puede afinar con el endpoint histórico de
> The Odds API (10 créditos por región·mercado) una vez haya key.

**Fuentes verificadas y usadas:**
- [`martj42/international_results`](https://github.com/martj42/international_results) (CC0) —
  49k partidos internacionales 1872→hoy, daily updated. Backbone del training set y del
  feed de scores cuando los partidos del Mundial se vayan jugando.
- [`openfootball/worldcup.json`](https://github.com/openfootball/worldcup.json) (CC-by-SA) —
  los 104 fixtures completos con grupos oficiales del sorteo FIFA, kickoff times con tz,
  placeholders de bracket (`1A`, `2B`, `3A/B/C/D/F`, `W89`, `L101`).

**Fuentes identificadas para fases siguientes (no integradas aún):**
- [`statsbomb/open-data`](https://github.com/statsbomb/open-data) (CC-BY-NC-SA) — xG, eventos
  con coordenadas y freeze frames para Mundiales 1958, 62, 70, 74, 86, 90, 2018, 2022.
  Único xG público real de Mundiales completos. Phase 2/3.
- [`jfjelstul/worldcup`](https://github.com/jfjelstul/worldcup) (CC-BY-SA 4.0) — squads + IDs
  + tournaments 1930-2022. Phase 3 para prior de fuerza de plantilla.
- TheSportsDB league 4429 — para mantener `match_id` consistente con la webapp en producción.

### Integración con la webapp (Lovable Cloud / Supabase)

El **modelo y la webapp son repos separados**. Este repo es el arma personal del autor
para generar SUS picks; la webapp gestiona los 30 participantes del pool.

- La webapp ya consume TheSportsDB (league `4350` para Liga MX, `4429` para WC). Este
  modelo usa la **misma fuente** para fixtures y live results → `match_id` y nombres
  de equipo son consistentes entre los dos sistemas.
- El modelo escribe `outputs/picks_{round}.json` con el shape del schema Supabase
  (`match_id`, `prediction_home`, `prediction_away`). El usuario los importa a mano a
  la webapp como un participante más.
- Sin conexión directa Python ↔ Supabase: cero riesgo de que el modelo escriba algo
  raro a la base que ven todos los usuarios.
- Recomendación para la webapp WC 2026: **proyecto Lovable separado** del de Liga MX
  (clonar + cambiar `LEAGUE_ID` a `4429`), no refactor multi-torneo. Pre-Mundial no
  hay tiempo para reorganizar tablas + RLS.

### Variables de entorno

Copia `.env.example` → `.env` (gitignored) y llena las que vayas a usar:

```
THESPORTSDB_API_KEY=...     # primaria — misma key del Patreon de la webapp
API_FOOTBALL_KEY=...        # opcional, solo si haces upgrade
THE_ODDS_API_KEY=...        # opcional, solo si pagas odds programáticos
```

Sin ninguna de las opcionales, el modelo cae a fallbacks (scrape de Wikipedia / odds
de football-data.co.uk / etc.).

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest                              # 173 tests (optimizer, fit, Elo, blend, ingest, calibration, league profiles)
```

---

## Roadmap (Mundial arranca el 11 jun 2026)

- [x] **Phase 0** — Limpieza, archivo Liga MX en `legacy/`, esqueleto del paquete, EV optimizer.
- [x] **Phase 1** — Ingesta. `ingest.martj42` (11.7k partidos histórico) + `ingest.openfootball`
      (104 fixtures WC2026, grupos A-L oficiales, placeholders de bracket).
- [x] **Phase 2** — Modelo base. MLE Poisson + Dixon-Coles. Replay Elo internacional
      (49k partidos). Bivariate Poisson probado (λ₃≈0 → no aporta, independent Poisson confirmado).
- [x] **Phase 3.1** — Elo blend. `blend_w30_ev_no_draw` (30% Elo + 70% Poisson, sin empates).
- [x] **Phase 4** — Validación. Backtest sobre WC 2014/18/22 + Euro 2024 + Copa América 2024
      (275 partidos). Calibración Brier + log-loss. Orquestador `pipeline.run`. CLI por ronda.
      El backtest ahora lee el CSV **versionado** `data/historical/international_matches.csv`,
      así que `python -m wc_predictor.pipeline.backtest` reproduce estos números desde un clon limpio.
- [x] **Phase 3.2** — Adjustments conectados: **host advantage** (USA/MEX/CAN) y **altitud**
      (Estadio Azteca 2240 m) ya alteran las lambdas vía `model.adjustments.apply_context_adjustments`.
      Travel y bajas quedan cableados pero en no-op hasta que se llenen sus feeds
      (`data/wc2026/injuries.json`).
- [x] **Phase 5** — Optimización de pool: `generate_picks --objective pool` cierra el loop con
      `model.pool_sim` y elige el boleto que maximiza **P(quedar #1)** en vez del EV individual.
- [x] **Calibración (jun 2026)** — ρ Dixon-Coles ajustado a datos, peso por competición
      en el fit (refuerza el loop en vivo J1/J2 → J3), y afinador del peso de odds contra
      la línea de cierre. Ver "Mejoras de calibración (junio 2026)".
- [x] **Endgame de pool (jul 2026)** — `ingest.pool_picks` ingiere los CSV exportados de la
      webapp: picks REALES de todos los participantes (`pool_picks.json`), leaderboard con
      exactos (`pool_standings.json`) y resultados a 90' mergeados a `fixtures.json` (fuente
      de verdad para eliminatorias — martj42 registra el marcador con tiempo extra). El pool
      optimizer ahora simula el campo con los boletos capturados, gana por la regla real del
      leaderboard `(puntos, exactos)` y puede moverse a cualquier outcome por partido
      (incluida la X). Calibración KO: `ko_draw_allow_min_prob=0.33` (la X se desbloquea en
      eliminatorias, ~25-35% terminan empatadas a 90') y `ko_goal_env_ratio=0.90` (amortigua
      la inflación de goles calibrada con fase de grupos).
- [x] **Empates en KO (jul 2026)** — el talón de Aquiles del boleto R32 (los fallos fueron
      empates a 90'): (1) en eliminatorias la X también se desbloquea cuando el marcador
      MODAL del blend es empate con P(X) ≥ `ko_modal_draw_min_prob=0.30` (las gates de
      probabilidad eran inalcanzables con odds al 55%); (2) el ranking de candidatos usa
      `ko_exacto_ev_bonus=0.5` — EV con peso efectivo del exacto 2.5, porque el leaderboard
      desempata por exactos y sin el tilt el EV puro nunca aterriza en la X modal. Solo KO:
      en 204 partidos de grupos históricos (WC14/18/22+Euro/Copa24) ambas palancas RESTAN
      puntos; en los 13 R32 resueltos a 90' suman (14 pts/4 exactos → 16/5). Además el
      greedy del pool optimizer desempata swaps de P(1.º) plana por exactos esperados, y
      `ingest.pool_picks` valida el "Resultado Real" contra los puntos de la app e infiere
      el marcador de 90' cuando la app muestra el score con tiempo extra (caso
      Bélgica-Senegal: mostraba 3-2, pagó sobre 2-2).
- [ ] **Pendiente (mayor ROI)** — squad strength (jfjelstul/worldcup); usar el mercado de
      totales (over/under) para calibrar el λ total por partido en vez del multiplicador
      global `goal_env_mult`.

### Mejoras de calibración (junio 2026)

Tres cambios para exprimir más puntos del blend, todos con tests en
`tests/test_improvements.py`:

1. **Dixon-Coles ρ ajustado a datos internacionales.** ρ se heredó como `-0.10`
   del modelo Liga MX y nunca se re-ajustó. `fit_model` ahora lo **perfila por
   verosimilitud penalizada** sobre los ~12k internacionales (grilla
   `[-0.25, +0.05]`) y persiste el ganador en `team_strengths.json`;
   `generate_picks` lo honra vía `dataclasses.replace` (antes el ρ guardado se
   ignoraba al construir la grilla de marcadores — un bug latente, ya que la forma
   del marcador exacto, la mitad de los puntos de la quiniela, depende de ρ). El
   fit actual cae en **ρ ≈ -0.05**. `--no-fit-rho` reproduce el comportamiento viejo.

2. **Peso por competición en el fit Poisson+DC.** La recencia exponencial pesaba
   igual un amistoso y un partido de Mundial de la misma antigüedad.
   `competition_weight_*` (amistoso 1.0 < eliminatoria 1.5 < torneo 2.0 < Mundial
   3.0) multiplica el peso de recencia según la competición, de modo que, una vez
   arrancado el torneo, los resultados de J1/J2 **sí mueven** las fuerzas de cara a
   J3 (el loop de refit en vivo) en lugar de quedar ahogados por años de amistosos.

3. **Afinador del peso de odds (`pipeline.tune_odds_weight`).** `blend_odds_weight`
   (0.55) era un default de literatura nunca medido (no hay odds históricas de
   selecciones). Tras cada jornada jugada, este comando empareja la **línea de
   cierre congelada** con el resultado real y, para una grilla de pesos, reproduce
   el blend de producción reportando **puntos de quiniela** (lo que importa) y
   calibración Brier/log-loss; recomienda el peso óptimo vs el de config. Antes del
   torneo (ningún partido liquidado) degrada a un no-op limpio — seguro de cablear
   a un cron post-jornada.

### Resultado del backtest (275 partidos, 5 torneos)

Reproducible: `python -m wc_predictor.pipeline.backtest` → `outputs/backtest_summary.md`.

| Estrategia | Total | Pts/match |
|---|---:|---:|
| **`blend_w35_ev_no_draw`** (mejor del sweep) | **195** | **0.71** |
| `blend_w30_ev_no_draw` (producción) | 194 | 0.71 |
| `always_1_0` (baseline trivial) | 184 | 0.67 |
| `ev_optimal` (modelo Phase 2, permite empates) | 171 | 0.62 |
| `modal_poisson` | 138 | 0.50 |

Ventaja sobre el baseline trivial: **+6%** (194 vs 184). Es real pero modesta —
el predictor de mayor impacto sigue apagado: **las odds de cierre** (mercado Brier
≈0.23 vs modelo ≈0.60). Calibración del modelo (agregado 275 partidos): Brier ≈0.60
(random uniforme 0.667). Prender las cuotas es lo más barato y de mayor ROI pendiente.

---

## Datos pendientes del usuario (no scrapeables)

1. **Reglamento oficial** completo del pool (deadline por ronda, bonos, desempate, distribución
   del premio). Llenar `data/wc2026/rules.json`.
2. **API-Football — upgrade a plan de pago** (~$19/mes Pro). La key ya está en `.env` y el
   módulo `ingest.api_football` está listo; el plan Free bloquea la temporada 2026, así que
   la ingesta de lesiones se activa sola al hacer el upgrade (sin tocar código).
3. **Bajas de última hora** por ronda (perplexity + manual). Llenar `data/wc2026/injuries.json`.
4. **Sesgo personal** opcional ("siempre quiero a México pase lo que pase") — se mete como
   override controlado, no como entrada al modelo.

---

## Política de versionado de datos

- **Sí se versiona:** `data/wc2026/*.json`, `data/historical/*.csv` (fuente de verdad).
- **No se versiona:** `data/raw/`, `data/processed/`, `outputs/` (intermedios y outputs grandes).

---

## Convenciones de commits

```
feat(ingest): bootstrap historical international matches dataset
feat(model): MLE fit for Poisson + DC params
fix(scoring): correct EV formula for non-exclusive pool variant
data(wc2026): update Group A teams post-draw
docs: explain blend weight reweighting when odds missing
```

---

## Licencia

Uso personal.
