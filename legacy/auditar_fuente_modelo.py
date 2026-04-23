
import os
import ast
import glob

# Configuración
SEARCH_DIR = "."
OUTPUT_FILE = "audit_model_source.txt"
TARGET_FUNCTION = "compute_components_and_lambdas"
TARGET_VARS = ["lambda_home_base", "lambda_away_base"]
MODEL_FILE = "modelo.py"

def scan_file_imports_and_defs(filepath):
    """
    Analiza un archivo Python para encontrar:
    - Imports de 'modelo'
    - Definiciones de funciones (TARGET_FUNCTION)
    - Asignaciones a variables target
    """
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        try:
            tree = ast.parse(f.read(), filename=filepath)
        except SyntaxError:
            return None

    results = {
        "file": filepath,
        "imports_modelo": [],
        "defines_function": [],
        "assigns_vars": [],
        "imports_target_func": []
    }

    for node in ast.walk(tree):
        # Check Imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "modelo" in alias.name:
                    results["imports_modelo"].append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and "modelo" in node.module:
                results["imports_modelo"].append(node.module)
            # Check if importing the target function from somewhere
            for alias in node.names:
                if alias.name == TARGET_FUNCTION:
                    results["imports_target_func"].append(f"from {node.module} import {alias.name}")

        # Check Function Defs
        if isinstance(node, ast.FunctionDef):
            if node.name == TARGET_FUNCTION:
                results["defines_function"].append(node.lineno)

        # Check Assignments (heuristic for variable usage)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id in TARGET_VARS:
                        results["assigns_vars"].append((target.id, node.lineno))

    return results

def main():
    print("=== AUDITORIA DE FUENTE DEL MODELO ===\n")
    report_lines = []
    
    # 1. Verificar existencia de modelo.py
    model_path = os.path.join(SEARCH_DIR, MODEL_FILE)
    if os.path.exists(model_path):
        msg = f"[INFO] {MODEL_FILE} EXISTE en {model_path}"
        print(msg)
        report_lines.append(msg)
    else:
        msg = f"[INFO] {MODEL_FILE} NO EXISTE en directorio actual."
        print(msg)
        report_lines.append(msg)

    # 2. Escanear archivos .py
    py_files = glob.glob(os.path.join(SEARCH_DIR, "**", "*.py"), recursive=True)
    
    definitions = []
    usages = []
    modelo_imports = []

    for py_file in py_files:
        if "venv" in py_file or "site-packages" in py_file:
            continue
            
        res = scan_file_imports_and_defs(py_file)
        if not res: continue

        if res["defines_function"]:
            definitions.append((py_file, res["defines_function"]))
        
        if res["imports_modelo"]:
            modelo_imports.append((py_file, res["imports_modelo"]))
            
        if res["imports_target_func"]:
            usages.append((py_file, res["imports_target_func"]))
            
        # Check for textual usage of diagnostico_lambda usage in imports
        # (AST covers this via ImportFrom, but let's be robust about 'import diagnostico_lambda')
        # We'll rely on the AST 'imports_target_func' for specific function imports, 
        # but broadly we want to see who imports the DEFINER.

    # 3. Identificar Fuente de Verdad
    print("\n--- FUENTE DE VERDAD ---")
    report_lines.append("\n--- FUENTE DE VERDAD ---")
    
    source_of_truth = None
    if len(definitions) == 0:
        msg = f"[ERROR] NO se encontró definición de '{TARGET_FUNCTION}' en ningún archivo."
        print(msg)
        report_lines.append(msg)
    elif len(definitions) == 1:
        source_of_truth = definitions[0][0]
        msg = f"[OK] ÚNICA definición encontrada en: {source_of_truth} (Líneas: {definitions[0][1]})"
        print(msg)
        report_lines.append(msg)
    else:
        msg = f"[WARNING] MÚLTIPLES definiciones encontradas:"
        print(msg)
        report_lines.append(msg)
        for d in definitions:
            line = f"  - {d[0]} en líneas {d[1]}"
            print(line)
            report_lines.append(line)
        # Heuristic: diagnostico_lambda is likely the one we are using
        for d in definitions:
            if "diagnostico_lambda" in d[0]:
                source_of_truth = d[0]
                break

    # 4. Verificar Consistencia en Consumidores Clave
    print("\n--- CONSUMIDORES CLAVE ---")
    report_lines.append("\n--- CONSUMIDORES CLAVE ---")
    
    key_consumers = ["gen_predicciones.py", "gen_reporte_tecnico.py", "diagnostico_lambda.py"]
    
    for consumer in key_consumers:
        if not os.path.exists(consumer):
            continue
            
        # Check import logic simply by reading file text to see where it comes from
        # AST is better but straightforward text search for "from X import compute..." or "import X"
        with open(consumer, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if consumer == "diagnostico_lambda.py":
             # Check if any definition file ends with this consumer name
             is_definer = any(d[0].endswith(consumer) for d in definitions)
             if is_definer:
                 msg = f"{consumer}: ES LA FUENTE DE VERDAD (Define la función localmente)."
             else:
                 msg = f"{consumer}: [ERROR] No define ni importa claramente la función (investigar)."
        else:
            if "diagnostico_lambda" in content and ("import diagnostico_lambda" in content or "from diagnostico_lambda" in content):
                 msg = f"{consumer}: Importa de 'diagnostico_lambda' [OK]"
            elif "modelo" in content and "import modelo" in content:
                 msg = f"{consumer}: [ERROR] Importa de 'modelo' (Deprecated?)"
            else:
                 msg = f"{consumer}: [WARNING] No se detectó import claro de la fuente de verdad."
                 
        print(msg)
        report_lines.append(msg)

    # 5. Reporte de Imports Obsoletos a modelo.py
    if modelo_imports:
        print("\n--- IMPORTS A modelo.py DETECTADOS (POSIBLE USO OBSOLETO) ---")
        report_lines.append("\n--- IMPORTS A modelo.py DETECTADOS ---")
        for f, imps in modelo_imports:
            l = f"  - {f} importa: {imps}"
            print(l)
            report_lines.append(l)
    else:
        print("\n--- No se detectaron imports activos a 'modelo' ---")
        report_lines.append("\n--- No se detectaron imports activos a 'modelo' ---")

    # Guardar reporte
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(report_lines))
    print(f"\nReporte guardado en {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
