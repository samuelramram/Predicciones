# Organización del repositorio (modelo final)

## Entrada principal
- **Script único en raíz para ejecución final:** `run_pipeline.py`

## Estructura operativa
- `app/steps/`:
  - `gen_predicciones.py`
  - `gen_reporte_tecnico.py`
  - `diagnostico_lambda.py`
- `src/predicciones/`: librería del modelo (core, config, data, utils, quiniela)
- `data/inputs/`: insumos activos del pipeline por jornada
- `outputs/`: salidas generadas del pipeline

## Estructura de soporte
- `data/raw/`: datos crudos API u orígenes intermedios
- `data/archive/`: archivos de datos obsoletos o no requeridos por el flujo canónico
- `docs/archive/`: documentación histórica/no operativa
- `legacy/`: scripts y resultados antiguos fuera del flujo productivo
- `scripts/`: utilidades auxiliares de mantenimiento

## Archivos marcados como obsoletos/no canónicos
- En `legacy/` y `legacy/unused_tools/`.
- En `data/archive/` (ej. caches/insumos ya reemplazados).
- En `docs/archive/` (bitácoras/prompts históricos).

## Convención de operación
Ejecutar siempre:

```bash
python run_pipeline.py --jornada 6
```

No ejecutar directamente scripts en `legacy/` ni utilitarios en `legacy/unused_tools/` para flujo de producción.
