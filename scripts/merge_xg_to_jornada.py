#!/usr/bin/env python3
"""
Merge xG Stats into Jornada JSON
Combines manual xG data from xg_stats.json with existing jornada JSON.

Usage:
    python merge_xg_to_jornada.py --xg data/xg_stats.json --jornada data/processed/jornada_5_final.json

This adds xG_home, xGA_home, xG_away, xGA_away fields to each team's clausura_2026 stats.
"""

import argparse
import json
from pathlib import Path
from typing import Dict, Any


def load_json(path: str) -> Dict[str, Any]:
    """Load JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data: Dict[str, Any], path: str):
    """Save JSON file."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def merge_xg_stats(jornada_data: Dict[str, Any], xg_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge xG stats into jornada data.
    
    Adds to each team's clausura_2026:
    - xG_per_match (as proxy for attack strength)
    - xGA_per_match (as proxy for defense weakness)
    """
    xg_teams = xg_data.get("teams", {})
    
    if not xg_teams:
        print("[WARN] No xG team data found")
        return jornada_data
    
    merged_count = 0
    missing_teams = []
    
    for match in jornada_data.get("matches", []):
        match_info = match.get("match", {})
        home_team = match_info.get("home", "")
        away_team = match_info.get("away", "")
        
        stats = match.get("stats", {})
        
        # Merge home team xG
        if home_team in xg_teams:
            home_xg = xg_teams[home_team]
            stats["home"]["clausura_2026"]["xG_per_match"] = home_xg.get("xG_per_match", 0.0)
            stats["home"]["clausura_2026"]["xGA_per_match"] = home_xg.get("xGA_per_match", 0.0)
            merged_count += 1
        else:
            missing_teams.append(home_team)
        
        # Merge away team xG
        if away_team in xg_teams:
            away_xg = xg_teams[away_team]
            stats["away"]["clausura_2026"]["xG_per_match"] = away_xg.get("xG_per_match", 0.0)
            stats["away"]["clausura_2026"]["xGA_per_match"] = away_xg.get("xGA_per_match", 0.0)
            merged_count += 1
        else:
            missing_teams.append(away_team)
    
    if missing_teams:
        print(f"[WARN] Missing xG data for teams: {set(missing_teams)}")
    
    print(f"[+] Merged xG stats for {merged_count} team entries")
    
    return jornada_data


def main():
    parser = argparse.ArgumentParser(description="Merge xG stats into jornada JSON")
    parser.add_argument("--xg", default="data/xg_stats.json", help="Path to xG stats JSON")
    parser.add_argument("--jornada", required=True, help="Path to jornada JSON")
    parser.add_argument("--output", default=None, help="Output path (default: overwrite jornada)")
    args = parser.parse_args()
    
    print("=" * 60)
    print("Merge xG Stats into Jornada")
    print("=" * 60)
    
    # Check xG file exists
    xg_path = Path(args.xg)
    if not xg_path.exists():
        print(f"[ERROR] xG file not found: {xg_path}")
        print("[*] Create the file by copying data from FBref manually or running the scraper.")
        return
    
    # Load files
    xg_data = load_json(args.xg)
    jornada_data = load_json(args.jornada)
    
    print(f"[*] Loaded xG data for {len(xg_data.get('teams', {}))} teams")
    print(f"[*] Loaded jornada with {len(jornada_data.get('matches', []))} matches")
    
    # Merge
    merged_data = merge_xg_stats(jornada_data, xg_data)
    
    # Save
    output_path = args.output or args.jornada
    save_json(merged_data, output_path)
    print(f"[+] Saved merged data to: {output_path}")


if __name__ == "__main__":
    main()
