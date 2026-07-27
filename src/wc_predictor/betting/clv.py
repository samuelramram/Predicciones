"""Closing-line-value (CLV) core — the honest measurement of a betting edge.

The closing line (the market price right before kickoff, de-vigged) is the
sharpest public estimate of a match's true probabilities. If you consistently
bet at prices BETTER than the close, your selection has real edge — regardless of
whether any single bet won. That's the whole point of the ledger: over a season,
a positive average CLV is evidence the model finds value; a negative one says the
"edges" were model error and the energy belongs in the quiniela.

Two readings, both recorded per bet:

- **CLV (line movement):** ``entry_price / close_price - 1``. Your locked-in
  decimal odds vs the closing decimal odds for the same selection (both real,
  vig-laden prices — so the comparison is clean, unlike mixing a vigged price
  with a de-vigged prob). Positive ⇒ you got a longer price than it closed at ⇒
  you beat the close. This is the primary metric and doesn't need the bet to
  settle. Captured at the same instant as entry it is 0 (no movement yet).
- **EV vs the sharp fair (secondary):** ``entry_price * close_fair_prob - 1``.
  Your price evaluated against the closing DE-VIGGED probability (the best proxy
  for the truth). Near-zero-to-negative for efficient markets because de-vigged
  fair odds exceed any real price; a genuine edge shows it less negative. A
  cross-check on CLV, not the headline.

Realized P&L (win/loss × stake) is tracked too, but it's secondary: it's noisy
over a season's worth of bets, while CLV converges much faster. Pure module (no
I/O); the pipeline (pipeline.ligamx_clv) persists the ledger and renders it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import mean


@dataclass
class LedgerEntry:
    """One logged bet and (once the line closes / the match settles) its CLV."""
    round: str
    match: str
    market: str
    selection: str
    model_prob: float
    entry_fair_prob: float       # book consensus fair prob at bet time
    entry_price: float           # best decimal odds we could take
    entry_book: str | None
    stake_mxn: float
    logged_at: str
    # filled by `close`:
    close_fair_prob: float | None = None
    close_price: float | None = None     # closing consensus/best decimal for the selection
    closed_at: str | None = None
    # filled by `settle` (when the match result is known):
    result: str | None = None            # "win" | "loss" | "void"
    profit_mxn: float | None = None

    def key(self) -> tuple:
        return (self.round, self.match, self.market, self.selection)


def clv_odds(entry_price: float, close_price: float | None) -> float | None:
    """Primary CLV: entry decimal odds vs closing decimal odds (both real prices).
    Positive ⇒ you locked a longer price than it closed at. None if no close."""
    if close_price is None or close_price <= 0:
        return None
    return entry_price / close_price - 1.0


def ev_vs_fair(entry_price: float, close_fair_prob: float | None) -> float | None:
    """Secondary: EV per unit at the closing de-vigged fair probability."""
    if close_fair_prob is None:
        return None
    return entry_price * close_fair_prob - 1.0


def beat_close(entry_price: float, close_price: float | None) -> bool | None:
    """True iff we locked in better odds than the closing price (same selection)."""
    if close_price is None or close_price <= 0:
        return None
    return entry_price > close_price


def settle_profit(entry_price: float, stake: float, result: str | None) -> float | None:
    """Realized profit for a settled bet (decimal odds, stake in MXN)."""
    if result == "win":
        return stake * (entry_price - 1.0)
    if result == "loss":
        return -stake
    if result == "void":
        return 0.0
    return None


def summarize(entries: list[LedgerEntry]) -> dict:
    """Aggregate CLV + realized stats over the ledger (and per market)."""
    def _agg(rows: list[LedgerEntry]) -> dict:
        closed = [e for e in rows if e.close_price is not None]
        clvs = [c for e in closed if (c := clv_odds(e.entry_price, e.close_price)) is not None]
        evs = [v for e in rows if (v := ev_vs_fair(e.entry_price, e.close_fair_prob)) is not None]
        beats = [b for e in closed if (b := beat_close(e.entry_price, e.close_price)) is not None]
        settled = [e for e in rows if e.profit_mxn is not None]
        staked = sum(e.stake_mxn for e in settled)
        profit = sum(e.profit_mxn for e in settled)
        return {
            "n": len(rows),
            "n_closed": len(closed),
            "avg_clv_pct": round(mean(clvs) * 100, 2) if clvs else None,
            "avg_ev_close_pct": round(mean(evs) * 100, 2) if evs else None,
            "pct_beat_close": round(sum(beats) / len(beats) * 100, 1) if beats else None,
            "n_settled": len(settled),
            "staked_mxn": round(staked, 2),
            "profit_mxn": round(profit, 2),
            "roi_pct": round(profit / staked * 100, 1) if staked else None,
            "wins": sum(1 for e in settled if e.result == "win"),
            "losses": sum(1 for e in settled if e.result == "loss"),
        }

    overall = _agg(entries)
    markets = sorted({e.market for e in entries})
    overall["by_market"] = {m: _agg([e for e in entries if e.market == m]) for m in markets}
    return overall


def entry_from_dict(d: dict) -> LedgerEntry:
    fields = LedgerEntry.__dataclass_fields__
    return LedgerEntry(**{k: v for k, v in d.items() if k in fields})


def entry_to_dict(e: LedgerEntry) -> dict:
    return asdict(e)
