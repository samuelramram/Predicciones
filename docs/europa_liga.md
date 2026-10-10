# Liga de bots en Europa: datos, mercados y resultados del backtest

## Datos

Los datos vienen de Football-Data.co.uk, a nivel de liga y temporada (`mmz4281/{temporada}/{liga}.csv`):

- **Cobertura:** Premier (E0), LaLiga (SP1), Serie A (I1), Bundesliga (D1) y Ligue 1 (F1), de la 2020/21 a la 2026/27 en curso.
- **Volumen:** 10,984 partidos en `data/europa/matches.csv`, todos con momios de cierre de 1X2, Over/Under 2.5 y hándicap asiático.
- **Probabilidad justa:** la de cierre de Pinnacle sin vig. La 26/27 ya no trae Pinnacle, así que ahí se usa el promedio sin vig.
- **Precio de apuesta:** el promedio de cierre, que es el realista para una sola casa.
- **Próximos partidos:** `fixtures.csv` trae momios previos, no de cierre.
- **Rezago:** el CSV de la temporada en curso se actualiza con atraso. El 9-oct-2026 llegaba al 20-sep.

## Mercados

Todos salen de la matriz de marcadores de cada bot, en `liga.markets`:

- **1X2 y marcador exacto:** las reglas del pool (2 exacto / 1 resultado).
- **Over/Under 2.5 y ambos anotan:** se califica el Brier binario (uniforme = 0.25).
- **Hándicap asiático:** líneas enteras (push), medias y de cuarto (la apuesta se parte en dos mitades).
- **Dinero ficticio:** una apuesta plana de 10 por partido y mercado, al lado de mayor valor esperado. Bankroll de 1,000 por liga.

### Lección de diseño: la forma del marcador también tiene que seguir al mercado

Primero el bot `calibrado` solo reescalaba las marginales 1X2 hacia el mercado. El problema: la matriz conservaba el ambiente de goles del modelo, así que un Barça al 88% seguía "esperando" un 2-0. Por eso veía valor ficticio enorme en hándicaps de favoritos grandes (Barça −2.75, PSG −2.75: +34%).

El arreglo fue `implied_lambdas`: busca las tasas de gol cuyo Poisson·DC reproduce P(local), P(visita) y P(Over 2.5) del mercado, y las mezcla geométricamente con las del modelo. Medido en el backtest:

- Las apuestas de hándicap del `borrego` bajaron de 640 a 118. Eran casi todas ilusión.
- El Brier de ambos anotan bajó de 0.2476 a 0.2442. Es señal real que da el total del mercado.

## Backtest walk-forward

Cubre 3,736 partidos de 2024-07 a 2026-09. Se re-ajustó cada semana por liga, y rho se perfiló una vez por temporada.

| bot | pts | exactos | Brier 1X2 | Brier O/U | Brier BTTS | ROI 1X2 | ROI O/U | ROI AH |
|---|---|---|---|---|---|---|---|---|
| borrego (mercado puro) | 2464 | 442 | 0.5763 | 0.2372 | 0.2442 | −21% (109) | −20% (71) | −7% (118) |
| **calibrado (0.9)** | 2446 | 432 | 0.5765 | 0.2373 | 0.2442 | −31% (88) | −23% (74) | −6% (145) |
| calibrado 0.75 | 2441 | 433 | 0.5769 | 0.2373 | 0.2443 | −23% (349) | −16% (100) | −6% (491) |
| calibrado 0.55 | 2429 | 438 | 0.5782 | 0.2375 | 0.2448 | −12% (1320) | +0.4% (407) | −8% (1346) |
| estadistico (sin mercado) | 2376 | 419 | 0.5891 | 0.2435 | 0.2477 | −11% (3063) | −7% (2516) | −7% (2763) |

Las pruebas pareadas contra `calibrado` 0.9 (|z| < 2 es ruido) dan esto:

- **estadistico:** Brier 1X2 z = +6.8, puntos −70 (z = −2.6). Ignorar el mercado sale caro.
- **calibrado 0.55** (el peso de Liga MX): Brier 1X2 z = +3.3. Por eso Europa usa 0.9.
- **borrego:** Brier 1X2 z = −1.5 (empate estadístico) y puntos +18 (z = +2.5).

Una corrida previa con la matriz vieja daba esta escalera de Brier 1X2 según el peso: 0.55 → 0.5797, 0.75 → 0.5777, 0.9 → 0.5767, mercado puro → 0.5763.

En el subconjunto top (1,106 partidos con un equipo del top-3) el orden es el mismo.

## Qué significa

- **Las líneas de cierre de Europa son eficientes.** Ningún bot le gana al mercado, y en ningún mercado un ROI positivo es significativo. El +0.4% de O/U de `calibrado 0.55` en 407 apuestas es ruido.
- **Los bots sirven como vara de medir.** Sirven para ver si Samuel, o un bot LLM que lea noticias, le saca algo al mercado. Ganar dinero no es su papel.
- **Liga MX es otra historia.** Allá el mercado es menos eficiente y el modelo propio sí aporta (ver `ligamx_apertura.md` §9). Por eso los pesos difieren por región.

## Pendiente

- **Props de jugadores (fase 2):** goleador y tarjetas, cuando haya una fuente de alineaciones + momios.
- **Liga MX con O/U y ambos anotan:** MEX.csv no trae momios de totales. Ahí se medirá solo el Brier.
- **Champions League:** Football-Data no la publica.

## Mejoras probadas (oct 2026): cuáles se quedaron y cuáles no

Mismo harness walk-forward (3,736 partidos, 2024-07 → 2026-09). Cada variante se comparó contra la base partido por partido con `europa_backtest --compare`. Regla: solo se queda lo que gana con |z| ≥ 2 y no empeora otra métrica.

**1. Backtest honesto: momios previos en lugar de los de cierre.** El bot en vivo nunca ve el cierre, así que ahora el backtest usa la línea previa de Football-Data (la del día anterior aproximadamente). Es el nuevo default.

| | Brier 1X2 calibrado | puntos borrego |
|---|---|---|
| con cierre (lo de arriba) | 0.5765 | 2462 |
| con momios previos (lo real) | 0.5779 | 2437 |

El cierre sabe más que la línea previa, así que los números de arriba eran un poco optimistas.

Además salieron **datos corruptos**: alrededor del 29-nov-2025, Football-Data trae precios de hándicap visitante de ~4.5 en líneas parejas. Con eso los bots veían +50% de ROI en hándicap, que era falso. El ingest ahora descarta todo mercado con margen fuera de 0–15% (`europa_fd._sane`): son ~40 filas.

**2. Recién ascendidos con el nivel de los descendidos (Elo + prior en el Poisson): no se queda.** El 1X2 no cambia (z=+0.4). Over/Under mejora (z=−3.0) pero ambos anotan empeora (z=+2.3). Queda como `--promoted` por si algún día se quiere medir solo en partidos de ascendidos.

**3. Memoria del modelo (half-life): se queda en 730 días.**

| half-life | O/U (estadístico) | O/U (calibrado) | ambos anotan (calibrado) | puntos |
|---|---|---|---|---|
| 365 | peor, z=+2.1 | peor, z=+2.7 | peor, z=+2.5 | — |
| 540 | — | peor, z=+1.8 | peor, z=+2.0 | — |
| 1095 | — | — | — | peor, z=−1.4 |

Con 365 empeora todo. Igual que en Liga MX: más datos le ganan a datos frescos.

**4. xG de Understat (`ingest/understat_xg.py`, `data/europa/xg.csv`): sí se queda, con peso 0.75.** El Poisson se ajusta sobre `0.25·goles + 0.75·xG`. La corrección Dixon-Coles sigue usando el marcador real.

| bot estadístico | goles | xG 0.5 | **xG 0.75** | xG 1.0 |
|---|---|---|---|---|
| Brier 1X2 | 0.5891 | 0.5870 (z=−4.0) | **0.5865 (z=−3.3)** | 0.5863 (z=−2.7) |
| Brier O/U | 0.2435 | 0.2410 (z=−4.1) | **0.2409 (z=−2.9)** | 0.2413 |
| Brier ambos anotan | 0.2477 | 0.2457 (z=−3.6) | **0.2456 (z=−2.6)** | 0.2460 |

0.75 le gana a 0.5 en 1X2 (z=−2.0). Los bots que siguen al mercado no se mueven (|z|<0.6), porque el mercado ya trae el xG en los momios. Los puntos de quiniela tampoco cambian: el pick es un argmax y casi nunca cruza el umbral. Liga MX no está en Understat.

**5. Peso del mercado, re-medido con xG y momios previos: se queda en 0.9.**

| peso | vs 0.9 (Brier 1X2) |
|---|---|
| 0.75 | peor, z=+2.7 |
| 0.6 | peor, z=+3.2 |

El modelo mejoró, pero el mercado sigue mandando en Europa.

**Pendiente:**
- Alineaciones y lesiones (bot Reportero).
- El backtest de Liga MX sigue con momios de cierre, porque MEX.csv no publica línea previa. Su peso 0.55 puede estar un poco inflado por eso.
