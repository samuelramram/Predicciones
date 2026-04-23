
import json
import os
import argparse

HISTORY_FILE = "data/historial_usuario.json"

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {"user": "Samuel", "history": []}
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_history(data):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def main():
    parser = argparse.ArgumentParser(description="Update user history manually")
    parser.add_argument("--jornada", type=int, help="Jornada number")
    parser.add_argument("--points", type=int, help="Points for the jornada")
    parser.add_argument("--exact", type=int, help="Exact picks")
    
    args = parser.parse_args()
    
    data = load_history()
    
    if args.jornada and args.points is not None:
        # Check if exists
        exists = False
        for entry in data['history']:
            if entry['jornada'] == args.jornada:
                print(f"Jornada {args.jornada} already exists. Updating...")
                entry['points'] = args.points
                if args.exact is not None:
                     entry['exact_picks'] = args.exact
                exists = True
                break
        
        if not exists:
             new_entry = {
                 "tournament": "Clausura 2026", # Default current
                 "jornada": args.jornada,
                 "points": args.points,
                 "exact_picks": args.exact if args.exact is not None else 0,
                 "matches": [] # Empty for manual quick add
             }
             data['history'].append(new_entry)
             print(f"Added Jornada {args.jornada}")
             
        save_history(data)
        print("History updated.")
    else:
        print("Current History:")
        print(json.dumps(data, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
