import json
import pprint

# Cargar datos
with open('jornada_6_final.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print("=" * 80)
print("INVESTIGACION: Estructura exacta de stats por equipo")
print("=" * 80)

# Analizar todos los partidos
for idx, match in enumerate(data['matches'][:3]):  # Primeros 3 partidos
    home_team = match['match']['home']
    away_team = match['match']['away']
    
    print(f"\n{'='*80}")
    print(f"PARTIDO {idx+1}: {home_team} vs {away_team}")
    print(f"{'='*80}")
    
    # Stats home
    stats_home = match['stats']['home']
    print(f"\n--- STATS HOME ({home_team}) ---")
    print(f"Tournaments disponibles: {list(stats_home.keys())}")
    
    if 'clausura_2026' in stats_home:
        c26_home = stats_home['clausura_2026']
        print(f"\nCLAUSURA_2026 HOME ({len(c26_home)} claves):")
        print("Claves disponibles:", sorted(c26_home.keys()))
        print("\nDICT COMPLETO:")
        pprint.pprint(dict(c26_home), width=100)
    
    if 'apertura_2025' in stats_home:
        a25_home = stats_home['apertura_2025']
        print(f"\nAPERTURA_2025 HOME ({len(a25_home)} claves):")
        print("Claves disponibles:", sorted(a25_home.keys()))
    
    # Stats away
    stats_away = match['stats']['away']
    print(f"\n--- STATS AWAY ({away_team}) ---")
    print(f"Tournaments disponibles: {list(stats_away.keys())}")
    
    if 'clausura_2026' in stats_away:
        c26_away = stats_away['clausura_2026']
        print(f"\nCLAUSURA_2026 AWAY ({len(c26_away)} claves):")
        print("Claves disponibles:", sorted(c26_away.keys()))
        print("\nDICT COMPLETO:")
        pprint.pprint(dict(c26_away), width=100)
    
    if 'apertura_2025' in stats_away:
        a25_away = stats_away['apertura_2025']
        print(f"\nAPERTURA_2025 AWAY ({len(a25_away)} claves):")
        print("Claves disponibles:", sorted(a25_away.keys()))

print("\n" + "=" * 80)
print("RESUMEN: Investigar si existen 'PJ', 'PJ_total', 'PJ_home', 'PJ_away'")
print("=" * 80)
