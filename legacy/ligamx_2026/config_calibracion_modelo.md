# Configuración de Calibración - Modelo Poisson

# Fecha: 10 de febrero, 2026

# Objetivo: Corregir subestimación de goles (-0.47 goles/partido)

## 🔧 CAMBIO 1: Curva de Shrinkage Más Lenta

### Problema identificado

- El modelo llega a w_curr_max = 0.85 demasiado rápido (divisor /12.0)
- Esto comprime las lambdas en torneos jóvenes (J5-J6)

### Solución

```python
# ANTES:
w_curr = min(0.85, (pj_effective / 12.0) * 0.85)

# DESPUÉS:
w_curr = min(0.85, (pj_effective / 18.0) * 0.85)
```

### Ubicación en código

Buscar la función que calcula `w_curr` basándose en `pj_effective`

### Impacto esperado

- En J5-J6 (pj_effective ≈ 4-5): w_curr pasa de ~0.28-0.35 a ~0.19-0.24
- Mayor peso en prior histórico → lambdas menos comprimidas
- **+0.25 goles/partido estimado**

---

## 🔧 CAMBIO 2: Reducir Impactos de Bajas "Medias" + Cap Ofensivo

### Problema identificado

- Bajas acumulativas están sobrecastigando (ej: Chivas -25% en J6)
- Impactos de "mediocampista" y "atacante" son demasiado agresivos

### Solución A: Reducir base_multiplier

```python
# ANTES:
injury_impact = {
    'goleador_top': -0.12,      # mantener
    'defensor_lider': +0.12,    # mantener (beneficia rival)
    'mediocampista': -0.05,     # CAMBIAR a -0.03
    'atacante': -0.09,          # CAMBIAR a -0.07
    'creativo_top': -0.10,      # mantener
    'portero_titular': +0.15    # mantener (beneficia rival)
}

# DESPUÉS:
injury_impact = {
    'goleador_top': -0.12,
    'defensor_lider': +0.12,
    'mediocampista': -0.03,     # ✅ -5% → -3%
    'atacante': -0.07,          # ✅ -9% → -7%
    'creativo_top': -0.10,
    'portero_titular': +0.15
}
```

### Solución B: Elevar Cap Ofensivo

```python
# ANTES:
min_offensive_modifier = 0.75  # Cap: máximo -25% de lambda

# DESPUÉS:
min_offensive_modifier = 0.82  # ✅ Cap: máximo -18% de lambda
```

### Ubicación en código

1. Diccionario de `injury_impact` o `base_multiplier`
2. Variable de cap: buscar `0.75` o `min_offensive_modifier`

### Impacto esperado

- Casos extremos como Guadalajara (-25%) ahora limitados a -18%
- **+0.15 goles/partido estimado**

---

## 🔍 CAMBIO 3: Investigar Depresión en Visitantes

### Problema identificado

- Visitante subestimado -23.6% vs. real
- Local subestimado sólo -14.3%
- **Asimetría sospechosa**

### Hipótesis

**Problema en cálculo de `defs_curr` con splits pequeños**

Cuando un equipo tiene pocos partidos como visitante:

- `PJ_away` es bajo (ej: 2-3 partidos)
- `GC_away` puede ser ruidoso
- `defs_curr_away = GC_away / PJ_away` tiene alta varianza
- El shrinkage empuja hacia prior, pero el prior puede estar desactualizado

### Código a revisar

```python
# Buscar donde se calcula la defensa actual (visitante)
# Ejemplo típico:

# Para defensa visitante del equipo RIVAL (afecta lambda_home):
defs_curr_away_rival = stats_rival['GC_away'] / stats_rival['PJ_away']

# Para defensa local del equipo RIVAL (afecta lambda_away):
defs_curr_home_rival = stats_rival['GC_home'] / stats_rival['PJ_home']
```

### Diagnóstico propuesto

1. **Agregar logging temporal:**

   ```python
   print(f"[DEBUG] {team_away}: PJ_away={pj_away}, GC_away={gc_away}, defs_curr={defs_curr_away}")
   ```

2. **Verificar splits:**
   - ¿Hay equipos con `PJ_away < 3`?
   - ¿Están siendo penalizados injustamente?

3. **Posible fix: Minimum PJ threshold**

   ```python
   # Si PJ_away < 3, usar promedio global o expandir ventana temporal
   if pj_away < 3:
       defs_curr_away = league_avg_gc_away  # fallback
   ```

### Datos de ejemplo (Jornada 6)

| Equipo | Lambda Away (modelo) | Observación |
|--------|---------------------|-------------|
| Pumas | 1.31 | OK |
| Tijuana | 0.88 | Bajo |
| Querétaro | 0.98 | ¿Deprimido? |
| Atlas | 0.52 | **MUY bajo** |
| León | 0.22 | **EXTREMO** |

**León (0.22)** es particularmente sospechoso → revisar stats de León como visitante

---

## 📋 Checklist de Implementación

### Prioridad 1 (Inmediato - Jornada 7)

- [ ] Cambio 2A: Reducir `mediocampista` -0.05 → -0.03
- [ ] Cambio 2A: Reducir `atacante` -0.09 → -0.07  
- [ ] Cambio 2B: Subir cap `0.75` → `0.82`

### Prioridad 2 (J7-J8)

- [ ] Cambio 1: Modificar curva shrinkage `/12.0` → `/18.0`
- [ ] Validar impacto midiendo avg_lambda J7 vs. real

### Prioridad 3 (Investigación J8+)

- [ ] Cambio 3: Agregar logging de `defs_curr` por split
- [ ] Revisar equipos con `PJ_away < 3`
- [ ] Considerar threshold mínimo o ventana expandida

---

## 🧪 Validación Post-Cambios

Después de implementar, correr predicciones de J7 y verificar:

```python
# Calcular métricas de diagnóstico
lambdas_j7 = [...]  # extraer de predicciones J7

avg_lambda_home_j7 = mean(lambdas_home)
avg_lambda_away_j7 = mean(lambdas_away)
avg_lambda_total_j7 = avg_lambda_home_j7 + avg_lambda_away_j7

# Comparar con real del Clausura 2026:
# - Real home: 1.42
# - Real away: 1.11
# - Real total: 2.53

# Target post-calibración: 2.50 - 2.60 goles/partido
```

**Criterio de éxito:**

- `|avg_lambda_total - 2.53| < 0.15` → Calibración exitosa
- Si `avg_lambda_total < 2.38` → Ajustar más (considerar shrinkage a /20.0)
- Si `avg_lambda_total > 2.70` → Sobre-corrección, revertir parcialmente

---

## 📌 Valores de Referencia

### Estadísticas Reales Clausura 2026 (J1-J5)

- Goles local promedio: **1.4222**
- Goles visitante promedio: **1.1111**
- Goles total promedio: **2.5333**
- % Empates 0-0: **13.33%**

### Modelo Actual (Jornada 6)

- Lambda local promedio: **1.2185** (-14.3%)
- Lambda visitante promedio: **0.8487** (-23.6%)
- Lambda total promedio: **2.0673** (-18.4%)
- % 0-0 predicho: **11.72%** (OK - dentro de rango)

### Modelo Objetivo Post-Calibración

- Lambda total: **2.50 - 2.60** (+0.47 ajuste)
- Distribución: 55-58% local / 42-45% visitante
- % 0-0: mantener en 11-14% (no requiere ajuste)
