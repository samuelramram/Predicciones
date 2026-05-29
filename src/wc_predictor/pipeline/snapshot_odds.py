"""CLI: capture the bookmaker CLOSING LINE for WC 2026 matches.

The /odds endpoint only returns the CURRENT price. The closing line — the most
predictive single input we can add — is whatever the market shows right before
kickoff. This command snapshots current odds and folds them into a persistent
per-match store, keeping for each match the latest price captured while it was
still upcoming and freezing it once the match starts.

    python -m wc_predictor.pipeline.snapshot_odds

Run it on a schedule so each match converges to its closing line. A cron that
fires ~10 minutes before each matchday's first kickoff is plenty (one call
returns every upcoming fixture and costs ~1-2 credits of the free 500/month):

    # 10 min before the typical 12:00Z and 19:00Z WC kickoffs, Jun–Jul 2026
    50 11 * 6,7 *  cd /path/to/Predicciones && python -m wc_predictor.pipeline.snapshot_odds
    50 18 * 6,7 *  cd /path/to/Predicciones && python -m wc_predictor.pipeline.snapshot_odds

`generate_picks` automatically prefers this closing-line store over a one-off
`fetch_odds` snapshot when it exists. Needs THE_ODDS_API_KEY in .env.
"""
from __future__ import annotations

from wc_predictor.config import get_odds_api_key
from wc_predictor.ingest.odds import CLOSING_LINE_PATH, snapshot_closing_odds


def main():
    key = get_odds_api_key()
    if not key:
        print("THE_ODDS_API_KEY not set.")
        print("Get a free key at https://the-odds-api.com/ (500 credits/month, no card),")
        print("then add it to .env:  THE_ODDS_API_KEY=your_key_here")
        return

    print("Snapshotting WC 2026 odds into the closing-line store ...")
    store = snapshot_closing_odds()
    upcoming = sum(1 for v in store.values() if "captured_at" in v)
    print(f"  closing-line store now holds {len(store)} matches "
          f"→ {CLOSING_LINE_PATH}")
    print("\nSample (first 5):")
    for k, v in list(store.items())[:5]:
        print(f"  {k:<45} P1={v['p1']:.2f} PX={v['px']:.2f} P2={v['p2']:.2f} "
              f"({v['n_books']} books, kickoff {v.get('commence_time')})")
    print("\ngenerate_picks will prefer this store automatically. Re-run before "
          "each jornada to converge on the true closing line.")


if __name__ == "__main__":
    main()
