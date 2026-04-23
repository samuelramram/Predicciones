import json

# Load cache
with open('event_stats_cache.json', 'r') as f:
    cache = json.load(f)

# Get events with stats
events_with_stats = [(k, v) for k, v in cache.items() if v and len(v) > 0]

print(f"Total eventos con estadísticas detalladas: {len(events_with_stats)}\n")

# Load all events to get dates
import requests
BASE_URL = "https://www.thesportsdb.com/api/v1/json/180725"

print("Event ID | Fecha      | Partido")
print("-" * 60)

for event_id, stats in events_with_stats[:11]:
    try:
        url = f"{BASE_URL}/lookupevent.php?id={event_id}"
        response = requests.get(url)
        data = response.json()
        
        if data and 'events' in data and data['events']:
            event = data['events'][0]
            date = event.get('dateEvent', 'N/A')
            home = event.get('strHomeTeam', 'N/A')
            away = event.get('strAwayTeam', 'N/A')
            
            print(f"{event_id} | {date} | {home} vs {away}")
    except Exception as e:
        print(f"{event_id} | ERROR | {e}")
