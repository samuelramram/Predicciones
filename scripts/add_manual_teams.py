#!/usr/bin/env python3
"""
Agregar manualmente el campo 'team' a los 8 contextos pendientes
Basado en análisis del contenido del claim
"""
import json

# Mapping manual de los 8 contextos que necesitan team
MANUAL_TEAM_ASSIGNMENTS = {
    "Tigres vs Santos Laguna": {
        "squad_trust": "home"  # Guido Pizarro (Tigres) confía en plantilla
    },
    "Mazatlán vs CD Guadalajara": {
        "pressure": "away",  # Chivas líder invicto busca record
        "momentum": "away"   # Chivas sin presión, en plenitud
    },
    "Toluca vs Cruz Azul": {
        "title_match": None,  # Neutral - afecta a ambos
        "squad_pressure": "home"  # Larcamón (Toluca) busca refuerzos
    },
    "CF America vs Monterrey": {
        "extreme_pressure": "home",  # Jardine (América) bajo presión
        "crisis_squad": "home",      # América con crisis de bajas
        "management": "home"          # Director Deportivo América cesado
    }
}

def add_manual_teams(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    for match in data.get("matches", []):
        match_info = match.get("match", {})
        home_team = match_info.get("home", "")
        away_team = match_info.get("away", "")
        match_id = f"{home_team} vs {away_team}"
        
        if match_id in MANUAL_TEAM_ASSIGNMENTS:
            print(f"[*] Fixing {match_id}")
            assignments = MANUAL_TEAM_ASSIGNMENTS[match_id]
            
            for ctx in match.get("competitive_context", []):
                ctx_type = ctx.get("type")
                if ctx_type in assignments:
                    team_val = assignments[ctx_type]
                    if team_val:
                        ctx["team"] = team_val
                        print(f"  [+] Set '{ctx_type}' team={team_val}")
                    else:
                        # Neutral context - skip (leave None)
                        print(f"  [~] Skipping '{ctx_type}' (neutral)")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    
    print(f"\n[+] Fixed JSON saved to: {output_file}")

if __name__ == "__main__":
    add_manual_teams(
        "data/processed/jornada_5_final_fixed.json",
        "data/processed/jornada_5_final_fixed.json"
    )
