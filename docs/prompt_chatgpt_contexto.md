# Prompt ChatGPT — Estructurar Contexto en JSON para el Modelo

Este prompt convierte el output de Perplexity (texto) en el JSON estructurado
que consume el pipeline. Se usa DESPUÉS de obtener el output de Perplexity.

---

## PROMPT (copia y pega, luego pega el output de Perplexity al final)

```
Vas a convertir un reporte de contexto cualitativo de Liga MX en un JSON estructurado
para alimentar un modelo de predicción de Poisson.

## El modelo y cómo usa este JSON

El modelo calcula lambda (goles esperados) para cada equipo con:
  lambda = base_estadistica × att_adj × def_adj × form_adj × bajas_adj × context_adj

Este JSON aporta el "context_adj". El modelo ya tiene bajas, forma reciente y estadísticas.
Solo necesitas capturar lo que las estadísticas NO pueden ver.

## Tipos de ajuste válidos

| type | Cuándo usarlo | att_adj típico | def_adj típico |
|---|---|---|---|
| squad_fatigue | 3+ partidos en 8 días, viaje largo | 0.94–0.97 | 1.03–1.06 |
| rotation_expected | Técnico confirma rotación, historial claro | 0.92–0.97 | 1.03–1.08 |
| tactical_change | Nuevo DT, cambio de sistema documentado | 0.94–1.05 | 0.95–1.05 |
| suspension | Jugador clave cumple fecha de sanción | 0.94–0.98 | 1.00 |
| motivation_crisis | Racha negativa + conflicto interno confirmado | 0.95–0.97 | 1.03–1.05 |
| motivation_boost | Partido bisagra + evidencia de motivación extra | 1.02–1.05 | 0.96–0.98 |

## Reglas de magnitud

1. Leve = desviación de ±2-3% (ej. att_adj: 0.97 o 1.03)
2. Moderado = desviación de ±4-6% (ej. att_adj: 0.95 o 1.05)
3. Alto = desviación de ±7-8% (ej. att_adj: 0.93 o 1.07). Solo con evidencia muy sólida.
4. NUNCA usar valores fuera del rango [0.90, 1.10] — fuera de ese rango hay cosas raras.
5. Si el contexto es ambiguo o la fuente no es reciente: confidence ≤ 0.55

## Regla anti-duplicación

Si una situación ya fue capturada en el archivo de bajas (lesión, enfermedad, molestia física),
NO la incluyas aquí aunque Perplexity la mencione. Solo incluir suspensiones disciplinarias
y los tipos listados arriba.

## Regla de omisión

Si un partido no tiene contexto con evidencia real, NO lo incluyas en context_adjustments.
Un array vacío es mejor que ajustes inventados. El modelo funciona bien sin este archivo.

## Nombres de equipos (usar exactamente estos)

América, Atlas, Atlético de San Luis, Cruz Azul, FC Juárez, Guadalajara, León,
Mazatlán, Monterrey, Necaxa, Pachuca, Puebla, Pumas, Querétaro, Santos Laguna,
Tigres, Tijuana, Toluca

## Schema JSON exacto a producir

{
  "jornada": [N],
  "torneo": "Clausura 2026",
  "generated_at": "[fecha ISO actual]",
  "context_adjustments": [
    {
      "match": "[Local] vs [Visitante]",
      "team": "[equipo afectado, exactamente como en la lista de arriba]",
      "type": "[uno de los tipos válidos]",
      "att_adj": [float entre 0.90 y 1.10],
      "def_adj": [float entre 0.90 y 1.10],
      "confidence": [float entre 0.30 y 1.00],
      "evidence": "[1 oración con fechas y hechos. NO opiniones.]",
      "evidence_url": "[URL de la fuente, si está disponible]",
      "notes": "[etiqueta corta para el reporte, ej: 'Fatiga Concachampions vuelta']"
    }
  ]
}

## Instrucción final

Produce ÚNICAMENTE el JSON válido. Sin explicaciones antes ni después.
Si no hay contexto real que justifique ningún ajuste, produce:
{ "jornada": [N], "torneo": "Clausura 2026", "generated_at": "...", "context_adjustments": [] }

---

## REPORTE DE PERPLEXITY A ESTRUCTURAR:

[PEGA AQUÍ EL OUTPUT DE PERPLEXITY]
```

---

## Archivo destino

Guarda el JSON resultante en:

```
data/inputs/context_adjustments_jornada{N}.json
```

Reemplaza `{N}` con el número de jornada correspondiente (ej. `context_adjustments_jornada8.json`).

---

## Checklist antes de guardar

- [ ] ¿Todos los nombres de equipo están en la lista de equipos válidos?
- [ ] ¿Todos los `att_adj` y `def_adj` están entre 0.90 y 1.10?
- [ ] ¿Ninguna baja/lesión se coló como `suspension` o `squad_fatigue`?
- [ ] ¿El JSON es válido? (puedes verificar en jsonlint.com)
- [ ] ¿Los partidos con "SIN CONTEXTO" de Perplexity están ausentes del array?
