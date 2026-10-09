"""Ligas top de Europa desde Football-Data.co.uk: resultados + momios de cierre.

Cinco ligas (Premier, LaLiga, Serie A, Bundesliga, Ligue 1), temporada 2020/21 en
adelante. Cada partido trae precios de CIERRE para tres mercados, que es lo que
permite medir a los bots con dinero ficticio contra una línea real:

- 1X2: Pinnacle (``PSC*``) devigado como probabilidad justa; promedio (``AvgC*``)
  como precio al que el bot "apuesta". Sin Pinnacle (la 26/27 ya no lo trae) se
  devigan los promedios.
- Over/Under 2.5 (``PC>2.5``, ``AvgC>2.5``…).
- Hándicap asiático (línea de cierre ``AHCh`` desde el local, ``AvgCAHH/A``).

Los nombres de equipo se quedan como los publica Football-Data: la fuente es
única y consistente, así que no hace falta mapearlos.

``fixtures.csv`` (próximos partidos con momios previos, no de cierre) se lee con
:func:`load_upcoming` para la liga en vivo.

Uso:
    python -m wc_predictor.ingest.europa_fd                 # descarga y normaliza
    python -m wc_predictor.ingest.europa_fd --src DIR       # desde CSVs ya bajados
"""
from __future__ import annotations

import argparse
import csv
import io
import urllib.request
from datetime import datetime
from pathlib import Path

from wc_predictor.config import DATA_DIR

BASE = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
LEAGUES = {
    "E0": "Premier League",
    "SP1": "LaLiga",
    "I1": "Serie A",
    "D1": "Bundesliga",
    "F1": "Ligue 1",
}
SEASONS = ("2021", "2122", "2223", "2324", "2425", "2526", "2627")
OUT_CSV = DATA_DIR / "europa" / "matches.csv"
FIELDS = ["league", "season", "date", "home", "away", "home_score", "away_score",
          "fair_p1", "fair_px", "fair_p2", "fair_source", "avg_o1", "avg_ox", "avg_o2",
          "fair_over25", "avg_over25", "avg_under25", "ah_line", "avg_ahh", "avg_aha"]


def _f(row: dict, key: str) -> float | None:
    v = (row.get(key) or "").strip()
    try:
        x = float(v)
    except ValueError:
        return None
    return x if x > 1.0 or key.startswith("AH") else None


def _date(s: str) -> str:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"fecha rara: {s!r}")


def devig(*odds: float) -> tuple[float, ...]:
    """Proportional devig: implied probabilities rescaled to sum to 1."""
    inv = [1.0 / o for o in odds]
    s = sum(inv)
    return tuple(x / s for x in inv)


def _fair_1x2(row: dict, closing: bool) -> tuple[tuple[float, float, float] | None, str]:
    pre = "C" if closing else ""
    for src, keys in (("pinnacle", (f"PS{pre}H", f"PS{pre}D", f"PS{pre}A")),
                      ("avg", (f"Avg{pre}H", f"Avg{pre}D", f"Avg{pre}A"))):
        o = [_f(row, k) for k in keys]
        if all(o):
            return devig(*o), src
    return None, ""


def _fair_over(row: dict, closing: bool) -> float | None:
    pre = "C" if closing else ""
    for keys in ((f"P{pre}>2.5", f"P{pre}<2.5"), (f"Avg{pre}>2.5", f"Avg{pre}<2.5")):
        o = [_f(row, k) for k in keys]
        if all(o):
            return devig(*o)[0]
    return None


def normalize_rows(raw_rows: list[dict], code: str, season: str, closing: bool = True) -> list[dict]:
    """Football-Data rows → normalized dicts. ``closing=False`` reads the
    pre-match columns (fixtures.csv has no closing prices yet)."""
    pre = "C" if closing else ""
    out = []
    for r in raw_rows:
        if not (r.get("HomeTeam") and r.get("AwayTeam") and r.get("Date")):
            continue
        fair, src = _fair_1x2(r, closing)
        played = (r.get("FTHG") or "").strip() != "" and (r.get("FTAG") or "").strip() != ""
        if closing and not played:
            continue
        o = {
            "league": code, "season": season, "date": _date(r["Date"]),
            "home": r["HomeTeam"].strip(), "away": r["AwayTeam"].strip(),
            "home_score": int(r["FTHG"]) if played else "",
            "away_score": int(r["FTAG"]) if played else "",
            "fair_p1": "", "fair_px": "", "fair_p2": "", "fair_source": src,
            "avg_o1": _f(r, f"Avg{pre}H") or "", "avg_ox": _f(r, f"Avg{pre}D") or "",
            "avg_o2": _f(r, f"Avg{pre}A") or "",
            "fair_over25": "", "avg_over25": _f(r, f"Avg{pre}>2.5") or "",
            "avg_under25": _f(r, f"Avg{pre}<2.5") or "",
            "ah_line": "", "avg_ahh": _f(r, f"Avg{pre}AHH") or "",
            "avg_aha": _f(r, f"Avg{pre}AHA") or "",
        }
        if fair:
            o["fair_p1"], o["fair_px"], o["fair_p2"] = (round(p, 4) for p in fair)
        fo = _fair_over(r, closing)
        if fo is not None:
            o["fair_over25"] = round(fo, 4)
        line = _f(r, "AHCh" if closing else "AHh")
        if line is not None:
            o["ah_line"] = line
        out.append(o)
    return out


def _read_text(src: Path | None, code: str, season: str) -> str | None:
    if src is not None:
        p = src / f"{code}_{season}.csv"
        return p.read_text(encoding="utf-8-sig", errors="replace") if p.exists() else None
    url = BASE.format(season=season, code=code)
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 (fixed https host)
        return resp.read().decode("utf-8-sig", errors="replace")


def build(src: Path | None = None) -> list[dict]:
    rows: list[dict] = []
    for season in SEASONS:
        for code in LEAGUES:
            text = _read_text(src, code, season)
            if not text:
                continue
            rows += normalize_rows(list(csv.DictReader(io.StringIO(text))), code, season)
    rows.sort(key=lambda r: (r["date"], r["league"], r["home"]))
    return rows


def write(rows: list[dict], dst: Path = OUT_CSV) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _num(v: str):
    if v == "":
        return None
    return float(v)


def load(src: Path = OUT_CSV) -> list[dict]:
    """Normalized matches with numeric fields parsed (None where missing) and the
    keys the shared model code expects (``neutral``, ``tournament``)."""
    out = []
    with src.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = dict(r)
            d["home_score"] = int(r["home_score"])
            d["away_score"] = int(r["away_score"])
            for k in FIELDS[7:]:
                if k != "fair_source":
                    d[k] = _num(r[k])
            d["neutral"] = False
            d["tournament"] = LEAGUES[r["league"]]
            out.append(d)
    return out


def load_upcoming(text: str | None = None) -> list[dict]:
    """Upcoming top-5 fixtures with PRE-match odds (fixtures.csv)."""
    if text is None:
        with urllib.request.urlopen(FIXTURES_URL, timeout=60) as resp:  # noqa: S310
            text = resp.read().decode("utf-8-sig", errors="replace")
    raw = [r for r in csv.DictReader(io.StringIO(text)) if r.get("Div") in LEAGUES]
    out = []
    for code in LEAGUES:
        out += normalize_rows([r for r in raw if r["Div"] == code], code, SEASONS[-1], closing=False)
    for d in out:
        for k in FIELDS[7:]:
            if k != "fair_source":
                d[k] = None if d[k] == "" else float(d[k])
        d["neutral"] = False
        d["tournament"] = LEAGUES[d["league"]]
    return sorted(out, key=lambda r: (r["date"], r["league"], r["home"]))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", type=Path, default=None,
                    help="carpeta con {CODE}_{SEASON}.csv ya descargados")
    args = ap.parse_args(argv)
    rows = build(args.src)
    write(rows)
    by = {}
    for r in rows:
        by[r["league"]] = by.get(r["league"], 0) + 1
    print(f"{len(rows)} partidos → {OUT_CSV}  ({', '.join(f'{k}:{v}' for k, v in by.items())})")
    print(f"  rango {rows[0]['date']} → {rows[-1]['date']}")
    for k in ("fair_p1", "fair_over25", "ah_line"):
        miss = sum(1 for r in rows if r[k] == "")
        print(f"  sin {k}: {miss}")


if __name__ == "__main__":
    main()
