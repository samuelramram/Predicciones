"""Fetch Liga MX bookmaker odds from The Odds API (sport soccer_mexico_ligamx).

Two products from one fetch:

  data/ligamx/odds_h2h.json      {home|away: {p1, px, p2, n_books, commence_time}}
                                 de-vigged, book-weighted 1X2 probs → the blend's
                                 third source (Fase 1b.2). Same shape the WC blend
                                 consumes.
  data/ligamx/odds_markets.json  per match: FAIR (no-vig) probs + BEST price/book
                                 for 1X2 and Over/Under lines → the value-betting
                                 module (Fase 3). Best price = line-shopping target.

Team names from the API ("Atlante FC", "América", …) are normalised to the
canonical name_es via ingest.ligamx.normalize_name so keys match fixtures.json.

Run (needs THE_ODDS_API_KEY):
    python -m wc_predictor.ingest.ligamx_odds
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from wc_predictor.config import get_odds_api_key
from wc_predictor.ingest.ligamx import normalize_name
from wc_predictor.ingest.odds import implied_probs_from_decimal
from wc_predictor.pipeline.ligamx import LIGAMX_DIR

ODDS_SPORT_KEY = "soccer_mexico_ligamx"
ODDS_H2H_JSON = LIGAMX_DIR / "odds_h2h.json"
ODDS_MARKETS_JSON = LIGAMX_DIR / "odds_markets.json"


def _devig_two(price_a: float, price_b: float) -> tuple[float, float]:
    """De-vig a 2-way market (e.g. Over/Under)."""
    ra, rb = 1.0 / price_a, 1.0 / price_b
    tot = ra + rb
    return ra / tot, rb / tot


def parse_h2h(payload: list[dict]) -> dict[str, dict]:
    """The-Odds-API response → {home|away: {p1,px,p2,n_books,commence_time}} with
    canonical name_es keys. Sharper books (lower overround) weighted more."""
    out: dict[str, dict] = {}
    for ev in payload:
        home = normalize_name(ev.get("home_team", ""))
        away = normalize_name(ev.get("away_team", ""))
        if not home or not away:
            continue
        acc_p1 = acc_px = acc_p2 = acc_w = 0.0
        n_books = 0
        for book in ev.get("bookmakers", []):
            h2h = next((m for m in book.get("markets", []) if m.get("key") == "h2h"), None)
            if not h2h:
                continue
            prices: dict[str, float] = {}
            for o in h2h.get("outcomes", []):
                nm = o["name"]
                if nm.lower() == "draw":
                    prices["draw"] = o["price"]
                elif normalize_name(nm) == home:
                    prices["home"] = o["price"]
                elif normalize_name(nm) == away:
                    prices["away"] = o["price"]
            if len(prices) != 3:
                continue
            p1, px, p2, overround = implied_probs_from_decimal(
                prices["home"], prices["draw"], prices["away"])
            w = 1.0 / max(overround - 1.0, 1e-3)
            acc_p1 += w * p1; acc_px += w * px; acc_p2 += w * p2; acc_w += w
            n_books += 1
        if n_books == 0 or acc_w == 0:
            continue
        out[f"{home}|{away}"] = {
            "p1": acc_p1 / acc_w, "px": acc_px / acc_w, "p2": acc_p2 / acc_w,
            "n_books": n_books, "commence_time": ev.get("commence_time"),
        }
    return out


def parse_markets(payload: list[dict]) -> dict[str, dict]:
    """Richer per-match view for value betting: fair (no-vig) probs + best price
    (max decimal odds across books, = line-shopping target) for 1X2 and each
    Over/Under total line."""
    out: dict[str, dict] = {}
    for ev in payload:
        home = normalize_name(ev.get("home_team", ""))
        away = normalize_name(ev.get("away_team", ""))
        if not home or not away:
            continue

        # --- 1X2: book-averaged fair probs + best price per outcome ---
        fair_acc = {"1": 0.0, "X": 0.0, "2": 0.0}
        fair_w = 0.0
        best_h2h = {"1": {"price": 0.0, "book": None},
                    "X": {"price": 0.0, "book": None},
                    "2": {"price": 0.0, "book": None}}
        # --- totals per line: fair + best over/under ---
        totals_fair: dict[float, dict] = defaultdict(lambda: {"over": 0.0, "under": 0.0, "w": 0.0})
        totals_best: dict[float, dict] = defaultdict(
            lambda: {"over": {"price": 0.0, "book": None}, "under": {"price": 0.0, "book": None}})
        line_counts: Counter = Counter()

        for book in ev.get("bookmakers", []):
            bk = book.get("key")
            markets = {m.get("key"): m for m in book.get("markets", [])}
            h2h = markets.get("h2h")
            if h2h:
                prices: dict[str, float] = {}
                for o in h2h.get("outcomes", []):
                    nm = o["name"]
                    key = ("X" if nm.lower() == "draw"
                           else "1" if normalize_name(nm) == home
                           else "2" if normalize_name(nm) == away else None)
                    if key:
                        prices[key] = o["price"]
                        if o["price"] > best_h2h[key]["price"]:
                            best_h2h[key] = {"price": o["price"], "book": bk}
                if len(prices) == 3:
                    p1, px, p2, ov = implied_probs_from_decimal(prices["1"], prices["X"], prices["2"])
                    w = 1.0 / max(ov - 1.0, 1e-3)
                    fair_acc["1"] += w * p1; fair_acc["X"] += w * px; fair_acc["2"] += w * p2
                    fair_w += w
            tot = markets.get("totals")
            if tot:
                by_line: dict[float, dict] = defaultdict(dict)
                for o in tot.get("outcomes", []):
                    pt = o.get("point")
                    if pt is None:
                        continue
                    by_line[pt][o["name"].lower()] = o["price"]
                for pt, oc in by_line.items():
                    if "over" in oc and "under" in oc:
                        line_counts[pt] += 1
                        p_over, p_under = _devig_two(oc["over"], oc["under"])
                        acc = totals_fair[pt]
                        acc["over"] += p_over; acc["under"] += p_under; acc["w"] += 1.0
                        if oc["over"] > totals_best[pt]["over"]["price"]:
                            totals_best[pt]["over"] = {"price": oc["over"], "book": bk}
                        if oc["under"] > totals_best[pt]["under"]["price"]:
                            totals_best[pt]["under"] = {"price": oc["under"], "book": bk}

        if fair_w == 0:
            continue
        totals_out = {}
        for pt, acc in totals_fair.items():
            if acc["w"] == 0:
                continue
            totals_out[str(pt)] = {
                "fair": {"over": acc["over"] / acc["w"], "under": acc["under"] / acc["w"]},
                "best": totals_best[pt],
                "n_books": int(line_counts[pt]),
            }
        out[f"{home}|{away}"] = {
            "commence_time": ev.get("commence_time"),
            "main_total_line": (line_counts.most_common(1)[0][0] if line_counts else None),
            "h2h": {
                "fair": {k: fair_acc[k] / fair_w for k in ("1", "X", "2")},
                "best": best_h2h,
            },
            "totals": totals_out,
        }
    return out


def fetch(api_key: str | None = None, regions: str = "us,eu,uk") -> list[dict]:
    import requests
    key = api_key or get_odds_api_key()
    if not key:
        raise SystemExit("Falta THE_ODDS_API_KEY en .env / entorno.")
    url = (f"https://api.the-odds-api.com/v4/sports/{ODDS_SPORT_KEY}/odds/"
           f"?apiKey={key}&regions={regions}&markets=h2h,totals&oddsFormat=decimal")
    resp = requests.get(url, timeout=40)
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    payload = fetch()
    h2h = parse_h2h(payload)
    markets = parse_markets(payload)
    as_of = datetime.utcnow().isoformat() + "Z"
    ODDS_H2H_JSON.write_text(json.dumps({"as_of": as_of, "matches": h2h},
                                        indent=2, ensure_ascii=False), encoding="utf-8")
    ODDS_MARKETS_JSON.write_text(json.dumps({"as_of": as_of, "matches": markets},
                                            indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {ODDS_H2H_JSON} ({len(h2h)} partidos)")
    print(f"  wrote {ODDS_MARKETS_JSON} ({len(markets)} partidos con 1X2+totals)")


if __name__ == "__main__":
    main()
