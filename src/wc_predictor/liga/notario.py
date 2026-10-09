"""Notario: sella el boleto de un humano (Samuel) contra la jornada publicada.

Claudio recibe en Telegram algo como ``2-1, 0-2, -, 1-3`` y llama a este módulo.
Los marcadores van en el orden numerado del boleto (``rounds/<jornada>.md``);
``-`` salta un partido. El Notario:

- rechaza el pick de un partido que ya empezó (hora de inicio en UTC),
- rechaza el pick de un partido que esa persona ya selló antes (no hay cambios),
- sella lo demás como una parte nueva de la jornada (``eu-2026-W41/2``…): un
  humano puede mandar su boleto en varias tandas, pero cada partido una vez.

También entiende marcadores con nombre, como los escribe un humano en Telegram:
``Bayern 2-0`` (gana Bayern 2-0, aunque sea visitante), ``Arsenal 2-0 Leeds``
(local primero) o ``Como 1-1``. Usa ``--dry-run`` para ver cómo lo entendió
antes de sellar.

Run:
    python -m wc_predictor.liga.notario --round eu-2026-W41 --picks "2-1, 0-2, -, 1-3"
    python -m wc_predictor.liga.notario --round eu-2026-W41 --picks "Bayern 2-0, City 2-1" --dry-run
    python -m wc_predictor.liga.notario --round eu-2026-W41 --status
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime, timezone

from wc_predictor.liga import seal
from wc_predictor.liga.paths import rounds_dir
from wc_predictor.liga.scoring import outcome_of

SCORE = re.compile(r"^(\d{1,2})\s*[-–:]\s*(\d{1,2})$")


def parse_picks(text: str) -> list[tuple[int, int] | None]:
    """'2-1, 0-2, -, 1-3' → [(2,1), (0,2), None, (1,3)]. Raises on garbage."""
    out: list[tuple[int, int] | None] = []
    for tok in re.split(r"[,\n;]+", text.strip()):
        tok = tok.strip()
        if not tok:
            continue
        if tok in ("-", "x", "skip"):
            out.append(None)
            continue
        m = SCORE.match(tok)
        if not m:
            raise ValueError(f"No entendí '{tok}': usa marcadores tipo 2-1, o '-' para saltar.")
        out.append((int(m.group(1)), int(m.group(2))))
    return out


# How people actually call teams → Football-Data names (lowercase, no accents).
ALIASES = {
    "barca": "barcelona", "madrid": "real madrid", "real": "real madrid",
    "atletico": "ath madrid", "atleti": "ath madrid", "atletico de madrid": "ath madrid",
    "city": "man city", "manchester city": "man city", "united": "man united",
    "manchester united": "man united", "psg": "paris sg", "paris": "paris sg",
    "bayern": "bayern munich", "bayern munchen": "bayern munich", "bvb": "dortmund",
    "borussia dortmund": "dortmund", "inter de milan": "inter", "napoles": "napoli",
    "leverkusen": "leverkusen", "bremen": "werder bremen", "alaves": "alaves",
    "spurs": "tottenham", "milan": "ac milan",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()
    return re.sub(r"\s+", " ", s)


def _team_in(name: str, team: str) -> bool:
    n, t = _norm(name), _norm(team)
    n = ALIASES.get(n, n)
    return n == t or (len(n) >= 4 and (t.startswith(n) or n in t.split()))


NAMED = re.compile(r"^(?P<a>.*?\D)\s*(?P<x>\d{1,2})\s*[-–:]\s*(?P<y>\d{1,2})\s*(?P<b>\D.*)?$")


def parse_named(text: str, rnd: dict) -> list[tuple[int, int] | None]:
    """'Bayern 2-0, Arsenal 2-0 Leeds, Como 1-1' → scores aligned to the numbered
    ticket (None where not mentioned). 'Team x-y' = that team wins x-y (or draws);
    'Home x-y Away' = literal. Raises when a name matches 0 or 2+ ticket matches."""
    ticket = [m for m in rnd["matches"] if m.get("n")]
    out: list[tuple[int, int] | None] = [None] * len(ticket)
    for tok in re.split(r"[,\n;]+", text.strip()):
        tok = re.sub(r"^\s*(\d{1,2}\s*[.)]\s+)", "", tok).strip()  # "3. Arsenal 2-0" numbering
        if not tok:
            continue
        m = NAMED.match(tok)
        if not m:
            raise ValueError(f"No entendí '{tok}'.")
        a, b = m.group("a").strip(), (m.group("b") or "").strip()
        x, y = int(m.group("x")), int(m.group("y"))
        hits = [i for i, t in enumerate(ticket)
                if _team_in(a, t["home"]) or _team_in(a, t["away"])]
        if b:
            hits = [i for i in hits if _team_in(b, ticket[i]["home"]) or _team_in(b, ticket[i]["away"])]
        if len(hits) != 1:
            raise ValueError(f"'{tok}': {'no encontré ese partido' if not hits else 'le queda a varios partidos'} "
                             f"en el boleto; usa el nombre completo o el número.")
        i = hits[0]
        t = ticket[i]
        named_home = _team_in(a, t["home"])
        if b:          # "Home x-y Away", or written backwards "Away x-y Home"
            hs, as_ = (x, y) if named_home else (y, x)
        else:          # "Team x-y": that team scores x
            hs, as_ = (x, y) if named_home else (y, x)
        if out[i] is not None and out[i] != (hs, as_):
            raise ValueError(f"Mandaste dos marcadores distintos para {t['home']}–{t['away']}.")
        out[i] = (hs, as_)
    while out and out[-1] is None:
        out.pop()
    return out


def read_picks(text: str, rnd: dict) -> list[tuple[int, int] | None]:
    """Positional ('2-1, -, 0-0') or named ('Bayern 2-0, …'); never a mix."""
    try:
        return parse_picks(text)
    except ValueError:
        return parse_named(text, rnd)


def load_round(round_id: str) -> dict:
    path = rounds_dir() / f"{round_id}.json"
    if not path.exists():
        raise SystemExit(f"No existe la jornada {round_id} ({path}). Corre europa_live primero.")
    return json.loads(path.read_text(encoding="utf-8"))


def _key(m: dict) -> tuple:
    return (m["league"], m["home"], m["away"])


def already_sealed(records: list[dict], round_id: str, who: str) -> set[tuple]:
    """Matches this person already sealed in any part of the round."""
    done = set()
    for r in records:
        base = r["round"].split("/")[0]
        if base == round_id and r["bot"] == who:
            done |= {(p["league"], p["home"], p["away"]) for p in r["picks"]}
    return done


def build_ticket(rnd: dict, picks: list[tuple[int, int] | None], records: list[dict],
                 who: str, now: datetime) -> tuple[list[dict], list[str]]:
    """(picks to seal, messages). Pure: no I/O, so it is testable."""
    ticket = [m for m in rnd["matches"] if m.get("n")]
    msgs: list[str] = []
    if len(picks) > len(ticket):
        raise ValueError(f"Mandaste {len(picks)} marcadores y el boleto tiene {len(ticket)} partidos.")
    done = already_sealed(records, rnd["round_id"], who)
    out = []
    for m, p in zip(ticket, picks):
        label = f"{m['n']}. {m['home']}–{m['away']}"
        if p is None:
            continue
        if _key(m) in done:
            msgs.append(f"{label}: ya lo tenías sellado, no se cambia.")
            continue
        ko = m.get("kickoff_utc")
        if ko and now >= datetime.fromisoformat(ko):
            msgs.append(f"{label}: ya empezó, no se puede sellar.")
            continue
        hs, as_ = p
        out.append({"n": m["n"], "league": m["league"], "date": m["date"], "kickoff_utc": ko,
                    "home": m["home"], "away": m["away"],
                    "pick_1x2": outcome_of(hs, as_), "pick_exact": f"{hs}-{as_}"})
        msgs.append(f"{label}: {hs}-{as_} ✔")
    return out, msgs


def next_part(records: list[dict], round_id: str, who: str) -> str:
    parts = [r["round"] for r in records if r["bot"] == who and r["round"].split("/")[0] == round_id]
    return f"{round_id}/{len(parts) + 1}"


def status(rnd: dict, records: list[dict], who: str) -> list[str]:
    done = already_sealed(records, rnd["round_id"], who)
    lines = []
    for m in rnd["matches"]:
        if not m.get("n"):
            continue
        mine = next((p for r in records if r["bot"] == who and r["round"].split("/")[0] == rnd["round_id"]
                     for p in r["picks"] if (p["league"], p["home"], p["away"]) == _key(m)), None)
        mark = mine["pick_exact"] if mine else ("pendiente" if _key(m) not in done else "?")
        lines.append(f"{m['n']}. {m['home']}–{m['away']}: {mark}")
    return lines


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--round", required=True, help="p. ej. eu-2026-W41")
    ap.add_argument("--who", default="samuel")
    ap.add_argument("--picks", help='marcadores en orden: "2-1, 0-2, -, 1-3"')
    ap.add_argument("--status", action="store_true", help="qué tiene sellado y qué falta")
    ap.add_argument("--dry-run", action="store_true", help="muestra cómo lo entendió, sin sellar")
    args = ap.parse_args(argv)
    rnd = load_round(args.round)
    rnd.setdefault("round_id", args.round)
    records = seal.read_ledger(seal.LEDGER)
    ok, why = seal.verify_chain(records)
    if not ok:
        raise SystemExit(f"Libro corrupto: {why}")
    if args.status or not args.picks:
        print("\n".join(status(rnd, records, args.who)))
        return
    try:
        ticket, msgs = build_ticket(rnd, read_picks(args.picks, rnd), records, args.who,
                                    datetime.now(timezone.utc))
    except ValueError as e:
        raise SystemExit(str(e))
    print("\n".join(msgs))
    if args.dry_run:
        print("(prueba: no se selló nada)")
        return
    if not ticket:
        print("Nada nuevo que sellar.")
        return
    rec = seal.append(next_part(records, args.round, args.who), args.who, ticket)
    print(f"Sellado {rec['round']} · {len(ticket)} partidos · {rec['sealed_at']} · hash {rec['hash'][:12]}")


if __name__ == "__main__":
    main()
