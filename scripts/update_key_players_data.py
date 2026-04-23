
import json
import os

FILE_PATH = "data/key_players.json"

# Data transcribed from screenshots
# Top 60 by Rating (Images 1, 2, 3)
# Structure: Name, Team (inferred), Stats (Goals, Assists, Rating)
top_players_data = [
    # Image 1 (1-20)
    {"rank": 1, "name": "Efraín Álvarez", "team": "CD Guadalajara", "rating": 7.58, "goals": 1, "assists": 1},
    {"rank": 2, "name": "Diego Lainez", "team": "Tigres UANL", "rating": 7.57, "goals": 2, "assists": 1},
    {"rank": 3, "name": "Marcel Ruiz", "team": "Toluca", "rating": 7.52, "goals": 1, "assists": 1},
    {"rank": 4, "name": "Adalberto Carrasquilla", "team": "Pumas UNAM", "rating": 7.50, "goals": 2, "assists": 0},
    {"rank": 5, "name": "Juan Manuel Sanabria", "team": "Atlético de San Luis", "rating": 7.50, "goals": 1, "assists": 1},
    {"rank": 6, "name": "Juan Pablo Vargas", "team": "Mazatlán", "rating": 7.50, "goals": 1, "assists": 0}, # Inferred team from logo/context
    {"rank": 7, "name": "Ricardo Gutierrez", "team": "Mazatlán", "rating": 7.47, "goals": 0, "assists": 0},
    {"rank": 8, "name": "Jonathan Dos Santos", "team": "Club América", "rating": 7.43, "goals": 0, "assists": 1},
    {"rank": 9, "name": "Israel Reyes", "team": "Club América", "rating": 7.42, "goals": 0, "assists": 0},
    {"rank": 10, "name": "Agustín Palavecino", "team": "Cruz Azul", "rating": 7.42, "goals": 2, "assists": 0},
    {"rank": 11, "name": "Antonio Rodríguez", "team": "Atlas", "rating": 7.42, "goals": 0, "assists": 0},
    {"rank": 12, "name": "Germán Berterame", "team": "Monterrey", "rating": 7.40, "goals": 2, "assists": 0},
    {"rank": 13, "name": "Carlos Moreno", "team": "Pachuca", "rating": 7.38, "goals": 0, "assists": 0},
    {"rank": 14, "name": "João Pedro Galvão", "team": "Atlético de San Luis", "rating": 7.37, "goals": 6, "assists": 0},
    {"rank": 15, "name": "José Paradela", "team": "Cruz Azul", "rating": 7.37, "goals": 4, "assists": 1},
    {"rank": 16, "name": "Daniel Aguirre", "team": "CD Guadalajara", "rating": 7.37, "goals": 2, "assists": 1},
    {"rank": 17, "name": "Luca Orellano", "team": "Monterrey", "rating": 7.37, "goals": 1, "assists": 1},
    {"rank": 18, "name": "Hugo Gonzalez", "team": "Atlético de San Luis", "rating": 7.30, "goals": 0, "assists": 0},
    {"rank": 19, "name": "Víctor Guzmán", "team": "Monterrey", "rating": 7.30, "goals": 0, "assists": 0},
    {"rank": 20, "name": "Kevin Castañeda", "team": "Tijuana", "rating": 7.27, "goals": 2, "assists": 1},
    # Image 2 (21-40)
    {"rank": 21, "name": "Carlos Rodríguez", "team": "Cruz Azul", "rating": 7.27, "goals": 1, "assists": 0},
    {"rank": 22, "name": "Oussama Idrissi", "team": "Pachuca", "rating": 7.25, "goals": 2, "assists": 1},
    {"rank": 23, "name": "Brian García", "team": "Pachuca", "rating": 7.24, "goals": 1, "assists": 0},
    {"rank": 24, "name": "Jhojan Julio", "team": "Santos Laguna", "rating": 7.22, "goals": 2, "assists": 0},
    {"rank": 25, "name": "Franco Romero", "team": "Atlético de San Luis", "rating": 7.22, "goals": 0, "assists": 0},
    {"rank": 26, "name": "Unai Bilbao", "team": "Tijuana", "rating": 7.22, "goals": 1, "assists": 0},
    {"rank": 27, "name": "Luis Malagón", "team": "Club América", "rating": 7.22, "goals": 0, "assists": 0},
    {"rank": 28, "name": "Marcelo Flores", "team": "Tigres UANL", "rating": 7.20, "goals": 3, "assists": 0},
    {"rank": 29, "name": "Helinho", "team": "Toluca", "rating": 7.20, "goals": 2, "assists": 0},
    {"rank": 30, "name": "Diego González", "team": "Atlas", "rating": 7.20, "goals": 0, "assists": 1},
    {"rank": 31, "name": "Roberto Alvarado", "team": "CD Guadalajara", "rating": 7.18, "goals": 1, "assists": 1},
    {"rank": 32, "name": "Keylor Navas", "team": "Pumas UNAM", "rating": 7.17, "goals": 0, "assists": 0},
    {"rank": 33, "name": "Erick Sánchez", "team": "Club América", "rating": 7.17, "goals": 0, "assists": 0},
    {"rank": 34, "name": "Bruno Méndez", "team": "Toluca", "rating": 7.15, "goals": 0, "assists": 0},
    {"rank": 35, "name": "Fernando Beltrán", "team": "León", "rating": 7.14, "goals": 0, "assists": 2}, # Logo looks like Leon in image 35
    {"rank": 36, "name": "Luis Romo", "team": "CD Guadalajara", "rating": 7.14, "goals": 0, "assists": 1},
    {"rank": 37, "name": "Joaquim", "team": "Tigres UANL", "rating": 7.13, "goals": 1, "assists": 0},
    {"rank": 38, "name": "Óliver Torres", "team": "Monterrey", "rating": 7.13, "goals": 0, "assists": 2},
    {"rank": 39, "name": "Nahuel Guzmán", "team": "Tigres UANL", "rating": 7.13, "goals": 0, "assists": 0},
    {"rank": 40, "name": "Guillermo Allison", "team": "Querétaro", "rating": 7.13, "goals": 0, "assists": 0},
    # Image 3 (41-60)
    {"rank": 41, "name": "Álvaro Fidalgo", "team": "Club América", "rating": 7.13, "goals": 0, "assists": 0},
    {"rank": 42, "name": "Eduardo Bauermann", "team": "Pachuca", "rating": 7.13, "goals": 0, "assists": 0}, # Logo 42 same as Pachuca
    {"rank": 43, "name": "Omar Govea", "team": "CD Guadalajara", "rating": 7.13, "goals": 0, "assists": 0},
    {"rank": 44, "name": "Alonso Aceves", "team": "Monterrey", "rating": 7.12, "goals": 0, "assists": 0}, # Logo 44 Rayados
    {"rank": 45, "name": "Juninho Vieira", "team": "Pumas UNAM", "rating": 7.10, "goals": 3, "assists": 2},
    {"rank": 46, "name": "Diego Sánchez", "team": "Tigres UANL", "rating": 7.10, "goals": 1, "assists": 0},
    {"rank": 47, "name": "Pedro Vite", "team": "Pumas UNAM", "rating": 7.10, "goals": 1, "assists": 0},
    {"rank": 48, "name": "Rodrigo Dourado", "team": "Club América", "rating": 7.10, "goals": 0, "assists": 1},
    {"rank": 49, "name": "Raúl Rangel", "team": "CD Guadalajara", "rating": 7.10, "goals": 0, "assists": 0},
    {"rank": 50, "name": "Sergio Barreto", "team": "Pachuca", "rating": 7.10, "goals": 0, "assists": 0},
    {"rank": 51, "name": "Emilio Lara", "team": "Necaxa", "rating": 7.10, "goals": 0, "assists": 0},
    {"rank": 52, "name": "Francisco Villalba", "team": "Santos Laguna", "rating": 7.08, "goals": 2, "assists": 1},
    {"rank": 53, "name": "Jackson Porozo", "team": "Tijuana", "rating": 7.08, "goals": 0, "assists": 0}, # Inferred Xolos
    {"rank": 54, "name": "Jordan Carrillo", "team": "Pumas UNAM", "rating": 7.08, "goals": 2, "assists": 1},
    {"rank": 55, "name": "Jesús Gallardo", "team": "Toluca", "rating": 7.08, "goals": 0, "assists": 1},
    {"rank": 56, "name": "Denzell Garcia", "team": "FC Juárez", "rating": 7.07, "goals": 1, "assists": 1},
    {"rank": 57, "name": "Santiago Simón", "team": "Atlético de San Luis", "rating": 7.07, "goals": 0, "assists": 1},
    {"rank": 58, "name": "Elías Montiel", "team": "Pachuca", "rating": 7.07, "goals": 0, "assists": 0},
    {"rank": 59, "name": "Iker Fimbres", "team": "Monterrey", "rating": 7.05, "goals": 2, "assists": 0},
    {"rank": 60, "name": "Francisco Nevarez", "team": "FC Juárez", "rating": 7.05, "goals": 1, "assists": 0}
]

# Elite Traits Data (Top Scorers/xG and Assists)
# Image 4: Top xG
elite_xg_leaders = [
    {"name": "Armando González", "team": "CD Guadalajara", "stat": "5.35 xG (5 goles)"},
    {"name": "João Pedro Galvão", "team": "Atlético de San Luis", "stat": "3.28 xG (6 goles)"},
    {"name": "Mateo Coronel", "team": "Querétaro", "stat": "3.21 xG (2 goles)"},
    {"name": "Lucas Di Yorio", "team": "Santos Laguna", "stat": "3.05 xG (3 goles)"},
    {"name": "Paulinho", "team": "Toluca", "stat": "2.95 xG (2 goles)"},
     {"name": "Ángel Correa", "team": "Tigres UANL", "stat": "2.89 xG (2 goles)"},
      {"name": "Óscar Estupiñán", "team": "FC Juárez", "stat": "2.85 xG (2 goles)"}
]

# Image 5: Top Assists
elite_assist_leaders = [
    {"name": "Alan Medina", "team": "Mazatlán", "stat": "3 asistencias"},
    {"name": "Franco Rossano", "team": "Necaxa", "stat": "3 asistencias"},
    {"name": "Gabriel Fernández", "team": "Cruz Azul", "stat": "3 asistencias"},
    {"name": "Fernando Beltrán", "team": "León", "stat": "2 asistencias"},
    {"name": "Óliver Torres", "team": "Monterrey", "stat": "2 asistencias"}
]


def update_json():
    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Update Meta
    data['_meta']['extracted'] = "2026-02-16 (Jornada 6)"
    data['_meta']['source'] = "SofaScore Screenshots (User Provided)"

    # Update Players
    # Try to preserve role if exists in current data, else 'tbd'
    existing_roles = {p['name']: p.get('role', 'tbd') for p in data['players']}
    
    new_players_list = []
    for p in top_players_data:
        role = existing_roles.get(p['name'], 'tbd')
        # Simple heuristic for role if TBD
        if role == 'tbd':
            if p['goals'] > 1: role = 'atacante'
            elif p['assists'] > 1: role = 'mediocampista'
            else: role = 'defensor' # Default fallback
            
        new_entry = {
            "rank": p['rank'],
            "name": p['name'],
            "team": p['team'],
            "role": role,
            "rating": p['rating'],
            "goals": p['goals'],
            "assists": p['assists']
        }
        new_players_list.append(new_entry)

    data['players'] = new_players_list

    # Update Elite Traits
    data['elite_traits_players']['elite_scorer'] = elite_xg_leaders
    data['elite_traits_players']['elite_playmaker'] = elite_assist_leaders
    
    # Save
    with open(FILE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    
    print("Successfully updated key_players.json")

if __name__ == "__main__":
    update_json()
