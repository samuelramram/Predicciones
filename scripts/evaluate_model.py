"""
evaluate_model.py
=================
Tres diagnósticos acumulativos del modelo:

  1. ANTI-LEAKAGE AUDIT
     Verifica que los timestamps de los JSONs de bajas (evaluacion_bajas.json
     y perplexity_bajas_semana.json) sean anteriores al kickoff más temprano
     de la jornada. Previene sesgo silencioso.

  2. LOG-LOSS ACUMULADO POR JORNADA
     Calcula -log(p_outcome) para cada partido donde existen tanto
     predicciones (CSV) como resultados (historial_usuario.json).
     Empieza el hábito ahora; con 100+ partidos será valioso.

  3. PODER PREDICTIVO DE LAS LAMBDAS
     Analiza: cuando λ_home > λ_away, ¿el modelo acertó el resultado 1X2
     más seguido? Diagnóstico directo del signal de las lambdas.

Uso:
    python scripts/evaluate_model.py
    python scripts/evaluate_model.py --jornada 9   # audit de una jornada específica
    python scripts/evaluate_model.py --seccion leakage
    python scripts/evaluate_model.py --seccion logloss
    python scripts/evaluate_model.py --seccion lambdas
"""

import os
import sys
import json
import math
import glob
import argparse
from datetime import datetime, timezone

# ── Añadir raíz del proyecto al path ─────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.predicciones.core import canonical_team_name

# ── Rutas por defecto ──────────────────────────────────────────────────────────
HISTORIAL_PATH      = os.path.join(ROOT, "data", "historial_usuario.json")
BAJAS_EVAL_PATH     = os.path.join(ROOT, "data", "inputs", "evaluacion_bajas.json")
BAJAS_PERP_PATH     = os.path.join(ROOT, "data", "inputs", "perplexity_bajas_semana.json")
PREDICTIONS_GLOB    = os.path.join(ROOT, "outputs", "predicciones_jornada_*_final.csv")
JORNADA_JSON_GLOB   = os.path.join(ROOT, "data", "inputs", "jornada_*_final.json")

SEPARATOR = "=" * 65


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _parse_dt(s):
    """Parsea ISO-8601 con o sin Z/+offset. Devuelve datetime naive (local)."""
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        # Convertir a naive local para comparar con kickoffs sin timezone
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_predictions_csv(path):
    """Lee CSV de predicciones sin pandas para evitar dependencia extra."""
    import csv
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _outcome_from_result(result_str):
    """'2-1' → '1', '1-1' → 'X', '0-2' → '2'"""
    try:
        gh, ga = map(int, result_str.strip().split("-"))
        if gh > ga:
            return "1"
        elif gh < ga:
            return "2"
        else:
            return "X"
    except Exception:
        return None


def _jornada_from_filename(fname):
    """'predicciones_jornada_8_final.csv' → 8"""
    try:
        parts = os.path.basename(fname).split("_")
        return int(parts[2])
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════
# 1. ANTI-LEAKAGE AUDIT
# ═══════════════════════════════════════════════════════════════════

def audit_leakage(jornada_filter=None):
    print(f"\n{SEPARATOR}")
    print("  SECCIÓN 1: ANTI-LEAKAGE AUDIT")
    print(SEPARATOR)
    print("  Verifica que los datos de bajas se generaron ANTES de los kickoffs.\n")

    # Cargar todos los JSONs de jornada
    jornada_files = sorted(glob.glob(JORNADA_JSON_GLOB))
    if not jornada_files:
        print("  [ERROR] No se encontraron archivos jornada_*_final.json")
        return

    # Si no hay filtro explícito, solo auditar la JORNADA MÁS RECIENTE.
    # Los archivos de bajas son semanales y se sobreescriben; comparar el
    # archivo actual contra kickoffs de jornadas pasadas produce falsos positivos.
    if jornada_filter is None:
        all_jornadas = []
        for jf in jornada_files:
            d = _load_json(jf)
            if d and d.get("jornada"):
                all_jornadas.append(d.get("jornada"))
        if all_jornadas:
            jornada_filter = max(all_jornadas)
            print(f"  (Auditando solo jornada {jornada_filter}. Usa --jornada N para otra.)\n")

    issues_found = 0

    for jfile in jornada_files:
        jdata = _load_json(jfile)
        if not jdata:
            continue

        jornada_num = jdata.get("jornada")
        if jornada_filter and jornada_num != jornada_filter:
            continue

        matches = jdata.get("matches", [])
        kickoffs = []
        for m in matches:
            ko_str = m.get("match", {}).get("kickoff_datetime")
            ko_dt  = _parse_dt(ko_str)
            if ko_dt:
                kickoffs.append((ko_dt, m["match"].get("home", "?"), m["match"].get("away", "?")))

        if not kickoffs:
            print(f"  J{jornada_num}: Sin kickoffs con timestamp — omitida.")
            continue

        earliest_ko, ko_home, ko_away = min(kickoffs, key=lambda x: x[0])
        print(f"  Jornada {jornada_num}")
        print(f"  Kickoff más temprano : {earliest_ko.strftime('%Y-%m-%d %H:%M')}  ({ko_home} vs {ko_away})")

        # ── Revisar evaluacion_bajas.json ──────────────────────────
        eval_data = _load_json(BAJAS_EVAL_PATH)
        if eval_data:
            meta_jornada = eval_data.get("meta", "")
            gen_str = eval_data.get("generated_at")
            if not gen_str:
                mtime = os.path.getmtime(BAJAS_EVAL_PATH)
                gen_dt = datetime.fromtimestamp(mtime)
                fuente = "mtime de archivo"
            else:
                gen_dt  = _parse_dt(gen_str)
                fuente  = "campo generated_at"

            if gen_dt:
                ok = gen_dt < earliest_ko
                tag = "OK" if ok else "LEAKAGE POTENCIAL"
                symbol = "✓" if ok else "✗"
                diff_h = (earliest_ko - gen_dt).total_seconds() / 3600
                print(f"  evaluacion_bajas.json [{fuente}]")
                print(f"    generated_at : {gen_dt.strftime('%Y-%m-%d %H:%M')}")
                print(f"    Margen       : {diff_h:+.1f}h antes del kickoff")
                print(f"    {symbol} {tag}")
                if not ok:
                    issues_found += 1
            else:
                print("  evaluacion_bajas.json : [ADVERTENCIA] Sin timestamp resoluble")
                issues_found += 1
        else:
            print("  evaluacion_bajas.json : [NO ENCONTRADO]")

        # ── Revisar perplexity_bajas_semana.json ───────────────────
        perp_data = _load_json(BAJAS_PERP_PATH)
        if perp_data:
            gen_str = perp_data.get("generated_at")
            gen_dt  = _parse_dt(gen_str)
            bajas   = perp_data.get("bajas", [])

            if gen_dt:
                ok = gen_dt < earliest_ko
                tag = "OK" if ok else "LEAKAGE POTENCIAL"
                symbol = "✓" if ok else "✗"
                diff_h = (earliest_ko - gen_dt).total_seconds() / 3600
                print(f"  perplexity_bajas.json  [campo generated_at]")
                print(f"    generated_at : {gen_dt.strftime('%Y-%m-%d %H:%M')}")
                print(f"    Margen       : {diff_h:+.1f}h antes del kickoff")
                print(f"    {symbol} {tag}")
                if not ok:
                    issues_found += 1

            # Revisar last_verified_at por baja individual
            leaky_bajas = []
            for b in bajas:
                lv_str = b.get("last_verified_at")
                lv_dt  = _parse_dt(lv_str)
                if lv_dt and lv_dt >= earliest_ko:
                    leaky_bajas.append((b.get("team", "?"), b.get("player", "?"), lv_dt))

            if leaky_bajas:
                print(f"  [ADVERTENCIA] {len(leaky_bajas)} baja(s) con last_verified_at >= kickoff:")
                for team, player, lv_dt in leaky_bajas:
                    print(f"    - {team} / {player}  →  {lv_dt.strftime('%Y-%m-%d %H:%M')}")
                issues_found += len(leaky_bajas)
            else:
                print(f"  ✓ Todas las bajas individuales verificadas antes del kickoff ({len(bajas)} revisadas)")
        else:
            print("  perplexity_bajas.json : [NO ENCONTRADO]")

        print()

    if issues_found == 0:
        print("  RESULTADO: Sin problemas de leakage detectados.")
    else:
        print(f"  RESULTADO: {issues_found} problema(s) de leakage detectado(s). Revisar arriba.")


# ═══════════════════════════════════════════════════════════════════
# 2. LOG-LOSS ACUMULADO POR JORNADA
# ═══════════════════════════════════════════════════════════════════

def compute_logloss():
    print(f"\n{SEPARATOR}")
    print("  SECCIÓN 2: LOG-LOSS ACUMULADO POR JORNADA")
    print(SEPARATOR)
    print("  Log-loss = -log(p_outcome_real)   [menor es mejor; ~1.10 = azar]\n")

    historial = _load_json(HISTORIAL_PATH)
    if not historial:
        print("  [ERROR] No se encontró historial_usuario.json")
        return

    # Construir mapa: (jornada, home_canon, away_canon) → resultado
    result_map = {}
    for entry in historial.get("history", []):
        jornada = entry["jornada"]
        for m in entry.get("matches", []):
            h = canonical_team_name(m["home"])
            a = canonical_team_name(m["away"])
            result_map[(jornada, h, a)] = m["result"]

    # Cargar todos los CSVs de predicciones
    csv_files = sorted(glob.glob(PREDICTIONS_GLOB))
    if not csv_files:
        print("  [ERROR] No se encontraron CSVs de predicciones.")
        return

    EPSILON = 1e-9   # evitar log(0)

    all_rows   = []   # (jornada, home, away, loss, outcome, pick, p_home, p_draw, p_away)
    cumulative = 0.0
    total_matches = 0

    jornada_stats = []  # (jornada, n, mean_loss, cumulative)

    for cpath in csv_files:
        jornada = _jornada_from_filename(cpath)
        if jornada is None:
            continue

        rows = _load_predictions_csv(cpath)
        losses = []

        for row in rows:
            h = row.get("home_team_canonical", "").strip()
            a = row.get("away_team_canonical", "").strip()
            key = (jornada, h, a)

            if key not in result_map:
                continue

            result = result_map[key]
            outcome = _outcome_from_result(result)
            if outcome is None:
                continue

            try:
                p_home = float(row["prob_home_win"])
                p_draw = float(row["prob_draw"])
                p_away = float(row["prob_away_win"])
            except (KeyError, ValueError):
                continue

            p_map = {"1": p_home, "X": p_draw, "2": p_away}
            p_true = max(p_map[outcome], EPSILON)
            loss   = -math.log(p_true)

            losses.append(loss)
            all_rows.append({
                "jornada": jornada,
                "home": h,
                "away": a,
                "result": result,
                "outcome": outcome,
                "pick": row.get("pick_1x2", "?"),
                "p_home": p_home,
                "p_draw": p_draw,
                "p_away": p_away,
                "loss": loss,
            })

        if losses:
            n          = len(losses)
            mean_loss  = sum(losses) / n
            total_matches += n
            cumulative += sum(losses)
            jornada_stats.append((jornada, n, mean_loss, cumulative / total_matches))

    if not jornada_stats:
        print("  Sin partidos con predicciones Y resultados disponibles.")
        print("  (Las jornadas en el historial necesitan CSVs de predicciones correspondientes)")
        return

    # Tabla resumen
    print(f"  {'Jornada':>8}  {'N':>4}  {'LL media':>10}  {'LL acum':>10}  {'vs azar':>8}")
    print(f"  {'-'*8}  {'-'*4}  {'-'*10}  {'-'*10}  {'-'*8}")
    RANDOM_LL = math.log(3)  # ~1.099 — log-loss de un modelo que dice 1/3 para todo

    for jornada, n, mean_ll, cum_ll in jornada_stats:
        delta = cum_ll - RANDOM_LL
        sign  = "+" if delta > 0 else ""
        print(f"  {'J'+str(jornada):>8}  {n:>4}  {mean_ll:>10.4f}  {cum_ll:>10.4f}  {sign}{delta:>+.4f}")

    print()
    final_cum = jornada_stats[-1][3]
    print(f"  Log-loss acumulado final : {final_cum:.4f}")
    print(f"  Referencia azar (1/3/1/3/1/3): {RANDOM_LL:.4f}")
    if final_cum < RANDOM_LL:
        diff = RANDOM_LL - final_cum
        print(f"  RESULTADO: Modelo MEJOR que azar por {diff:.4f} puntos de log-loss.")
    else:
        diff = final_cum - RANDOM_LL
        print(f"  RESULTADO: Modelo PEOR que azar por {diff:.4f} puntos (muestra pequeña — normal al inicio).")

    # Detalle por partido
    print(f"\n  Detalle por partido:")
    print(f"  {'J':>2}  {'Home':<22}  {'Away':<22}  {'Res':>5}  {'Pick':>4}  {'p_pred':>7}  {'Loss':>7}")
    print(f"  {'-'*2}  {'-'*22}  {'-'*22}  {'-'*5}  {'-'*4}  {'-'*7}  {'-'*7}")
    for r in sorted(all_rows, key=lambda x: x["jornada"]):
        p_pred = {"1": r["p_home"], "X": r["p_draw"], "2": r["p_away"]}[r["outcome"]]
        correct = "✓" if r["pick"] == r["outcome"] else " "
        print(f"  {r['jornada']:>2}  {r['home']:<22}  {r['away']:<22}  "
              f"{r['result']:>5}  {r['pick']:>4}{correct} {p_pred:>7.3f}  {r['loss']:>7.4f}")


# ═══════════════════════════════════════════════════════════════════
# 3. PODER PREDICTIVO DE LAS LAMBDAS
# ═══════════════════════════════════════════════════════════════════

def lambda_power():
    print(f"\n{SEPARATOR}")
    print("  SECCIÓN 3: PODER PREDICTIVO DE LAS LAMBDAS")
    print(SEPARATOR)
    print("  Pregunta: cuando λ_home > λ_away, ¿el equipo local ganó más?\n")

    historial = _load_json(HISTORIAL_PATH)
    if not historial:
        print("  [ERROR] No se encontró historial_usuario.json")
        return

    result_map = {}
    for entry in historial.get("history", []):
        jornada = entry["jornada"]
        for m in entry.get("matches", []):
            h = canonical_team_name(m["home"])
            a = canonical_team_name(m["away"])
            result_map[(jornada, h, a)] = m["result"]

    csv_files = sorted(glob.glob(PREDICTIONS_GLOB))

    # Contadores globales
    total        = 0    # partidos con lambdas + resultado
    lh_gt_la     = 0    # λ_home > λ_away
    lh_gt_la_win = 0    # λ_home > λ_away  Y  home ganó
    la_gt_lh     = 0    # λ_away > λ_home
    la_gt_lh_win = 0    # λ_away > λ_home  Y  away ganó
    equal_l      = 0    # lambdas iguales (raro)

    detail_rows = []

    for cpath in csv_files:
        jornada = _jornada_from_filename(cpath)
        if jornada is None:
            continue

        rows = _load_predictions_csv(cpath)
        for row in rows:
            h = row.get("home_team_canonical", "").strip()
            a = row.get("away_team_canonical", "").strip()
            key = (jornada, h, a)

            if key not in result_map:
                continue

            result  = result_map[key]
            outcome = _outcome_from_result(result)
            if outcome is None:
                continue

            try:
                lh = float(row["lambda_home_final"])
                la = float(row["lambda_away_final"])
            except (KeyError, ValueError):
                continue

            total += 1
            pred_signal = "1" if lh > la else ("2" if la > lh else "eq")
            correct_signal = (pred_signal == outcome) if pred_signal != "eq" else False

            if lh > la:
                lh_gt_la += 1
                if outcome == "1":
                    lh_gt_la_win += 1
            elif la > lh:
                la_gt_lh += 1
                if outcome == "2":
                    la_gt_lh_win += 1
            else:
                equal_l += 1

            detail_rows.append({
                "jornada": jornada,
                "home": h,
                "away": a,
                "lh": lh,
                "la": la,
                "diff": lh - la,
                "signal": pred_signal,
                "result": result,
                "outcome": outcome,
                "correct_signal": correct_signal,
            })

    if total == 0:
        print("  Sin partidos con lambdas Y resultados disponibles.")
        return

    # Tabla resumen
    print(f"  Total partidos analizados : {total}")
    print()

    if lh_gt_la > 0:
        acc_home = lh_gt_la_win / lh_gt_la
        print(f"  λ_home > λ_away  →  {lh_gt_la} partidos  →  local ganó {lh_gt_la_win} ({acc_home:.1%})")
        note = "FUERTE" if acc_home >= 0.55 else ("DÉBIL" if acc_home < 0.40 else "MODERADO")
        print(f"    Signal: {note}")
    else:
        print("  Sin partidos con λ_home > λ_away en la muestra")

    if la_gt_lh > 0:
        acc_away = la_gt_lh_win / la_gt_lh
        print(f"  λ_away > λ_home  →  {la_gt_lh} partidos  →  visitante ganó {la_gt_lh_win} ({acc_away:.1%})")
        note = "FUERTE" if acc_away >= 0.55 else ("DÉBIL" if acc_away < 0.40 else "MODERADO")
        print(f"    Signal: {note}")
    else:
        print("  Sin partidos con λ_away > λ_home en la muestra")

    # Acierto combinado: el equipo con mayor lambda ganó
    combined_correct = lh_gt_la_win + la_gt_lh_win
    combined_total   = lh_gt_la + la_gt_lh
    if combined_total > 0:
        acc_combined = combined_correct / combined_total
        print(f"\n  El equipo con mayor lambda ganó: {combined_correct}/{combined_total} ({acc_combined:.1%})")
        print(f"  Referencia azar (solo victorias ~45% de los partidos): ~45%")
        if acc_combined > 0.50:
            print("  RESULTADO: Las lambdas tienen signal positivo sobre victorias.")
        else:
            print("  RESULTADO: Las lambdas no predicen bien victorias con esta muestra (normal con N pequeño).")

    # Detalle
    print(f"\n  Detalle por partido (ordenado por |λ_home - λ_away|):")
    header = f"  {'J':>2}  {'Home':<20}  {'Away':<20}  {'λH':>5}  {'λA':>5}  {'Señal':>5}  {'Res':>5}  {'OK':>3}"
    print(header)
    print(f"  {'-'*2}  {'-'*20}  {'-'*20}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*3}")
    for r in sorted(detail_rows, key=lambda x: -abs(x["diff"])):
        ok = "✓" if r["correct_signal"] else ("=" if r["signal"] == "eq" else " ")
        print(f"  {r['jornada']:>2}  {r['home']:<20}  {r['away']:<20}  "
              f"{r['lh']:>5.2f}  {r['la']:>5.2f}  {r['signal']:>5}  "
              f"{r['result']:>5}  {ok:>3}")


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Evaluación del modelo de predicciones")
    parser.add_argument("--seccion", choices=["leakage", "logloss", "lambdas"],
                        default=None, help="Ejecutar solo una sección")
    parser.add_argument("--jornada", type=int, default=None,
                        help="Filtrar audit de leakage a una jornada específica")
    args = parser.parse_args()

    print(f"\n{'='*65}")
    print("  EVALUATE_MODEL.PY — Diagnósticos del Modelo")
    print(f"  Fecha de ejecución: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*65}")

    run_all = args.seccion is None

    if run_all or args.seccion == "leakage":
        audit_leakage(jornada_filter=args.jornada)

    if run_all or args.seccion == "logloss":
        compute_logloss()

    if run_all or args.seccion == "lambdas":
        lambda_power()

    print(f"\n{SEPARATOR}\n")


if __name__ == "__main__":
    main()
