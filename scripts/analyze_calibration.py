import pandas as pd
import json
import os
import glob
from collections import defaultdict

def main():
    print("=== ANALISIS DE CALIBRACION DE PREDICCIONES ===")
    
    # 1. Load History (Actual Results)
    history_path = 'data/historial_usuario.json'
    if not os.path.exists(history_path):
        print(f"ERROR: No se encontró {history_path}")
        return
        
    with open(history_path, 'r', encoding='utf-8') as f:
        history_data = json.load(f)
        
    # Map: (Tournament, Jornada, Team) -> Result Result like '2-1'
    # Actually we need to match matches. A match is defined by Home vs Away.
    # Let's map (Home, Away) -> {Result, Jornada}
    actual_results = {} 
    
    for entry in history_data['history']:
        jornada = entry['jornada']
        for m in entry['matches']:
            key = (m['home'], m['away'])
            actual_results[key] = {
                'result': m['result'],
                'jornada': jornada
            }
            
    # 2. Load Predictions (CSVs)
    # We only have outputs/predicciones_jornada_*.csv
    csv_files = glob.glob('outputs/predicciones_jornada_*_final.csv')
    
    print(f"Archivos de predicciones encontrados: {len(csv_files)}")
    
    predictions = []
    
    for fpath in csv_files:
        try:
            df = pd.read_csv(fpath)
            # Jornada? extract from filename
            # predicciones_jornada_6_final.csv
            fname = os.path.basename(fpath)
            parts = fname.split('_')
            # parts: ['predicciones', 'jornada', '6', 'final.csv']
            if len(parts) >= 3 and parts[1] == 'jornada':
                jornada = int(parts[2])
            else:
                jornada = 0
                
            for _, row in df.iterrows():
                # Columns: home_team_canonical, away_team_canonical, prob_home_win, pick_1x2, ...
                # Problem: History uses raw names, CSV uses canonical. 
                # We can't easily join them without canonicalizing "actual_results" keys or similar.
                # But 'actual_results' has raw names.
                # Let's just store the prediction and we will fuzzy match or use a helper if needed.
                # Actually, simpler: The history JSON has the raw names used in the Input JSON.
                # The CSV has canonical. 
                # We need to canonicalize the history keys to match.
                
                predictions.append({
                    'jornada': jornada,
                    'home_canon': row['home_team_canonical'],
                    'away_canon': row['away_team_canonical'],
                    'prob_home': row['prob_home_win'],
                    'prob_draw': row['prob_draw'],
                    'prob_away': row['prob_away_win'],
                    'pick': row['pick_1x2']
                })
        except Exception as e:
            print(f"Error reading {fpath}: {e}")

    if not predictions:
        print("No hay predicciones para analizar.")
        return

    # 3. Canonicalize History Keys
    import src.predicciones.core as dl
    
    actual_results_canon = {}
    for (h, a), data in actual_results.items():
        h_can = dl.canonical_team_name(h)
        a_can = dl.canonical_team_name(a)
        actual_results_canon[(h_can, a_can)] = data

    # 4. Analyze
    # Metric: High Confidence Home Win (> 55%)
    
    high_conf_hits = 0
    high_conf_total = 0
    
    high_conf_threshold = 0.55
    
    print(f"\nAnalizando Picks Local > {high_conf_threshold:.0%}:")
    
    for p in predictions:
        key = (p['home_canon'], p['away_canon'])
        
        if key not in actual_results_canon:
            # Maybe match hasn't happened or names mismatch widely
            continue
            
        res_data = actual_results_canon[key]
        result_score = res_data['result'] # "2-1"
        
        try:
            g_home, g_away = map(int, result_score.split('-'))
            
            outcome = 'X'
            if g_home > g_away: outcome = '1'
            elif g_away > g_home: outcome = '2'
            
            # Check Home Win High Conf
            if p['prob_home'] > high_conf_threshold:
                high_conf_total += 1
                is_hit = (outcome == '1')
                if is_hit:
                    high_conf_hits += 1
                
                print(f"  J{p['jornada']}: {p['home_canon']} vs {p['away_canon']} | Prob: {p['prob_home']:.2f} | Res: {result_score} ({outcome}) -> {'ACIERTO' if is_hit else 'FALLO'}")
                
        except:
            continue
            
    print("-" * 30)
    if high_conf_total > 0:
        acc = high_conf_hits / high_conf_total
        print(f"Total High Conf Picks: {high_conf_total}")
        print(f"Aciertos: {high_conf_hits}")
        print(f"Precision: {acc:.1%}")
        
        # Check Calibration: Avg Prob vs Accuracy
        # (Very rough with small sample)
        print(f"Target Accuracy (avg prob): >{high_conf_threshold:.0%}")
        if acc < high_conf_threshold:
            print(">> El modelo esta SOBRE-CONFIADO (Precision < Threshold)")
        else:
            print(">> El modelo esta BIEN CALIBRADO o CONSERVADOR")
    else:
        print("No se encontraron partidos jugados que cumplan el criterio de confianza alta en los CSVs disponibles.")

if __name__ == "__main__":
    main()
