# ¿Cómo funciona el Modelo de Predicciones? (Explicación Simplificada)

Este documento explica paso a paso cómo "piensa" el modelo para calcular el resultado de un partido, diseñado para que cualquier persona pueda entender la lógica detrás de los números.

## 1. La Base: ¿Qué tan buenos son normalmente?

Primero, el modelo analiza la historia reciente (torneos anteriores y el actual) para responder dos preguntas básicas sobre cada equipo:

* **Ataque:** ¿Cuántos goles suelen meter? (Comparado con el promedio de la liga).
* **Defensa:** ¿Cuántos goles suelen recibir? (Comparado con el promedio de la liga).

* *Ejemplo:* Si el **América** mete 2 goles por partido y el promedio de la liga es 1.5, su "Fuerza de Ataque" es 1.33 (es un 33% mejor que el promedio).

## 2. El Contexto Actual: ¿Cómo vienen jugando *ahora*?

El modelo no vive del pasado. Le da un peso especial a lo que ha pasado en el **Torneo Actual (Clausura 2026)**.

* Usa una técnica llamada "Suavizado Bayesiano":
  * Si van pocos partidos (ej. jornada 1-3), confía más en la historia (torneos pasados).
  * Si van muchos partidos (ej. jornada 10+), confía casi totalmente en el desempeño actual (Jornada 1-9 del torneo presente).

## 3. El Partido Específico: Choque de Fuerzas

Para un partido específico (ej. **Puebla vs Pumas**), el modelo cruza los datos de ambos:

* **Goles Esperados Puebla** = (Ataque de Puebla) × (Defensa de Pumas) × (Promedio de Goles de Local en la Liga).
* **Goles Esperados Pumas** = (Ataque de Pumas) × (Defensa de Puebla) × (Promedio de Goles de Visitante en la Liga).

Esto nos da un número decimal, por ejemplo: Puebla debería meter **1.2 goles** y Pumas **1.4 goles**. A estos números les llamamos "Lambdas".

## 4. Ajustes "Humanos" y Situacionales (El Toque Fino)

Aquí es donde el modelo se vuelve inteligente y considera factores que una simple tabla de posiciones no ve:

* **Lesiones Clave:** Si falta el goleador estrella o el portero titular, reducimos manualmente su fuerza (ej. ataque -10%).
* **Racha (Nuevo):** Si un equipo viene de ganar sus últimos 5 partidos, le damos un pequeño "bono de confianza/inercia".
* **Factor Cancha:** Si un equipo es invencible en casa (como Toluca en la altura) o visita muy mal, el modelo lo ajusta.

## 5. Simulación (La Quiniela)

Con los números finales ajustados (ej. Puebla 1.15 - Pumas 1.35), el modelo no dice simplemente "Gana Pumas". Usa matemáticas (Distribución de Poisson) para calcular la probabilidad de **todos los marcadores posibles** (0-0, 1-0, 0-1, 2-1, 1-1, etc.).

* **¿Quién gana?** Suma todas las probabilidades de los marcadores donde gana el local, empata o gana la visita.
* **Marcador Más Probable:** Busca el marcador exacto con mayor probabilidad matemática individual (ej. 1-1).
* **Pick Inteligente:** Para la quiniela, busca la opción que maximice los puntos esperados (arriesgarse a un marcador exacto vs ir a la segura con el resultado 1X2).

---
**Resumen:**

1. Datos Históricos
2. * Forma Actual (Torneo Presente)
3. * Ajustes por Lesiones/Contexto (Humanos)
4. -> Simulación Matemática de Goles
5. -> **Predicción Final**
