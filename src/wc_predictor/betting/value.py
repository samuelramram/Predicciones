"""Value-betting core: model probability vs de-vigged market, edge, ¼-Kelly stake.

Deliberately conservative (see docs/ligamx_apertura.md §6). A bet is flagged only
when the MODEL's INDEPENDENT probability (Poisson+Elo, WITHOUT the market in the
blend — otherwise the model just echoes the book and no edge is real) beats the
book's no-vig fair probability by `edge_min`, AND the best available price yields
positive expected value. Stake = fraction of ¼-Kelly, hard-capped at `max_stake`
of the bankroll. Markets covered: 1X2 and Over/Under totals — the two the odds
feed prices densely; double-chance/BTTS are documented extensions.

All functions here are pure (no I/O). The pipeline (pipeline.ligamx_bets) wires
them to the fitted model + odds_markets.json.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValueBet:
    match: str
    market: str          # "1X2" | "O/U 2.5" | ...
    selection: str       # "1" | "X" | "2" | "Over" | "Under"
    model_prob: float
    fair_prob: float     # book consensus, de-vigged
    edge: float          # model_prob - fair_prob
    price: float         # best decimal odds across books
    book: str | None
    ev: float            # expected profit per 1 unit staked
    kelly_stake: float   # recommended stake as a fraction of bankroll (post ¼-Kelly + cap)


def ev_per_unit(prob: float, price: float) -> float:
    """Expected profit per 1 unit staked at `price` (decimal) with true `prob`."""
    return prob * (price - 1.0) - (1.0 - prob)


def kelly_fraction(prob: float, price: float) -> float:
    """Full-Kelly stake fraction for a decimal-odds bet. 0 when no edge."""
    b = price - 1.0
    if b <= 0:
        return 0.0
    f = (prob * price - 1.0) / b
    return max(0.0, f)


def over_under_probs(cells: list[dict], line: float = 2.5) -> tuple[float, float]:
    """(P_over, P_under) for a totals line from the blended score matrix."""
    over = sum(c["prob"] for c in cells if (c["h"] + c["a"]) > line)
    return over, 1.0 - over


def btts_probs(cells: list[dict]) -> tuple[float, float]:
    """(P_yes, P_no) both-teams-to-score from the score matrix."""
    yes = sum(c["prob"] for c in cells if c["h"] >= 1 and c["a"] >= 1)
    return yes, 1.0 - yes


def _consider(match: str, market: str, selection: str, model_prob: float,
              fair_prob: float, best: dict | None, edge_min: float,
              kelly_mult: float, max_stake: float) -> ValueBet | None:
    """Emit a ValueBet if model beats fair by edge_min AND best price is +EV."""
    if not best or not best.get("price"):
        return None
    price = float(best["price"])
    edge = model_prob - fair_prob
    ev = ev_per_unit(model_prob, price)
    if edge < edge_min or ev <= 0:
        return None
    stake = min(kelly_fraction(model_prob, price) * kelly_mult, max_stake)
    if stake <= 0:
        return None
    return ValueBet(match, market, selection, model_prob, fair_prob, edge, price,
                    best.get("book"), ev, stake)


def find_value_bets(
    match: str,
    model_1x2: tuple[float, float, float],
    cells: list[dict],
    market: dict,
    *,
    edge_min: float = 0.03,
    kelly_mult: float = 0.25,
    max_stake: float = 0.02,
    total_line: float = 2.5,
) -> list[ValueBet]:
    """All value bets for one match across the covered markets.

    model_1x2: the model's INDEPENDENT (no-odds) blended (p1, px, p2).
    cells:     the model's blended score matrix (for totals).
    market:    one match entry from odds_markets.json (h2h.fair/best, totals).
    """
    out: list[ValueBet] = []
    p1, px, p2 = model_1x2

    # --- 1X2 ---
    h2h = market.get("h2h") or {}
    fair = h2h.get("fair") or {}
    best = h2h.get("best") or {}
    for sel, mp in (("1", p1), ("X", px), ("2", p2)):
        vb = _consider(match, "1X2", sel, mp, float(fair.get(sel, 1.0)),
                       best.get(sel), edge_min, kelly_mult, max_stake)
        if vb:
            out.append(vb)

    # --- Over/Under at the requested line (if the book prices it) ---
    totals = market.get("totals") or {}
    line_key = str(total_line)
    if line_key in totals:
        p_over, p_under = over_under_probs(cells, total_line)
        t = totals[line_key]
        tfair, tbest = t.get("fair") or {}, t.get("best") or {}
        for sel, mp, fkey in (("Over", p_over, "over"), ("Under", p_under, "under")):
            vb = _consider(match, f"O/U {total_line}", sel, mp,
                           float(tfair.get(fkey, 1.0)), tbest.get(fkey),
                           edge_min, kelly_mult, max_stake)
            if vb:
                out.append(vb)

    return out
