import json
from datetime import datetime

# Cargar archivo de la API
with open('jornada_6_api.json', 'r', encoding='utf-8') as f:
    api_data = json.load(f)

print(f"Total partidos en API: {len(api_data['matches'])}")
print("\nPartidos encontrados:")

# Partidos correctos de Jornada 6 según imagen del usuario
jornada_6_matches = [
    ("Puebla", "Pumas"),
    ("Toluca", "Tijuana"),
    ("Atletico de San Luis", "Queretaro FC"),
    ("Pachuca", "Atlas"),
    ("Monterrey", "León"),
    ("FC Juarez", "Necaxa"),
    ("CD Guadalajara", "CF America"),
    ("Santos Laguna", "Mazatlán"),
    ("Cruz Azul", "Tigres")
]

# Filtrar solo los 9 partidos correctos
filtered_matches = []
for i, match in enumerate(api_data['matches']):
    home = match['match']['home']
    away = match['match']['away']
    
    # Normalizar nombres
    home_norm = home.replace("Mazatlán", "Mazatlan").strip()
    away_norm = away.replace("Mazatlán", "Mazatlan").strip()
    
    # Buscar coincidencia
    match_found = False
    for h, a in jornada_6_matches:
        h_norm = h.replace("Mazatlán", "Mazatlan").strip()
        a_norm = a.replace("Mazatlán", "Mazatlan").strip()
        
        if (h_norm in home_norm or home_norm in h_norm) and (a_norm in away_norm or away_norm in a_norm):
            filtered_matches.append(match)
            print(f"  ✓ {home} vs {away}")
            match_found = True
            break
    
    if not match_found:
        print(f"  ✗ {home} vs {away} (no está en J6)")

# Guardar archivo filtrado
api_data_filtered = {
    "jornada": 6,
    "tournament": "Liga MX Clausura 2026",
    "meta": api_data.get('meta', {}),
    "matches": filtered_matches
}

with open('jornada_6_api_filtered.json', 'w', encoding='utf-8') as f:
    json.dump(api_data_filtered, f, indent=4, ensure_ascii=False)

print(f"\n✓ Archivo filtrado creado: {len(filtered_matches)} partidos de Jornada 6")
print("  Guardado en: jornada_6_api_filtered.json")
