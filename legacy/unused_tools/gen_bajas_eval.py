import json
import re
import difflib
import os

def canonical_team_name(name):
    name = name.lower()
    mapping = {
        'cf america': 'america', 'club america': 'america', 'américa': 'america',
        'pumas': 'pumas', 'pumas unam': 'pumas', 'unam': 'pumas',
        'queretaro fc': 'queretaro', 'querétaro': 'queretaro',
        'tigres uanl': 'tigres', 'tigres': 'tigres', 'uanl': 'tigres',
        'cd guadalajara': 'guadalajara', 'chivas': 'guadalajara',
        'fc juarez': 'juarez', 'juarez': 'juarez', 'bravos': 'juarez',
        'atletico san luis': 'atletico de san luis', 'san luis': 'atletico de san luis',
        'santos': 'santos laguna', 'santos laguna': 'santos laguna',
        'leon': 'leon', 'león': 'leon',
        'mazatlan': 'mazatlan', 'mazatlán': 'mazatlan',
        'toluca': 'toluca',
        'pachuca': 'pachuca',
        'puebla': 'puebla',
        'atlas': 'atlas',
        'necaxa': 'necaxa',
        'tijuana': 'tijuana', 'xolos': 'tijuana',
        'cruz azul': 'cruz azul',
        'monterrey': 'monterrey', 'rayados': 'monterrey'
    }
    for k, v in mapping.items():
        if k in name:
            return v
    return name

def parse_qualitative(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    bajas = []
    current_team = None
    section = None
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        m_ausencias = re.search(r"AUSENCIAS CONFIRMADAS \((.*?)\):", line)
        if m_ausencias:
            current_team = canonical_team_name(m_ausencias.group(1))
            section = 'ausencias'
            i += 1
            continue
            
        if "TRANSFERENCIAS" in line: section = 'transfers'
        if "CONTEXTO" in line: section = 'contexto'
        
        if section == 'ausencias' and current_team:
            if "Jugador:" in line:
                name_m = re.search(r"Jugador:\s*(.*?)\s*\|", line)
                status_m = re.search(r"Estatus:\s*(.*?)\s*\|", line)
                role_m = re.search(r"Posición/rol:\s*(.*?)\s*\|", line)
                what_m = re.search(r"Qué pasó:\s*(.*)", line)
                
                name = name_m.group(1).strip() if name_m else "Unknown"
                status = status_m.group(1).strip() if status_m else "Unknown"
                role = role_m.group(1).strip() if role_m else "Unknown"
                reason = what_m.group(1).strip() if what_m else ""

                bajas.append({
                    'team': current_team,
                    'player': name,
                    'status': status,
                    'role': role,
                    'reason': reason
                })
            elif len(line) > 10 and not line.startswith("Fuente") and not line.startswith("http"):
                 # Free text check (simple)
                 # If it contains "baja" or "lesion" or names we might care, but for now stick to structured if possible
                 # Or treat as "General Note"
                 pass
        
        i+=1
    return bajas

def load_key_players():
    path = "data/key_players.json"
    if not os.path.exists(path): return []
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('players', [])

def similarity(s1, s2):
    return difflib.SequenceMatcher(None, s1.lower(), s2.lower()).ratio()

def main():
    bajas = parse_qualitative("Investigacion_cualitativa_jornada6.json")
    key_players = load_key_players()
    
    output_list = []
    
    for baja in bajas:
        player_name = baja['player']
        team_name = baja['team']
        
        # Try to match with key players
        match = None
        best_score = 0
        
        for kp in key_players:
            # Check team first (loose match)
            kp_team = canonical_team_name(kp['team'])
            if kp_team != team_name: continue
            
            score = similarity(player_name, kp['name'])
            if score > 0.6 and score > best_score: # Threshold
                best_score = score
                match = kp
        
        item = {
            'team': team_name,
            'player': player_name,
            'status': baja['status'],
            'role': baja['role'],
            'reason': baja['reason'],
            'stats_source': 'key_players.json' if match else 'Not Found in Top 100',
            'key_data': {
                'rank': match['rank'],
                'rating': match['rating'],
                'goals': match.get('goals',0),
                'assists': match.get('assists',0)
            } if match else None,
            'suggested_impact': "HIGH (Top 100)" if match else "Low/Unknown",
            'user_weight': 0.0, # TO FILL
            'notes': ""
        }
        output_list.append(item)
        
    # Validation / Output
    final_obj = {
        "meta": "Evaluacion de Impacto de Bajas - Jornada 6",
        "instructions": "Revise la lista y asigne un valor entre 0.0 y 1.0 en 'user_weight' para indicar cuanto debe afectar al equipo.",
        "bajas_identificadas": output_list
    }
    
    with open("evaluacion_bajas.json", "w", encoding='utf-8') as f:
        json.dump(final_obj, f, indent=4, ensure_ascii=False)
        
    print("Archivo generado: evaluacion_bajas.json")

    # Also generate MD for display
    with open("evaluacion_bajas.md", "w", encoding='utf-8') as f:
        f.write("# 📋 Evaluación de Bajas - Jornada 6\n\n")
        f.write("| Equipo | Jugador | Estatus | Stats Key (Rank/Rating) | Impacto Sugerido |\n")
        f.write("|---|---|---|---|---|\n")
        for item in output_list:
            stats = f"Rank {item['key_data']['rank']} (Rat: {item['key_data']['rating']})" if item['key_data'] else "-"
            f.write(f"| {item['team'].title()} | **{item['player']}** | {item['status']} | {stats} | {item['suggested_impact']} |\n")
    print("Archivo generado: evaluacion_bajas.md")

if __name__ == "__main__":
    main()
