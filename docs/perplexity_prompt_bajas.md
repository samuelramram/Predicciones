# Prompt para Perplexity — Bajas semanales Liga MX

Copia y pega este prompt en Perplexity y adjunta la imagen del fixture de la jornada.

---

Te voy a adjuntar una **imagen del fixture de la jornada** de Liga MX.
Necesito que generes un reporte de bajas **en JSON puro** (sin texto adicional, sin markdown) para alimentar un modelo de predicción.

## Objetivo
Incluir solo bajas **confirmadas** y vigentes para los partidos de la jornada mostrada en la imagen.

## Reglas críticas (obligatorias)
1. Usa la imagen para identificar **solo equipos que sí juegan esta jornada**.
2. Incluye solo jugadores de esos equipos.
3. Verifica que el jugador **sigue en ese club actualmente** (no retirado, no transferido a otro club).
4. Si un jugador está retirado o en otro equipo: **NO incluirlo**.
5. Excluye noticias viejas/no confirmadas.
6. Si una noticia tiene más de 21 días sin confirmación reciente, no la incluyas.
7. Si no puedes confirmar vigencia para el siguiente partido, marca `is_active_for_next_match: false`.
8. **NO usar la página https://www.lesionadosysuspendidos.mx**.
9. **NO incluir jugadores en duda** (`status: "Duda"`). Solo bajas confirmadas: `"Fuera"` o `"Suspendido"`. Si no hay certeza de que el jugador se pierde el partido, omitirlo completamente.

## Verificación mínima requerida por registro
- Debe tener al menos una fuente confiable reciente.
- Debe incluir:
  - `last_verified_at` (ISO datetime)
  - `is_active_for_next_match` (true/false)
  - `current_team`
  - `is_retired` (true/false)
  - `is_transferred_out` (true/false)
  - `verification_status` (`confirmed` | `unverified` | `stale` | `mismatch`)

## Reglas de formato
1. Devuelve **solo JSON válido**.
2. `confidence` entre `0.50` y `1.00` (las bajas confirmadas tienen confianza alta).
3. `impact_level`: `High`, `Mid`, `Low`.
4. `role`: `Portero`, `Defensa`, `Mediocampista`, `Delantero`.
5. `status`: solo `"Fuera"` o `"Suspendido"`. Nunca `"Duda"`.
6. Equipos en español (ej. "América", "Pumas", "Cruz Azul").

## Formato exacto esperado
```json
{
  "week_reference": "2026-W09",
  "source": "perplexity",
  "generated_at": "2026-02-24T12:00:00Z",
  "bajas": [
    {
      "team": "América",
      "current_team": "América",
      "player": "Jugador Ejemplo",
      "role": "Delantero",
      "status": "Fuera",
      "impact_level": "High",
      "confidence": 0.90,
      "recency_days": 2,
      "is_active_for_next_match": true,
      "is_retired": false,
      "is_transferred_out": false,
      "verification_status": "confirmed",
      "last_verified_at": "2026-02-24T09:30:00Z",
      "reason": "Lesión muscular",
      "evidence": "https://..."
    }
  ]
}
```

## Salida final
Entrega **únicamente** el JSON. Sin explicaciones, sin markdown.

---

## Cómo guardarlo

Guardar el resultado como:

`data/inputs/perplexity_bajas_semana.json`

Así el pipeline lo integra automáticamente.
