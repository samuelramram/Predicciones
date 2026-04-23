
import json
import os

FILE_PATH = "data/key_players.json"

# Data transcribed from screenshots
elite_scorers = [
    {"name": "João Pedro Galvão", "team": "Atlético de San Luis", "stat": "6 goals (3.28 xG)"},
    {"name": "Armando González", "team": "CD Guadalajara", "stat": "5 goals (5.35 xG)"},
    {"name": "José Paradela", "team": "Cruz Azul", "stat": "4 goals (1.15 xG)"},
    {"name": "Marcelo Flores", "team": "Tigres UANL", "stat": "3 goals (0.84 xG)"},
    {"name": "Juninho Vieira", "team": "Pumas UNAM", "stat": "3 goals (1.11 xG)"}
]

elite_playmakers = [
    {"name": "Efraín Álvarez", "team": "CD Guadalajara", "stat": "5 Big Chances Created"},
    {"name": "Fernando Beltrán", "team": "León", "stat": "5 Big Chances Created"},
    {"name": "Diego González", "team": "Atlas", "stat": "4 Big Chances Created"},
    {"name": "Santiago Simón", "team": "Atlético de San Luis", "stat": "4 Big Chances Created"},
    {"name": "Oussama Idrissi", "team": "Pachuca", "stat": "3 Big Chances Created"}
]

elite_goalkeepers = [
    {"name": "Ricardo Gutierrez", "team": "Mazatlán", "stat": "26 Saves (7.47 Rating)"},
    {"name": "Antonio Rodríguez", "team": "Atlas", "stat": "20 Saves (7.42 Rating)"},
    {"name": "Carlos Moreno", "team": "Pachuca", "stat": "11 Saves (7.38 Rating)"},
    {"name": "Hugo González", "team": "Atlético de San Luis", "stat": "12 Saves (7.30 Rating)"},
    {"name": "Luis Malagón", "team": "Club América", "stat": "12 Saves (7.22 Rating)"}
]

high_volume_shooters = [
    {"name": "Armando González", "team": "CD Guadalajara", "stat": "20 Total Shots"},
    {"name": "João Pedro Galvão", "team": "Atlético de San Luis", "stat": "19 Total Shots"},
    {"name": "Kevin Castañeda", "team": "Tijuana", "stat": "18 Total Shots"},
    {"name": "José Paradela", "team": "Cruz Azul", "stat": "16 Total Shots"},
    {"name": "Salomón Rondón", "team": "Pachuca", "stat": "15 Total Shots"}
]

elite_defenders = [
    {"name": "Marcel Ruiz", "team": "Toluca", "stat": "17 Tackles"},
    {"name": "Ricardo Chávez", "team": "Atlético de San Luis", "stat": "16 Tackles"}, # Inferred team, usually San Luis
    {"name": "Santiago Homenchenko", "team": "Querétaro", "stat": "16 Tackles"}, # Inferred
    {"name": "Gaddi Aguirre", "team": "Atlas", "stat": "16 Tackles"},
    {"name": "Carlos Rotondi", "team": "Cruz Azul", "stat": "16 Tackles"}
]

def update_json():
    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Update Elite Traits
    data['elite_traits_players']['elite_scorer'] = elite_scorers
    data['elite_traits_players']['elite_playmaker'] = elite_playmakers
    data['elite_traits_players']['elite_goalkeeper'] = elite_goalkeepers
    data['elite_traits_players']['high_volume_shooter'] = high_volume_shooters
    
    # Add new category if not exists (or update)
    if 'elite_traits' in data['_meta']:
        data['_meta']['elite_traits']['elite_defender'] = "Tackles >= 15 - Top defensores"
    else:
        # Fallback if structure is different, though we saw it in _meta
        print("Warning: Could not find _meta.elite_traits to add definition.")
    
    data['elite_traits_players']['elite_defender'] = elite_defenders
    
    # Save
    with open(FILE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    
    print("Successfully updated elite players in key_players.json")

if __name__ == "__main__":
    update_json()
