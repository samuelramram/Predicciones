"""
Script de Diagnostico: Depresion en Lambdas de Visitante
Analiza componentes de lambda_away_base por partido
Output con encoding UTF-8 sin emojis
"""

import json
import pandas as pd

def calculate_lambda_away_components():
    """Calcula componentes de lambda_away_base por partido"""
    
    output_lines = []
    def log(msg):
        output_lines.append(msg)
    
    log("=" * 80)
    log("DIAGNOSTICO: Componentes de Lambda Away Base")
    log("=" * 80)
    
    # Cargar datos del reporte
    with open('jornada_6_final.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    log(f"\n[INFO] Datos cargados: {len(data['matches'])} partidos\n")
    
    # Parametros del modelo (basados en shrinkage actual)
    W_CURR_MAX = 0.85
    SHRINKAGE_DIVISOR = 12.0  # Actual en el modelo
    
    # Calcular league_avg (promedio de goles de la liga)
    stats_df = pd.read_csv('Stats_liga_mx.json', sep='\t')
    clausura_2026 = stats_df[stats_df['tournament'] == 'Clausura 2026']
    
    league_avg_home = clausura_2026['home_goals'].mean()
    league_avg_away = clausura_2026['away_goals'].mean()
    league_avg = (league_avg_home + league_avg_away) / 2.0
    
    log("[PARAMETROS]")
    log(f"  League Avg Home: {league_avg_home:.4f}")
    log(f"  League Avg Away: {league_avg_away:.4f}")
    log(f"  League Avg (promedio): {league_avg:.4f}")
    log(f"  Shrinkage divisor: {SHRINKAGE_DIVISOR}")
    log(f"  W_curr_max: {W_CURR_MAX}\n")
    
    # Analizar cada partido
    results = []
    
    for match in data['matches']:
        home_team = match['match']['home']
        away_team = match['match']['away']
        
        # Stats del visitante (para ataque)
        stats_away = match['stats']['away']
        curr_away = stats_away.get('clausura_2026', {})
        prior_away = stats_away.get('apertura_2025', {})
        
        # Stats del local (para defensa)
        stats_home = match['stats']['home']
        curr_home = stats_home.get('clausura_2026', {})
        prior_home = stats_home.get('apertura_2025', {})
        
        # --- COMPONENTE 1: atts_curr y atts_prior del VISITANTE ---
        pj_away_visitante = curr_away.get('PJ_away', 0)
        gf_away_visitante = curr_away.get('GF_away', 0)
        
        # atts_curr del visitante (goles por partido como visitante)
        atts_curr = gf_away_visitante / pj_away_visitante if pj_away_visitante > 0 else 0
        
        # atts_prior del visitante (del torneo anterior)
        pj_prior_away = prior_away.get('PJ', 0)
        gf_prior_away = prior_away.get('GF', 0)
        atts_prior = gf_prior_away / pj_prior_away if pj_prior_away > 0 else league_avg_away
        
        # --- COMPONENTE 2: defs_curr y defs_prior del LOCAL (rival) ---
        pj_home_local = curr_home.get('PJ_home', 0)
        gc_home_local = curr_home.get('GC_home', 0)
        
        # defs_curr del local (goles concedidos por partido como local)
        defs_curr = gc_home_local / pj_home_local if pj_home_local > 0 else 0
        
        # defs_prior del local (del torneo anterior)
        pj_prior_home = prior_home.get('PJ', 0)
        gc_prior_home = prior_home.get('GC', 0)
        defs_prior = gc_prior_home / pj_prior_home if pj_prior_home > 0 else league_avg_home
        
        # --- COMPONENTE 3: w_curr para el VISITANTE ---
        # Formula simplificada sin context_data
        pj_total = curr_away.get('PJ', pj_away_visitante)
        pj_effective = 0.7 * pj_away_visitante + 0.3 * pj_total
        w_curr = min(W_CURR_MAX, (pj_effective / SHRINKAGE_DIVISOR) * W_CURR_MAX)
        w_prior = 1.0 - w_curr
        
        # --- CALCULO DE LAMBDA_AWAY_BASE ---
        # lambda_away = atts_away_normalized * defs_home_normalized * league_avg
        atts_away_normalized = (w_curr * (atts_curr / league_avg_away) + 
                                w_prior * (atts_prior / league_avg_away))
        defs_home_normalized = (w_curr * (defs_curr / league_avg_home) + 
                                w_prior * (defs_prior / league_avg_home))
        
        lambda_away_base = atts_away_normalized * defs_home_normalized * league_avg
        
        results.append({
            'visitante': away_team,
            'local': home_team,
            'pj_away_vis': pj_away_visitante,
            'pj_home_loc': pj_home_local,
            'atts_curr': atts_curr,
            'atts_prior': atts_prior,
            'defs_curr': defs_curr,
            'defs_prior': defs_prior,
            'w_curr': w_curr,
            'lambda_away_base': lambda_away_base,
        })
    
    df = pd.DataFrame(results)
    
    # Calcular promedios
    promedios = df[['pj_away_vis', 'pj_home_loc', 'atts_curr', 'atts_prior', 
                     'defs_curr', 'defs_prior', 'w_curr', 'lambda_away_base']].mean()
    
    log("\n" + "=" * 80)
    log("TABLA DE COMPONENTES POR PARTIDO")
    log("=" * 80)
    log("")
    
    # Configurar pandas
    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    pd.set_option('display.float_format', '{:.4f}'.format)
    
    # Convertir tabla a string
    tabla_str = df.to_string(index=False)
    for line in tabla_str.split('\n'):
        log(line)
    
    log("\n" + "-" * 80)
    log("PROMEDIOS")
    log("-" * 80)
    log(f"PJ Away (visitante):    {promedios['pj_away_vis']:.2f}")
    log(f"PJ Home (local):        {promedios['pj_home_loc']:.2f}")
    log(f"Atts Curr:              {promedios['atts_curr']:.4f}")
    log(f"Atts Prior:             {promedios['atts_prior']:.4f}")
    log(f"Defs Curr:              {promedios['defs_curr']:.4f}")
    log(f"Defs Prior:             {promedios['defs_prior']:.4f}")
    log(f"W Curr:                 {promedios['w_curr']:.4f}")
    log(f"Lambda Away Base:       {promedios['lambda_away_base']:.4f}")
    
    # Comparacion con datos reales
    log("\n" + "=" * 80)
    log("COMPARACION CON DATOS REALES")
    log("=" * 80)
    
    avg_gf_away_real = clausura_2026['away_goals'].mean()
    
    log(f"\n[REAL] Goles ANOTADOS por visitante (promedio real): {avg_gf_away_real:.4f}")
    log(f"[MODELO] Lambda Away Base (promedio calculado):      {promedios['lambda_away_base']:.4f}")
    diferencia = promedios['lambda_away_base'] - avg_gf_away_real
    pct_diferencia = (promedios['lambda_away_base'] / avg_gf_away_real - 1) * 100
    log(f"[DIFERENCIA] {diferencia:+.4f} ({pct_diferencia:+.2f}%)")
    
    # Analisis de splits pequenos
    log("\n" + "=" * 80)
    log("ANALISIS DE SPLITS PEQUENOS")
    log("=" * 80)
    
    log("\n[VISITANTE] Equipos con pocos partidos como visitante (PJ_away < 3):")
    low_pj_away = df[df['pj_away_vis'] < 3]
    if len(low_pj_away) > 0:
        tabla_low_away = low_pj_away[['visitante', 'pj_away_vis', 'atts_curr', 'w_curr', 'lambda_away_base']].to_string(index=False)
        for line in tabla_low_away.split('\n'):
            log(line)
        log(f"\n  Total: {len(low_pj_away)} equipos")
        log(f"  Lambda Away promedio (splits pequenos): {low_pj_away['lambda_away_base'].mean():.4f}")
    else:
        log("  [OK] Ningun equipo con PJ_away < 3")
    
    log("\n[LOCAL] Equipos locales con pocos partidos en casa (PJ_home < 3):")
    low_pj_home = df[df['pj_home_loc'] < 3]
    if len(low_pj_home) > 0:
        tabla_low_home = low_pj_home[['local', 'pj_home_loc', 'defs_curr', 'w_curr', 'lambda_away_base']].to_string(index=False)
        for line in tabla_low_home.split('\n'):
            log(line)
        log(f"\n  Total: {len(low_pj_home)} equipos")
        log(f"  Lambda Away promedio (cuando local con splits pequenos): {low_pj_home['lambda_away_base'].mean():.4f}")
    else:
        log("  [OK] Ningun equipo local con PJ_home < 3")
    
    # Diagnostico final
    log("\n" + "=" * 80)
    log("DIAGNOSTICO FINAL")
    log("=" * 80)
    
    log(f"\n[DATO] Lambda Away promedio (modelo): {promedios['lambda_away_base']:.4f}")
    log(f"[DATO] Goles Away real (Clausura 2026): {avg_gf_away_real:.4f}")
    log(f"[DATO] Diferencia: {diferencia:+.4f} ({pct_diferencia:+.2f}%)")
    
    log("\nCAUSAS POSIBLES:")
    log("1. Shrinkage excesivo (w_curr basado en /12.0)")
    log("2. Splits pequenos generan ruido en atts_curr y defs_curr")
    log("3. Prior historico desactualizado o no representativo")
    
    log("\nSOLUCIONES APROBADAS:")
    log("1. Cambiar shrinkage a /18.0 (ralentiza convergencia)")
    log("2. Reducir ROSTER_PENALTIES de bajas medias:")
    log("   - (mediocampista, media): 0.95 -> 0.97")
    log("   - (atacante, media): 0.91 -> 0.93")
    log("3. Subir OFFENSIVE_CAP_LOWER: 0.75 -> 0.82")
    
    log("\n" + "=" * 80)
    
    return "\n".join(output_lines)

if __name__ == "__main__":
    try:
        output_text = calculate_lambda_away_components()
        
        # Guardar a archivo con UTF-8
        with open('diagnostico_output_final.txt', 'w', encoding='utf-8') as f:
            f.write(output_text)
        
        # Imprimir a consola
        print(output_text)
        
        print("\n[INFO] Output guardado en: diagnostico_output_final.txt")
        
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
