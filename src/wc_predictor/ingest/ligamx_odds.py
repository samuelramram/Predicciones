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
    python -m wc_predictor.ingest.ligamx_odds            # 1 crédito: eu, solo 1X2
    python -m wc_predictor.ingest.ligamx_odds --totals   # 2: + Over/Under (apuestas)

Créditos (la llave es compartida con otros proyectos, 500/mes): cada llamada
cobra #mercados × #regiones. Antes pedía us,eu,uk × h2h,totals = 6 por corrida,
y con 3-4 re-corridas por jornada eso se comía el mes. Ahora: región eu (trae
Pinnacle y ~15 casas, suficiente para la línea justa del blend), solo 1X2 salvo
--totals, no vuelve a pedir si los momios tienen menos de --max-age-h, no paga
si no hay partidos de Liga MX en las próximas 96 h (calendario gratis) y respeta
la reserva de ODDS_API_RESERVE (ver ingest.odds_budget).
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
BOOKS_JSON = LIGAMX_DIR / "books.json"


def load_books_config(path: Path = BOOKS_JSON) -> dict:
    """Which books I can actually bet at, plus hand-captured prices for the ones
    The Odds API doesn't carry (Caliente isn't in the Liga MX feed).

    Returns ``{"available": [...], "manual": {book: {match_key: {...}}}}`` — empty
    when the file is absent, which restores plain best-of-all-books behaviour.
    """
    if not path.exists():
        return {"available": [], "manual": {}}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {"available": [b.lower() for b in doc.get("available") or []],
            "manual": doc.get("manual") or {}}


def manual_prices_for(cfg: dict, match_key: str) -> dict[str, dict[str, float]]:
    """{book: {"1": price, ...}} of hand-captured 1X2 prices for one match."""
    out: dict[str, dict[str, float]] = {}
    for book, entry in (cfg.get("manual") or {}).items():
        h2h = ((entry.get("matches") or {}).get(match_key) or {}).get("h2h")
        if h2h:
            out[book] = {k: float(v) for k, v in h2h.items()}
    return out


def manual_totals_for(cfg: dict, match_key: str) -> dict[str, dict[str, dict[str, float]]]:
    """{book: {line: {"over": price, "under": price}}} of hand-captured totals."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for book, entry in (cfg.get("manual") or {}).items():
        totals = ((entry.get("matches") or {}).get(match_key) or {}).get("totals")
        if totals:
            out[book] = {str(line): {k: float(v) for k, v in oc.items()}
                         for line, oc in totals.items()}
    return out


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


def parse_markets(payload: list[dict], books_cfg: dict | None = None) -> dict[str, dict]:
    """Richer per-match view for value betting: fair (no-vig) probs + best price
    (max decimal odds across books, = line-shopping target) for 1X2 and each
    Over/Under total line.

    With `books_cfg` (see :func:`load_books_config`) each outcome also carries
    ``best_available``: the best price among the books I can actually bet at,
    including hand-captured ones the API doesn't cover. The FAIR line keeps using
    every book in the feed — it is the sharp reference the price is judged
    against, so narrowing it to my own books would defeat the purpose.
    """
    books_cfg = books_cfg or {"available": [], "manual": {}}
    available = set(books_cfg.get("available") or [])
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
        avail_h2h = {"1": {"price": 0.0, "book": None},
                     "X": {"price": 0.0, "book": None},
                     "2": {"price": 0.0, "book": None}}
        # Per-book prices among MY books, so a boleto can be priced at a SPECIFIC
        # house (Betway/Caliente) — `best_available` only keeps the single best.
        by_book_h2h: dict[str, dict[str, float]] = defaultdict(dict)
        by_book_totals: dict[float, dict[str, dict[str, float]]] = defaultdict(
            lambda: {"over": {}, "under": {}})
        # --- totals per line: fair + best over/under ---
        totals_fair: dict[float, dict] = defaultdict(lambda: {"over": 0.0, "under": 0.0, "w": 0.0})
        totals_best: dict[float, dict] = defaultdict(
            lambda: {"over": {"price": 0.0, "book": None}, "under": {"price": 0.0, "book": None}})
        totals_avail: dict[float, dict] = defaultdict(
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
                        if bk in available and o["price"] > avail_h2h[key]["price"]:
                            avail_h2h[key] = {"price": o["price"], "book": bk}
                        if bk in available:
                            prev = by_book_h2h[bk].get(key, 0.0)
                            if o["price"] > prev:
                                by_book_h2h[bk][key] = o["price"]
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
                        if bk in available:
                            if oc["over"] > totals_avail[pt]["over"]["price"]:
                                totals_avail[pt]["over"] = {"price": oc["over"], "book": bk}
                            if oc["under"] > totals_avail[pt]["under"]["price"]:
                                totals_avail[pt]["under"] = {"price": oc["under"], "book": bk}
                            for side in ("over", "under"):
                                if oc[side] > by_book_totals[pt][side].get(bk, 0.0):
                                    by_book_totals[pt][side][bk] = oc[side]

        if fair_w == 0:
            continue

        # Hand-captured books (not in the feed) compete for best_available only —
        # never for the fair line, which must stay the sharp consensus.
        match_key = f"{home}|{away}"
        for bk, prices in manual_prices_for(books_cfg, match_key).items():
            if bk not in available:
                continue
            for key, price in prices.items():
                if key in avail_h2h and price > avail_h2h[key]["price"]:
                    avail_h2h[key] = {"price": price, "book": bk}
                if key in ("1", "X", "2") and price > by_book_h2h[bk].get(key, 0.0):
                    by_book_h2h[bk][key] = price
        for bk, lines in manual_totals_for(books_cfg, match_key).items():
            if bk not in available:
                continue
            for line, oc in lines.items():
                try:
                    pt = float(line)
                except (TypeError, ValueError):
                    continue
                # Only a line the feed also prices can be judged: the fair side of
                # the comparison comes from the API books.
                if pt not in totals_fair:
                    continue
                for side in ("over", "under"):
                    price = oc.get(side)
                    if price and price > totals_avail[pt][side]["price"]:
                        totals_avail[pt][side] = {"price": price, "book": bk}
                    if price and price > by_book_totals[pt][side].get(bk, 0.0):
                        by_book_totals[pt][side][bk] = price

        totals_out = {}
        for pt, acc in totals_fair.items():
            if acc["w"] == 0:
                continue
            totals_out[str(pt)] = {
                "fair": {"over": acc["over"] / acc["w"], "under": acc["under"] / acc["w"]},
                "best": totals_best[pt],
                "best_available": totals_avail[pt],
                "by_book": {"over": dict(by_book_totals[pt]["over"]),
                            "under": dict(by_book_totals[pt]["under"])},
                "n_books": int(line_counts[pt]),
            }
        out[match_key] = {
            "commence_time": ev.get("commence_time"),
            "main_total_line": (line_counts.most_common(1)[0][0] if line_counts else None),
            "h2h": {
                "fair": {k: fair_acc[k] / fair_w for k in ("1", "X", "2")},
                "best": best_h2h,
                "best_available": avail_h2h,
                # {book: {"1"/"X"/"2": price}} — prices at each of MY books, for the
                # per-house boleto. Only books in `available` (feed + manual) appear.
                "by_book": {bk: dict(px) for bk, px in by_book_h2h.items()},
            },
            "totals": totals_out,
        }
    return out


def fetch(api_key: str | None = None, regions: str = "eu",
          markets: str = "h2h") -> list[dict]:
    import requests
    key = api_key or get_odds_api_key()
    if not key:
        raise SystemExit("Falta THE_ODDS_API_KEY en .env / entorno.")
    url = (f"https://api.the-odds-api.com/v4/sports/{ODDS_SPORT_KEY}/odds/"
           f"?apiKey={key}&regions={regions}&markets={markets}&oddsFormat=decimal")
    resp = requests.get(url, timeout=40)
    resp.raise_for_status()
    print(f"  The Odds API: costó {resp.headers.get('x-requests-last')} crédito(s); "
          f"quedan {resp.headers.get('x-requests-remaining')}")
    return resp.json()


def request_cost(regions: str, markets: str) -> int:
    return len([r for r in regions.split(",") if r.strip()]) * \
        len([m for m in markets.split(",") if m.strip()])


def main(argv: list[str] | None = None) -> None:
    import argparse
    import time
    from wc_predictor.ingest import odds_budget
    ap = argparse.ArgumentParser(description="Momios Liga MX (The Odds API), cuidando créditos.")
    ap.add_argument("--regions", default="eu", help="regiones (cada una cobra; default eu)")
    ap.add_argument("--totals", action="store_true",
                    help="también Over/Under (para apuestas; duplica el costo)")
    ap.add_argument("--max-age-h", type=float, default=2.0,
                    help="no vuelve a pedir si odds_h2h.json es más nuevo que esto")
    ap.add_argument("--reserve", type=int, default=25,
                    help="créditos que se dejan intactos para otros proyectos (default 25)")
    ap.add_argument("--force", action="store_true",
                    help="ignora frescura, calendario y reserva")
    args = ap.parse_args(argv)
    markets = "h2h,totals" if args.totals else "h2h"
    cost = request_cost(args.regions, markets)
    if not args.force and ODDS_H2H_JSON.exists():
        age_h = (time.time() - ODDS_H2H_JSON.stat().st_mtime) / 3600
        if age_h < args.max_age_h:
            print(f"  {ODDS_H2H_JSON.name} tiene {age_h:.1f} h (< {args.max_age_h:g}); "
                  "no gasto créditos (--force para refrescar).")
            return
    key = get_odds_api_key()
    if not key:
        raise SystemExit("Falta THE_ODDS_API_KEY en .env / entorno.")
    if not args.force:
        ev = odds_budget.upcoming_events(key, ODDS_SPORT_KEY, hours=96)
        if ev is not None and not ev:
            print("  sin partidos de Liga MX en las próximas 96 h; no gasto créditos.")
            return
        if not odds_budget.can_spend(key, cost, label="Liga MX", reserve_floor=args.reserve):
            return
    payload = fetch(key, regions=args.regions, markets=markets)
    books_cfg = load_books_config()
    h2h = parse_h2h(payload)
    markets = parse_markets(payload, books_cfg)
    as_of = datetime.utcnow().isoformat() + "Z"
    if books_cfg["available"]:
        n_avail = sum(1 for m in markets.values()
                      if any(o["price"] for o in m["h2h"]["best_available"].values()))
        print(f"  casas propias: {', '.join(books_cfg['available'])} "
              f"(precio disponible en {n_avail}/{len(markets)} partidos)")
    ODDS_H2H_JSON.write_text(json.dumps({"as_of": as_of, "matches": h2h},
                                        indent=2, ensure_ascii=False), encoding="utf-8")
    ODDS_MARKETS_JSON.write_text(json.dumps({"as_of": as_of, "matches": markets},
                                            indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {ODDS_H2H_JSON} ({len(h2h)} partidos)")
    print(f"  wrote {ODDS_MARKETS_JSON} ({len(markets)} partidos)")


if __name__ == "__main__":
    main()
