---
name: liga-sellar
description: Sella los marcadores que Samuel manda para la jornada con el Notario; nunca los escribe a mano.
---

# Sellar el boleto de Samuel

Úsala cuando Samuel mande marcadores ("mis picks: 2-1, 0-2, …").

El Notario entiende dos formas; pásale el texto de Samuel TAL CUAL (une renglones con comas):
- en orden del boleto: `2-1, 0-2, -, 1-3` (`-` salta uno),
- con nombre: `Bayern 2-0` (= gana Bayern 2-0, aunque sea visitante), `Arsenal 2-0 Leeds`
  (local primero), `Como 1-1`. Apodos comunes (Barça, Madrid, City, PSG, Atlético) los conoce.

1. Identifica la jornada: la más reciente en `/workspace/liga/rounds/` de la liga que
   corresponde (`mx-AAAA-Jnn` para Liga MX, `eu-AAAA-Wnn` para Europa). Si Samuel mezcla
   partidos de las dos en un mensaje, sepáralos y corre el Notario una vez por jornada.
2. PRUEBA primero (no sella nada):
   `cd /workspace/predicciones && LIGA_HOME=/workspace/liga PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m wc_predictor.liga.notario --round eu-AAAA-Wnn --picks "<texto de Samuel>" --dry-run`
3. Muéstrale cómo lo entendió (local-visita, por número) y pregúntale "¿lo sello?".
   Sellar no tiene vuelta atrás, así que no te saltes esta confirmación.
4. Con su "sí", corre el mismo comando SIN `--dry-run` y devuélvele la salida completa
   (qué quedó sellado ✔, qué no y por qué) y el hash corto.
5. Si el Notario dice que no entendió algo o que un nombre le queda a varios partidos,
   pregúntale a Samuel ese partido; no lo adivines tú.
4. Si pregunta qué le falta: `... python3 -m wc_predictor.liga.notario --round eu-AAAA-Wnn --status`

Reglas duras:
- NUNCA edites `/workspace/liga/ledger.jsonl` ni escribas picks a mano: solo el Notario sella.
- No "corrijas" sus marcadores ni adivines a qué partido se refería; si el número de
  marcadores no cuadra o algo es ambiguo, pregúntale antes de correr nada.
- Un partido ya empezado o ya sellado no se puede cambiar: díselo, sin buscarle la vuelta.
