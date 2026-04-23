# Predicciones Liga MX — Modelo de Quiniela

Modelo probabilístico de predicciones para la quiniela de Liga MX.
Optimiza directamente el **valor esperado de puntos** bajo scoring de
quiniela: **2 puntos por marcador exacto + 1 punto por resultado 1X2**.

> Estado: Clausura 2026, última jornada procesada **J10** (5 de marzo, 2026).
> Próxima corrida: sincronizar datos hasta jornada actual antes de generar predicciones.

---

## ¿Qué hace el modelo?

Para cada partido de una jornada, el pipeline calcula:

1. **λ_home / λ_away** — goles esperados de cada equipo (distribución Poisson bivariada).
2. Corrección **Dixon-Coles** (ρ negativo) para empates de marcador bajo.
3. **P(1), P(X), P(2)** y matriz completa de marcadores con grilla Poisson adaptativa.
4. **Optimizador de pick por EV de quiniela**: elige el par `(resultado 1X2, marcador exacto)`
   que maximiza `EV = P(exacto) + P(resultado 1X2)` — no solo el marcador más probable.
5. Flag de **ABSTAIN** si el gap entre candidatos es muy chico (baja confianza).

Salida principal: `outputs/predicciones_jornada_{N}_final.csv` + reporte técnico markdown.

---

## Arquitectura

```
src/predicciones/
├── config.py        # Hiperparámetros + alias canónicos de equipos
├── core.py          # Canonicalización, build de stats, shrinkage bayesiano,
│                    # blend multi-torneo, cómputo de lambdas
├── data.py          # Ingesta de inputs manuales (stats, bajas, cualitativa)
│                    # + penalizaciones por jugadores clave
├── improvements.py  # Momentum, home-crisis/stronghold, rivalry factor
├── quiniela.py      # Poisson + Dixon-Coles + optimizador de pick por EV
└── utils.py         # Cacheo, helpers

app/steps/
├── diagnostico_lambda.py    # Paso 1: calcula y exporta λ y componentes
├── gen_predicciones.py      # Paso 2: corre optimizador → CSV final
└── gen_reporte_tecnico.py   # Paso 3: reporte markdown por jornada

scripts/
├── evaluate_model.py        # Backtest + log-loss + anti-leakage audit
├── fetch_fbref_stats.py     # Scraper de FBref (semi-auto)
├── update_key_players_data.py
└── ... (utilidades de ingesta y debug)

run_pipeline.py              # Orquesta los 3 pasos de app/steps/
```

### Componentes clave del cálculo de λ

| Componente | Descripción |
|---|---|
| **Priors multi-torneo** | Clausura 2024 (10%), Apertura 2024 (15%), Clausura 2025 (25%), Apertura 2025 (50%) |
| **Shrinkage bayesiano** | `w_curr = min(0.85, PJ_eff/18 × 0.85)` — dominio del torneo actual crece con jornadas jugadas |
| **xG blend** | 40% xG + 60% goles reales en el suavizado bayesiano (xgscore.io) |
| **xPTS regression** | Ajusta hasta ±3% la λ si el equipo está sobre/sub-performing resultados vs xG |
| **Home advantage por equipo** | Multiplicador calibrado (Toluca 1.586 máx → Pachuca 0.694 mín) |
| **Bajas / jugadores clave** | Penalización por posición, categoría y estatus (titular/duda) con caps ofensivos |
| **Momentum** | Dirección (últimos 2 vs 3 previos partidos) → ±2% en λ |
| **Home crisis / stronghold** | Últimos N partidos de local → -8% crisis, +4% stronghold |
| **Factor rivalidad** | -12% en λ en clásicos |
| **Dixon-Coles ρ** | -0.10 (aumenta P(0-0), P(1-1); reduce P(1-0), P(0-1)) |

### Scoring de quiniela (objetivo de optimización)

```
Exacto acertado  → +2 pts
Resultado 1X2 acertado (sin exacto) → +1 pt
```

El optimizador calcula, para cada candidato `(1X2, exacto)`:

```
EV = P(exacto) + P(resultado 1X2)
```

y elige el de máximo EV, con chequeo de `ev_confidence_gap` vs segundo mejor.

---

## Cómo correr el pipeline

### 1. Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac
pip install -r requirements.txt
```

### 2. Preparar inputs de la jornada (manual hoy, ver Roadmap)

Para jornada `N`, necesitas en `data/inputs/`:

| Archivo | Contenido | Fuente |
|---|---|---|
| `Stats_liga_mx.json` | Histórico de partidos Clausura 2024 → actual | FBref / manual |
| `jornada_N_final.json` | Fixtures de la jornada | Liga MX / manual |
| `Investigacion_cualitativa_jornadaN.json` | Contexto cualitativo | Prompts en `docs/prompt_chatgpt_contexto.md` |
| `context_adjustments_jornadaN.json` | Ajustes manuales (clásicos, etc.) | Manual |
| `evaluacion_bajas.json` | Bajas conocidas de la temporada | Manual |
| `perplexity_bajas_semana.json` | Bajas específicas de la semana | `docs/perplexity_prompt_bajas.md` |
| `xg_stats.json` (raíz `data/`) | xG por equipo | xgscore.io |

### 3. Correr

```bash
# Jornada explícita
python run_pipeline.py --jornada 11

# O por variable de entorno
set PRED_JORNADA=11
python run_pipeline.py
```

Genera en `outputs/`:
- `predicciones_jornada_{N}_final.csv` — picks 1X2 + exactos + EV
- `reporte_tecnico_jornada_{N}.md` — breakdown por partido
- `diagnostico_lambda_components.csv` — componentes de λ por partido
- `fingerprint_jornada_{N}.json` — hashes de inputs para reproducibilidad

### 4. Evaluar después de la jornada

Cuando tengas resultados reales, actualiza `data/historial_usuario.json`
y corre:

```bash
python scripts/evaluate_model.py                 # todos los diagnósticos
python scripts/evaluate_model.py --seccion logloss
python scripts/evaluate_model.py --jornada 11
```

---

## Roadmap

### Corto plazo — automatización de ingesta (siguiente sprint)

Hoy todo input es manual. El objetivo es llegar a **máximo automatizado**:

- [ ] Scraper FBref/SofaScore → merge auto a `Stats_liga_mx.json`
- [ ] Fetcher xgscore.io semanal → `xg_stats.json`
- [ ] Fetcher fixtures Liga MX por jornada
- [ ] Hoy manual: contexto cualitativo + bajas (quedan humanos)

### Mejoras al modelo (siguiente)

- [ ] Backtest rolling-origin con métrica real `quiniela_pts_per_match`
- [ ] Calibración probabilística (reliability curves, Brier, logloss sobre 1X2 y exactos)
- [ ] Negative Binomial / Dixon-Coles MLE sobre sobre-dispersión
- [ ] Grid/Optuna de hiperparámetros (BAYES_K, BLEND_K, CLAMPs, XG_BLEND) optimizando EV de quiniela
- [ ] Componente "contrarian" para concursos masivos
- [ ] Migrar pipeline a workflow declarativo (Prefect/Dagster)

### Técnico

- [ ] CI con GitHub Actions (pytest + linting)
- [ ] Tipado con `mypy`
- [ ] `pyproject.toml` + packaging limpio

---

## Estructura de directorios

```
Predicciones/
├── app/steps/           # Pasos del pipeline
├── data/
│   ├── inputs/          # Inputs manuales por jornada (JSON)
│   ├── archive/         # Snapshots históricos
│   ├── raw/             # (ignorado) dumps de APIs
│   └── processed/       # (ignorado) cache procesado
├── docs/                # Documentación, prompts, plans
├── legacy/              # Código deprecado (no usar)
├── outputs/             # (ignorado salvo .gitkeep) CSVs y reportes por jornada
├── scripts/             # Utilidades CLI
├── src/predicciones/    # Paquete principal
├── tests/               # pytest
├── config_calibracion_modelo.md
├── requirements.txt
├── run_pipeline.py
└── README.md
```

---

## Política de versionado de datos

- **Sí se versiona:** `data/inputs/*.json`, `data/xg_stats.json`, `data/key_players.json`,
  `data/historial_usuario.json` (son la fuente de verdad reproducible).
- **No se versiona:** `outputs/*` (generados), `reporte_tecnico_*.md` en raíz (generados),
  `data/raw/`, `data/processed/`, `data/cache/` (intermedios grandes).

Ver `.gitignore` para detalles.

---

## Convenciones de commits

```
feat(data): actualizar resultados Jornada 11 Clausura 2026
feat(model): integrar xPTS regression factor
fix(quiniela): corregir normalización con grilla adaptativa
docs: explicar blend bayesiano en README
```

---

## Licencia

Uso personal.
