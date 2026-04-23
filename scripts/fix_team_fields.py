"""
Script para arreglar el campo 'team' faltante en competitive_context.
Analiza el claim y asigna 'home' o 'away' según el equipo mencionado.
"""
import json
import sys

def fix_team_fields(input_path, output_path=None):
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    fixes_made = []
    
    for match in data.get('matches', []):
        home_team = match['match']['home'].lower()
        away_team = match['match']['away'].lower()
        match_id = f"{match['match']['home']} vs {match['match']['away']}"
        
        for ctx in match.get('competitive_context', []):
            if 'team' not in ctx or ctx['team'] is None:
                claim = ctx.get('claim', '').lower()
                ctx_type = ctx.get('type', '')
                
                # Attempt to detect team from claim
                team = None
                
                # Check if home team name is in the claim
                if home_team in claim:
                    team = 'home'
                elif away_team in claim:
                    team = 'away'
                # Handle special cases based on type
                elif ctx_type == 'franchise_end':
                    # Usually affects home team (the franchise ending)
                    team = 'home'
                elif ctx_type == 'squad_rebuild':
                    team = 'home'  # Usually mentioned for home team
                elif ctx_type == 'squad_complete':
                    team = 'away'  # Usually mentioned for away team (León in Querétaro vs León)
                
                if team:
                    ctx['team'] = team
                    fixes_made.append({
                        'match': match_id,
                        'type': ctx_type,
                        'team_assigned': team,
                        'claim_preview': ctx.get('claim', '')[:50] + '...'
                    })
                else:
                    print(f"WARNING: Could not determine team for {match_id} | {ctx_type}: {claim[:60]}...")
    
    # Save fixed file
    out = output_path or input_path
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    
    print(f"\n=== Fixes Applied: {len(fixes_made)} ===")
    for fix in fixes_made:
        print(f"  [{fix['team_assigned'].upper()}] {fix['match']} | {fix['type']}")
    
    print(f"\nSaved to: {out}")
    return fixes_made

if __name__ == '__main__':
    input_file = sys.argv[1] if len(sys.argv) > 1 else 'data/processed/jornada_5_final.json'
    fix_team_fields(input_file)
