
import sys
import os
import json

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.predicciones import data
import src.predicciones.core as dl

# Mock key_players.json for test
TEST_KEY_PLAYERS = {
    "players": [
        {"name": "Test Star", "team": "Test FC", "rank": 1, "rating": 8.0}
    ],
    "elite_traits_players": {
        "elite_scorer": [
            {"name": "Elite Striker", "team": "Test FC"}
        ]
    }
}

TEST_BAJAS = {
    "bajas_identificadas": [
        {
            "team": "Test FC",
            "player": "Test Star",
            "role": "Mediocampista",
            "status": "Lesionado",
            "manual_impact_level": "Low", # Should upgrade to High
            "minutes_played": 90
        },
        {
            "team": "Test FC",
            "player": "Elite Striker",
            "role": "Atacante",
            "status": "Fuera",
            "manual_impact_level": "Mid", # Should upgrade to High
            "minutes_played": 90
        },
        {
            "team": "Test FC",
            "player": "Random Scrub",
            "role": "Defensa",
            "status": "Fuera",
            "manual_impact_level": "Mid", # Should stay Mid
            "minutes_played": 90
        }
    ]
}

def setup_mocks():
    with open("data/test_key_players.json", "w", encoding="utf-8") as f:
        json.dump(TEST_KEY_PLAYERS, f)
        
    with open("data/test_bajas.json", "w", encoding="utf-8") as f:
        json.dump(TEST_BAJAS, f)

def run_test():
    print("--- Running Key Player Impact Test ---")
    
    # Let's use REAL key_players.json for a real integration test
    print("Testing with REAL key_players.json data...")
    
    # "Armando González" (Chivas) is Elite Scorer -> Should be High
    # "Efraín Álvarez" (Chivas) is Rank 1 -> Should be High
    
    # Mock a baja input
    real_bajas_input = {
        "bajas_identificadas": [
            {
                "team": "CD Guadalajara",
                "player": "Armando González",
                "role": "Atacante",
                "status": "Fuera",
                "manual_impact_level": "Low",
                "minutes_played": 100
            },
            {
                "team": "CD Guadalajara",
                "player": "Efraín Álvarez",
                "role": "Mediocampista",
                "status": "Fuera",
                "manual_impact_level": "Low",
                "minutes_played": 100
            }
        ]
    }
    
    with open("data/temp_real_bajas_test.json", "w", encoding="utf-8") as f:
        json.dump(real_bajas_input, f)
        
    # Clear cache just in case
    data.KEY_PLAYERS_CACHE = {}
    
    # Run logic
    try:
        adj = data.load_bajas_penalties("data/temp_real_bajas_test.json")
    except Exception as e:
        print(f"CRITICAL ERROR in load_bajas_penalties: {e}")
        import traceback
        traceback.print_exc()
        return

    # Keys are canonicalized!
    # "CD Guadalajara" -> "guadalajara"
    target_team_key = "guadalajara"
    
    # Debug: print keys
    print(f"Adjustment keys: {list(adj.keys())}")

    chivas = adj.get(target_team_key)
    if not chivas:
        print(f"FAIL: No adjustments for {target_team_key}")
        return
        
    print("\nLogs for Chivas:")
    for note in chivas['notes']:
        print(f"  - {note}")
        
    # Check assertions
    failed = False
    
    # Armando Gonzalez
    found_armando = any("Armando González" in n and "High" in n for n in chivas['notes'])
    if found_armando:
        print("PASS: Armando González upgraded to High (Elite Scorer)")
    else:
        print("FAIL: Armando González NOT upgraded to High")
        failed = True
        
    # Efrain Alvarez
    found_efrain = any("Efraín Álvarez" in n and "High" in n for n in chivas['notes'])
    if found_efrain:
        print("PASS: Efraín Álvarez upgraded to High (Rank 1)")
    else:
        print("FAIL: Efraín Álvarez NOT upgraded to High")
        failed = True

    if not failed:
        print("\n✅ TEST PASSED")
    else:
        print("\n❌ TEST FAILED")

    # Cleanup
    if os.path.exists("data/temp_real_bajas_test.json"):
        os.remove("data/temp_real_bajas_test.json")

if __name__ == "__main__":
    run_test()
