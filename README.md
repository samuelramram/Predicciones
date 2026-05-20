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
llenan el resto. Ver `data/wc2026/rules.json` para las reglas exactas del pool.

| Archivo | Quién lo llena | Cuándo |
|---|---|---|
| `wc2026/rules.json` | Usuario | Una vez (al definir el pool) |
| `wc2026/teams.json` | Scraper / usuario | Una vez (post-draw, ya pasó) |
| `wc2026/venues.json` | Curado a mano | Una vez |
| `wc2026/fixtures.json` | Scraper Wikipedia | Una vez + actualizaciones de bracket |
| `wc2026/squads.json` | Transfermarkt / usuario | ~7 días antes del torneo (cuando FIFA confirma 26) |
| `wc2026/injuries.json` | Usuario + Perplexity | Antes de cada ronda |
| `historical/international_matches.csv` | Scraper martj42 | Bootstrap + actualización semanal |
| `historical/elo_history.csv` | Scraper eloratings.net | Bootstrap + actualización semanal |

---

## Cómo correr (Phase 0 — limpieza + esqueleto. Pipeline real arranca en Phase 1)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest                              # corre los tests del optimizer (los únicos hoy)
```

---

## Roadmap (3 semanas hasta el inicio del Mundial, 11 jun 2026)

- [x] **Phase 0** — Limpieza, archivo Liga MX en `legacy/`, esqueleto del paquete, EV optimizer
      + scorer + tests del optimizer.
- [ ] **Phase 1 (días 1-4)** — Ingesta. Bootstrap `international_matches.csv` (martj42),
      `elo_history.csv` (eloratings.net), `fixtures.json` (Wikipedia draw), `venues.json`
      (ya en seed). Validación de joins.
- [ ] **Phase 2 (días 3-7)** — Modelo base. MLE bivariate Poisson + Dixon-Coles sobre 2014-2026.
      Validación contra Mundial 2018 + 2022 + Euro 2024 + Copa América 2024.
- [ ] **Phase 3 (días 7-14)** — Mejoras. Squad strength (Elo de club × minutos), host advantage
      CONCACAF, fatiga viaje/altitud, blend con odds scrapeados.
- [ ] **Phase 4 (días 14-19)** — Calibración + EV. Brier, reliability curves, backtest del
      scorer sobre Mundiales anteriores, pipeline orchestrator.
- [ ] **Phase 5 (días 19-21)** — Picks fase de grupos lockeados, dashboard mínimo (CSV+MD),
      sistema de log post-ronda.

---

## Datos pendientes del usuario (no scrapeables)

1. **Reglamento oficial** completo del pool (deadline por ronda, bonos, desempate, distribución
   del premio). Llenar `data/wc2026/rules.json`.
2. **API-Football key** cuando estés listo a contratar (~$25/mes). Sin esto sigo con scraping.
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
