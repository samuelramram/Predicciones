#!/usr/bin/env python3
"""
FBref Liga MX xG Scraper
Extrae estadísticas de Expected Goals (xG) de FBref para Liga MX Clausura.

Uso:
    python fetch_fbref_stats.py                    # Modo normal
    python fetch_fbref_stats.py --test             # Modo test (no guarda)
    python fetch_fbref_stats.py --output stats.json

El script genera un archivo JSON con xG por equipo que puede integrarse
al JSON de jornada existente.
"""

import argparse
import json
import re
import time
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import pandas as pd
    import cloudscraper
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"ERROR: Dependencias faltantes. Ejecuta: pip install pandas beautifulsoup4 lxml cloudscraper")
    raise e

# Create cloudscraper session (bypasses Cloudflare)
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'mobile': False
    }
)

# --- Configuration ---
FBREF_LIGA_MX_URL = "https://fbref.com/en/comps/31/Liga-MX-Stats"
FBREF_CLAUSURA_URL = "https://fbref.com/en/comps/31/Liga-MX-Stats"  # Will be updated dynamically

# Headers to avoid 403
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

# Team name mapping: FBref -> JSON (modelo.py uses these names)
TEAM_NAME_MAP = {
    # FBref name : JSON name
    "Tigres UANL": "Tigres",
    "UANL": "Tigres",
    "Guadalajara": "CD Guadalajara",
    "Chivas": "CD Guadalajara",
    "Club América": "CF America",
    "América": "CF America",
    "America": "CF America",
    "Cruz Azul": "Cruz Azul",
    "Monterrey": "Monterrey",
    "Rayados": "Monterrey",
    "Pumas UNAM": "Pumas UNAM",
    "UNAM": "Pumas UNAM",
    "Toluca": "Toluca",
    "Santos Laguna": "Santos Laguna",
    "Santos": "Santos Laguna",
    "León": "León",
    "Leon": "León",
    "Necaxa": "Necaxa",
    "Puebla": "Puebla",
    "Pachuca": "Pachuca",
    "Querétaro": "Queretaro FC",
    "Queretaro": "Queretaro FC",
    "Atlas": "Atlas",
    "Tijuana": "Tijuana",
    "Xolos": "Tijuana",
    "San Luis": "Atletico de San Luis",
    "Atlético San Luis": "Atletico de San Luis",
    "Mazatlán": "Mazatlán",
    "Mazatlan": "Mazatlán",
    "Juárez": "FC Juarez",
    "Juarez": "FC Juarez",
    "FC Juárez": "FC Juarez",
}


def normalize_team_name(fbref_name: str) -> str:
    """Convert FBref team name to JSON format."""
    # Clean up name
    name = fbref_name.strip()
    
    # Try direct mapping
    if name in TEAM_NAME_MAP:
        return TEAM_NAME_MAP[name]
    
    # Try partial matches
    for fbref_key, json_name in TEAM_NAME_MAP.items():
        if fbref_key.lower() in name.lower() or name.lower() in fbref_key.lower():
            return json_name
    
    # Return original if no match found
    print(f"  [WARN] No mapping for team: '{name}'")
    return name


def fetch_fbref_page(url: str) -> Optional[str]:
    """Fetch HTML content from FBref using cloudscraper to bypass Cloudflare."""
    print(f"[*] Fetching: {url}")
    
    try:
        response = scraper.get(url, timeout=30)
        response.raise_for_status()
        
        # Rate limiting - be respectful
        time.sleep(3)
        
        return response.text
    except Exception as e:
        print(f"[ERROR] Failed to fetch FBref: {e}")
        return None


def parse_xg_table(html: str) -> Dict[str, Dict[str, float]]:
    """
    Parse FBref HTML to extract xG statistics.
    Returns dict: {team_name: {xG, xGA, PJ, npxG}}
    """
    soup = BeautifulSoup(html, "lxml")
    
    # FBref has multiple tables, we want the main stats table
    # Look for table with id containing "stats" or "overall"
    tables = soup.find_all("table")
    
    print(f"[*] Found {len(tables)} tables on page")
    
    xg_data = {}
    
    for table in tables:
        # Check if this looks like a stats table with xG columns
        header_row = table.find("thead")
        if not header_row:
            continue
            
        headers = [th.get_text(strip=True) for th in header_row.find_all("th")]
        
        # Look for xG column
        if "xG" not in headers and "xg" not in [h.lower() for h in headers]:
            continue
            
        print(f"[*] Found xG table with headers: {headers[:10]}...")
        
        # Parse using pandas for cleaner extraction
        try:
            # Get table HTML and parse with pandas
            table_html = str(table)
            dfs = pd.read_html(table_html)
            
            if not dfs:
                continue
                
            df = dfs[0]
            
            # Handle multi-level columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [' '.join(col).strip() if isinstance(col, tuple) else col for col in df.columns]
            
            # Flatten column names
            df.columns = [str(col).strip() for col in df.columns]
            
            print(f"[*] DataFrame columns: {list(df.columns)[:10]}...")
            
            # Find relevant columns
            team_col = None
            xg_col = None
            xga_col = None
            pj_col = None
            npxg_col = None
            
            for col in df.columns:
                col_lower = col.lower()
                if 'squad' in col_lower or 'team' in col_lower or col_lower == 'team':
                    team_col = col
                elif col_lower == 'xg' or col == 'xG':
                    xg_col = col
                elif col_lower == 'xga' or 'xg against' in col_lower or col == 'xGA':
                    xga_col = col
                elif col_lower == 'mp' or col_lower == 'pj' or 'matches' in col_lower:
                    pj_col = col
                elif 'npxg' in col_lower:
                    npxg_col = col
            
            if not team_col or not xg_col:
                print(f"  [SKIP] Missing required columns (team={team_col}, xG={xg_col})")
                continue
            
            print(f"[*] Using columns: team={team_col}, xG={xg_col}, xGA={xga_col}, PJ={pj_col}")
            
            # Extract data per team
            for _, row in df.iterrows():
                team_raw = str(row.get(team_col, "")).strip()
                
                # Skip header rows / empty
                if not team_raw or team_raw.lower() in ['squad', 'team', 'total', 'vs']:
                    continue
                
                team_name = normalize_team_name(team_raw)
                
                # Extract values
                try:
                    xg_val = float(row.get(xg_col, 0) or 0)
                    xga_val = float(row.get(xga_col, 0) or 0) if xga_col else 0.0
                    pj_val = int(row.get(pj_col, 0) or 0) if pj_col else 0
                    npxg_val = float(row.get(npxg_col, 0) or 0) if npxg_col else xg_val
                    
                    xg_data[team_name] = {
                        "xG": round(xg_val, 2),
                        "xGA": round(xga_val, 2),
                        "npxG": round(npxg_val, 2),
                        "PJ": pj_val,
                        "xG_per_match": round(xg_val / max(1, pj_val), 3),
                        "xGA_per_match": round(xga_val / max(1, pj_val), 3),
                        "source": "FBref",
                    }
                    
                except (ValueError, TypeError) as e:
                    print(f"  [WARN] Failed to parse row for {team_raw}: {e}")
                    continue
            
            if xg_data:
                break  # Found data, stop searching tables
                
        except Exception as e:
            print(f"  [ERROR] Failed to parse table: {e}")
            continue
    
    return xg_data


def fetch_xg_stats() -> Dict[str, Any]:
    """Main function to fetch and parse FBref xG data."""
    
    # Fetch main page
    html = fetch_fbref_page(FBREF_LIGA_MX_URL)
    
    if not html:
        return {"error": "Failed to fetch FBref page", "teams": {}}
    
    # Parse xG table
    xg_data = parse_xg_table(html)
    
    if not xg_data:
        print("[WARN] No xG data found. FBref may have changed structure or blocked request.")
        return {"error": "No xG data found", "teams": {}}
    
    print(f"[+] Successfully extracted xG for {len(xg_data)} teams")
    
    result = {
        "meta": {
            "source": "FBref",
            "url": FBREF_LIGA_MX_URL,
            "competition": "Liga MX",
            "season": "Clausura 2026",
            "extracted_at": pd.Timestamp.now().isoformat(),
            "team_count": len(xg_data),
        },
        "teams": xg_data
    }
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Fetch xG stats from FBref for Liga MX")
    parser.add_argument("--test", action="store_true", help="Test mode - don't save output")
    parser.add_argument("--output", default="data/xg_stats.json", help="Output file path")
    args = parser.parse_args()
    
    print("=" * 60)
    print("FBref Liga MX xG Scraper")
    print("=" * 60)
    
    result = fetch_xg_stats()
    
    if result.get("error"):
        print(f"\n[!] Error: {result['error']}")
    else:
        print(f"\n[+] Extracted data for {len(result['teams'])} teams:")
        for team, stats in sorted(result['teams'].items()):
            print(f"    {team}: xG={stats['xG']:.2f}, xGA={stats['xGA']:.2f}, PJ={stats['PJ']}")
    
    if not args.test and result.get("teams"):
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        print(f"\n[+] Saved to: {output_path}")
    elif args.test:
        print("\n[*] Test mode - output not saved")
    
    return result


if __name__ == "__main__":
    main()
