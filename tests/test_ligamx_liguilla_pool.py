"""The liguilla pool is its own tournament (app: tournament='liguilla_mx', own
pot 80/20): everyone starts at 0, 14 legs, skill carried from the regular
season. Fed the regular table, the optimizer would chase a gap that does not
exist in this pool."""
from __future__ import annotations

import json

from wc_predictor.model.pool_optimizer import OpponentState, TicketMatch, optimize_ticket
from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.pipeline.ligamx import load_liguilla_pool_context


def _doc(tmp_path, players):
    path = tmp_path / "liguilla_pool.json"
    path.write_text(json.dumps({"you": "Claudio", "total_matches": 14, "players": players}),
                    encoding="utf-8")
    return path


def test_context_starts_from_zero_with_regular_season_skill(tmp_path):
    path = _doc(tmp_path, {
        "Claudio": {"points": 0, "exactos": 0, "reg_n": 133, "reg_hits": 51,
                    "reg_exactos": 6, "reg_draw_picks": 4},
        "Arturo": {"points": 0, "exactos": 0, "reg_n": 135, "reg_hits": 64,
                   "reg_exactos": 19, "reg_draw_picks": 37},
        "Aldo": {"points": 0, "exactos": 0, "reg_n": 135, "reg_hits": 59,
                 "reg_exactos": 17, "reg_draw_picks": 24},
    })
    ctx = load_liguilla_pool_context(path)
    assert ctx.your_points == 0 and ctx.leader_points == 0
    assert ctx.total_matches == 14 and ctx.matches_resolved == 0
    arturo = next(o for o in ctx.opponents if o.name == "Arturo")
    assert abs(arturo.draw_prop - 37 / 135) < 1e-12
    # Shrunk toward the pool mean: Arturo's raw 1X2 rate (0.474) is pulled in.
    assert ctx.your_q_rate <= arturo.q_rate <= 64 / 135


def test_context_requires_your_row(tmp_path):
    path = _doc(tmp_path, {"Arturo": {"points": 0, "exactos": 0}})
    try:
        load_liguilla_pool_context(path)
    except SystemExit as e:
        assert "Claudio" in str(e)
    else:
        raise AssertionError("must refuse a pool without your row")


def _cells(p):
    """1-0 / 1-1 / 0-1 toy grid with outcome masses p."""
    return [{"h": 1, "a": 0, "score": "1-0", "outcome": "1", "prob": p[0]},
            {"h": 1, "a": 1, "score": "1-1", "outcome": "X", "prob": p[1]},
            {"h": 0, "a": 1, "score": "0-1", "outcome": "2", "prob": p[2]}]


def test_draw_prop_drives_the_synthetic_field():
    """A field that never picks the draw leaves the 1-1 uncovered; one that
    always does takes the differentiation away. Same match, same seed."""
    rules = LIGAMX_APERTURA_PROFILE.rules
    m = TicketMatch(match_id="m", cells=_cells((0.36, 0.30, 0.34)), elo_probs=(0.36, 0.30, 0.34),
                    ev_pick=("1", "1-0"), contra_pick=("X", "1-1"),
                    alt_picks=[("X", "1-1"), ("2", "0-1")])

    def run(dp):
        opps = [OpponentState(f"o{i}", 0.0, 0.45, 0.08, draw_prop=dp) for i in range(8)]
        return optimize_ticket([m], rules, opponents=opps, n_sims=4000, seed=3)

    assert run(0.0).prize_pool > 0 and run(1.0).prize_pool > 0
    assert run(0.0).chosen["m"] != run(1.0).chosen["m"] or \
        run(0.0).prize_pool != run(1.0).prize_pool
