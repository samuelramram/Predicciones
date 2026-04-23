# Cómo calcula predicciones este modelo (explicado fácil)

Piensa que el modelo hace 6 pasos sencillos:

## 1) Junta la información
Toma cuatro fuentes principales:
- partidos de la jornada a pronosticar,
- historial de goles de la liga,
- bajas/lesiones/sanciones (incluyendo feed semanal de Perplexity),
- contexto cualitativo (transferencias, noticias relevantes).

## 2) Limpia nombres de equipos
Normaliza nombres para que "América", "Club América" y variaciones se vuelvan el mismo equipo.
Así evita duplicados o errores por escritura.

## 3) Calcula la fuerza de cada equipo
Para cada equipo estima:
- qué tan fuerte ataca,
- qué tan fuerte defiende,
- y separa local/visita.

No usa solo partidos recientes: mezcla temporada actual con torneos anteriores (multi-torneo) para no reaccionar de más a rachas cortas.

## 4) Ajusta por contexto real
Aplica multiplicadores por bajas importantes y situaciones cualitativas.
Ejemplo: si falta un defensa clave, sube la expectativa de gol del rival.

## 5) Convierte eso en goles esperados (lambdas)
Con las fuerzas anteriores calcula cuántos goles se esperan de local y visitante.
Ese par de valores (`lambda_home`, `lambda_away`) es la base matemática de la predicción.

## 6) Elige el pick para maximizar puntos de quiniela
Con distribución Poisson genera probabilidades de marcadores.
Luego escoge el marcador que maximiza:

**EV = Probabilidad del resultado (1/X/2) + Probabilidad del exacto**

Esto está alineado con tu sistema:
- 2 puntos por exacto,
- 1 punto por acertar ganador/empate.

Además usa una grilla de goles adaptativa y normaliza probabilidades para reducir sesgo cuando se corta la cola de marcadores muy altos.

---

## Qué más conviene considerar para mejorar precisión
1. **Backtesting histórico por puntos de quiniela** (no solo por error estadístico).
2. **Calibración de probabilidades** (que 60% realmente ocurra ~60% del tiempo).
3. **Modelo con sobre-dispersión** (Negative Binomial o Dixon-Coles) para mejorar exactos.
4. **Ajustes de hiperparámetros automáticos** por validación temporal.
5. **Control de riesgo en picks** (si buscas ganar concurso grande, no solo acertar promedio).
