
import json
import re
import pandas as pd
from datetime import datetime
import src.predicciones.core as dl
import src.predicciones.config as config
from math import isnan, exp

# === CONFIG (Same as gen_predicciones) ===
# ... (Repeated logic for parsing will be refined to capture text)

import src.predicciones.data as data_loader
import src.predicciones.quiniela as qx
import src.predicciones.improvements as improvements

def should_abstain(prob_1, prob_x, prob_2, gap, config):
    """
    Determina si el modelo debe abstenerse de dar un pick.
    Criterio: Gap muy bajo Y las probabilidades están muy dispersas (aka no hay favorito claro).
    """
    threshold = config.get('ABSTAIN_GAP_THRESHOLD', 0.03)
    spread_threshold = config.get('ABSTAIN_SPREAD_THRESHOLD', 0.10)
    
    max_p = max(prob_1, prob_x, prob_2)
    min_p = min(prob_1, prob_x, prob_2)
    spread = max_p - min_p
    
    return gap < threshold and spread < spread_threshold

def main():
    runtime_config = config.resolve_config()
    print("Generando Reporte Técnico Automático...")
    
    # Load inputs
    # Load Inputs
    with open(runtime_config['INPUT_MATCHES'], 'r', encoding='utf-8') as f:
        matches_data = json.load(f)
    stats_df = pd.read_csv(runtime_config['INPUT_STATS'], sep='\t')
    
    team_stats_current, _ = dl.build_team_stats_canonical(stats_df, runtime_config['CURRENT_TOURNAMENT'])
    # PRIOR MULTI
    print("Building Multi-Tournament Weights...")
    prior_weighted_stats = dl.build_weighted_prior_stats(stats_df, runtime_config)
    
    league_avg_curr = dl.calculate_league_averages_by_tournament(stats_df, runtime_config['CURRENT_TOURNAMENT'])
    
    # Parse bajas con flujo deduplicado (igual que gen_predicciones.py)
    raw_manual = data_loader.collect_manual_bajas(runtime_config['INPUT_EVALUATION'])
    raw_perplexity = data_loader.collect_perplexity_bajas(runtime_config.get('INPUT_PERPLEXITY_BAJAS', 'data/inputs/perplexity_bajas_semana.json'))
    all_bajas = raw_manual + raw_perplexity
    deduped_bajas = data_loader.deduplicate_bajas(all_bajas)
    print(f"  > Raw Manual: {len(raw_manual)} | Raw Perplexity: {len(raw_perplexity)}")
    print(f"  > Deduplicated Total: {len(deduped_bajas)} (Removed {len(all_bajas) - len(deduped_bajas)} duplicates)")
    adj_map = {}
    data_loader.apply_bajas_list(adj_map, deduped_bajas)
    adj_map = data_loader.load_qualitative_adjustments(adj_map, runtime_config['INPUT_QUALITATIVE'])

    # Structured context adjustments (same channel as gen_predicciones.py)
    context_list = data_loader.collect_context_adjustments(runtime_config.get('INPUT_CONTEXT', ''))
    if context_list:
        print(f"  > Context adjustments loaded: {len(context_list)} entries")
        adj_map = data_loader.apply_context_adjustments(adj_map, context_list)
    else:
        print("  > No context adjustments file for this jornada (optional)")
    # OUTPUT MARKDOWN BUILDER
    md_output = []
    # ... header lines ...
    md_output.append(f"# 🔢 Reporte Técnico: Jornada {runtime_config.get('JORNADA', '?')} (Liga MX)")
    md_output.append(f"**Generado:** {datetime.now().isoformat()}")
    md_output.append(f"**Estrategia:** Maximizar Puntos (Quiniela EV)")
    md_output.append(f"**Fórmula EV:** Prob. Exacta + Prob. Resultado")
    md_output.append(f"**Prior:** Multi-Torneo Ponderado (Estabilidad Aumentada)")
    md_output.append(f"\n---")
    
    summary_picks = []

    for match in matches_data['matches']:
        home_raw = match['match']['home']
        away_raw = match['match']['away']
        home_canon = dl.canonical_team_name(home_raw)
        away_canon = dl.canonical_team_name(away_raw)
        
        # Get Data
        home_data = adj_map.get(home_canon, {'att_adj':1.0, 'def_adj':1.0, 'report_log':[], 'context_txt':[], 'ausencias_txt':[], 'movimientos_txt':[]})
        away_data = adj_map.get(away_canon, {'att_adj':1.0, 'def_adj':1.0, 'report_log':[], 'context_txt':[], 'ausencias_txt':[], 'movimientos_txt':[]})
        
        # Calculate Recent Form
        form_mult_home, form_details_home = improvements.calculate_recent_form(
             stats_df, home_canon, match['match']['kickoff_datetime'], runtime_config.get('RECENT_FORM_GAMES', 5)
        )
        form_mult_away, form_details_away = improvements.calculate_recent_form(
             stats_df, away_canon, match['match']['kickoff_datetime'], runtime_config.get('RECENT_FORM_GAMES', 5)
        )

        match_adjustments = {
            'home_att_adj': home_data['att_adj'],
            'home_def_adj': home_data['def_adj'],
            'away_att_adj': away_data['att_adj'],
            'away_def_adj': away_data['def_adj'],
            'home_form_adj': form_mult_home,
            'away_form_adj': form_mult_away
        }
        
        # Add to report logs locally
        if abs(form_mult_home - 1.0) > 0.001:
             pct = (form_mult_home - 1.0) * 100
             home_data['report_log'].append({
                 'desc': f"RECENT FORM: {form_details_home['points']}pts ({form_details_home['pct']*100:.0f}%)",
                 'pct': pct,
                 'type': 'HOME'
             })
             
        if abs(form_mult_away - 1.0) > 0.001:
             pct = (form_mult_away - 1.0) * 100
             away_data['report_log'].append({
                 'desc': f"RECENT FORM: {form_details_away['points']}pts ({form_details_away['pct']*100:.0f}%)",
                 'pct': pct,
                 'type': 'AWAY'
             })
        
        comp, errors = dl.compute_components_and_lambdas(match, team_stats_current, 
                                                         prior_weighted_stats, # CHANGED
                                                         league_avg_curr, runtime_config,
                                                         runtime_config['SHRINKAGE_DIVISOR_ACTUAL'], match_adjustments)
        
        if errors: continue

        l_home = comp['lambda_home_final']
        l_away = comp['lambda_away_final']
        l_home_base = comp['lambda_home_base']
        l_away_base = comp['lambda_away_base']
        
        # Probs + pick optimization for quiniela scoring
        quiniela = qx.optimize_pick_for_quiniela(l_home, l_away)
        prob_home = quiniela['prob_home_win']
        prob_draw = quiniela['prob_draw']
        prob_away = quiniela['prob_away_win']

        # Build Match Report Section
        md_output.append(f"\n## {home_raw} vs. {away_raw}")
        
        # --- QUINIELA METRICS ---
        top_5 = quiniela['top_5_by_prob']
        pick_exact = quiniela['pick_exact']
        pick_1x2_raw = quiniela['pick_1x2']
        pick_1x2 = {'1': '1 (Local)', 'X': 'X (Empate)', '2': '2 (Visita)'}[pick_1x2_raw]
        prob_res = {'1': prob_home, 'X': prob_draw, '2': prob_away}[pick_1x2_raw]
        ev = quiniela['ev']
        
        md_output.append(f"\n### 🎯 Pronóstico Quiniela")
        md_output.append(f"- **Pick 1X2:** {pick_1x2} (Prob: {prob_res:.1%})")
        md_output.append(f"- **Pick Exacto:** {pick_exact} (Prob: {top_5[0]['prob']:.1%})")
        md_output.append(f"- **Valor Esperado (EV):** {ev:.3f}")
        
        # Confidence logic
        ev_gap = quiniela['ev_confidence_gap']
        if ev_gap >= 0.03:
            conf_label = 'ALTO 🟢'
        elif ev_gap >= 0.015:
            conf_label = 'MEDIO 🟡'
        else:
            conf_label = 'BAJO 🔴'
            
        # Abstention Logic
        if should_abstain(prob_home, prob_draw, prob_away, ev_gap, runtime_config):
            conf_label = 'SIN VENTAJA ⚪'
            pick_1x2 = 'N/A (Abstención)'
            pick_exact = 'N/A'
            
        md_output.append(f"- **Confianza del pick:** {conf_label} (gap: {ev_gap:.3f})")
        md_output.append(f"- **Top 5 Marcadores:**")
        for s in top_5:
            md_output.append(f"  - {s['score']}: {s['prob']:.1%}")
            
        # --- END QUINIELA METRICS ---
        
        # Context
        md_output.append(f"### 🗞️ Contexto y Novedades")
        for line in home_data['context_txt'] + away_data['context_txt']:
            md_output.append(line)
        if not home_data['context_txt'] and not away_data['context_txt']:
            md_output.append("- *Sin contexto crítico destacado.*")
            
        md_output.append(f"\n**Movimientos de Mercado:**")
        for line in home_data['movimientos_txt'] + away_data['movimientos_txt']:
            md_output.append(line)
            
        md_output.append(f"\n**Ausencias Relevantes:**")
        
        # Helper to format absence line
        def fmt_abs(item):
            # If item is string (legacy fallback)
            if isinstance(item, str): return item
            # If item is dict (new structure)
            icon = "🚑" if "fuera" in item.get('status','').lower() else "⚠️"
            return f"{icon} **{item['player']}** ({item['role']}): {item['status']} [Imp:{item['impact_level']}]"

        # Collect all structured items
        all_items = home_data.get('ausencias_items', []) + away_data.get('ausencias_items', [])
        
        # If no structured items, fall back to txt (legacy support if mixed)
        if not all_items:
             for line in home_data['ausencias_txt'] + away_data['ausencias_txt']:
                md_output.append(line)
        else:
            vigentes = []
            historicas = []
            
            for item in all_items:
                # Logic: Vigente if Impact High/Mid OR Status Fuera/Duda
                # Historica if Impact Low AND/OR Status Recuperado/Largo Plazo
                
                # Check 1: Status keywords
                st = item.get('status', '').lower()
                imp = item.get('impact_level', 'Low').lower()
                
                is_vigente = True
                if 'recuperado' in st or 'alta' in st:
                    is_vigente = False
                elif imp == 'low' and 'duda' not in st and 'fuera' not in st:
                    is_vigente = False
                elif item.get('recency_days', 0) > 30 and imp == 'low':
                    is_vigente = False
                
                # Formatted string with team prefix to know who it belongs to (since we combined lists)
                # But wait, we don't know the team in the combined list easily unless we stored it.
                # 'data.py' stores 'source' but not 'team' in the item? 
                # Actually, we rely on the fact that home_data comes from home_canon key.
                # Let's process separately to keep team context.
                pass 
            
            # Re-do split with team context
            def process_list(items, team_tag):
                v, h = [], []
                for item in items:
                    st = item.get('status', '').lower()
                    imp = item.get('impact_level', 'Low').lower()
                    
                    is_vigente = True
                    # Relaxed rule: High/Mid is always vigente. Low only if recent or explicitly "Fuera"
                    if imp in ['high', 'mid']:
                        is_vigente = True
                    elif 'fuera' in st or 'duda' in st or 'suspendido' in st:
                        is_vigente = True
                    else:
                        is_vigente = False # Low impact, not explicitly out/doubt -> historical/minor
                    
                    line = f"- {team_tag} {fmt_abs(item)}"
                    if is_vigente: v.append(line)
                    else: h.append(line)
                return v, h

            v_home, h_home = process_list(home_data.get('ausencias_items', []), f"({home_raw})")
            v_away, h_away = process_list(away_data.get('ausencias_items', []), f"({away_raw})")
            
            vigentes = v_home + v_away
            historicas = h_home + h_away
            
            if vigentes:
                md_output.append("**🔴 Vigentes (Impacto Inmediato):**")
                for line in vigentes: md_output.append(line)
            
            if historicas:
                md_output.append("\n**🕒 Históricas / Menor Impacto:**")
                for line in historicas: md_output.append(line)
                
            if not vigentes and not historicas:
                md_output.append("- *Sin ausencias reportadas.*")
            
        # Analysis
        md_output.append(f"\n### 🧪 Análisis de Lambdas (Goles Esperados)")
        
        # Home Analysis
        # Att Force = att_home_rel_blend
        att_force_h = comp['att_home_rel_blend']
        def_force_a = comp['def_away_rel_blend']
        avg_h = league_avg_curr['home']
        
        md_output.append(f"**{home_raw} (Local) = {l_home:.4f}**")
        md_output.append(f"- *Fuerza Ataque*: {att_force_h:.3f}")
        md_output.append(f"- *Fuerza Defensa Rival*: {def_force_a:.3f}")
        md_output.append(f"- *Media Liga Local*: {avg_h:.3f}")
        md_output.append(f"- *Cálculo Base*: {att_force_h:.3f} * {def_force_a:.3f} * {avg_h:.3f} = {l_home_base:.3f}")
        
        # Away Analysis
        att_force_a = comp['att_away_rel_blend']
        def_force_h = comp['def_home_rel_blend']
        avg_a = league_avg_curr['away']
        
        md_output.append(f"\n**{away_raw} (Visita) = {l_away:.4f}**")
        md_output.append(f"- *Fuerza Ataque*: {att_force_a:.3f}")
        md_output.append(f"- *Fuerza Defensa Rival*: {def_force_h:.3f}")
        md_output.append(f"- *Media Liga Visita*: {avg_a:.3f}")
        md_output.append(f"- *Cálculo Base*: {att_force_a:.3f} * {def_force_h:.3f} * {avg_a:.3f} = {l_away_base:.3f}")

        # --- P(anotar >= 1) SECTION ---
        md_output.append(f"\n**📈 Probabilidad de Anotar (≥ 1 gol):**")
        md_output.append(f"> Fórmula: P = 1 − e^(−λ)  *(Poisson independiente)*")
        md_output.append(f"")
        md_output.append(f"| Equipo | λ (goles esp.) | P(≥ 1 gol) | Nivel |")
        md_output.append(f"| :--- | :---: | :---: | :---: |")

        def _scoring_prob_row(team_name, lam):
            p = 1.0 - exp(-lam)
            if p >= 0.65:
                nivel = "Alta 🟢"
            elif p >= 0.40:
                nivel = "Media 🟡"
            else:
                nivel = "Baja 🔴"
            return f"| {team_name} | {lam:.3f} | **{p:.1%}** | {nivel} |"

        md_output.append(_scoring_prob_row(f"{home_raw} (Local)", l_home))
        md_output.append(_scoring_prob_row(f"{away_raw} (Visita)", l_away))

        # Interpretación narrativa automática
        p_home_score = 1.0 - exp(-l_home)
        p_away_score = 1.0 - exp(-l_away)
        md_output.append(f"")
        md_output.append(
            f"> 💬 Aunque el marcador exacto más probable puede ser un {int(round(l_home))}-0 o similar, "
            f"**{away_raw}** tiene **{p_away_score:.0%}** de probabilidad de anotar al menos 1 gol. "
            f"Esos goles están dispersos en marcadores menos probables individualmente (ej. {int(round(l_home))}-1, {max(0,int(round(l_home))-1)}-1), "
            f"que el modelo sí contempla pero no aparecen en el top 5."
        )

        # --- Garbage Goal metric (EXACT: suma sobre grilla Poisson) ---
        # ∑ P(H=h)*P(A=a) donde el fav gana Y el underdog anota ≥1
        from math import factorial

        MAX_G = 15  # techo razonable; P(X>15) es despreciable para λ<5

        def poisson_pmf(lam, k):
            return (lam ** k) * exp(-lam) / factorial(k)

        # Determinar favorito
        if prob_home >= prob_away:
            fav_name, und_name = home_raw, away_raw
            p_fav_win   = prob_home
            p_und_score = p_away_score
            # HOME fav: h > a, a >= 1
            p_garbage_exact = sum(
                poisson_pmf(l_home, h) * poisson_pmf(l_away, a)
                for h in range(1, MAX_G + 1)
                for a in range(1, h)          # a >= 1 y a < h
            )
        else:
            fav_name, und_name = away_raw, home_raw
            p_fav_win   = prob_away
            p_und_score = p_home_score
            # AWAY fav: a > h, h >= 1
            p_garbage_exact = sum(
                poisson_pmf(l_home, h) * poisson_pmf(l_away, a)
                for a in range(1, MAX_G + 1)
                for h in range(1, a)          # h >= 1 y h < a
            )

        # Proxy (para comparación)
        p_garbage_proxy = p_fav_win * p_und_score
        p_garbage = p_garbage_exact   # el que usamos en resumen

        md_output.append(f"")
        md_output.append(
            f"**🗑️ P(Garbage Goal):** {p_garbage_exact:.1%} *(exacta)*"
            f"  ·  proxy simple: {p_garbage_proxy:.1%}"
        )
        md_output.append(
            f"> = Σ P({fav_name}=h)·P({und_name}=a) donde fav gana y underdog ≥1 gol"
        )
        # --- END P(anotar >= 1) SECTION ---

        # Adjustments Table
        md_output.append(f"\n**📊 Desglose Completo de Ajustes:**")
        md_output.append("```")
        
        # Home Log
        md_output.append(f"{home_raw} (Local):")
        md_output.append(f"  λ_base  = {l_home_base:.4f}")
        # Add Home-specific adjustments (those affecting lambda_home)
        # 1. Home Attack Adjustments
        for adj in home_data['report_log']:
            if "Lambda Propio" in adj['desc']: 
                 md_output.append(f"  [HOME] [{adj['pct']:+.1f}%] {adj['desc']}")
            elif "Contexto" in adj['desc'] or "RECENT FORM" in adj['desc']: # Allow Context messages
                 md_output.append(f"  [HOME] [{adj['pct']:+.1f}%] {adj['desc']}")

        # 2. Away Defense Adjustments (affect Home Goals)
        for adj in away_data['report_log']:
            if "Lambda Rival" in adj['desc']: # Increases Home Goals
                 md_output.append(f"  [HOME] [{adj['pct']:+.1f}%] {adj['desc']} (en {away_raw})")
                 
        md_output.append(f"  λ_final = {l_home:.4f}")
        impact_h = ((l_home - l_home_base) / l_home_base) * 100
        md_output.append(f"  Impacto Total: {impact_h:+.1f}%")

        md_output.append("")
        
        # Away Log
        md_output.append(f"{away_raw} (Visita):")
        md_output.append(f"  λ_base  = {l_away_base:.4f}")
        # Away adjustments
        for adj in away_data['report_log']:
            if "Lambda Propio" in adj['desc']:
                 md_output.append(f"  [AWAY] [{adj['pct']:+.1f}%] {adj['desc']}")
            elif "Contexto" in adj['desc'] or "RECENT FORM" in adj['desc']:
                 md_output.append(f"  [AWAY] [{adj['pct']:+.1f}%] {adj['desc']}")
        for adj in home_data['report_log']:
            if "Lambda Rival" in adj['desc']:
                 md_output.append(f"  [AWAY] [{adj['pct']:+.1f}%] {adj['desc']} (en {home_raw})")
                 
        md_output.append(f"  λ_final = {l_away:.4f}")
        impact_a = ((l_away - l_away_base) / l_away_base) * 100
        md_output.append(f"  Impacto Total: {impact_a:+.1f}%")
        md_output.append("```")
        
        # Interpretacion
        md_output.append(f"\n**🔍 Interpretación:**")
        md_output.append(f"- Probabilidades Generales: Local {prob_home*100:.1f}% | Empate {prob_draw*100:.1f}% | Visita {prob_away*100:.1f}%")
        
        # EV Table
        md_output.append(f"\n### 🎯 Mejores Opciones (Ranking por Valor Esperado)")
        md_output.append(f"| Marcador | Tipo | P.Exacta | P.Gral | **Valor Esperado** |")
        md_output.append(f"| :--- | :--- | :--- | :--- | :--- |")
        
        # Generate options from grilla top (ordenadas por EV real de quiniela)
        options = []
        for item in quiniela['top_5_by_ev']:
            h, a = item['h'], item['a']
            p_exact = item['prob']

            if h > a:
                p_result = prob_home
                res_type = "HOME"
            elif h == a:
                p_result = prob_draw
                res_type = "DRAW"
            else:
                p_result = prob_away
                res_type = "AWAY"

            options.append({
                'score': item['score'],
                'type': res_type,
                'p_exact': p_exact,
                'p_gral': p_result,
                'ev': p_result + p_exact
            })

        # Sort by EV descending
        options.sort(key=lambda x: x['ev'], reverse=True)
        
        # Top 8
        for opt in options[:8]:
            md_output.append(f"| **{opt['score']}** | {opt['type']} | {opt['p_exact']*100:.1f}% | {opt['p_gral']*100:.1f}% | **{opt['ev']:.3f}** |")
            
        # Add to summary
        best = options[0]
        summary_picks.append({
            'match': f"{home_raw} vs {away_raw}",
            'pick': best['score'],
            'ev': best['ev'],
            'trend': f"{best['type']} ({best['p_gral']*100:.0f}%)",
            'p_home_score': p_home_score,
            'p_away_score': p_away_score,
            'p_garbage': p_garbage,
            'und_name': und_name,
        })
        
        md_output.append("\n---")

    # Final Summary
    md_output.append(f"# 🏆 Resumen Final: Picks Recomendados")
    md_output.append(f"| Partido | Pick Óptimo | Valor (Puntos Esp.) | Tendencia Base | P(Local ≥1) | P(Visita ≥1) | 🗑️ P(Garbage) |")
    md_output.append(f"| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
    for s in summary_picks:
        md_output.append(
            f"| {s['match']} | **{s['pick']}** | EV: {s['ev']:.3f} | {s['trend']} "
            f"| {s['p_home_score']:.0%} | {s['p_away_score']:.0%} | {s['p_garbage']:.0%} |"
        )
        
    # Write File (outputs + copia en raíz para consulta rápida)
    jornada = runtime_config.get('JORNADA', 'X')
    out_file = f'outputs/reporte_tecnico_jornada_{jornada}.md'
    root_file = f'reporte_tecnico_jornada_{jornada}.md'

    report_content = "\n".join(md_output)

    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(report_content)

    with open(root_file, 'w', encoding='utf-8') as f:
        f.write(report_content)

    print(f"Reporte generado: {out_file}")
    print(f"Copia en raíz: {root_file}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
