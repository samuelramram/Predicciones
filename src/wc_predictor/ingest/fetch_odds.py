"""CLI: fetch live WC 2026 bookmaker odds from The Odds API.

Requires a free API key — set THE_ODDS_API_KEY in .env (sign up at
https://the-odds-api.com/, free tier = 500 credits/month, no card).

    python -m wc_predictor.ingest.fetch_odds

One call returns every upcoming WC fixture and costs ~1-2 credits. The raw
response is cached to data/raw/odds_the_odds_api.json; generate_picks reads
that cache automatically and switches to the 3-way (Poisson+Elo+odds) blend.

If no key is set, this exits cleanly with instructions — the pipeline still
works without odds (it falls back to the backtested 70/30 Poisson/Elo blend).
"""
from __future__ import annotations

from wc_predictor.config import get_odds_api_key
from wc_predictor.ingest.odds import fetch_odds_api


def main():
    key = get_odds_api_key()
    if not key:
        print("THE_ODDS_API_KEY not set.")
        print("Get a free key at https://the-odds-api.com/ (500 credits/month, no card),")
        print("then add it to .env:  THE_ODDS_API_KEY=your_key_here")
        print("\nThe pipeline runs fine without odds — it uses the 70/30 Poisson/Elo blend.")
        return

    print("Fetching WC 2026 odds from The Odds API ...")
    odds = fetch_odds_api()
    print(f"  got odds for {len(odds)} matches → cached to data/raw/odds_the_odds_api.json")
    if odds:
        print("\nSample (first 5):")
        for key_, v in list(odds.items())[:5]:
            print(f"  {key_:<45} P1={v['p1']:.2f} PX={v['px']:.2f} P2={v['p2']:.2f} "
                  f"({v['n_books']} books)")
    print("\nNow run: python -m wc_predictor.pipeline.generate_picks --round <round>")


if __name__ == "__main__":
    main()
