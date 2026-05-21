# Auditoría y optimización del proceso de predicciones

## Estado actual (post-optimización)
Se implementó un flujo canónico más robusto y explícito para ejecutar predicciones, reporte técnico y diagnóstico en una sola corrida controlada.

## Workflow canónico definitivo
1. `run_pipeline.py --jornada <N>`
2. Preflight automático:
   - Validación de import/runtime del core
   - Validación de dependencias (`pandas`, `scipy`)
   - Validación de inputs requeridos por jornada
3. Ejecución secuencial:
   - `gen_predicciones.py`
   - `gen_reporte_tecnico.py`
   - `diagnostico_lambda.py`
4. Generación de `fingerprint_jornada_<N>.json` con hashes de entradas/salidas.

## Lógica consolidada
- La lógica de cálculo permanece centralizada en `src/predicciones/core.py`.
- Los scripts consumidores usan configuración dinámica por jornada mediante `resolve_config()`.
- `run_pipeline.py` propaga `PRED_JORNADA` a todos los subprocesos para mantener consistencia de configuración.

## Archivos realmente involucrados
### Ejecutables canónicos
- `run_pipeline.py`
- `gen_predicciones.py`
- `gen_reporte_tecnico.py`
- `diagnostico_lambda.py`

### Librería activa
- `src/predicciones/config.py`
- `src/predicciones/core.py`
- `src/predicciones/data.py`
- `src/predicciones/utils.py`

### Inputs requeridos por jornada
- `jornada_<N>_final.json`
- `Investigacion_cualitativa_jornada<N>.json`
- `evaluacion_bajas.json`
- `Stats_liga_mx.json`

### Outputs
- `predicciones_jornada_<N>_final.csv`
- `reporte_tecnico_jornada_<N>.md`
- `diagnostico_lambda_components.csv`
- `diagnostico_report.txt`
- `fingerprint_jornada_<N>.json`

## Incongruencias corregidas
- `run_pipeline.py` ya importa `json`.
- `run_pipeline.py` ya define `timestamp_start`.
- Se agregó preflight de dependencias para fallar temprano con mensaje claro.
- Se parametrizó jornada para evitar dependencia rígida de `CONFIG = get_config(6)`.

## Código no involucrado (oculto)
Los utilitarios fuera del flujo canónico se movieron a `legacy/unused_tools/` para reducir ruido operativo y evitar ejecuciones accidentales.

## Recomendación operativa
Usar exclusivamente:

```bash
python run_pipeline.py --jornada 6
```

y tratar el resto de scripts fuera del flujo como soporte histórico o tooling secundario.
