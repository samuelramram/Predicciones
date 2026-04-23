import json
import re
import os
import pandas as pd
from datetime import datetime
import src.predicciones.config as config
import src.predicciones.core as dl  # Alias dl to minimize refactor
import src.predicciones.data as data_loader
import src.predicciones.quiniela as qx
import src.predicciones.improvements as improvements

def should_abstain(prob_1, prob_x, prob_2, gap, config):
    """
    Determina si el modelo debe abstenerse de dar un pick.
    Criterio A: Gap muy bajo Y probabilidades muy equilibradas (sin favorito claro).
    Criterio B: Ningún resultado supera la probabilidad mínima de confianza.
    """
    threshold = config.get('ABSTAIN_GAP_THRESHOLD', 0.03)
    spread_threshold = config.get('ABSTAIN_SPREAD_THRESHOLD', 0.10)
    min_prob_threshold = config.get('ABSTAIN_MIN_PROB', 0.40)

    max_p = max(prob_1, prob_x, prob_2)
    min_p = min(prob_1, prob_x, prob_2)
    spread = max_p - min_p

    is_tight = gap < threshold
    is_balanced = spread < spread_threshold
    is_low_confidence = max_p < min_prob_threshold

    return (is_tight and is_balanced) or is_low_confidence

def main():
    runtime_config = config.resolve_config()
    print(f"=== GENERADOR DE PREDICCIONES JORNADA {runtime_config.get('JORNADA', '?')} ===")
    
    # 1. Load Data/Setup
    print("Loading data...")

    with open(runtime_config['INPUT_MATCHES'], 'r', encoding='utf-8') as f:
        matches_data = json.load(f)
        
    stats_df = pd.read_csv(runtime_config['INPUT_STATS'], sep='\t')
    
    # 2. Parse Qualitative
    print("Parsing qualitative data (New Dedup Flow)...")
    
    # A. Collect Raw
    raw_manual = data_loader.collect_manual_bajas(runtime_config['INPUT_EVALUATION'])
    raw_perplexity = data_loader.collect_perplexity_bajas(runtime_config.get('INPUT_PERPLEXITY_BAJAS', 'data/inputs/perplexity_bajas_semana.json'))
    
    # B. Merge and Deduplicate
    all_bajas = raw_manual + raw_perplexity
    deduped_bajas = data_loader.deduplicate_bajas(all_bajas)
    
    print(f"  > Raw Manual: {len(raw_manual)} | Raw Perplexity: {len(raw_perplexity)}")
    print(f"  > Deduplicated Total: {len(deduped_bajas)} (Removed {len(all_bajas) - len(deduped_bajas)} duplicates)")
    
    # C. Apply
    adj_map = {} # Initialize empty
    data_loader.apply_bajas_list(adj_map, deduped_bajas)
    
    # D. Qualitative Context (legacy free-text parser, kept for backwards compat)
    adj_map = data_loader.load_qualitative_adjustments(adj_map, runtime_config['INPUT_QUALITATIVE'])

    # E. Structured Context Adjustments (fatigue, rotation, suspension, motivation...)
    context_list = data_loader.collect_context_adjustments(runtime_config.get('INPUT_CONTEXT', ''))
    if context_list:
        print(f"  > Context adjustments loaded: {len(context_list)} entries")
        adj_map = data_loader.apply_context_adjustments(adj_map, context_list)
    else:
        print("  > No context adjustments file for this jornada (optional)")

    # Debug adjustments
    print("\nADJUSTMENTS APPLIED:")
    for team, data in adj_map.items():
        if data['att_adj'] != 1.0 or data['def_adj'] != 1.0:
            print(f"{team}: Att*{data['att_adj']:.2f}, Def*{data['def_adj']:.2f} | Notes: {len(data['notes'])} items")

    
    # 3. Build Stats
    # OPTIMIZATION: Pre-calculate canonical names for stats_df
    if 'home_team_canonical' not in stats_df.columns:
        stats_df['home_team_canonical'] = stats_df['home_team'].apply(dl.canonical_team_name)
    if 'away_team_canonical' not in stats_df.columns:
        stats_df['away_team_canonical'] = stats_df['away_team'].apply(dl.canonical_team_name)

    team_stats_current, _ = dl.build_team_stats_canonical(stats_df, runtime_config['CURRENT_TOURNAMENT'])

    # MULTI-TOURNAMENT PRIOR (Weighted)
    print("Building Multi-Tournament Weighted Prior...")
    prior_weighted_stats = dl.build_weighted_prior_stats(stats_df, runtime_config)

    # Calculate League Avgs (Current only needed for main calculation)
    league_avg_curr = dl.calculate_league_averages_by_tournament(stats_df, runtime_config['CURRENT_TOURNAMENT'])
    # league_avg_prior not needed for computation anymore (baked into weighted stats) but verify signature

    # Compute current table for equilibrium detection
    current_table = dl.calculate_current_table(stats_df, runtime_config['CURRENT_TOURNAMENT'])
    dc_rho_base = runtime_config.get('DC_RHO', -0.10)

    # === INTEGRACION xG (xgscore.io) ===
    # 1. Cargar xg_stats.json y construir lookup por nombre canónico
    xg_lookup = {}
    xg_stats_path = runtime_config.get('XG_STATS_PATH', 'data/xg_stats.json')
    if os.path.exists(xg_stats_path):
        with open(xg_stats_path, 'r', encoding='utf-8') as f:
            xg_raw = json.load(f)
        for team_name, entry in xg_raw.get('teams', {}).items():
            canon = dl.canonical_team_name(team_name)
            if canon not in xg_lookup:  # first-entry wins: evita duplicado 'pumas'
                xg_lookup[canon] = entry
        pj_xg = xg_raw.get('meta', {}).get('matches_played', '?')
        print(f"\n[xG] {len(xg_lookup)} equipos cargados de {xg_stats_path} (PJ={pj_xg})")

        # 2. Aplicar regresión xPTS al adj_map (ANTES del match loop)
        # Si actual_pts >> xPTS → equipo sobreperformó resultados → reducción leve de lambda
        # Si actual_pts << xPTS → equipo subperformó → boost leve
        XG_PTS_FACTOR = runtime_config.get('XG_PTS_REGRESSION_FACTOR', 0.15)
        xpts_count = 0
        for team_canon, xg_entry in xg_lookup.items():
            xpts = xg_entry.get('xPTS', 0)
            if xpts <= 0:
                continue
            actual_pts = current_table.get(team_canon, {}).get('pts', 0)
            if actual_pts == 0:
                continue
            pts_diff_ratio = (actual_pts - xpts) / xpts
            adj = max(0.97, min(1.03, 1.0 - pts_diff_ratio * XG_PTS_FACTOR))
            if abs(adj - 1.0) < 0.003:
                continue  # efecto insignificante (<0.3%), ignorar
            if team_canon not in adj_map:
                adj_map[team_canon] = {'att_adj': 1.0, 'def_adj': 1.0, 'notes': []}
            adj_map[team_canon]['att_adj'] *= adj
            direction = "↓ sobrerendimiento" if adj < 1.0 else "↑ subrendimiento"
            adj_map[team_canon]['notes'].append(
                f"xPTS-REGRESION {direction}: {actual_pts:.0f}pts vs {xpts:.1f}xPTS → x{adj:.3f}"
            )
            print(f"  [xPTS] {team_canon}: {actual_pts:.0f}pts reales vs {xpts:.1f}xPTS → x{adj:.3f}")
            xpts_count += 1
        print(f"[xG] Regresión xPTS aplicada a {xpts_count} equipos")
    else:
        print(f"[xG] WARNING: No se encontró {xg_stats_path} — modelo sin datos xG")

    # 4. Generate Predictions
    print("Generating predictions...")
    results = []
    
    print("\nPREDICCIONES Y METRICAS QUINIELA:")
    for match in matches_data['matches']:
        home_raw = match['match']['home']
        away_raw = match['match']['away']
        
        home_canon = dl.canonical_team_name(home_raw)
        away_canon = dl.canonical_team_name(away_raw)
        
        
        # Calculate Recent Form
        form_mult_home, form_details_home = improvements.calculate_recent_form(
             stats_df, home_canon, match['match']['kickoff_datetime'], runtime_config.get('RECENT_FORM_GAMES', 5)
        )
        form_mult_away, form_details_away = improvements.calculate_recent_form(
             stats_df, away_canon, match['match']['kickoff_datetime'], runtime_config.get('RECENT_FORM_GAMES', 5)
        )

        # Momentum direction (aceleración/desaceleración dentro de la ventana de forma)
        momentum_home, momentum_info_home = improvements.calculate_momentum_direction(
            stats_df, home_canon, match['match']['kickoff_datetime'],
            threshold=runtime_config.get('MOMENTUM_THRESHOLD', 0.20),
            bonus_max=runtime_config.get('MOMENTUM_BONUS_MAX', 0.02),
        )
        momentum_away, momentum_info_away = improvements.calculate_momentum_direction(
            stats_df, away_canon, match['match']['kickoff_datetime'],
            threshold=runtime_config.get('MOMENTUM_THRESHOLD', 0.20),
            bonus_max=runtime_config.get('MOMENTUM_BONUS_MAX', 0.02),
        )

        # Home crisis / stronghold (basado solo en partidos de local)
        home_crisis_mult, crisis_info = improvements.calculate_home_crisis_factor(
            stats_df, home_canon, match['match']['kickoff_datetime'],
            n_home=runtime_config.get('N_HOME_FORM', 4),
            crisis_threshold=runtime_config.get('HOME_CRISIS_WINS_THRESHOLD', 1),
        )

        # Combined home form adjustment: forma general × momentum × crisis local
        combined_home_form = form_mult_home * momentum_home * home_crisis_mult
        combined_away_form = form_mult_away * momentum_away

        match_adjustments = {
            'home_att_adj': 1.0, 'home_def_adj': 1.0,
            'away_att_adj': 1.0, 'away_def_adj': 1.0,
            'home_form_adj': combined_home_form,
            'away_form_adj': combined_away_form,
        }

        # Log Form
        if abs(form_mult_home - 1.0) > 0.001:
             print(f"  > HOME FORM: {home_canon} {form_details_home['pct']:.2f} -> {form_mult_home:.3f}")
             if home_canon in adj_map:
                 adj_map[home_canon]['notes'].append(f"RECENT FORM: {form_details_home['points']}pts ({form_details_home['pct']*100:.0f}%) -> {form_mult_home:.3f}")

        if abs(form_mult_away - 1.0) > 0.001:
             print(f"  > AWAY FORM: {away_canon} {form_details_away['pct']:.2f} -> {form_mult_away:.3f}")
             if away_canon in adj_map:
                 adj_map[away_canon]['notes'].append(f"RECENT FORM: {form_details_away['points']}pts ({form_details_away['pct']*100:.0f}%) -> {form_mult_away:.3f}")

        # Log Momentum
        if abs(momentum_home - 1.0) > 0.005:
            direction_str = "↑ acelerando" if momentum_home > 1.0 else "↓ desacelerando"
            print(f"  > MOMENTUM HOME: {home_canon} {direction_str} -> {momentum_home:.3f}")
            adj_map.setdefault(home_canon, {'att_adj': 1.0, 'def_adj': 1.0, 'notes': []})['notes'].append(
                f"MOMENTUM: {direction_str} ({momentum_info_home['recent_2_pts']}pts/2 vs {momentum_info_home['prior_3_pts']}pts/3) -> {momentum_home:.3f}"
            )
        if abs(momentum_away - 1.0) > 0.005:
            direction_str = "↑ acelerando" if momentum_away > 1.0 else "↓ desacelerando"
            print(f"  > MOMENTUM AWAY: {away_canon} {direction_str} -> {momentum_away:.3f}")
            adj_map.setdefault(away_canon, {'att_adj': 1.0, 'def_adj': 1.0, 'notes': []})['notes'].append(
                f"MOMENTUM: {direction_str} ({momentum_info_away['recent_2_pts']}pts/2 vs {momentum_info_away['prior_3_pts']}pts/3) -> {momentum_away:.3f}"
            )

        # Log Home Crisis / Stronghold
        if abs(home_crisis_mult - 1.0) > 0.001:
            label = crisis_info.get('label', 'normal')
            print(f"  > HOME {label.upper()}: {home_canon} {crisis_info['home_wins']}V/{crisis_info['home_games']}J local -> {home_crisis_mult:.3f}")
            adj_map.setdefault(home_canon, {'att_adj': 1.0, 'def_adj': 1.0, 'notes': []})['notes'].append(
                f"LOCAL {label.upper()}: {crisis_info['home_wins']}V en {crisis_info['home_games']}J de local -> {home_crisis_mult:.3f}"
            )
        
        # Apply adjustments from adj_map
        if home_canon in adj_map:
             match_adjustments['home_att_adj'] = adj_map[home_canon].get('att_adj', 1.0)
             match_adjustments['home_def_adj'] = adj_map[home_canon].get('def_adj', 1.0)
        if away_canon in adj_map:
             match_adjustments['away_att_adj'] = adj_map[away_canon].get('att_adj', 1.0)
             match_adjustments['away_def_adj'] = adj_map[away_canon].get('def_adj', 1.0)
        
        # Compute Lambda Components
        try:
             comp, errors = dl.compute_components_and_lambdas(
                match, team_stats_current,
                prior_weighted_stats,
                league_avg_curr, runtime_config,
                runtime_config['SHRINKAGE_DIVISOR_ACTUAL'], match_adjustments,
                xg_lookup=xg_lookup
            )
        except Exception as e:
            print(f"CRITICAL ERROR in {home_raw}-{away_raw}: {e}")
            continue
        
        if errors:
            print(f"Error in {home_raw}-{away_raw}: {errors}")
            continue
            
        l_home = comp['lambda_home_final']
        l_away = comp['lambda_away_final']

        # Tabla: detectar equilibrio (diferencia ≤ 3 pts → más probabilidad de empate)
        home_pts_table = current_table.get(home_canon, {}).get('pts', 0)
        away_pts_table = current_table.get(away_canon, {}).get('pts', 0)
        is_equilibrio = abs(home_pts_table - away_pts_table) <= 3
        # Con equilibrio en tabla usamos rho más negativo (mayor corrección hacia empate)
        dc_rho = (dc_rho_base - 0.04) if is_equilibrio else dc_rho_base

        # Optimize pick for quiniela scoring (2 exacto / 1 resultado) con Dixon-Coles
        quiniela = qx.optimize_pick_for_quiniela(l_home, l_away, dc_rho=dc_rho)
        prob_home_win = quiniela['prob_home_win']
        prob_draw = quiniela['prob_draw']
        prob_away_win = quiniela['prob_away_win']
        top_5 = quiniela['top_5_by_prob']
        pick_exact = quiniela['pick_exact']
        pick_1x2 = quiniela['pick_1x2']
        ev = quiniela['ev']
        ev_gap = quiniela['ev_confidence_gap']
        
        if ev_gap >= 0.10:
            conf_label = 'ALTO'
        elif ev_gap >= 0.02:
            conf_label = 'MEDIO'
        else:
            conf_label = 'BAJO (VOLADO)'
            
        # Abstention Logic
        if should_abstain(prob_home_win, prob_draw, prob_away_win, ev_gap, runtime_config):
            conf_label = 'SIN VENTAJA'
            pick_1x2 = 'N/A'
            pick_exact = 'N/A'

        # Baja uncertainty capping: si bajas combinadas son muy altas, bajar confianza a MEDIO
        if conf_label == 'ALTO':
            combined_baja_penalty = 0.0
            if home_canon in adj_map:
                combined_baja_penalty += abs(1.0 - adj_map[home_canon].get('att_adj', 1.0))
                combined_baja_penalty += abs(1.0 - adj_map[home_canon].get('def_adj', 1.0))
            if away_canon in adj_map:
                combined_baja_penalty += abs(1.0 - adj_map[away_canon].get('att_adj', 1.0))
                combined_baja_penalty += abs(1.0 - adj_map[away_canon].get('def_adj', 1.0))
            baja_threshold = runtime_config.get('BAJA_UNCERTAINTY_THRESHOLD', 0.25)
            if combined_baja_penalty > baja_threshold:
                conf_label = 'MEDIO'
                adj_map.setdefault(home_canon, {'att_adj': 1.0, 'def_adj': 1.0, 'notes': []})['notes'].append(
                    f"[BAJA-CAP: impacto={combined_baja_penalty:.2f} > {baja_threshold:.2f} → rebajado a MEDIO]"
                )

        # Equilibrio en tabla: añadir nota informativa
        if is_equilibrio and pick_1x2 != 'N/A':
            adj_map.setdefault(home_canon, {'att_adj': 1.0, 'def_adj': 1.0, 'notes': []})['notes'].append(
                f"TABLA-EQUILIBRIO: {home_canon}({home_pts_table}pts) vs {away_canon}({away_pts_table}pts) → DC-ρ={dc_rho:.2f}"
            )

        # Qualitative Notes
        notes_str = ""
        if home_canon in adj_map and adj_map[home_canon]['notes']:
            notes_str += f"{' | '.join(adj_map[home_canon]['notes'])}"
        if away_canon in adj_map and adj_map[away_canon]['notes']:
            if notes_str: notes_str += " | "
            notes_str += f"{' | '.join(adj_map[away_canon]['notes'])}"

        results.append({
            'home_team_canonical': home_canon,
            'away_team_canonical': away_canon,
            'pick_1x2': pick_1x2,
            'pick_exact': pick_exact,
            'ev': quiniela['ev'],
            'prob_home_win': prob_home_win,
            'prob_draw': prob_draw,
            'prob_away_win': prob_away_win,
            'lambda_home_final': l_home,
            'lambda_away_final': l_away,
            'top_5_scorelines': "|".join([f"{x['score']}:{x['prob']:.3f}" for x in top_5]),
            'top_5_ev': "|".join([f"{x['score']}:{x['ev']:.3f}" for x in quiniela['top_5_by_ev']]),
            'ev_confidence_gap': quiniela['ev_confidence_gap'],
            'grid_max_goals': quiniela['grid_max_goals'],
            'captured_mass': quiniela['captured_mass'],
            'confidence_label': conf_label,
            'qualitative_notes': notes_str
        })
        # Print summary
        print(f"\n{home_raw} vs {away_raw}")
        print(f"  Lambda Final: {l_home:.2f} - {l_away:.2f}")
        print(f"  Probs: 1({prob_home_win:.1%}) X({prob_draw:.1%}) 2({prob_away_win:.1%})")
        print(f"  Pick: {pick_1x2} (Exact: {pick_exact}) | EV: {ev:.3f} | Mass: {quiniela['captured_mass']:.3f}")
        


    # Save CSV
    jornada = runtime_config.get('JORNADA', 'X')
    out_file = f'outputs/predicciones_jornada_{jornada}_final.csv'
    df = pd.DataFrame(results)
    
    # Reorder columns for usability
    cols = ['home_team_canonical', 'away_team_canonical', 'pick_1x2', 'pick_exact', 'ev', 
            'prob_home_win', 'prob_draw', 'prob_away_win', 
            'lambda_home_final', 'lambda_away_final', 
            'confidence_label', 'top_5_scorelines', 'top_5_ev', 'ev_confidence_gap', 'grid_max_goals', 'captured_mass', 'qualitative_notes']
    
    # Ensure all columns exist
    for c in cols:
        if c not in df.columns:
            df[c] = None
            
    df = df[cols]
    df = df.drop_duplicates(subset=['home_team_canonical', 'away_team_canonical'])
    df.to_csv(out_file, index=False)
    print(f"\nGuardado en {out_file}")

if __name__ == "__main__":
    main()
