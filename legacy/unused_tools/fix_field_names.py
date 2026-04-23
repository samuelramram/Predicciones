import json

# Cargar archivo original
with open('Investigacion_cualitativa_jornada6.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Renombrar todos los campos "player" a "name"
def rename_player_to_name(obj):
    if isinstance(obj, dict):
        new_dict = {}
        for key, value in obj.items():
            if key == "player":
                new_dict["name"] = value
            else:
                new_dict[key] = rename_player_to_name(value)
        return new_dict
    elif isinstance(obj, list):
        return [rename_player_to_name(item) for item in obj]
    else:
        return obj

data_fixed = rename_player_to_name(data)

# Guardar archivo corregido
with open('Investigacion_cualitativa_jornada6.json', 'w', encoding='utf-8') as f:
    json.dump(data_fixed, f, indent=2, ensure_ascii=False)

print("✓ Campo 'player' renombrado a 'name' exitosamente")
