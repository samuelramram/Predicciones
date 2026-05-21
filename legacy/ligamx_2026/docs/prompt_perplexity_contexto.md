# Prompt Perplexity — Contexto Cualitativo por Jornada

Usa este prompt para obtener el contexto competitivo de la jornada.
Es un paso **separado** del prompt de bajas. Solo cubre lo que las estadísticas no capturan.

Adjunta la imagen del fixture antes de enviar.

---

## PROMPT (copia y pega)

```
Adjunto el fixture de la Jornada [N] de Liga MX Clausura 2026.

Necesito que investigues con búsquedas web recientes (últimos 7 días) el contexto competitivo de cada partido. NO me des información de lesiones o bajas — esas las tengo por otro canal. Enfócate exclusivamente en:

1. CONGESTIÓN DE CALENDARIO: ¿Algún equipo jugó Concachampions, Copa MX u otro torneo en los 7 días previos a este partido? ¿Cuántos partidos en cuántos días? ¿Hubo viaje largo?

2. ROTACIÓN CONFIRMADA O MUY PROBABLE: ¿El técnico declaró en conferencia que va a rotar? ¿Hay historial claro de que este DT rota en estas circunstancias?

3. SUSPENSIONES DISCIPLINARIAS: ¿Algún jugador clave cumple fecha de suspensión por amarillas acumuladas o roja directa? (NO incluir lesiones)

4. CONTEXTO MOTIVACIONAL REAL: ¿Hay algún partido que sea verdaderamente crítico en términos de posición en tabla, riesgo de descenso, o dinámica especial (no inventar "ambiente caldeado" genérico)?

## REGLAS CRÍTICAS — LEE ANTES DE RESPONDER

- Si no encuentras información reciente verificada para un equipo, escribe explícitamente: "Sin información para [Equipo]". NO inventes contexto.
- Cada dato debe tener una URL de fuente real y reciente (< 7 días). Si no tienes URL, NO incluyas el dato.
- No incluyas especulaciones, opiniones de analistas, o "se espera que...". Solo hechos verificables.
- No repitas información de lesiones/bajas.
- Si un partido no tiene ningún contexto relevante, dilo explícitamente: "Partido sin contexto diferencial identificado".

## FORMATO DE RESPUESTA

Para cada partido con contexto real, responde así:

---
PARTIDO: [Local] vs [Visitante]
EQUIPO AFECTADO: [nombre]
TIPO: [congestión_calendario | rotación | suspensión | contexto_motivacional]
DETALLE: [1-2 oraciones concretas con fechas y hechos]
MAGNITUD ESTIMADA: [Leve / Moderada / Alta]
FUENTE: [URL directa]
---

Si el partido no tiene contexto relevante:
---
PARTIDO: [Local] vs [Visitante]
SIN CONTEXTO DIFERENCIAL VERIFICADO
---
```

---

## Qué hacer con el output

El resultado de Perplexity va al siguiente paso: el **Prompt ChatGPT de estructuración** (`docs/prompt_chatgpt_contexto.md`), que convierte el texto en el JSON que consume el modelo.

No pegues el texto de Perplexity directamente en ningún archivo del modelo — pasa por ChatGPT primero.

---

## Qué NO preguntarle a Perplexity aquí

| ❌ No preguntar | ✅ Usar en cambio |
|---|---|
| Lesiones y bajas | `docs/perplexity_prompt_bajas.md` |
| Predicciones o favoritos | Eso lo hace el modelo |
| "¿Quién va a ganar?" | No relevante para este paso |
| Estadísticas históricas | Ya están en `Stats_liga_mx.json` |

---

## Archivo destino

El JSON final generado por ChatGPT se guarda en:

```
data/inputs/context_adjustments_jornada{N}.json
```

El pipeline lo carga automáticamente al correr `python run_pipeline.py --jornada N`.
