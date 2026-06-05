"""Mini-backtest: does match-day venue temperature carry incremental signal
about scoring, beyond team strength (Elo)?

This is a throwaway research probe (NOT wired into the pipeline). It answers the
question we deferred before touching `model/adjustments.py`: is a Klement-style
climate term worth adding to the quiniela model?

Method:
  1. Load the historical training set (2014+, ~11.7k internationals).
  2. Replay the project's own Elo to capture PRE-MATCH ratings for both teams
     (point-in-time strength control — no look-ahead).
  3. Geocode each unique city (open-meteo) and pull the real match-day
     temperature from open-meteo's ERA5 archive. Everything is cached on disk so
     reruns are free.
  4. OLS: total_goals ~ strength controls (+ temperature). Report the
     incremental R^2, the temperature coefficient, its t-stat, and a transparent
     binned view. Also test a quadratic term (Klement's "~14C optimum").
"""
from __future__ import annotations

import csv
import json
import math
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np

from wc_predictor.config import ModelConfig
from wc_predictor.ratings.elo import update_elo, EloMatch

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(__file__).resolve().parent / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
GEO_CACHE = CACHE / "geocode.json"
WX_CACHE = CACHE / "weather"
WX_CACHE.mkdir(exist_ok=True)

HIST = ROOT / "data" / "historical" / "international_matches.csv"


# ---------------------------------------------------------------- data loading
def load_matches() -> list[dict]:
    rows = list(csv.DictReader(HIST.open()))
    for r in rows:
        r["home_score"] = int(r["home_score"])
        r["away_score"] = int(r["away_score"])
        r["neutral"] = str(r["neutral"]).upper() in {"TRUE", "T", "1", "YES"}
    rows.sort(key=lambda r: r["date"])
    return rows


def attach_prematch_elo(rows: list[dict]) -> None:
    """Replay Elo chronologically; record each team's rating BEFORE the match."""
    cfg = ModelConfig()
    elos: dict[str, float] = {}
    for r in rows:
        r["elo_home"] = elos.get(r["home"], 1500.0)
        r["elo_away"] = elos.get(r["away"], 1500.0)
        update_elo(elos, EloMatch(r["home"], r["away"], r["home_score"],
                                  r["away_score"], r["neutral"], r["tournament"]), cfg)


# --------------------------------------------------------------- geocoding/wx
def _get_json(url: str, tries: int = 4) -> dict | None:
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None


def geocode_all(cities: list[tuple[str, str]]) -> dict[str, dict]:
    cache = json.loads(GEO_CACHE.read_text()) if GEO_CACHE.exists() else {}

    def key(city: str, country: str) -> str:
        return f"{city}|{country}"

    todo = [(c, k) for c, k in cities if key(c, k) not in cache]

    def work(item):
        city, country = item
        q = urllib.parse.quote(city)
        url = f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=10&language=en&format=json"
        data = _get_json(url)
        res = (data or {}).get("results") or []
        # prefer a result whose country matches; else first
        pick = None
        for r in res:
            if r.get("country", "").lower() == country.lower():
                pick = r
                break
        if pick is None and res:
            pick = res[0]
        return key(city, country), (
            {"lat": pick["latitude"], "lon": pick["longitude"]} if pick else None
        )

    if todo:
        print(f"  geocoding {len(todo)} new cities...")
        with ThreadPoolExecutor(max_workers=8) as ex:
            for k, v in ex.map(work, todo):
                cache[k] = v
        GEO_CACHE.write_text(json.dumps(cache))
    return cache


def fetch_weather(coords: dict[str, dict], city_dates: dict[str, set]) -> dict[str, dict]:
    """For each geocoded city, one archive call over its full match-date span.
    Returns {city_key: {date_iso: {tmax, tmean}}}. Cached per city on disk."""
    out: dict[str, dict] = {}
    todo = []
    for ckey, dates in city_dates.items():
        c = coords.get(ckey)
        if not c:
            continue
        fp = WX_CACHE / (urllib.parse.quote(ckey, safe="") + ".json")
        if fp.exists():
            out[ckey] = json.loads(fp.read_text())
        else:
            todo.append((ckey, c, sorted(dates)))

    def work(item):
        ckey, c, dates = item
        start, end = dates[0], dates[-1]
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?latitude={c['lat']}"
            f"&longitude={c['lon']}&start_date={start}&end_date={end}"
            f"&daily=temperature_2m_max,temperature_2m_mean&timezone=auto"
        )
        data = _get_json(url)
        daily = (data or {}).get("daily") or {}
        days = daily.get("time") or []
        tmax = daily.get("temperature_2m_max") or []
        tmean = daily.get("temperature_2m_mean") or []
        m = {}
        for i, d in enumerate(days):
            if i < len(tmax) and tmax[i] is not None:
                m[d] = {"tmax": tmax[i], "tmean": tmean[i] if i < len(tmean) else None}
        fp = WX_CACHE / (urllib.parse.quote(ckey, safe="") + ".json")
        fp.write_text(json.dumps(m))
        return ckey, m

    if todo:
        print(f"  fetching weather for {len(todo)} new cities...")
        with ThreadPoolExecutor(max_workers=8) as ex:
            for ckey, m in ex.map(work, todo):
                out[ckey] = m
    return out


# ------------------------------------------------------------------ OLS helper
def ols(X: np.ndarray, y: np.ndarray) -> dict:
    """OLS with t-stats. X already includes an intercept column."""
    n, k = X.shape
    beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    rss = float(resid @ resid)
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - rss / tss
    sigma2 = rss / (n - k)
    XtX_inv = np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(sigma2 * XtX_inv))
    t = beta / se
    return {"beta": beta, "se": se, "t": t, "r2": r2, "n": n, "rss": rss}


# ------------------------------------------------------------------------ main
def main() -> None:
    rows = load_matches()
    print(f"loaded {len(rows)} matches")
    attach_prematch_elo(rows)

    cities = sorted({(r["city"], r["country"]) for r in rows if r["city"]})
    coords = geocode_all(cities)

    city_dates: dict[str, set] = defaultdict(set)
    for r in rows:
        if not r["city"]:
            continue
        ckey = f"{r['city']}|{r['country']}"
        if coords.get(ckey):
            city_dates[ckey].add(r["date"])
    wx = fetch_weather(coords, city_dates)

    # assemble dataset
    data = []
    for r in rows:
        ckey = f"{r['city']}|{r['country']}"
        m = wx.get(ckey)
        if not m:
            continue
        t = m.get(r["date"])
        if not t or t.get("tmean") is None:
            continue
        data.append({
            "tg": r["home_score"] + r["away_score"],
            "gd": r["home_score"] - r["away_score"],
            "elo_avg": (r["elo_home"] + r["elo_away"]) / 2.0,
            "elo_absdiff": abs(r["elo_home"] - r["elo_away"]),
            "neutral": 1.0 if r["neutral"] else 0.0,
            "tmean": float(t["tmean"]),
            "tmax": float(t["tmax"]),
        })

    n = len(data)
    matched = sum(1 for r in rows if wx.get(f"{r['city']}|{r['country']}"))
    print(f"\nmatches with temperature: {n} / {len(rows)} "
          f"({100*n/len(rows):.0f}%)   [geocoded coverage {100*matched/len(rows):.0f}%]")

    tg = np.array([d["tg"] for d in data], float)
    tmean = np.array([d["tmean"] for d in data], float)
    elo_avg = np.array([d["elo_avg"] for d in data], float)
    elo_absdiff = np.array([d["elo_absdiff"] for d in data], float)
    ones = np.ones(n)

    # standardize controls for readable coefficients
    def z(a):
        return (a - a.mean()) / a.std()

    print(f"\ntemperature range: {tmean.min():.1f}..{tmean.max():.1f} C  "
          f"mean {tmean.mean():.1f}  sd {tmean.std():.1f}")
    print(f"total-goals mean {tg.mean():.3f}")

    # Model A: strength only
    XA = np.column_stack([ones, z(elo_avg), z(elo_absdiff), [d["neutral"] for d in data]])
    rA = ols(XA, tg)
    # Model B: + temperature (linear)
    XB = np.column_stack([XA.T[0], XA.T[1], XA.T[2], XA.T[3], tmean]).T if False else \
        np.column_stack([ones, z(elo_avg), z(elo_absdiff), [d["neutral"] for d in data], tmean])
    rB = ols(XB, tg)
    # Model C: + quadratic temperature (optimum test)
    XC = np.column_stack([ones, z(elo_avg), z(elo_absdiff),
                          [d["neutral"] for d in data], tmean, tmean ** 2])
    rC = ols(XC, tg)

    print("\n=== OLS: total goals ===")
    print(f"  A strength-only       R2={rA['r2']:.4f}")
    print(f"  B +temp(linear)       R2={rB['r2']:.4f}   dR2={rB['r2']-rA['r2']:+.5f}")
    print(f"      temp coef={rB['beta'][-1]:+.5f} goals/C   t={rB['t'][-1]:+.2f}   "
          f"=> {rB['beta'][-1]*10:+.3f} goals per +10C")
    print(f"  C +temp+temp^2        R2={rC['r2']:.4f}   dR2={rC['r2']-rA['r2']:+.5f}")
    print(f"      lin={rC['beta'][4]:+.5f} (t={rC['t'][4]:+.2f})  "
          f"quad={rC['beta'][5]:+.6f} (t={rC['t'][5]:+.2f})")
    if rC["beta"][5] < 0:
        vertex = -rC["beta"][4] / (2 * rC["beta"][5])
        print(f"      implied goal-maximizing temperature ~ {vertex:.1f} C")

    # Binned view (residualized for strength so it's apples-to-apples)
    resid = tg - XA @ rA["beta"]
    edges = [-100, 5, 10, 15, 20, 25, 30, 35, 100]
    print("\n=== residual total goals by temperature bin (strength-controlled) ===")
    print("   bin(C)        n     mean_resid_goals    raw_mean_goals")
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (tmean >= lo) & (tmean < hi)
        if mask.sum() < 20:
            continue
        lbl = f"[{lo},{hi})" if hi < 100 else f">={lo}"
        lbl = lbl.replace("[-100", "<")
        print(f"   {lbl:<10} {int(mask.sum()):>6}      {resid[mask].mean():+.3f}            "
              f"{tg[mask].mean():.3f}")

    # Outcome angle: does heat move goal difference (home/fav advantage)? mostly neutral venues
    gd = np.array([d["gd"] for d in data], float)
    Xo = np.column_stack([ones, z(elo_avg), z(elo_absdiff), tmean])
    ro = ols(Xo, np.abs(gd))
    print(f"\n=== |goal difference| vs temp (margin/blowout test) ===")
    print(f"   temp coef={ro['beta'][-1]:+.5f} |gd|/C   t={ro['t'][-1]:+.2f}")


if __name__ == "__main__":
    main()
