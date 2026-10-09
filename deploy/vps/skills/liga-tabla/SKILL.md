---
name: liga-tabla
description: Califica todos los boletos sellados con el Árbitro y le cuenta a Samuel cómo va contra los bots.
---

# Tabla de la liga

Úsala cuando Samuel pregunte "cómo voy", "la tabla", o cuando una automatización lo pida.

1. Corre:
   `cd /workspace/predicciones && LIGA_HOME=/workspace/liga PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m wc_predictor.liga.arbitro`
2. Lee `/workspace/liga/tabla/tabla.md` y resume:
   - **Mano a mano**: puntos de Samuel vs cada bot en SUS partidos y el z.
     |z| < 2 = "todavía puede ser suerte"; dilo así, sin exagerar rachas.
   - Bots: puntos, Brier (más bajo = mejor calibrado) y su dinero ficticio por mercado.
   - Partidos pendientes de resultado (Football-Data llega con días de rezago).
3. Si el Árbitro dice "Libro corrupto", NO intentes arreglarlo: avísale a Samuel tal cual.

Todo es dinero ficticio. Si Samuel habla de apostar dinero real, recuérdale que la
regla del proyecto es solo ficticio (ROI real medido −22.5%) y que lo confirme explícitamente.
