# Predicciones Mundial 2026 — Modelo de Quiniela

Modelo probabilístico para ganar una quiniela del **Mundial FIFA 2026** (USA · Canadá · México).
Scoring de la quiniela: **2 puntos por marcador exacto, 1 por resultado 1X2** (excluyente, solo 90 min).

> Estado: **rebuild en marcha (mayo 2026)**. Modelo base Poisson + Dixon-Coles del proyecto Liga MX
> archivado en `legacy/ligamx_2026/` y reusado donde aplica.

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
python -m wc_predictor.pipeline.fit_model                         # fit Poisson + Dixon-Coles
python -m wc_predictor.pipeline.generate_picks --round group_stage
python -m wc_predictor.pipeline.backtest                          # validación 5 torneos
python -m wc_predictor.pipeline.simulate_pool                     # simulación de pool 30 personas
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
pytest                              # 55 tests (optimizer, fit, Elo, blend, ingest, calibration)
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
- [ ] **Pendiente (mayor ROI)** — odds de cierre (requiere `THE_ODDS_API_KEY`, código listo en
      `ingest.fetch_odds`), squad strength (jfjelstul/worldcup), y el loop en vivo
      (ingerir scores J1/J2 → refit → J3).

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
