"""
PIPELINE CANON DE PREDICCIONES
Ejecuta la secuencia completa de generación de predicciones y reportes.
Fuente de Verdad: src.predicciones.core
"""

import argparse
import json
import os
import sys
import subprocess
import hashlib
from datetime import datetime

# Reconfigure stdout to UTF-8 so subprocess output with emojis (✅ ⚠️) can be
# reprinted on Windows without hitting the cp1252 codec limit.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')


import src.predicciones.config as config
import src.predicciones.utils as utils


def calculate_file_hash(filepath):
    """Calcula SHA256 de un archivo."""
    if not os.path.exists(filepath):
        return "FILE_NOT_FOUND"

    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def check_legacy_guard():
    """Detecta archivos legacy peligrosos en raíz."""
    legacy_files = ["diagnostico_visitante.py", "modelo.py"]
    found = [f for f in legacy_files if os.path.exists(f)]

    if found:
        print("\n" + "!" * 80)
        print("WARNING: LEGACY SCRIPT DETECTED")
        for filename in found:
            print(f"  - {filename}")
        print("DO NOT USE THESE FILES. THEY CONTAIN OUTDATED LOGIC.")
        print("SUGGESTION: Move them to the legacy folder or delete them.")
        print("!" * 80 + "\n")
        return False
    return True


def validate_runtime_imports():
    """Valida que el core sea el correcto."""
    print("-" * 80)
    print("VALIDACION DE RUNTIME")

    import src.predicciones.core as core
    print(f"CORE IMPORTADO: {core.__file__}")

    if hasattr(core, 'compute_components_and_lambdas'):
        print("  [OK] compute_components_and_lambdas existe en core")
        print("-" * 80)
        return True

    print("  [ERROR] compute_components_and_lambdas NO encontrado en core")
    print("-" * 80)
    return False


def check_dependencies():
    """Preflight de dependencias para evitar fallas a mitad del pipeline."""
    print("-" * 80)
    print("PREFLIGHT DE DEPENDENCIAS")

    required_modules = ["pandas", "scipy"]
    missing = []

    for module_name in required_modules:
        try:
            __import__(module_name)
            print(f"  [OK] {module_name}")
        except ModuleNotFoundError:
            print(f"  [ERROR] falta dependencia: {module_name}")
            missing.append(module_name)

    print("-" * 80)
    return missing


def validate_inputs(cfg):
    """Valida inputs críticos declarados por configuración."""
    print("-" * 80)
    print("PREFLIGHT DE INPUTS")

    required = [
        cfg['INPUT_MATCHES'],
        cfg['INPUT_STATS'],
        cfg['INPUT_EVALUATION'],
        cfg['INPUT_QUALITATIVE'],
    ]

    all_ok = True
    for filepath in required:
        if os.path.exists(filepath):
            print(f"  [OK] {filepath}")
        else:
            print(f"  [ERROR] no existe: {filepath}")
            all_ok = False

    print("-" * 80)
    return all_ok


def run_step(script_name, description, env):
    """Ejecuta un script de python como subprocess."""
    print(f"\n>>> EJECUTANDO: {description} ({script_name})...")
    start_time = datetime.now()

    try:
        result = subprocess.run(
            ["python", script_name],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            env=env,
        )
        print(f"  [OK] Completado en {datetime.now() - start_time}")
        lines = result.stdout.splitlines()
        for line in lines[:3]:
            print(f"  > {line}")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"  [ERROR] Falló ejecución de {script_name}")
        print("  STDOUT:", exc.stdout)
        print("  STDERR:", exc.stderr)
        return False


def parse_args():
    parser = argparse.ArgumentParser(description="Pipeline canónico de predicciones")
    parser.add_argument("--jornada", type=int, default=None, help="Jornada a procesar")
    return parser.parse_args()


def main():
    timestamp_start = datetime.now()
    args = parse_args()
    cfg = config.resolve_config(args.jornada)

    print("=" * 80)
    print(f"INICIANDO PIPELINE CANON - {timestamp_start}")
    print(f"JORNADA OBJETIVO: {cfg['JORNADA']}")
    print("=" * 80)

    check_legacy_guard()

    if not validate_runtime_imports():
        sys.exit(1)

    missing_modules = check_dependencies()
    if missing_modules:
        print(f"\nPipeline ABORTADO por dependencias faltantes: {', '.join(missing_modules)}")
        sys.exit(1)

    if not validate_inputs(cfg):
        print("\nPipeline ABORTADO por inputs faltantes.")
        sys.exit(1)

    os.makedirs("outputs", exist_ok=True)

    env = os.environ.copy()
    env["PRED_JORNADA"] = str(cfg['JORNADA'])
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"

    steps = [
        ("app/steps/gen_predicciones.py", "Generación de CSV de Predicciones"),
        ("app/steps/gen_reporte_tecnico.py", "Generación de Reporte Markdown"),
        ("app/steps/diagnostico_lambda.py", "Auditoría de Sistema (Diagnóstico)"),
    ]

    for script, desc in steps:
        if not run_step(script, desc, env):
            print("\nPipeline ABORTADO por error.")
            sys.exit(1)

    print("\n" + "=" * 80)
    print("RESUMEN DE EJECUCIÓN")
    print("=" * 80)

    jornada = cfg['JORNADA']
    fingerprint = {
        'timestamp': datetime.now().isoformat(),
        'config_version': '2026.02.12',
        'jornada': jornada,
        'git_commit': utils.get_git_commit(),
        'git_dirty': utils.is_git_dirty(),
        'input_hashes': {
            'stats': calculate_file_hash(cfg['INPUT_STATS']),
            'matches': calculate_file_hash(cfg['INPUT_MATCHES']),
            'bajas': calculate_file_hash(cfg['INPUT_EVALUATION']),
            'qualitative': calculate_file_hash(cfg['INPUT_QUALITATIVE']),
        },
        'config_hash': utils.calculate_config_hash(cfg),
        'output_hashes': {}
    }

    print("-" * 80)
    print("CALCULO DE HASHES SHA-256 (Determinismo)")

    files_to_hash = [
        f"outputs/predicciones_jornada_{jornada}_final.csv",
        f"outputs/reporte_tecnico_jornada_{jornada}.md",
        cfg['OUTPUT_TXT'],
        cfg['OUTPUT_CSV'],
    ]

    for filepath in files_to_hash:
        file_hash = calculate_file_hash(filepath)
        fingerprint['output_hashes'][filepath] = file_hash
        print(f"  {filepath:<35} : {file_hash}")

    fp_filename = f"outputs/fingerprint_jornada_{jornada}.json"
    with open(fp_filename, 'w', encoding='utf-8') as fp_file:
        json.dump(fingerprint, fp_file, indent=2)
    print(f"\n[OK] Fingerprint guardado: {fp_filename}")

    print("-" * 80)
    print(f"PIPELINE FINALIZADO EN {datetime.now() - timestamp_start}")
    print("=" * 80)
    print("PIPELINE COMPLETADO EXITOSAMENTE")


if __name__ == "__main__":
    main()
