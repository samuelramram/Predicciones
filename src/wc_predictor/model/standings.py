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


def _rates(points: float, exactos: float, matches_resolved: int) -> tuple[float, float]:
    """(q_rate, e_rate) from a player's cumulative marker stats."""
    if matches_resolved <= 0:
        return 0.0, 0.0
    e = exactos / matches_resolved
    q = (points - exactos) / matches_resolved
    e = max(0.0, min(1.0, e))
    q = max(e, min(1.0, q))
    return q, e


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
    your_q = your_e = 0.0
    opponents: list[OpponentState] = []
    for p in players:
        q, e = _rates(p["points"], p.get("exactos", 0), matches_resolved)
        if p["name"] == you:
            your_points = float(p["points"])
            your_q, your_e = q, e
        else:
            opponents.append(OpponentState(p["name"], float(p["points"]), q, e))

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
    )


def compute_horizon(ctx: PoolContext, decision_pending: int) -> int:
    """Matches still to be played AFTER this decision round.

    horizon = total_matches - matches_resolved - decision_pending
    (the tail both you and the field will accumulate beyond the round you are
    deciding now). Clamped at 0.
    """
    tail = ctx.total_matches - ctx.matches_resolved - decision_pending
    return max(0, tail)
