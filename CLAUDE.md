# CLAUDE.md

Modelo de quiniela del Mundial 2026 (Poisson + Dixon-Coles + Elo, picks
EV-óptimos). La documentación completa está en `README.md`.

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
refresca la línea de cierre del mercado y luego corre `generate_picks`. No uses
un snapshot de odds viejo si se puede actualizar.

```bash
# 1) Refrescar la línea de cierre (best-effort). Si no hay THE_ODDS_API_KEY,
#    falla la red o la API, NO aborta: generate_picks usará la línea guardada
#    más reciente. El comando degrada solo.
python -m wc_predictor.pipeline.snapshot_odds

# 2) Generar los picks de la ronda con el blend completo
#    (Poisson + Dixon-Coles + Elo + odds, e incentivos de clasificación si aplican)
python -m wc_predictor.pipeline.generate_picks --round j3
```

Salida en `outputs/picks_{ronda}.{csv,json,md}`. Tras correr, reporta de qué
fecha es la línea de cierre que se usó (`captured_at` en
`data/raw/odds_closing_line.json`) para que el usuario sepa qué tan fresco es el
mercado detrás del boleto.

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
