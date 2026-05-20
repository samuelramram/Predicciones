import requests
import json
from datetime import datetime

API_KEY = "180725"
LEAGUE_ID = "4350"
SEASON = "2025-2026"
BASE_URL = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"

def fetch_events():
    url = f"{BASE_URL}/eventsseason.php?id={LEAGUE_ID}&s={SEASON}"
    try:
        r = requests.get(url)
        return r.json().get("events", [])
    except Exception as e:
        print(f"Error: {e}")
        return []

def calculate_table(matches):
    table = {} # { team_name: {pj, w, d, l, gf, gc, pts} }
    
    for m in matches:
        # Skip if not finished
        if m.get('intHomeScore') is None:
            continue
            
        home = m.get('strHomeTeam')
        away = m.get('strAwayTeam')
        try:
            sh = int(m.get('intHomeScore'))
            sa = int(m.get('intAwayScore'))
        except:
            continue
            
        if home not in table: table[home] = {'pj':0,'w':0,'d':0,'l':0,'gf':0,'gc':0,'pts':0}
        if away not in table: table[away] = {'pj':0,'w':0,'d':0,'l':0,'gf':0,'gc':0,'pts':0}
        
        # Home
        table[home]['pj'] += 1
        table[home]['gf'] += sh
        table[home]['gc'] += sa
        if sh > sa:
            table[home]['w'] += 1
            table[home]['pts'] += 3
        elif sh == sa:
            table[home]['d'] += 1
            table[home]['pts'] += 1
        else:
            table[home]['l'] += 1
            
        # Away
        table[away]['pj'] += 1
        table[away]['gf'] += sa
        table[away]['gc'] += sh
        if sa > sh:
            table[away]['w'] += 1
            table[away]['pts'] += 3
        elif sa == sh:
            table[away]['d'] += 1
            table[away]['pts'] += 1
        else:
            table[away]['l'] += 1
            
    return table

def print_table(title, table_data):
    print(f"\n### {title}")
    print("| Equipo | PJ | G | E | P | GF | GC | PTS |")
    print("|---|---|---|---|---|---|---|---|")
    
    # Sort by PTS desc, then GD desc
    sorted_teams = sorted(table_data.items(), key=lambda x: (x[1]['pts'], x[1]['gf']-x[1]['gc']), reverse=True)
    
    for team, stats in sorted_teams:
        print(f"| {team} | {stats['pj']} | {stats['w']} | {stats['d']} | {stats['l']} | {stats['gf']} | {stats['gc']} | {stats['pts']} |")

def main():
    events = fetch_events()
    print(f"Total events found: {len(events)}")
    if events:
        print(f"Sample Event Keys: {list(events[0].keys())}")
        print(f"Sample Event Round Info: Round={events[0].get('intRound')}, strRound={events[0].get('strRound')}")
    
    apertura_matches = []
    apertura_liguilla = []
    clausura_matches = []
    
    for e in events:
        date_str = e.get('dateEvent', '')
        if not date_str: continue
        
        # Simple split: Clausura 2026 starts in Jan 2026
        if date_str >= "2026-01-01":
            clausura_matches.append(e)
        else:
            try:
                round_num = int(e.get('intRound', 0))
            except:
                round_num = 0
            
            # Regular Season: Rounds 1-17
            if 1 <= round_num <= 17:
                apertura_matches.append(e)
            # Liguilla: Late Nov/Dec games (Round 0 or >17)
            elif date_str >= "2025-11-20" and date_str <= "2025-12-31":
                apertura_liguilla.append(e)

    apertura_table = calculate_table(apertura_matches)
    clausura_table = calculate_table(clausura_matches)
    
    print_table("Apertura 2025 (Jul - Dec 2025) - Fase Regular", apertura_table)
    print_table("Clausura 2026 (Jan 2026 - Present)", clausura_table)

    print("\n### Apertura 2025 - Liguilla (Playoffs)")
    apertura_liguilla.sort(key=lambda x: x.get('dateEvent', ''))
    for m in apertura_liguilla:
        print(f"{m.get('dateEvent')} [R{m.get('intRound')}]: {m.get('strHomeTeam')} {m.get('intHomeScore')}-{m.get('intAwayScore')} {m.get('strAwayTeam')}")

    print("\n### Apertura 2025 - Liguilla (Playoffs)")
    # Sort liguilla by date
    apertura_liguilla.sort(key=lambda x: x.get('dateEvent', ''))
    for m in apertura_liguilla:
        print(f"{m.get('dateEvent')} [R{m.get('intRound')}]: {m.get('strHomeTeam')} {m.get('intHomeScore')}-{m.get('intAwayScore')} {m.get('strAwayTeam')}")

if __name__ == "__main__":
    main()


