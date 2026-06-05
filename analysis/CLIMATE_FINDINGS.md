# ¿Vale la pena un término de clima/temperatura tipo Klement? — NO

Probe de investigación (no toca el pipeline). Responde la pregunta que dejamos
pendiente antes de modificar `model/adjustments.py`: el modelo de Joachim
Klement (PIB per cápita + población + ranking FIFA + temperatura + localía +
experiencia mundialista) predice **al campeón / qué tan lejos llega una
selección**, no resultados partido a partido. De sus 6 factores, el único
genuinamente ortogonal a lo que ya tiene la quiniela (Elo + odds ya capturan
PIB/población/FIFA/experiencia) era la **temperatura del partido**. Esto mide si
ese término aporta algo.

## Método

- 8,772 partidos internacionales (2014–2026), 75% del histórico — el 25% restante
  se perdió por ciudades que open-meteo no pudo geocodificar sin ambigüedad.
- **Temperatura real** de cada partido: archivo ERA5 de open-meteo por
  (ciudad geocodificada, fecha). Rango -17.8 a 40.0 °C (media 19.9, sd 7.4) —
  amplia variación, buena potencia estadística.
- **Control de fuerza**: Elo pre-partido del propio modelo (replay sin
  look-ahead): `elo_avg`, `elo_absdiff`, indicador de cancha neutral.
- OLS sobre goles totales con y sin temperatura → ΔR², coeficiente y t.

Reproducir: `python -m analysis.climate_backtest` (cachea geocoding+clima en
`analysis/cache/`, ignorado por git; la primera corrida tarda ~10 min).

## Resultados

```
=== OLS: goles totales ===
  A  solo-fuerza        R2=0.0318
  B  +temp (lineal)     R2=0.0319   dR2=+0.00009   coef=+0.0024 goles/°C  t=+0.89  (=> +0.024 goles por +10°C)
  C  +temp+temp²        R2=0.0320   dR2=+0.00025   lin t=-0.94  quad t=+1.21

=== goles totales residuales por bin de temperatura (controlado por fuerza) ===
   <5°C        n=249    +0.098
   5–10        734      -0.023
   10–15      1295      +0.031
   15–20      1780      -0.065
   20–25      2002      -0.096
   25–30      2279      +0.126
   30–35       320      -0.137
   >=35        113      +0.145      <- no monotónico: ni señal de "calor => menos goles"

=== |diferencia de goles| vs temp (márgenes/blowouts) ===
   coef=+0.0075 |gd|/°C   t=+3.28   (significativo, pero +0.075 |gd| por +10°C)
```

## Lectura

1. **Sobre goles totales: efecto nulo.** Añadir temperatura sube el R² en
   +0.00009 (lineal) / +0.00025 (cuadrático); el coeficiente no es significativo
   (t<1). Los bins no muestran patrón monotónico — la idea de "calor deprime el
   ritmo y los goles" **no aparece en los datos**. El término cuadrático, además,
   curva hacia *arriba* (mínimo de goles ~15 °C), lo contrario al "óptimo 14 °C"
   de Klement (que de todos modos es sobre éxito de la selección, no sobre goles).

2. **Único efecto significativo: el margen.** El |gd| crece con el calor
   (t=3.28), pero +0.075 goles de margen por +10 °C es minúsculo y probablemente
   confundido con tipo de competición/región (amistosos y eliminatorias en
   confederaciones débiles se juegan en climas cálidos → más mismatches). Aun si
   fuera causal, es demasiado pequeño para mover un pick EV-óptimo (que cambia de
   marcador en saltos de goles enteros) o un 1X2.

## Veredicto

**No incorporar el término de clima** — ni el resto del índice macro de Klement.
Incluso el único componente potencialmente ortogonal (temperatura) no mueve la
aguja a nivel partido, que es la unidad de la quiniela. El esfuerzo de mayor ROI
sigue siendo el que ya marca el README: encender las odds de cierre.

### Salvedades

- El control es solo-Elo (R² de fuerza ~0.03 porque los goles totales son
  intrínsecamente ruidosos); pero la pregunta era el **aporte incremental** de la
  temperatura, y ese es ~0.
- Mide temperatura del **venue el día del partido**, no el "clima de origen" de
  cada selección (ese ángulo de Klement es justo el redundante con Elo).
- No se probó el diferencial de **aclimatación** (equipo de clima frío jugando en
  calor extremo). Es una hipótesis más fina y hambrienta de datos; dado el nulo
  en el efecto principal, es baja prioridad.
