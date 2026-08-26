"""Pool standings → optimizer inputs (gap + empirical skill + horizon).

Reads `data/wc2026/pool_standings.json`, a user-maintained snapshot of the
leaderboard, and turns it into the gap/skill/horizon inputs the pool optimizer
needs to decide chase vs cushion mathematically.

Per-player empirical skill is derived purely from the marker stats — no narrative
knobs:
    e_rate = exactos / matches_resolved              (exact-score rate)
    q_rate = (points - exactos) / matches_resolved   (1X2 rate, includes exacts)

File schema (see data/wc2026/pool_standings.json):
    {
      "as_of": "2026-06-29",
      "you": "Claudio",
      "matches_resolved": 74,        # matches already scored (group stage + played KO)
      "total_matches": 104,          # full tournament size
      "total_participants": 27,      # pool size (pads beyond listed players)
      "players": [{"name","points","exactos"}, ...],   # the known leaderboard (top first)
      "field_baseline": {"points","exactos"}           # stand-in for unlisted players
    }
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from wc_predictor.model.pool_optimizer import OpponentState


@dataclass
class PoolContext:
    you: str
    your_points: float
    your_q_rate: float
    your_e_rate: float
    opponents: list[OpponentState]
    matches_resolved: int
    total_matches: int
    leader_points: float           # the current top score in the field (excluding you)
    estimated_fill: int            # how many opponents were padded from field_baseline
    your_exactos: float = 0.0      # cumulative exact hits — the leaderboard tiebreaker


def _rates(points: float, exactos: float, matches_resolved: int) -> tuple[float, float]:
    """(q_rate, e_rate) from a player's cumulative marker stats."""
    if matches_resolved <= 0:
        return 0.0, 0.0
    e = exactos / matches_resolved
    q = (points - exactos) / matches_resolved
    e = max(0.0, min(1.0, e))
    q = max(e, min(1.0, q))
    return q, e


def shrink_rates(rates: list[float], matches_resolved: int) -> list[float]:
    """Empirical-Bayes (James-Stein) shrink of per-player rates toward the pool mean.

    A rate measured over `matches_resolved` matches carries binomial noise of
    ``p(1-p)/n``. When the spread ACROSS players is no larger than that noise,
    the leaderboard is luck and every player's best estimate is the pool mean.
    Keeping only the fraction of the observed variance that survives subtracting
    luck retains real skill when it shows up and discards it when it doesn't.

    This matters because the simulator projects these rates over the REMAINING
    horizon. Raw sample means from a short sample get extrapolated as permanent
    skill: measured on the Apertura after 18 matches, the pool's observed spread
    (0.126 pts/match) was actually SMALLER than luck alone (0.156), yet the raw
    rates implied the leader would finish ~60 points clear — reporting
    P(1st)=0 and flattening the optimizer's whole objective to zero.
    """
    k = len(rates)
    if k < 2 or matches_resolved <= 0:
        return list(rates)
    mean = sum(rates) / k
    obs_var = sum((r - mean) ** 2 for r in rates) / k
    if obs_var <= 0.0:
        return [mean] * k
    luck_var = mean * (1.0 - mean) / matches_resolved
    weight = max(0.0, obs_var - luck_var) / obs_var      # share of spread that is real
    return [mean + weight * (r - mean) for r in rates]


def load_pool_context(path: Path) -> PoolContext | None:
    """Load the standings snapshot, or None if the file is absent."""
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        doc = json.load(f)

    you = doc["you"]
    matches_resolved = int(doc.get("matches_resolved", 0))
    total_matches = int(doc.get("total_matches", 0))
    players = doc.get("players", [])

    your_points = 0.0
    your_exactos = 0.0
    your_q = your_e = 0.0
    opponents: list[OpponentState] = []

    # Raw rates first, then shrink the whole field together: a player's edge is
    # only carried into the projection to the extent the field's spread exceeds
    # what luck alone explains over the matches played so far.
    raw = [_rates(p["points"], p.get("exactos", 0), matches_resolved) for p in players]
    q_shrunk = shrink_rates([r[0] for r in raw], matches_resolved)
    e_shrunk = shrink_rates([r[1] for r in raw], matches_resolved)

    for p, q, e in zip(players, q_shrunk, e_shrunk):
        e = max(0.0, min(1.0, e))
        q = max(e, min(1.0, q))                  # keep the q >= e invariant
        if p["name"] == you:
            your_points = float(p["points"])
            your_exactos = float(p.get("exactos", 0))
            your_q, your_e = q, e
        else:
            opponents.append(OpponentState(p["name"], float(p["points"]), q, e,
                                           exactos=float(p.get("exactos", 0))))

    # Pad the rest of the field with a documented baseline so the pool size is
    # right even before the full leaderboard is captured. These are dominated by
    # the top of the table for the P(rank=1) objective, so the gap stays accurate.
    estimated_fill = 0
    total_participants = int(doc.get("total_participants", len(players)))
    base = doc.get("field_baseline")
    listed = len(players)
    if base and total_participants > listed:
        bq, be = _rates(base["points"], base.get("exactos", 0), matches_resolved)
        for _ in range(total_participants - listed):
            opponents.append(OpponentState("(estimado)", float(base["points"]), bq, be))
            estimated_fill += 1

    leader_points = max((o.points for o in opponents), default=0.0)

    return PoolContext(
        you=you,
        your_points=your_points,
        your_q_rate=your_q,
        your_e_rate=your_e,
        opponents=opponents,
        matches_resolved=matches_resolved,
        total_matches=total_matches,
        leader_points=leader_points,
        estimated_fill=estimated_fill,
        your_exactos=your_exactos,
    )


def attach_real_picks(ctx: PoolContext, picks_path: Path) -> int:
    """Attach real submitted picks (ingest.pool_picks → pool_picks.json) to each
    opponent. Returns how many opponents got at least one pick attached.

    The optimizer only consults picks for the matches it is deciding, so it is
    fine to attach the full pick history — resolved matches are simply ignored.
    """
    if not picks_path.exists():
        return 0
    with picks_path.open(encoding="utf-8") as f:
        doc = json.load(f)
    players = doc.get("players", {})
    attached = 0
    for opp in ctx.opponents:
        picks = players.get(opp.name)
        if picks:
            opp.picks = picks
            attached += 1
    return attached


def compute_horizon(ctx: PoolContext, decision_pending: int) -> int:
    """Matches still to be played AFTER this decision round.

    horizon = total_matches - matches_resolved - decision_pending
    (the tail both you and the field will accumulate beyond the round you are
    deciding now). Clamped at 0.
    """
    tail = ctx.total_matches - ctx.matches_resolved - decision_pending
    return max(0, tail)
