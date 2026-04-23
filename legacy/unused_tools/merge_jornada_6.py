import json
import sys
from pathlib import Path
import unicodedata

def remove_accents(text):
    """Remove accents from text"""
    if not text:
        return ""
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

def normalize_team_name(name):
    """Normaliza nombres de equipos con tabla completa de mapeo"""
    if not name:
        return ""
    
    # Remove accents and convert to lowercase
    name_clean = remove_accents(name).lower().strip()
    
    # Comprehensive normalization map
    normalization_map = {
        # Official names with variations
        "cd guadalajara": "chivas",
        "guadalajara": "chivas",
        "cf america": "america",
        "club america": "america",
        "fc juarez": "juarez",
        "atletico de san luis": "san luis",
        "atletico san luis": "san luis",
        "san luis": "san luis",
        "queretaro fc": "queretaro",
        "queretaro": "queretaro",
        "santos laguna": "santos",
        "mazatlan fc": "mazatlan",
        "mazatlan": "mazatlan",
        "leon": "leon",
        "pachuca": "pachuca",
        "atlas": "atlas",
        "toluca": "toluca",
        "tijuana": "tijuana",
        "monterrey": "monterrey",
        "necaxa": "necaxa",
        "cruz azul": "cruz azul",
        "pumas": "pumas",
        "puebla": "puebla",
        "tigres": "tigres",
    }
    
    return normalization_map.get(name_clean, name_clean)

def find_qual_match(home, away, qual_matches):
    """Busca el match cualitativo correspondiente con normalización robusta"""
    home_norm = normalize_team_name(home)
    away_norm = normalize_team_name(away)
    
    for qual in qual_matches:
        qual_home_norm = normalize_team_name(qual.get('home', ''))
        qual_away_norm = normalize_team_name(qual.get('away', ''))
        
        if home_norm == qual_home_norm and away_norm == qual_away_norm:
            return qual
    
    return None

def merge_jornada_6():
    """
    Fusiona datos cuantitativos de la API con investigación cualitativa para Jornada 6
    """
    # Cargar archivos
    api_file = Path("jornada_6_api.json")
    qual_file = Path("Investigacion_cualitativa_jornada6.json")
    output_file = Path("jornada_6_final.json")
    
    print(f"[INFO] Cargando datos de API: {api_file}")
    with open(api_file, 'r', encoding='utf-8') as f:
        api_data = json.load(f)
    
    print(f"[INFO] Cargando investigación cualitativa: {qual_file}")
    with open(qual_file, 'r', encoding='utf-8') as f:
        qual_data = json.load(f)
    
    qual_matches = qual_data['matches']
    
    print(f"[INFO] Fusionando {len(api_data['matches'])} partidos...")
    matches_merged = []
    matched_count = 0
    
    for match_api in api_data['matches']:
        home = match_api['match']['home']
        away = match_api['match']['away']
        
        # Copiar estructura base de la API
        merged = match_api.copy()
        
        # Buscar datos cualitativos correspondientes
        qual_match = find_qual_match(home, away, qual_matches)
        
        if qual_match:
            matched_count += 1
            print(f"  [OK] {home} vs {away}: Fusionando datos cualitativos")
            
            # Reemplazar/agregar secciones cualitativas
            merged['absences'] = qual_match.get('absences', {'home': [], 'away': []})
            merged['roster_changes'] = qual_match.get('roster_changes', {'home': [], 'away': []})
            merged['competitive_context'] = qual_match.get('competitive_context', [])
        else:
            print(f"  [SKIP] {home} vs {away}: Sin datos cualitativos, usando solo API")
            # Mantener estructura vacía
            if 'absences' not in merged:
                merged['absences'] = {'home': [], 'away': []}
            if 'roster_changes' not in merged:
                merged['roster_changes'] = {'home': [], 'away': []}
            if 'competitive_context' not in merged:
                merged['competitive_context'] = []
        
        matches_merged.append(merged)
    
    # Crear archivo final
    final_data = {
        "jornada": 6,
        "tournament": "Liga MX Clausura 2026",
        "meta": api_data.get('meta', {}),
        "matches": matches_merged
    }
    
    print(f"[INFO] Guardando archivo fusionado: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, indent=4, ensure_ascii=False)
    
    print(f"[OK] Fusión completada exitosamente!")
    print(f"  - Total partidos: {len(matches_merged)}")
    print(f"  - Partidos con datos cualitativos: {matched_count}")
    print(f"  - Partidos sin datos cualitativos: {len(matches_merged) - matched_count}")
    print(f"  - Archivo generado: {output_file}")
    
    return output_file

if __name__ == "__main__":
    try:
        output = merge_jornada_6()
        sys.exit(0)
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
