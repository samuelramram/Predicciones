# Diagnóstico tras J5 — por qué vamos abajo (quiniela) y por qué perdimos (apuestas)

Medido el 2026-08-24, con 27 partidos del pool resueltos (J3-J5), 62 apuestas
liquidadas y un backtest walk-forward de 656 partidos de rol regular OOS.

Este documento existe para lo mismo que la sección "Calibración: qué se probó y
por qué NO se cambió" de `CLAUDE.md`: **dejar medido lo que se revisó, para que
nadie vuelva a tunear a ciegas.**

---

## 1. El modelo NO está descalibrado

Backtest walk-forward, 656 partidos de rol regular fuera de muestra:

| | predicho | real | Δ |
|---|---|---|---|
| local | 47.9% | 46.8% | −1.1pp |
| empate | 24.3% | 23.8% | −0.5pp |
| visita | 27.9% | 29.4% | +1.5pp |

Dentro de ±1.5pp en los tres resultados. La curva de fiabilidad no muestra sesgo
sistemático. **El 1X2 está bien calibrado; no hay un bug de calibración que
arreglar.** Esto reconfirma lo que ya decía `CLAUDE.md`.

Skill base OOS: **+13.1%** vs baseline "1-0" (241 pts vs 213 en 381 partidos
desde 2025-07-01). Exactos 9%, a la par del campo.

---

## 2. El techo de Liga MX es ~53%, y eso explica el contraste con el Mundial

Confianza media del modelo: **55.1%**. Acierto real del argmax: **53.2%**.
El modelo está entregando casi exactamente lo que su propia confianza promete —
lo que pasa es que esa confianza es baja.

**La distribución cruda de resultados es idéntica entre las dos competencias**,
así que "Liga MX es más aleatoria" es falso como se suele decir:

| | entropía 1X2 | goles/partido | marcador modal | top-5 marcadores |
|---|---|---|---|---|
| Mundial 2026 (grupos, n=72) | 1.524 bits | 2.99 | 1-1 (12.5%) | 43.1% |
| Liga MX rol regular (n=963) | 1.526 bits | 2.86 | 1-1 (12.0%) | 45.4% |

Lo que cambia no es el ruido: es **cuánta señal trae cada partido**. La
dispersión de fuerza es mucho mayor en el Mundial:

| | sd de Elo | \|ΔElo\| mediana del enfrentamiento | % partidos con \|ΔElo\|>200 |
|---|---|---|---|
| Mundial (48 selecciones) | 161 | 193 | **47%** |
| Liga MX (18 equipos) | 109 | 113 | **21%** |

Y la predictibilidad sube monotónicamente con esa brecha (656 partidos OOS):

| \|ΔElo\| | n | acierto 1X2 | pts/partido |
|---|---|---|---|
| 0-75 | 176 | 46.6% | 0.562 |
| 75-150 | 184 | 47.3% | 0.576 |
| 150-250 | 169 | 59.2% | 0.686 |
| 250+ | 127 | **63.8%** | 0.740 |

**Contrafactual:** el mismo modelo, sobre la mezcla de brechas del Mundial,
pasaría de 53.4% a **56.0%** de acierto y de 0.633 a **0.660** pts/partido. Eso
cubre una parte del salto contra los 0.765 pts/partido reales del Mundial; el
resto fue el blend con odds, la calibración de KO y suerte.

**Conclusión:** el Mundial no salió mejor porque el modelo estuviera más
afinado. Salió mejor porque Brasil-vs-un-debutante es un partido con señal y
Atlas-vs-Querétaro no lo es. Liga MX no es rara; es **pareja**, que es peor.

---

## 3. J3-J5 fue una racha de sorpresas, no un colapso del modelo

En los 27 partidos que cuentan para el pool:

- **el favorito por Elo ganó solo 37.0%** de los partidos (histórico OOS: 50.5%)
- el modelo acertó 40.7% teniendo 55.0% de confianza media
- de 9 picks con confianza ≥65%, solo entraron 4 (esperado ~6.4)

Cayeron Cruz Azul (p=0.73 y p=0.75, perdió las dos), Pachuca (p=0.75, perdió) y
Pumas (p=0.65 y p=0.68, empató las dos). La desviación es de ~1.5σ: mala racha,
no evidencia de un defecto. **No se cambió nada por esto.**

Nuestro desempeño acumulado vs el campo (J3-J5, 27 partidos):

| | acierto 1X2 | exactos | pts |
|---|---|---|---|
| nosotros | 37.0% | 3.7% (1) | 11 |
| campo (media) | 43.8% | 10.4% | 14.2 |
| modelo puro sobre esos partidos | 40.7% | 3.7% | ~12 |

Nuestros picks siguieron al modelo; el modelo tuvo la racha en contra. El déficit
de exactos (1 vs ~2.7 esperados) tampoco es significativo con n=27 (p≈0.23).

---

## 4. Arranque de torneo: el modelo es optimista ~5pp (señal débil, no accionable en la quiniela)

Hipótesis probada: como Liga MX corre dos torneos cortos al año con rotación de
plantillas, las fuerzas heredadas quedan rancias al arrancar cada torneo.

| fase | n | acierto | confianza | Δ |
|---|---|---|---|---|
| J1-J3 | 134 | 49.3% | 55.6% | **−6.3pp** |
| J4-J6 | 126 | 53.2% | 54.9% | −1.7pp |
| J7-J10 | 144 | 60.4% | 55.5% | +4.9pp |
| J11-J14 | 144 | 51.4% | 54.7% | −3.3pp |
| J15-J17 | 108 | 51.9% | 54.7% | −2.9pp |

Agrupado: **J1-J5 acierta 50.0% creyéndose 55.4% (Δ −5.4pp); de J6 en adelante
está perfectamente calibrado (Δ +0.1pp).** La dirección es la esperada, pero
**z = −1.24: no alcanza significancia.**

Para la quiniela esto **no es accionable**: encoger las probabilidades hacia la
media preserva el argmax, así que el pick no cambia y no hay puntos que ganar —
el mismo resultado que ya tenían los knobs de empate y de ambiente de goles.

Para **apuestas sí importa**, porque ahí el valor de la probabilidad entra en el
EV y en el stake. Ver la sección siguiente.

---

## 5. Apuestas: el modelo no le gana al mercado, y el selector de apuestas es adverso

Ledger completo tras liquidar J5: **−$248 sobre $1,598 (−15.5% ROI, 25W-37L)**,
CLV promedio **−5.56%**, solo **19%** de las apuestas le ganaron al cierre.
Desglose por jornada: J3 +$38 (n=15, stakes de $10), J4 +$5 (n=21),
**J5 −$291 (n=26, −39.3%)**.

El hallazgo de fondo, sobre las 62 apuestas registradas:

| | prob. media asignada | vs realidad |
|---|---|---|
| modelo | 48.8% | **+8.5pp de más** |
| mercado (línea justa devigada) | 40.9% | **+0.5pp** |
| lo que de verdad pasó | 40.3% | — |

Brier: **modelo 0.2354 vs mercado 0.2156** — el mercado es estrictamente mejor
sobre los mismos eventos. Y el patrón se repite en TODOS los cortes:

| corte | n | modelo | mercado | real | ROI |
|---|---|---|---|---|---|
| 1X2 | 43 | 46.0% | 37.6% | 37.2% | −17.8% |
| O/U 2.5 | 19 | 55.2% | 48.2% | 47.4% | −7.3% |
| favorito (<1.80) | 12 | 69.9% | 59.8% | 58.3% | −14.2% |
| longshot (≥3.00) | 22 | 29.6% | 23.4% | 22.7% | −23.4% |

**El mercado clava la realidad dentro de ~1pp en cada corte; el modelo se pasa
6-10pp en cada corte.** Eso es lo que hace tóxico al selector: la regla de
selección es "apostar donde el modelo > mercado", que es exactamente un filtro
para quedarse con los errores de sobreconfianza del modelo. Selección adversa de
manual.

Nota metodológica honesta: esa muestra está sesgada por construcción (se
eligieron por discrepar del mercado). La muestra limpia — los 9 partidos de J4
del `source_tracker`, registrados antes de jugarse y sin selección — apunta en
la misma dirección (log-loss mercado 1.129 < blend 1.143 < modelo 1.178) pero es
demasiado chica para concluir sola.

### El peor corte: los empates apostados

| n | modelo | mercado | real | ROI |
|---|---|---|---|---|
| 9 | 28.1% | 24.8% | **11.1%** | **−90.3%** |

Ironía del proyecto: en la quiniela nos duele **no** picar empates, y en apuestas
los empates fueron el agujero más grande del boleto. **Los empates quedan fuera
del boleto de apuestas hasta que haya evidencia que los sostenga.**

### El menos malo: totals

O/U 2.5 tiene CLV **−1.2%** contra **−6.9%** del 1X2. Sigue siendo negativo, pero
es el único mercado cerca de romper parejo. Si algún día hay boleto, ahí es donde
el modelo se defiende mejor.

---

## 6. Odds históricas: sigue bloqueado (verificado, no asumido)

`CLAUDE.md` dice que el peso del mercado (0.55) no se puede backtestear por falta
de feed histórico. **Se verificó contra la API el 2026-08-24**: el endpoint
`/v4/historical/sports/soccer_mexico_ligamx/odds/` responde **401
`HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN`**. Sigue siendo cierto. La única vía
para calibrar `blend_odds_weight` sigue siendo el `source_tracker` en vivo (9
partidos registrados; hacen falta ~45-55 para concluir).

---

## Qué NO se cambió y por qué

- **Nada de calibración.** El modelo está dentro de ±1.5pp; el déficit de J3-J5
  es ~1.5σ de varianza. Cambiar knobs por una racha es justo el error que
  `CLAUDE.md` prohíbe.
- **Nada del gate de empates.** Ya estaba medido (cero cambio de puntos hasta
  umbral 0.22) y esta revisión no aporta evidencia nueva a favor.
- **El peso del mercado sigue en 0.55**, aunque toda la evidencia de apuestas
  apunta a que el mercado es mejor que el modelo. No se mueve sin la muestra del
  `source_tracker`, porque moverlo con 9 partidos sería el mismo pecado.

## Qué sí cambia (decisiones, no código)

1. **Se retira el boleto de despliegue por casa** (`--budget-*`). Es −EV por
   construcción y ya costó $291 en una jornada. Cualquier apuesta futura pasa por
   `--require-clv`.
2. **Sin empates en el boleto de apuestas** (−90.3% ROI, 9 apuestas).
3. **Preferencia por totals sobre 1X2** cuando haya algo que pase el gate de CLV.
4. **La quiniela sigue igual.** Es donde el modelo tiene ventaja real y medida
   (+13.1% OOS), y donde la varianza de 27 partidos todavía no dice nada.
