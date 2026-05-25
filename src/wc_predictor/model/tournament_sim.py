"""Monte Carlo simulation of the full WC 2026 tournament.

Simulates N complete tournaments to produce P(team reaches each round):
  advance_group  – qualifies for round of 32 (top-2 per group or best-8 3rd)
  reach_r16      – wins R32, plays round of 16
  reach_qf       – wins R16, plays quarter-final
  reach_sf       – wins QF, plays semi-final
  reach_final    – wins SF, plays final
  champion       – wins final

Method:
1. Precompute Poisson+Elo blended outcome probabilities and score CDFs for all 72
   group-stage fixtures using actual venue/host data (same as generate_picks pipeline).
2. Precompute P(team A beats team B) for all C(48,2)=1128 pairs, neutral venue.
3. For each of N simulations:
   a. Sample scores for all 72 group matches from the precomputed CDFs.
   b. Rank 4 teams per group: points → GD → GF → random tiebreak.
   c. Pick best 8 of 12 third-place teams (by points → GD → GF → random).
   d. Assign 3rd-place teams to R32 slots via greedy bipartite matching against
      the official FIFA eligible-group lookup table.
   e. Simulate R32 → R16 → QF → SF → Final using precomputed win probabilities,
      with draws resolved by proportional-strength ET/penalties model.
4. Aggregate counts → P(round) per team.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from math import exp, factorial

from wc_predictor.config import ModelConfig
from wc_predictor.model.adjustments import apply_wc_lambdas
from wc_predictor.model.blend import log_pool
from wc_predictor.model.poisson_dc import FitResult, predict_lambdas
from wc_predictor.ratings.elo import elo_to_1x2_probs
from wc_predictor.scoring.quiniela import dc_correction


# ---------------------------------------------------------------------------
# Official WC 2026 bracket constants
# ---------------------------------------------------------------------------

ROUNDS = ("advance_group", "reach_r16", "reach_qf", "reach_sf", "reach_final", "champion")

ROUND_LABELS: dict[str, str] = {
    "advance_group": "Clasifica de grupo (top-32)",
    "reach_r16":     "Octavos de final",
    "reach_qf":      "Cuartos de final",
    "reach_sf":      "Semifinal",
    "reach_final":   "Final",
    "champion":      "Campeón",
}

# R32 match slots 0..15 (correspond to global match numbers 73–88).
# Each entry: (home_spec, away_spec).
# Spec formats: "1G"/"2G" = 1st/2nd place of group G; "3ABCDF" = best-3rd from groups A,B,C,D,F.
R32_SLOTS: list[tuple[str, str]] = [
    ("2A", "2B"),        # 0  M73
    ("1E", "3ABCDF"),    # 1  M74
    ("1F", "2C"),        # 2  M75
    ("1C", "2F"),        # 3  M76
    ("1I", "3CDFGH"),    # 4  M77
    ("2E", "2I"),        # 5  M78
    ("1A", "3CEFHI"),    # 6  M79
    ("1L", "3EHIJK"),    # 7  M80
    ("1D", "3BEFIJ"),    # 8  M81
    ("1G", "3AEHIJ"),    # 9  M82
    ("2K", "2L"),        # 10 M83
    ("1H", "2J"),        # 11 M84
    ("1B", "3EFGIJ"),    # 12 M85
    ("1J", "2H"),        # 13 M86
    ("1K", "3DEIJL"),    # 14 M87
    ("2D", "2G"),        # 15 M88
]

# R16: pairs of R32 slot indices whose winners play each other.
R16_BRACKET: list[tuple[int, int]] = [
    (1, 4),    # R16[0] = W74 vs W77
    (0, 2),    # R16[1] = W73 vs W75
    (3, 5),    # R16[2] = W76 vs W78
    (6, 7),    # R16[3] = W79 vs W80
    (10, 11),  # R16[4] = W83 vs W84
    (8, 9),    # R16[5] = W81 vs W82
    (13, 15),  # R16[6] = W86 vs W88
    (12, 14),  # R16[7] = W85 vs W87
]

# QF: pairs of R16 match indices.
QF_BRACKET: list[tuple[int, int]] = [
    (0, 1),  # QF[0] = W89 vs W90
    (4, 5),  # QF[1] = W93 vs W94
    (2, 3),  # QF[2] = W91 vs W92
    (6, 7),  # QF[3] = W95 vs W96
]

# SF: pairs of QF match indices.
SF_BRACKET: list[tuple[int, int]] = [
    (0, 1),  # SF[0] = W97 vs W98
    (2, 3),  # SF[1] = W99 vs W100
]

# Official eligible-group sets for each 3rd-place R32 slot index.
THIRD_ELIGIBLE: dict[int, frozenset[str]] = {
    1:  frozenset("ABCDF"),
    4:  frozenset("CDFGH"),
    6:  frozenset("CEFHI"),
    7:  frozenset("EHIJK"),
    8:  frozenset("BEFIJ"),
    9:  frozenset("AEHIJ"),
    12: frozenset("EFGIJ"),
    14: frozenset("DEIJL"),
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GroupResult:
    ranked: list[str]           # [1st, 2nd, 3rd, 4th]
    pts: dict[str, int]         # final points per team
    gd: dict[str, int]          # final goal difference per team
    gf: dict[str, int]          # final goals for per team


@dataclass
class TournamentSimResult:
    """Summary statistics of N Monte Carlo tournament simulations."""
    n_sims: int
    groups: dict[str, list[str]]
    # team → {round_key → probability of reaching that round}
    advance_rates: dict[str, dict[str, float]]
    # team → {rank (1–4) → probability of finishing in that group position}
    group_finish: dict[str, dict[int, float]]
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def _pois(lam: float, k: int) -> float:
    return (lam ** k * exp(-lam)) / factorial(k)


def _outcome_probs(
    lh: float, la: float, rho: float, max_g: int = 10
) -> tuple[float, float, float]:
    p1 = px = p2 = 0.0
    for h in range(max_g + 1):
        ph = _pois(lh, h)
        for a in range(max_g + 1):
            p = ph * _pois(la, a) * dc_correction(h, a, lh, la, rho)
            if h > a:    p1 += p
            elif h == a: px += p
            else:        p2 += p
    s = p1 + px + p2
    if s < 1e-12:
        return 1 / 3, 1 / 3, 1 / 3
    return p1 / s, px / s, p2 / s


def _blended_1x2(
    lh: float, la: float, rho: float,
    r_h: float, r_a: float, home_adv_elo: float,
    w_poisson: float = 0.70, w_elo: float = 0.30,
) -> tuple[float, float, float]:
    pp1, ppx, pp2 = _outcome_probs(lh, la, rho)
    ep1, epx, ep2 = elo_to_1x2_probs(r_h, r_a, home_adv_elo)
    return log_pool([(pp1, ppx, pp2), (ep1, epx, ep2)], [w_poisson, w_elo])


def _build_cdf(
    lh: float, la: float, rho: float,
    p1: float, px: float, p2: float,
    max_g: int = 9,
) -> list[tuple[int, int, float]]:
    """Score CDF rescaled to blended marginals (p1, px, p2), sorted by prob desc."""
    raw: list[tuple[int, int, float]] = []
    rp1 = rpx = rp2 = 0.0
    for h in range(max_g + 1):
        ph = _pois(lh, h)
        for a in range(max_g + 1):
            prob = ph * _pois(la, a) * dc_correction(h, a, lh, la, rho)
            raw.append((h, a, prob))
            if h > a:    rp1 += prob
            elif h == a: rpx += prob
            else:        rp2 += prob

    scale = {
        "1": p1 / max(rp1, 1e-12),
        "X": px / max(rpx, 1e-12),
        "2": p2 / max(rp2, 1e-12),
    }
    rescaled: list[tuple[int, int, float]] = []
    total = 0.0
    for h, a, prob in raw:
        o = "1" if h > a else ("X" if h == a else "2")
        rp = prob * scale[o]
        rescaled.append((h, a, rp))
        total += rp

    normalized = [(h, a, rp / total) for h, a, rp in rescaled]
    normalized.sort(key=lambda x: -x[2])  # sort descending for fast sampling

    cum = 0.0
    cdf: list[tuple[int, int, float]] = []
    for h, a, prob in normalized:
        cum += prob
        cdf.append((h, a, cum))
    return cdf


def _sample_cdf(cdf: list[tuple[int, int, float]], r: float) -> tuple[int, int]:
    for h, a, cum in cdf:
        if r <= cum:
            return h, a
    h, a, _ = cdf[-1]
    return h, a


def _ko_win_prob(p1: float, px: float, p2: float) -> float:
    """P(home team wins a knockout match).

    90-min result + proportional-strength model for ET/penalties on draws:
        P(home wins ET | draw in 90min) ≈ p1 / (p1 + p2)
    """
    p_et_home = p1 / max(p1 + p2, 1e-12)
    return p1 + px * p_et_home


# ---------------------------------------------------------------------------
# Group simulation
# ---------------------------------------------------------------------------

def _simulate_group(
    match_pairs: list[tuple[str, str]],  # (home, away) for each of 6 fixtures
    cdfs: dict[tuple[str, str], list[tuple[int, int, float]]],
    rng: random.Random,
) -> GroupResult:
    """Simulate one 4-team group; return ranked list [1st, 2nd, 3rd, 4th] + stats."""
    teams = list({t for pair in match_pairs for t in pair})
    standings: dict[str, dict[str, int]] = {t: {"pts": 0, "gd": 0, "gf": 0} for t in teams}

    for home, away in match_pairs:
        cdf = cdfs[(home, away)]
        h, a = _sample_cdf(cdf, rng.random())
        standings[home]["gf"] += h
        standings[home]["gd"] += h - a
        standings[away]["gf"] += a
        standings[away]["gd"] += a - h
        if h > a:
            standings[home]["pts"] += 3
        elif h == a:
            standings[home]["pts"] += 1
            standings[away]["pts"] += 1
        else:
            standings[away]["pts"] += 3

    ranked = sorted(
        teams,
        key=lambda t: (
            -standings[t]["pts"],
            -standings[t]["gd"],
            -standings[t]["gf"],
            rng.random(),   # random tiebreak (FIFA: drawing of lots)
        ),
    )
    return GroupResult(
        ranked=ranked,
        pts={t: standings[t]["pts"] for t in teams},
        gd={t: standings[t]["gd"] for t in teams},
        gf={t: standings[t]["gf"] for t in teams},
    )


# ---------------------------------------------------------------------------
# 3rd-place slot assignment (greedy bipartite matching)
# ---------------------------------------------------------------------------

def _assign_thirds(
    best8: list[tuple[str, str, int, int, int]],  # (team, group, pts, gd, gf) best→worst
    rng: random.Random,
) -> dict[int, str]:
    """Assign 8 qualified 3rd-place teams to R32 slot indices.

    Uses greedy bipartite matching: sort slots by number of eligible candidates
    (ascending = most constrained first), then assign the best available
    eligible team. Falls back to any remaining team if a slot cannot be filled
    via official constraints (rare edge case in simulation).
    """
    available: list[tuple[str, str]] = [(team, group) for team, group, *_ in best8]

    slot_order = sorted(
        THIRD_ELIGIBLE.keys(),
        key=lambda s: sum(1 for _, g in available if g in THIRD_ELIGIBLE[s]),
    )

    assignment: dict[int, str] = {}
    for slot in slot_order:
        eligible = [(i, t) for i, (t, g) in enumerate(available) if g in THIRD_ELIGIBLE[slot]]
        if not eligible:
            eligible = [(i, t) for i, (t, g) in enumerate(available)]
        if not eligible:
            break
        # Pick the best-ranked (lowest index = highest rank among best8)
        best_i, best_team = min(eligible, key=lambda x: x[0])
        assignment[slot] = best_team
        available.pop(best_i)

    return assignment


# ---------------------------------------------------------------------------
# Precomputation
# ---------------------------------------------------------------------------

def _host_role(fixture: dict, venues: dict) -> str | None:
    venue = fixture.get("venue")
    if not venue or venue not in venues:
        return None
    vc = venues[venue]["country"]
    if vc == fixture["home"]:
        return "home"
    if vc == fixture["away"]:
        return "away"
    return None


def precompute_group_cdfs(
    group_fixtures: list[dict],
    fit: FitResult,
    elos: dict[str, float],
    venues: dict,
    cfg: ModelConfig,
) -> dict[tuple[str, str], list[tuple[int, int, float]]]:
    """Build score CDFs for all 72 group matches, keyed by (home, away) team names."""
    cdfs: dict[tuple[str, str], list] = {}
    base_lambda = exp(fit.mu) * cfg.wc_lambda_inflation

    for fx in group_fixtures:
        home, away = fx["home"], fx["away"]
        host = _host_role(fx, venues)
        home_adv_elo = (
            cfg.elo_home_bonus if host == "home"
            else (-cfg.elo_home_bonus if host == "away" else 0.0)
        )
        r_h = elos.get(home, 1500.0)
        r_a = elos.get(away, 1500.0)

        if home in fit.strengths and away in fit.strengths:
            lh, la = predict_lambdas(
                fit.strengths[home], fit.strengths[away], fit.mu, fit.gamma, host=host
            )
            lh, la = apply_wc_lambdas(lh, la, cfg)
        else:
            lh = la = base_lambda

        p1, px, p2 = _blended_1x2(lh, la, fit.rho, r_h, r_a, home_adv_elo)
        cdfs[(home, away)] = _build_cdf(lh, la, fit.rho, p1, px, p2)

    return cdfs


def precompute_ko_probs(
    teams: list[str],
    fit: FitResult,
    elos: dict[str, float],
    cfg: ModelConfig,
) -> dict[tuple[str, str], float]:
    """P(team_a beats team_b) in a knockout match, assuming neutral venue.

    Returns a dict for both orderings: probs[(a, b)] + probs[(b, a)] = 1.0.
    """
    probs: dict[tuple[str, str], float] = {}
    base_lambda = exp(fit.mu) * cfg.wc_lambda_inflation

    for i, a in enumerate(teams):
        for b in teams[i + 1:]:
            r_a = elos.get(a, 1500.0)
            r_b = elos.get(b, 1500.0)

            if a in fit.strengths and b in fit.strengths:
                lh, la = predict_lambdas(
                    fit.strengths[a], fit.strengths[b], fit.mu, fit.gamma, host=None
                )
                lh, la = apply_wc_lambdas(lh, la, cfg)
            else:
                lh = la = base_lambda

            p1, px, p2 = _blended_1x2(lh, la, fit.rho, r_a, r_b, 0.0)
            p_a_wins = _ko_win_prob(p1, px, p2)
            probs[(a, b)] = p_a_wins
            probs[(b, a)] = 1.0 - p_a_wins

    return probs


# ---------------------------------------------------------------------------
# Main simulation entry point
# ---------------------------------------------------------------------------

def simulate_tournament(
    groups: dict[str, list[str]],
    group_fixtures: list[dict],
    fit: FitResult,
    elos: dict[str, float],
    venues: dict,
    cfg: ModelConfig,
    n_sims: int = 20_000,
    seed: int = 20260611,
) -> TournamentSimResult:
    """Run N Monte Carlo WC2026 tournament simulations.

    Args:
        groups: group letter → list of 4 team names (from fixtures.json).
        group_fixtures: the 72 group-stage fixture dicts with home/away/venue.
        fit: fitted Poisson+DC model.
        elos: current Elo ratings per team.
        venues: venue metadata dict (keyed by venue name, from venues.json).
        cfg: ModelConfig hyperparameters.
        n_sims: number of simulated tournaments.
        seed: RNG seed for reproducibility.

    Returns:
        TournamentSimResult with P(team reaches each round) and group-finish rates.
    """
    t0 = time.time()
    all_teams: list[str] = [t for letter in sorted(groups) for t in groups[letter]]

    # Precompute once --------------------------------------------------------
    print(f"  precomputing {len(group_fixtures)} group CDFs ...")
    group_cdfs = precompute_group_cdfs(group_fixtures, fit, elos, venues, cfg)

    print(f"  precomputing KO win-probs for {len(all_teams)} teams "
          f"({len(all_teams) * (len(all_teams) - 1) // 2} pairs) ...")
    ko_probs = precompute_ko_probs(all_teams, fit, elos, cfg)

    # Build fixture pair lists per group ------------------------------------
    group_pairs: dict[str, list[tuple[str, str]]] = {letter: [] for letter in groups}
    for fx in group_fixtures:
        letter = fx.get("group")
        if letter:
            group_pairs[letter].append((fx["home"], fx["away"]))

    # Accumulators ----------------------------------------------------------
    advance_counts: dict[str, dict[str, int]] = {
        t: {r: 0 for r in ROUNDS} for t in all_teams
    }
    finish_counts: dict[str, dict[int, int]] = {
        t: {rank: 0 for rank in range(1, 5)} for t in all_teams
    }

    rng = random.Random(seed)
    print(f"  running {n_sims:,} simulations ...")

    for _ in range(n_sims):

        # ── Group stage ────────────────────────────────────────────────────
        group_results: dict[str, GroupResult] = {}
        for letter, teams in groups.items():
            result = _simulate_group(group_pairs[letter], group_cdfs, rng)
            group_results[letter] = result
            for rank_idx, team in enumerate(result.ranked, start=1):
                finish_counts[team][rank_idx] += 1

        # ── 3rd-place qualification ────────────────────────────────────────
        all_thirds: list[tuple[str, str, int, int, int]] = []
        for letter, result in group_results.items():
            third = result.ranked[2]
            all_thirds.append((
                third, letter,
                result.pts[third], result.gd[third], result.gf[third],
            ))

        all_thirds.sort(key=lambda x: (-x[2], -x[3], -x[4], rng.random()))
        best8 = all_thirds[:8]

        # top-2 per group + best-8 3rd all qualify
        for letter, result in group_results.items():
            advance_counts[result.ranked[0]]["advance_group"] += 1
            advance_counts[result.ranked[1]]["advance_group"] += 1
        for team, *_ in best8:
            advance_counts[team]["advance_group"] += 1

        # ── Build R32 bracket ──────────────────────────────────────────────
        third_assignment = _assign_thirds(best8, rng)

        r32_pairs: list[tuple[str | None, str | None]] = []
        for slot_idx, (home_spec, away_spec) in enumerate(R32_SLOTS):
            def _resolve(spec: str) -> str | None:
                if spec.startswith("3"):
                    return third_assignment.get(slot_idx)
                pos = int(spec[0])
                letter = spec[1]
                ranked = group_results[letter].ranked
                return ranked[pos - 1] if pos - 1 < len(ranked) else None

            r32_pairs.append((_resolve(home_spec), _resolve(away_spec)))

        # ── Simulate knockout rounds ───────────────────────────────────────
        def _ko(a: str | None, b: str | None) -> str | None:
            if a is None or b is None:
                return a or b
            p = ko_probs.get((a, b), 0.5)
            return a if rng.random() < p else b

        # R32
        r32_w: list[str | None] = []
        for home, away in r32_pairs:
            w = _ko(home, away)
            r32_w.append(w)
            if w is not None:
                advance_counts[w]["reach_r16"] += 1

        # R16
        r16_w: list[str | None] = []
        for a_i, b_i in R16_BRACKET:
            w = _ko(r32_w[a_i], r32_w[b_i])
            r16_w.append(w)
            if w is not None:
                advance_counts[w]["reach_qf"] += 1

        # QF
        qf_w: list[str | None] = []
        for a_i, b_i in QF_BRACKET:
            w = _ko(r16_w[a_i], r16_w[b_i])
            qf_w.append(w)
            if w is not None:
                advance_counts[w]["reach_sf"] += 1

        # SF
        sf_w: list[str | None] = []
        for a_i, b_i in SF_BRACKET:
            w = _ko(qf_w[a_i], qf_w[b_i])
            sf_w.append(w)
            if w is not None:
                advance_counts[w]["reach_final"] += 1

        # Final
        champion = _ko(sf_w[0] if sf_w else None, sf_w[1] if len(sf_w) > 1 else None)
        if champion is not None:
            advance_counts[champion]["champion"] += 1

    # Convert counts → rates ------------------------------------------------
    advance_rates: dict[str, dict[str, float]] = {
        t: {r: advance_counts[t][r] / n_sims for r in ROUNDS}
        for t in all_teams
    }
    group_finish: dict[str, dict[int, float]] = {
        t: {rank: finish_counts[t][rank] / n_sims for rank in range(1, 5)}
        for t in all_teams
    }

    return TournamentSimResult(
        n_sims=n_sims,
        groups=groups,
        advance_rates=advance_rates,
        group_finish=group_finish,
        elapsed_seconds=time.time() - t0,
    )
