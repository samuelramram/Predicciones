import json
import re

def main():
    # 1. Load Current JSON (which now has roles but reset weights)
    try:
        with open("evaluacion_bajas.json", "r", encoding='utf-8') as f:
            data = json.load(f)
            bajas = data.get('bajas_identificadas', [])
    except FileNotFoundError:
        print("Error: evaluacion_bajas.json not found.")
        return

    # 2. Parse MD File "evaluacion_bajas.md"
    try:
        with open("evaluacion_bajas.md", "r", encoding='utf-8') as f:
            md_lines = f.readlines()
    except FileNotFoundError:
        print("Error: evaluacion_bajas.md not found.")
        return

    print("Syncing MD changes to JSON...")
    
    # Map (Team, Player) -> Impact String
    # MD Line format: | Team | **Player** | Status | KeyData | Impact |
    manual_impacts = {}
    
    for line in md_lines:
        if not line.strip().startswith('|') or "---" in line or "Impacto Sugerido" in line:
            continue
            
        parts = [p.strip() for p in line.split('|')]
        if len(parts) < 6: continue
        
        # parts[0] is empty (before first pipe)
        # parts[1] is Team
        # parts[2] is Player (with ** **)
        # parts[5] is Impact
        
        team_name = parts[1].lower()
        player_name = parts[2].replace('**', '').strip()
        impact = parts[5]
        
        # Create unique key
        key = f"{team_name}_{player_name}"
        manual_impacts[key] = impact

    # 3. Update JSON
    updates_count = 0
    for item in bajas:
        t = item['team'].lower()
        p = item['player']
        k = f"{t}_{p}"
        
        if k in manual_impacts:
            old_impact = item.get('suggested_impact', '')
            new_impact = manual_impacts[k]
            
            # Update field
            item['suggested_impact'] = new_impact
            
            # Simple normalization for manual_impact_level
            # Users might type "High", "HIGH", "Mid", "Low", "None"
            level = "Low"
            imp_lower = new_impact.lower()
            
            if "high" in imp_lower: level = "High"
            elif "mid" in imp_lower: level = "Mid"
            elif "low" in imp_lower: level = "Low"
            elif "none" in imp_lower: level = "None"
            
            item['manual_impact_level'] = level
            updates_count += 1
            
    # 4. Save JSON
    data['bajas_identificadas'] = bajas
    with open("evaluacion_bajas.json", "w", encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        
    print(f"Synced {updates_count} players from MD to JSON.")
    print("New field 'manual_impact_level' added to JSON items.")

if __name__ == "__main__":
    main()
