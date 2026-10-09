---
name: liga-sellar
description: Sella los marcadores que Samuel manda para la jornada con el Notario; nunca los escribe a mano.
---

# Sellar el boleto de Samuel

Úsala cuando Samuel mande marcadores ("mis picks: 2-1, 0-2, …").

1. Identifica la jornada: la más reciente en `/workspace/liga/rounds/` (`eu-AAAA-Wnn`).
2. Copia sus marcadores TAL CUAL, en el orden que los mandó, y corre:
   `cd /workspace/predicciones && LIGA_HOME=/workspace/liga PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m wc_predictor.liga.notario --round eu-AAAA-Wnn --picks "2-1, 0-2, -, 1-3"`
3. Devuélvele la salida del Notario completa (qué quedó sellado ✔, qué no y por qué) y el hash corto.
4. Si pregunta qué le falta: `... python3 -m wc_predictor.liga.notario --round eu-AAAA-Wnn --status`

Reglas duras:
- NUNCA edites `/workspace/liga/ledger.jsonl` ni escribas picks a mano: solo el Notario sella.
- No "corrijas" sus marcadores ni adivines a qué partido se refería; si el número de
  marcadores no cuadra o algo es ambiguo, pregúntale antes de correr nada.
- Un partido ya empezado o ya sellado no se puede cambiar: díselo, sin buscarle la vuelta.
