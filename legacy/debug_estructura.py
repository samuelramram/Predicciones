import json

# Cargar datos
with open('jornada_6_final.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Primer partido
match = data['matches'][0]
home_team = match['match']['home']
away_team = match['match']['away']

print(f"=== PARTIDO: {home_team} vs {away_team} ===\n")

# Stats home
print("--- STATS HOME (", home_team, ") ---")
stats_home = match['stats']['home']
print("Tournaments disponibles:", list(stats_home.keys()))

if 'clausura_2026' in stats_home:
    c26_home = stats_home['clausura_2026']
    print("\nClausura 2026 HOME - todas las claves:")
    for key in sorted(c26_home.keys()):
        print(f"  {key}: {c26_home[key]}")

if 'apertura_2025' in stats_home:
    a25_home = stats_home['apertura_2025']
    print("\nApertura 2025 HOME - todas las claves:")
    for key in sorted(a25_home.keys()):
        print(f"  {key}: {a25_home[key]}")

# Stats away
print("\n--- STATS AWAY (", away_team, ") ---")
stats_away = match['stats']['away']
print("Tournaments disponibles:", list(stats_away.keys()))

if 'clausura_2026' in stats_away:
    c26_away = stats_away['clausura_2026']
    print("\nClausura 2026 AWAY - todas las claves:")
    for key in sorted(c26_away.keys()):
        print(f"  {key}: {c26_away[key]}")

if 'apertura_2025' in stats_away:
    a25_away = stats_away['apertura_2025']
    print("\nApertura 2025 AWAY - todas las claves:")
    for key in sorted(a25_away.keys()):
        print(f"  {key}: {a25_away[key]}")
