"""Bookmaker odds ingestion — the strongest single predictor we can add.

Reality check (researched May 2026):
- There is NO free, clean historical dataset of 1X2 odds for *international*
  football. football-data.co.uk — the de-facto standard — is club leagues only.
  Therefore the odds blend CANNOT be backtested the way the Elo blend was.
- For LIVE WC 2026 odds, two free options exist:
    * The Odds API  — free tier 500 credits/month, sport key
      `soccer_fifa_world_cup`. One request returns all upcoming matches.
    * API-Football  — free tier 100 req/day, includes pre-match odds.
  Both need a free API key (see .env.example).

This module is source-agnostic: each fetcher returns the same normalized shape
    {match_key: {"p1": float, "px": float, "p2": float, "n_books": int}}
where match_key is "HOME|AWAY" using canonical (martj42) team names.

De-vigging: each bookmaker's raw implied probabilities (1/decimal_odds) sum to
>1 (the overround / "vig"). We remove it multiplicatively per book, then average
across books weighted by inverse overround (sharper books — lower vig — count more).
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from wc_predictor.config import RAW_DIR, get_odds_api_key

THE_ODDS_API_URL = (
    "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds/"
    "?apiKey={key}&regions={regions}&markets=h2h&oddsFormat=decimal"
)

# The Odds API / bookmakers use some names that differ from martj42 canonical.
ODDS_TEAM_CANONICAL = {
    "USA": "United States",
    "United States of America": "United States",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Korea Republic": "South Korea",
    "South Korea": "South Korea",
    "Czechia": "Czech Republic",
    "Cabo Verde": "Cape Verde",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
}


def _canon(name: str) -> str:
    return ODDS_TEAM_CANONICAL.get(name.strip(), name.strip())


def implied_probs_from_decimal(odds_home: float, odds_draw: float, odds_away: float
                               ) -> tuple[float, float, float, float]:
    """De-vig one bookmaker's decimal odds.

    Returns (p_home, p_draw, p_away, overround). Probabilities are normalized to
    sum to 1; overround is the raw sum before normalization (≈1.05 typical).
    """
    raw = (1.0 / odds_home, 1.0 / odds_draw, 1.0 / odds_away)
    overround = sum(raw)
    return raw[0] / overround, raw[1] / overround, raw[2] / overround, overround


def parse_odds_api_response(payload: list[dict]) -> dict[str, dict]:
    """Convert a The-Odds-API /v4 h2h response into normalized per-match probabilities.

    Pure function — no network. Each event aggregates all bookmakers via
    inverse-overround-weighted averaging of de-vigged probabilities.
    """
    out: dict[str, dict] = {}
    for event in payload:
        home = _canon(event.get("home_team", ""))
        away = _canon(event.get("away_team", ""))
        if not home or not away:
            continue

        acc_p1 = acc_px = acc_p2 = acc_w = 0.0
        n_books = 0
        for book in event.get("bookmakers", []):
            h2h = next((m for m in book.get("markets", []) if m.get("key") == "h2h"), None)
            if not h2h:
                continue
            prices: dict[str, float] = {}
            for o in h2h.get("outcomes", []):
                name = o["name"]
                if name.lower() == "draw":
                    prices["draw"] = o["price"]
                elif _canon(name) == home:
                    prices["home"] = o["price"]
                elif _canon(name) == away:
                    prices["away"] = o["price"]
            if len(prices) != 3:
                continue
            p1, px, p2, overround = implied_probs_from_decimal(
                prices["home"], prices["draw"], prices["away"]
            )
            # Sharper books (lower overround) get more weight.
            w = 1.0 / max(overround - 1.0, 1e-3)
            acc_p1 += w * p1
            acc_px += w * px
            acc_p2 += w * p2
            acc_w += w
            n_books += 1

        if n_books == 0 or acc_w == 0:
            continue
        out[f"{home}|{away}"] = {
            "p1": acc_p1 / acc_w,
            "px": acc_px / acc_w,
            "p2": acc_p2 / acc_w,
            "n_books": n_books,
        }
    return out


def fetch_odds_api(api_key: str | None = None, regions: str = "eu,uk",
                   cache_path: Path | None = None) -> dict[str, dict]:
    """Fetch live WC 2026 odds from The Odds API. Returns normalized per-match probs.

    One call returns every upcoming WC fixture, costing ~1-2 credits. Caches the
    raw response to data/raw/ for reproducibility and to avoid burning credits.
    """
    key = api_key or get_odds_api_key()
    if not key:
        raise RuntimeError(
            "No odds API key. Set THE_ODDS_API_KEY in .env (free tier at the-odds-api.com)."
        )
    url = THE_ODDS_API_URL.format(key=key, regions=regions)
    with urllib.request.urlopen(url) as resp:
        payload = json.loads(resp.read())

    cache = cache_path or (RAW_DIR / "odds_the_odds_api.json")
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return parse_odds_api_response(payload)


def load_cached_odds(cache_path: Path | None = None) -> dict[str, dict]:
    """Load and parse a previously cached The-Odds-API response (offline re-runs)."""
    cache = cache_path or (RAW_DIR / "odds_the_odds_api.json")
    if not cache.exists():
        return {}
    with cache.open(encoding="utf-8") as f:
        return parse_odds_api_response(json.load(f))
