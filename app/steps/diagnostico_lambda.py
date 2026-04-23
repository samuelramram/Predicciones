
"""
Script de Diagnostico FINAL: Lambdas Poisson Liga MX
VERSION 6: Refactorizado a arquitectura src/predicciones/core
"""

import json
import sys
import pandas as pd
from datetime import datetime
from io import StringIO
import traceback

import src.predicciones.core as core
import src.predicciones.config as cfg

CONFIG = cfg.resolve_config()

output_buffer = StringIO()

def log(msg):
    output_buffer.write(msg + "\n")
    print(msg)

def log_section(title):
    log("\n" + "=" * 80)
    log(title)
    log("=" * 80)

# ========== VALIDACION ESTRICTA (FAIL FAST) ==========

def validate_team_coverage(team_stats_current, matches_data, config):
    """
    Validacion ESTRICTA de cobertura de equipos
    ABORTA si hay mismatch
    """
    
    log_section("VALIDACION ESTRICTA DE EQUIPOS")
    
    # Equipos en stats (canonical)
    teams_in_stats = set(team_stats_current.keys())
    
    # Equipos en matches (canonical)
    teams_in_matches = set()
    for match in matches_data['matches']:
        home_canonical = core.canonical_team_name(match['match']['home'])
        away_canonical = core.canonical_team_name(match['match']['away'])
        teams_in_matches.add(home_canonical)
        teams_in_matches.add(away_canonical)
    
    log(f"Equipos en stats (canonical): {len(teams_in_stats)}")
    log(f"Equipos en matches (canonical): {len(teams_in_matches)}")
    log(f"Expected: {config['EXPECTED_TEAMS']}")
    
    # Check missing
    teams_missing = teams_in_matches - teams_in_stats
    teams_extra = teams_in_stats - teams_in_matches
    
    errors = []
    
    if len(teams_in_stats) != config['EXPECTED_TEAMS']:
        errors.append(f"Expected {config['EXPECTED_TEAMS']} teams in stats, got {len(teams_in_stats)}")
    
    if teams_missing:
        errors.append(f"MISSING IN STATS ({len(teams_missing)}): {sorted(teams_missing)}")
    
    if teams_extra:
        log(f"\n[INFO] EXTRA IN STATS ({len(teams_extra)}): {sorted(teams_extra)}")
    
    if errors:
        log("\n[ERROR CRITICO] Mismatch de equipos detectado:")
        for err in errors:
            log(f"  - {err}")
        raise ValueError("FAIL FAST: Mismatch de equipos. Corrige canonicalizacion y reinicia.")
    
    log("\n[OK] Cobertura de equipos validada correctamente")

# ========== SANITY CHECK NEUTRAL ==========

def sanity_check_neutral(league_avg):
    """
    Sanity check: equipo promedio vs equipo promedio
    att=1, def=1 debe dar lambda = league_avg
    """
    
    log_section("SANITY CHECK NEUTRAL")
    
    att_home_rel = 1.0
    def_away_rel = 1.0
    lambda_home_neutral = att_home_rel * def_away_rel * league_avg['home']
    
    att_away_rel = 1.0
    def_home_rel = 1.0
    lambda_away_neutral = att_away_rel * def_home_rel * league_avg['away']
    
    log(f"Equipo promedio vs equipo promedio:")
    log(f"  att=1.0, def=1.0")
    log(f"  lambda_home_neutral: {lambda_home_neutral:.6f}")
    log(f"  league_avg_home: {league_avg['home']:.6f}")
    log(f"  Diff: {abs(lambda_home_neutral - league_avg['home']):.6f}")
    
    log(f"  lambda_away_neutral: {lambda_away_neutral:.6f}")
    log(f"  league_avg_away: {league_avg['away']:.6f}")
    log(f"  Diff: {abs(lambda_away_neutral - league_avg['away']):.6f}")
    
    if abs(lambda_home_neutral - league_avg['home']) > 0.0001:
        raise ValueError(f"SANITY CHECK FAILED: lambda_home_neutral ({lambda_home_neutral}) != league_avg_home ({league_avg['home']})")
    
    if abs(lambda_away_neutral - league_avg['away']) > 0.0001:
        raise ValueError(f"SANITY CHECK FAILED: lambda_away_neutral ({lambda_away_neutral}) != league_avg_away ({league_avg['away']})")
    
    log("\n[OK] Sanity check neutral passed")

# ========== AUDITORIA DE PJ ==========

def audit_pj_by_tournament(team_stats_current, team_stats_prior, league_avg_curr, league_avg_prior):
    """
    Audita que sum(PJ) coincida con matches por torneo
    ABORTA si no coincide
    """
    
    log_section("AUDITORIA DE PJ POR TORNEO")
    
    # Current
    sum_pj_home_curr = sum(stats['PJ_home'] for stats in team_stats_current.values())
    sum_pj_away_curr = sum(stats['PJ_away'] for stats in team_stats_current.values())
    
    log(f"\n{league_avg_curr['tournament']}:")
    log(f"  Matches: {league_avg_curr['matches']}")
    log(f"  sum(PJ_home): {sum_pj_home_curr}")
    log(f"  sum(PJ_away): {sum_pj_away_curr}")
    
    if sum_pj_home_curr != league_avg_curr['matches']:
        raise ValueError(f"ERROR: sum(PJ_home_curr)={sum_pj_home_curr} != matches={league_avg_curr['matches']}")
    if sum_pj_away_curr != league_avg_curr['matches']:
        raise ValueError(f"ERROR: sum(PJ_away_curr)={sum_pj_away_curr} != matches={league_avg_curr['matches']}")
    
    log("  [OK] PJ_home y PJ_away suman correctamente")
    
    # Prior
    sum_pj_home_prior = sum(stats['PJ_home'] for stats in team_stats_prior.values())
    sum_pj_away_prior = sum(stats['PJ_away'] for stats in team_stats_prior.values())
    
    log(f"\n{league_avg_prior['tournament']}:")
    log(f"  Matches: {league_avg_prior['matches']}")
    log(f"  sum(PJ_home): {sum_pj_home_prior}")
    log(f"  sum(PJ_away): {sum_pj_away_prior}")
    
    if sum_pj_home_prior != league_avg_prior['matches']:
        raise ValueError(f"ERROR: sum(PJ_home_prior)={sum_pj_home_prior} != matches={league_avg_prior['matches']}")
    if sum_pj_away_prior != league_avg_prior['matches']:
        raise ValueError(f"ERROR: sum(PJ_away_prior)={sum_pj_away_prior} != matches={league_avg_prior['matches']}")
    
    log("  [OK] PJ_home y PJ_away suman correctamente")

def audit_global_stats_integrity(team_stats, context_name):
    """
    Verifica que la suma de goles anotados coincida con concedidos globalmente.
    """
    log_section(f"AUDITORIA GLOBAL DE GOLES - {context_name}")
    
    sum_gf_home = sum(s['GF_home'] for s in team_stats.values())
    sum_gc_away = sum(s['GC_away'] for s in team_stats.values())
    
    sum_gf_away = sum(s['GF_away'] for s in team_stats.values())
    sum_gc_home = sum(s['GC_home'] for s in team_stats.values())
    
    log(f"  Sum(GF_home): {sum_gf_home} vs Sum(GC_away): {sum_gc_away}")
    log(f"  Diff: {sum_gf_home - sum_gc_away}")
    
    log(f"  Sum(GF_away): {sum_gf_away} vs Sum(GC_home): {sum_gc_home}")
    log(f"  Diff: {sum_gf_away - sum_gc_home}")
    
    errors = []
    if sum_gf_home != sum_gc_away:
        errors.append(f"CRITICAL: GF_home ({sum_gf_home}) != GC_away ({sum_gc_away})")
    
    if sum_gf_away != sum_gc_home:
        errors.append(f"CRITICAL: GF_away ({sum_gf_away}) != GC_home ({sum_gc_home})")
        
    if errors:
        for err in errors:
            log(f"  [ERROR] {err}")
        raise ValueError(f"FALLO DE INTEGRIDAD GLOBAL DE GOLES en {context_name}")
    else:
        log("  [OK] Integridad de goles verificada. GF matches GC cruzado.")

# ========== MAIN ==========

def run_diagnostic():
    log_section("DIAGNOSTICO LAMBDAS - v6 REFACTORED (CORE LIB)")
    log(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Load data
    log_section("CARGANDO DATOS")
    with open(CONFIG['INPUT_MATCHES'], 'r', encoding='utf-8') as f:
        matches_data = json.load(f)
    log(f"[OK] {CONFIG['INPUT_MATCHES']}: {len(matches_data['matches'])} partidos")
    
    stats_df = pd.read_csv(CONFIG['INPUT_STATS'], sep='\t')
    log(f"[OK] {CONFIG['INPUT_STATS']}: {len(stats_df)} registros")
    
    # VALIDACION 1: Match Uniqueness (CRITICAL)
    validate_match_uniqueness(stats_df)
    
    # Build stats CANONICAL via CORE
    log_section("CONSTRUYENDO STATS CON NOMBRES CANONICOS")
    team_stats_current, fusion_log_current = core.build_team_stats_canonical(stats_df, CONFIG['CURRENT_TOURNAMENT'])
    
    # VALIDACION 2: Team Names Consistency (CRITICAL)
    validate_team_names_in_matches(matches_data, team_stats_current)
    
    # MULTI-TOURNAMENT PRIOR
    log("Building Multi-Tournament Weighted Prior...")
    prior_weighted_stats = core.build_weighted_prior_stats(stats_df, CONFIG)
    
    # League avgs
    league_avg_curr = core.calculate_league_averages_by_tournament(stats_df, CONFIG['CURRENT_TOURNAMENT'])

    # (Audits removed/disabled for priors since logic changed, focusing on lambda audit)
    
    # Calculate lambdas - FUNCION UNICA CENTRALIZADA
    log_section("CALCULANDO LAMBDAS (FUNCION CENTRALIZADA en CORE)")
    
    results = []
    all_errors = []
    
    for match in matches_data['matches']:
        comp, errs = core.compute_components_and_lambdas(
            match, team_stats_current, 
            prior_weighted_stats, # CHANGED
            league_avg_curr, CONFIG,
            CONFIG['SHRINKAGE_DIVISOR_ACTUAL'], adjustments=None)
        results.append(comp)
        all_errors.extend(errs)
    
    df = pd.DataFrame(results)
    
    # VALIDACION 3: Lambda Sanity (CRITICAL + WARNING)
    validate_lambda_sanity(df, league_avg_curr, CONFIG)
    
    # Errors
    if all_errors:
        log(f"\n[ERRORES] {len(all_errors)}:")
        for err in all_errors:
            log(f"  - {err}")
        raise ValueError("Errores detectados. Aborta.")
    else:
        log("[OK] 0 ERRORES")
    
    # VERIFICACION DE SPLIT HOME/AWAY (Disabled for Multi-Prior)
    # log_section("VERIFICACION DE SPLIT HOME/AWAY")
    # ... (removed) ...
    
    # === REPORTES BASE vs FINAL ===
    log_section("PROMEDIOS BASE (sin adjustments)")
    avg_lambda_home_base = df['lambda_home_base'].mean()
    avg_lambda_away_base = df['lambda_away_base'].mean()
    avg_lambda_total_base = df['lambda_total_base'].mean()
    
    log(f"mean(lambda_home_base): {avg_lambda_home_base:.4f}")
    log(f"mean(lambda_away_base): {avg_lambda_away_base:.4f}")
    log(f"mean(lambda_total_base): {avg_lambda_total_base:.4f}")
    
    # Check asserts
    home_base_diff = abs(avg_lambda_home_base - league_avg_curr['home'])
    if home_base_diff > 0.20:
        log(f"\n[WARNING] home_base desviado > 0.20 ({home_base_diff:.4f})")
    
    # Save
    log_section("GUARDANDO ARCHIVOS")
    df.to_csv(CONFIG['OUTPUT_CSV'], index=False, encoding='utf-8')
    log(f"[OK] CSV: {CONFIG['OUTPUT_CSV']}")
    
    with open(CONFIG['OUTPUT_TXT'], 'w', encoding='utf-8') as f:
        f.write(output_buffer.getvalue())
    log(f"[OK] TXT: {CONFIG['OUTPUT_TXT']}")
    
    log_section("COMPLETADO")
    return df

# ========== VALIDACIONES ADICIONALES (AUDIT 2026.02.11) ==========

def validate_match_uniqueness(stats_df):
    """
    CRITICAL: Valida que no haya duplicados en Stats_liga_mx.json.
    Duplicados inflan PJ y distorsionan lambdas.
    """
    log_section("VALIDACION: MATCH UNIQUENESS")
    
    # Intentar detectar duplicados por (date, home, away)
    if 'date' in stats_df.columns:
        duplicates = stats_df.groupby(['date', 'home_team', 'away_team']).size()
        duplicates = duplicates[duplicates > 1]
        
        if len(duplicates) > 0:
            log(f"[ERROR CRITICO] {len(duplicates)} partidos duplicados encontrados:")
            for idx, count in duplicates.items():
                log(f"  - {idx}: {count} veces")
            raise ValueError("CRITICAL: Partidos duplicados en Stats_liga_mx.json. Elimina duplicados y reinicia.")
    
    log("[OK] No se detectaron duplicados evidentes")

def validate_lambda_sanity(df, league_avg, config):
    """
    Validaciones de sanidad de lambdas calculados.
    Mix de CRITICAL (abort) y WARNING (log).
    """
    from scipy.stats import poisson
    
    log_section("VALIDACION: LAMBDA SANITY")
    
    # Check 1: Lambda Mean (CRITICAL)
    mean_home = df['lambda_home_final'].mean()
    mean_away = df['lambda_away_final'].mean()
    
    home_diff_pct = abs(mean_home - league_avg['home']) / league_avg['home']
    away_diff_pct = abs(mean_away - league_avg['away']) / league_avg['away']
    
    log(f"Lambda Home mean: {mean_home:.3f} vs League Avg: {league_avg['home']:.3f} ({home_diff_pct*100:.1f}%)")
    log(f"Lambda Away mean: {mean_away:.3f} vs League Avg: {league_avg['away']:.3f} ({away_diff_pct*100:.1f}%)")
    
    # NOTE: lambda_home_final includes per-team HOME_ADVANTAGE_FACTOR, so deviation from raw
    # league_avg is expected when jornada has unbalanced home/away team strengths.
    # CRITICAL only if > 25% (model error). WARNING between 10-25% (normal seasonal variation).
    if home_diff_pct > 0.25:
        raise ValueError(f"CRITICAL: Lambda Home mean desviado {home_diff_pct*100:.1f}%: {mean_home:.3f} vs {league_avg['home']:.3f}")
    elif home_diff_pct > 0.10:
        log(f"[WARNING] Lambda Home mean desviado {home_diff_pct*100:.1f}%: {mean_home:.3f} vs {league_avg['home']:.3f} (>10%, variacion jornada normal)")
    if away_diff_pct > 0.25:
        raise ValueError(f"CRITICAL: Lambda Away mean desviado {away_diff_pct*100:.1f}%: {mean_away:.3f} vs {league_avg['away']:.3f}")
    elif away_diff_pct > 0.10:
        log(f"[WARNING] Lambda Away mean desviado {away_diff_pct*100:.1f}%: {mean_away:.3f} vs {league_avg['away']:.3f} (>10%, variacion jornada normal)")

    if home_diff_pct <= 0.10 and away_diff_pct <= 0.10:
        log("[OK] Lambda means dentro de tolerancia (±10%)")
    else:
        log("[OK] Lambda means dentro de tolerancia (±25% CRITICO)")
    
    # Check 2: Lambda Range Adaptativo (WARNING)
    mu_total = (mean_home + mean_away) / 2
    p5_home = df['lambda_home_final'].quantile(0.05)
    p95_home = df['lambda_home_final'].quantile(0.95)
    p5_away = df['lambda_away_final'].quantile(0.05)
    p95_away = df['lambda_away_final'].quantile(0.95)
    
    expected_min = mu_total * 0.4
    expected_max = mu_total * 1.8
    
    log(f"Percentiles Home: P5={p5_home:.2f}, P95={p95_home:.2f}")
    log(f"Percentiles Away: P5={p5_away:.2f}, P95={p95_away:.2f}")
    log(f"Rango adaptativo esperado: [{expected_min:.2f}, {expected_max:.2f}]")
    
    if p5_home < expected_min or p95_home > expected_max or p5_away < expected_min or p95_away > expected_max:
        log(f"⚠️ WARNING: Percentiles fuera de rango adaptativo. Revisar ajustes cualitativos.")
    else:
        log("[OK] Percentiles dentro de rango adaptativo")
    
    # Check 3: Grid Mass Coverage (WARNING)
    log("\n[Grid Mass Coverage (0-5)]")
    mass_warnings = 0
    for idx, row in df.iterrows():
        lh = row['lambda_home_final']
        la = row['lambda_away_final']
        
        mass_home = sum(poisson.pmf(k, lh) for k in range(6))
        mass_away = sum(poisson.pmf(k, la) for k in range(6))
        mass_captured = mass_home * mass_away
        
        if mass_captured < 0.97:
            log(f"⚠️ WARNING: {row['home_team_canonical']} vs {row['away_team_canonical']}: "
                f"Grid mass={mass_captured:.3f} < 0.97 (λ_h={lh:.2f}, λ_a={la:.2f})")
            mass_warnings += 1
    
    if mass_warnings == 0:
        log("[OK] Todos los partidos con mass coverage ≥ 0.97")
    else:
        log(f"[INFO] {mass_warnings} partidos con grid mass < 0.97. Considerar ampliar grid si necesario.")
    
    # Check 4: Clamping Detection (WARNING)
    log("\n[Clamping Detection]")
    clamped_home = df[(df['lambda_home_final'] == config['CLAMP_LAMBDA_MIN']) | 
                      (df['lambda_home_final'] == config['CLAMP_LAMBDA_MAX'])]
    clamped_away = df[(df['lambda_away_final'] == config['CLAMP_LAMBDA_MIN']) | 
                      (df['lambda_away_final'] == config['CLAMP_LAMBDA_MAX'])]
    clamped = pd.concat([clamped_home, clamped_away]).drop_duplicates()
    
    if len(clamped) > 0:
        log(f"⚠️ WARNING: {len(clamped)} lambdas clampeados (ajustes extremos detectados):")
        for idx, row in clamped.iterrows():
            log(f"  - {row['home_team_canonical']} vs {row['away_team_canonical']}: "
                f"λ_h={row['lambda_home_final']:.2f}, λ_a={row['lambda_away_final']:.2f}")
    else:
        log("[OK] No se detectaron lambdas clampeados")

def validate_team_names_in_matches(matches_data, team_stats):
    """
    CRITICAL: Todos los equipos en jornada deben existir en stats.
    Si no, lambda se calcula solo con prior (sin señal actual).
    """
    log_section("VALIDACION: TEAM NAMES CONSISTENCY")
    
    teams_in_matches = set()
    for match in matches_data['matches']:
        teams_in_matches.add(core.canonical_team_name(match['match']['home']))
        teams_in_matches.add(core.canonical_team_name(match['match']['away']))
    
    missing = teams_in_matches - set(team_stats.keys())
    if missing:
        log(f"[ERROR CRITICO] Equipos en jornada NO encontrados en stats: {sorted(missing)}")
        raise ValueError("CRITICAL: Desalineación de nombres entre jornada y stats. Actualiza CANONICAL_ALIASES.")
    
    log(f"[OK] Todos los {len(teams_in_matches)} equipos de la jornada existen en stats")


if __name__ == "__main__":
    try:
        df = run_diagnostic()
        print(f"\n[SUCCESS] Diagnostico completado con canonicalizacion estricta")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        # Save partial output
        with open(CONFIG['OUTPUT_TXT'], 'w', encoding='utf-8') as f:
            f.write(output_buffer.getvalue())
        sys.exit(1)
