# Mejoras propuestas al modelo para ganar quiniela (2 exacto / 1 resultado)

## 1) Lo que ya está bien
- Ajustes por bajas y contexto cualitativo.
- Priors multi-torneo con shrinkage.
- Cálculo centralizado de lambdas en `core`.

## 2) Mejora aplicada en este cambio
### Optimización explícita por función de puntos de quiniela
Se agregó un optimizador de picks que maximiza directamente:

- **EV(score) = P(resultado de score) + P(score exacto)**

Esto está alineado con tu scoring:
- Exacto = 2 puntos
- Solo resultado = 1 punto

Además se usa una grilla Poisson adaptativa (no fija 0-5) para evitar sesgo por truncamiento cuando los lambdas son altos.

## 3) Mejoras recomendadas siguientes (prioridad)
1. **Backtest por jornada con scoring real**
   - Simular picks históricos y medir puntos promedio por partido / varianza.
   - Comparar versión actual vs variantes de hiperparámetros.

2. **Calibración probabilística**
   - Verificar calibración de 1X2 y exactos (reliability curves, Brier/logloss).
   - Ajustar clamps y `LEAGUE_AVG_K`, `BLEND_K`, `BAYES_ALPHA_*` por validación temporal.

3. **Modelo de goles con sobre-dispersión**
   - Probar Negative Binomial o Poisson bivariado / Dixon-Coles para mejorar exactos.

4. **Selección de pick con control de riesgo**
   - En concursos masivos, incluir un componente de "diferenciación" (contrarian) para evitar picks demasiado populares.

5. **Automatizar ranking de configuraciones**
   - Grid/Optuna sobre hiperparámetros, optimizando puntos de quiniela en backtest rolling-origin.

## 4) Métrica objetivo sugerida
- Primaria: **Puntos de quiniela promedio por partido**.
- Secundarias:
  - % acierto exacto
  - % acierto resultado
  - robustez por jornada (std)

## 5) Conclusión
Con esta mejora, el pick deja de ser “score más probable” y pasa a ser “score con mayor valor esperado de puntos”, que es exactamente tu objetivo competitivo.
