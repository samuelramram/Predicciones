"""Historical Liga MX closing odds from Football-Data.co.uk → data/ligamx/historical_odds.csv.

Football-Data publishes a free CSV for Mexico (``new/MEX.csv``) with every Liga MX
match since 2012 and its CLOSING 1X2 prices: Pinnacle (``PSC*``), market average
(``AvgC*``), market maximum (``MaxC*``), Betfair exchange and Bet365. Until now the
repo assumed there was no historical Liga MX odds feed, so the market weight of the
blend could only be measured live (``ligamx_source_tracker``). With this file it can
be backtested — and the liga-de-bots backtest (``pipeline.liga_backtest``) uses it
for the market-following bots and the fictitious bankroll.

What gets written (one row per match, our team names, ISO date):
    date, home, away, home_score, away_score,
    fair_p1, fair_px, fair_p2   — de-vigged closing probabilities
    fair_source                 — "pinnacle" (sharp) or "avg" (fallback when the
                                  Pinnacle columns are blank, as in 2026/27)
    avg_o1, avg_ox, avg_o2      — average closing PRICE: what a normal bettor would
                                  have been paid. The fictitious bankroll settles here.
    max_o1, max_ox, max_o2      — best closing price across books (line-shopping ceiling)

Dates: Football-Data stamps kick-off in UK time, so a Saturday-night Mexican match
often lands on the next calendar day. Joins against matches_history.csv therefore
match on (home, away) within ±1 day — see :func:`lookup`.

Run:
    python -m wc_predictor.ingest.ligamx_fd_odds                 # download + normalize
    python -m wc_predictor.ingest.ligamx_fd_odds --src MEX.csv   # from a local copy

Source & licence: https://www.football-data.co.uk/mexico.php (free for personal use;
credit Football-Data.co.uk).
"""
from __future__ import annotations

import argparse
import csv
import io
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from wc_predictor.config import DATA_DIR

FD_URL = "https://www.football-data.co.uk/new/MEX.csv"
OUT_CSV = DATA_DIR / "ligamx" / "historical_odds.csv"
MIN_SEASON = "2020"  # 2020/21 on: same 18-club league the model trains on (no Veracruz, Lobos…)

# Football-Data spelling → our source-of-truth spelling (matches_history.csv).
FD_TEAM = {
    "Atl. San Luis": "San Luis", "Atlante": "Atlante", "Atlas": "Atlas",
    "Club America": "América", "Club Leon": "León", "Club Tijuana": "Tijuana",
    "Cruz Azul": "Cruz Azul", "Guadalajara Chivas": "Guadalajara", "Juarez": "Juárez",
    "Mazatlan FC": "Mazatlán", "Monterrey": "Monterrey", "Necaxa": "Necaxa",
    "Pachuca": "Pachuca", "Puebla": "Puebla", "Queretaro": "Querétaro",
    "Santos Laguna": "Santos", "Tigres UANL": "Tigres", "Toluca": "Toluca",
    "UNAM Pumas": "Pumas",
}

FIELDS = ["date", "home", "away", "home_score", "away_score",
          "fair_p1", "fair_px", "fair_p2", "fair_source",
          "avg_o1", "avg_ox", "avg_o2", "max_o1", "max_ox", "max_o2"]


def devig(o1: float, ox: float, o2: float) -> tuple[float, float, float]:
    """Proportional de-vig of a 1X2 price triple → fair probabilities summing to 1."""
    inv = (1.0 / o1, 1.0 / ox, 1.0 / o2)
    s = sum(inv)
    return inv[0] / s, inv[1] / s, inv[2] / s


def _f(x: str) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 1.0 else None


def _triple(r: dict, prefix: str) -> tuple[float, float, float] | None:
    t = (_f(r.get(f"{prefix}H")), _f(r.get(f"{prefix}D")), _f(r.get(f"{prefix}A")))
    return t if all(t) else None


def normalize(raw_text: str, min_season: str = MIN_SEASON) -> tuple[list[dict], set[str]]:
    """Parse Football-Data's MEX.csv text → (normalized rows, unmapped team names).

    Rows without any usable closing triple (Pinnacle nor average) are dropped —
    a match with no market is useless to every consumer of this file."""
    out: list[dict] = []
    unmapped: set[str] = set()
    for r in csv.DictReader(io.StringIO(raw_text.lstrip("﻿"))):
        if r.get("League") != "Liga MX" or (r.get("Season") or "") < min_season:
            continue
        home, away = FD_TEAM.get(r["Home"]), FD_TEAM.get(r["Away"])
        if home is None or away is None:
            unmapped.update(n for n, m in ((r["Home"], home), (r["Away"], away)) if m is None)
            continue
        pin, avg, mx = _triple(r, "PSC"), _triple(r, "AvgC"), _triple(r, "MaxC")
        fair_src = pin or avg
        if fair_src is None or avg is None:
            continue
        p1, px, p2 = devig(*fair_src)
        out.append({
            "date": datetime.strptime(r["Date"], "%d/%m/%Y").date().isoformat(),
            "home": home, "away": away,
            "home_score": int(r["HG"]), "away_score": int(r["AG"]),
            "fair_p1": round(p1, 4), "fair_px": round(px, 4), "fair_p2": round(p2, 4),
            "fair_source": "pinnacle" if pin else "avg",
            "avg_o1": avg[0], "avg_ox": avg[1], "avg_o2": avg[2],
            "max_o1": (mx or avg)[0], "max_ox": (mx or avg)[1], "max_o2": (mx or avg)[2],
        })
    out.sort(key=lambda x: (x["date"], x["home"]))
    return out, unmapped


def load(path: Path = OUT_CSV) -> list[dict]:
    """Read the normalized file back with numeric types."""
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k in FIELDS[3:]:
                if k != "fair_source":
                    r[k] = float(r[k]) if "." in r[k] else int(r[k])
            rows.append(r)
    return rows


def index(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """(home, away) → rows, for :func:`lookup`."""
    idx: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        idx.setdefault((r["home"], r["away"]), []).append(r)
    return idx


def lookup(idx: dict, home: str, away: str, iso_date: str, tol_days: int = 1) -> dict | None:
    """Odds row for a match, tolerating the UK-time date shift (±tol_days).

    The same pairing repeats every tournament (and in liguillas), so the date
    window — not the team pair alone — is what identifies the match."""
    d = date.fromisoformat(iso_date)
    best = None
    for r in idx.get((home, away), ()):
        gap = abs((date.fromisoformat(r["date"]) - d).days)
        if gap <= tol_days and (best is None or gap < best[0]):
            best = (gap, r)
    return best[1] if best else None


def write(rows: list[dict], path: Path = OUT_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Momios históricos de cierre Liga MX (Football-Data).")
    ap.add_argument("--src", type=Path, help="usar un MEX.csv local en vez de descargarlo")
    ap.add_argument("--min-season", default=MIN_SEASON)
    args = ap.parse_args(argv)
    if args.src:
        text = args.src.read_text(encoding="utf-8-sig")
    else:
        req = urllib.request.Request(FD_URL, headers={"User-Agent": "predicciones/liga-bots"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8-sig")
    rows, unmapped = normalize(text, args.min_season)
    if unmapped:
        raise SystemExit(f"Equipos sin mapear en FD_TEAM: {sorted(unmapped)} — agrégalos antes de escribir.")
    write(rows)
    pin = sum(r["fair_source"] == "pinnacle" for r in rows)
    print(f"historical_odds.csv: {len(rows)} partidos ({rows[0]['date']} → {rows[-1]['date']}); "
          f"línea justa Pinnacle en {pin}, promedio del mercado en {len(rows) - pin}.")


if __name__ == "__main__":
    main()
