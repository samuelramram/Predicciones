"""Liga MX liguilla (playoffs) — general table, seeding, two-legged series and a
Monte-Carlo projection of the whole bracket.

Format (Apertura 2026, per the league's rule change that scrapped the Play-In):

  - 17 regular jornadas → general table.
  - Top 8 qualify directly (no play-in / reclasificación).
  - Quarter-finals cross by seed: 1-8, 2-7, 3-6, 4-5.
  - After the quarters, the four survivors are RE-SEEDED by their general-table
    position: best-remaining vs worst-remaining, 2nd-best vs 3rd-best.
  - Every series is two-legged on aggregate. The better-seeded team closes at
    home (hosts the second leg / vuelta); the lower seed hosts the first leg.
  - Aggregate-tie rule: in the quarter-finals and semi-finals the better-seeded
    team advances (no extra time, no penalties). In the FINAL an aggregate tie
    goes to extra time and penalties (modelled ≈ coin flip).

The pool scores each LEG at 90' like any other fixture, so a series contributes
two normal scoreline picks (ida + vuelta) — the picks pipeline just runs the
per-leg matrix. What is genuinely new here is (a) the aggregate + tie rule that
decides who advances, needed both for the "who's favoured in this series" read
and for the projection, and (b) the projection Monte-Carlo that, months before
the bracket exists, simulates the rest of the regular season → final table →
seeding → bracket to give P(each team reaches each round).

Everything is pure (no I/O); the pipeline feeds it fixtures + a `blended_matchup`
closure and renders the result.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


# --- general table ------------------------------------------------------------
@dataclass
class TableRow:
    team: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    gf: int = 0
    ga: int = 0

    @property
    def points(self) -> int:
        return 3 * self.won + self.drawn

    @property
    def gd(self) -> int:
        return self.gf - self.ga

    def sort_key(self) -> tuple:
        # Liga MX general-table tiebreakers (practical): points → goal
        # difference → goals for. (The official list continues with fair-play and
        # a draw of lots, which we don't model — irrelevant this far out and never
        # the deciding factor in a projection.)
        return (-self.points, -self.gd, -self.gf, self.team)


def compute_table(matches: list[dict], teams: list[str] | None = None) -> list[TableRow]:
    """General table from PLAYED regular-season matches (home_score not None).

    `teams` seeds rows for sides yet to play (so an 18-team table is complete
    even in week 1). Returned sorted best-first by the Liga MX tiebreakers.
    """
    rows: dict[str, TableRow] = {t: TableRow(t) for t in (teams or [])}
    for m in matches:
        if m.get("stage") not in (None, "regular"):
            continue
        hs, as_ = m.get("home_score"), m.get("away_score")
        if hs is None or as_ is None:
            continue
        h, a = m["home"], m["away"]
        rh = rows.setdefault(h, TableRow(h))
        ra = rows.setdefault(a, TableRow(a))
        rh.played += 1; ra.played += 1
        rh.gf += hs; rh.ga += as_
        ra.gf += as_; ra.ga += hs
        if hs > as_:
            rh.won += 1; ra.lost += 1
        elif hs < as_:
            ra.won += 1; rh.lost += 1
        else:
            rh.drawn += 1; ra.drawn += 1
    return sorted(rows.values(), key=lambda r: r.sort_key())


# --- score-matrix sampling ----------------------------------------------------
def build_cdf(cells: list[dict]) -> list[tuple[int, int, float]]:
    """(h, a, cumulative_prob) sorted by prob desc for fast sampling."""
    ordered = sorted(cells, key=lambda c: -c["prob"])
    cdf: list[tuple[int, int, float]] = []
    cum = 0.0
    for c in ordered:
        cum += c["prob"]
        cdf.append((c["h"], c["a"], cum))
    return cdf


def sample_cdf(cdf: list[tuple[int, int, float]], r: float) -> tuple[int, int]:
    for h, a, cum in cdf:
        if r <= cum:
            return h, a
    return cdf[-1][0], cdf[-1][1]


# --- two-legged series --------------------------------------------------------
def _diff_dist(cells: list[dict], home_is_target: bool) -> dict[int, float]:
    """Distribution of (target team goals − opponent goals) in one leg, from that
    leg's blended score matrix. `home_is_target` picks the sign (home team's diff
    is h−a; the away team's is a−h)."""
    dist: dict[int, float] = {}
    for c in cells:
        d = (c["h"] - c["a"]) if home_is_target else (c["a"] - c["h"])
        dist[d] = dist.get(d, 0.0) + c["prob"]
    return dist


def _convolve(d1: dict[int, float], d2: dict[int, float]) -> dict[int, float]:
    out: dict[int, float] = {}
    for k1, p1 in d1.items():
        for k2, p2 in d2.items():
            out[k1 + k2] = out.get(k1 + k2, 0.0) + p1 * p2
    return out


def series_advance_prob(cells_ida: list[dict], cells_vuelta: list[dict],
                        tie_to_higher: bool = True) -> float:
    """P(the higher seed advances) over two legs on aggregate.

    `cells_ida` is the first leg's matrix with the LOWER seed at home; `cells_vuelta`
    is the second leg with the HIGHER seed at home. The higher seed's aggregate
    goal difference is convolved across the two legs; `tie_to_higher` applies the
    round's aggregate-tie rule (True for QF/SF → higher seed advances; the final
    passes 0.5 via `final_tie_prob`).
    """
    # Higher seed is AWAY in the ida (target = away) and HOME in the vuelta.
    d_ida = _diff_dist(cells_ida, home_is_target=False)
    d_vta = _diff_dist(cells_vuelta, home_is_target=True)
    agg = _convolve(d_ida, d_vta)
    p_win = sum(p for d, p in agg.items() if d > 0)
    p_tie = sum(p for d, p in agg.items() if d == 0)
    tie_factor = 1.0 if tie_to_higher else 0.5
    total = sum(agg.values()) or 1.0
    return (p_win + p_tie * tie_factor) / total


def sim_series(rng: random.Random, cdf_ida, cdf_vuelta, final_tie_prob: float | None = None) -> bool:
    """Sample both legs; return True iff the HIGHER seed advances.

    cdf_ida = lower-seed-home matrix, cdf_vuelta = higher-seed-home matrix.
    `final_tie_prob` (the final's coin flip) overrides the default "higher seed
    advances on aggregate tie" used by QF/SF.
    """
    h1, a1 = sample_cdf(cdf_ida, rng.random())      # low home (h1) vs high away (a1)
    h2, a2 = sample_cdf(cdf_vuelta, rng.random())   # high home (h2) vs low away (a2)
    high_agg = a1 + h2
    low_agg = h1 + a2
    if high_agg > low_agg:
        return True
    if high_agg < low_agg:
        return False
    return rng.random() < (0.5 if final_tie_prob is None else final_tie_prob)


# --- bracket construction -----------------------------------------------------
# Quarter-final crossings by seed index (0-based: seed 1 = index 0).
QF_CROSS = [(0, 7), (1, 6), (2, 5), (3, 4)]  # 1-8, 2-7, 3-6, 4-5

ROUND_LABELS = {
    "liguilla": "Clasifica a Liguilla (top-8)",
    "quarter_final": "Cuartos de final",
    "semi_final": "Semifinal",
    "final": "Final",
    "champion": "Campeón",
}
LIGUILLA_ROUNDS = ("quarter_final", "semi_final", "final")


@dataclass
class Series:
    """One two-legged tie. `high`/`low` are team names; `high_seed`/`low_seed` are
    1-based general-table seeds (high_seed < low_seed). The higher seed hosts the
    vuelta."""
    round_key: str
    high: str
    low: str
    high_seed: int
    low_seed: int

    def legs(self) -> list[tuple[str, str, str]]:
        """[(leg, home, away)] — ida at the lower seed, vuelta at the higher seed."""
        return [("ida", self.low, self.high), ("vuelta", self.high, self.low)]


def build_quarterfinals(seeds: list[str]) -> list[Series]:
    """seeds = general-table order (seeds[0] = 1st). Returns the 4 QF series."""
    out = []
    for hi, lo in QF_CROSS:
        out.append(Series("quarter_final", seeds[hi], seeds[lo], hi + 1, lo + 1))
    return out


def reseed_semifinals(qf_winners: list[str], seed_of: dict[str, int]) -> list[Series]:
    """Re-seed the four QF winners by GENERAL-TABLE position: best vs worst,
    2nd-best vs 3rd-best (the Apertura 2026 rule)."""
    ordered = sorted(qf_winners, key=lambda t: seed_of[t])  # best (lowest seed) first
    pairs = [(ordered[0], ordered[3]), (ordered[1], ordered[2])]
    return [Series("semi_final", hi, lo, seed_of[hi], seed_of[lo]) for hi, lo in pairs]


def build_final(sf_winners: list[str], seed_of: dict[str, int]) -> Series:
    hi, lo = sorted(sf_winners, key=lambda t: seed_of[t])
    return Series("final", hi, lo, seed_of[hi], seed_of[lo])


# --- projection Monte-Carlo ---------------------------------------------------
@dataclass
class LiguillaProjection:
    n_sims: int
    table_now: list[TableRow]
    # team → {round_key → probability}
    reach: dict[str, dict[str, float]]
    # team → {seed (1..8) → P(finishing the regular season in that seed)}
    seed_rates: dict[str, dict[int, float]]
    # most-likely projected bracket (from the current table, deterministic)
    projected_qf: list[Series]
    elapsed_seconds: float = 0.0


REACH_ROUNDS = ("liguilla", "quarter_final", "semi_final", "final", "champion")


def project_liguilla(
    table_matches: list[dict],
    remaining_fixtures: list[dict],
    matchup_cells,               # (home, away) -> cells | None
    teams: list[str],
    n_sims: int = 10000,
    seed: int = 20260727,
    final_tie_prob: float = 0.5,
) -> LiguillaProjection:
    """Simulate the rest of the regular season → table → seeding → bracket.

    `matchup_cells(home, away)` returns the blended score matrix for any pairing
    (the pipeline passes a memoised `blended_matchup` closure). `table_matches`
    are the already-played regular fixtures (fixed starting standings);
    `remaining_fixtures` the unplayed ones (sampled each sim).
    """
    import time
    t0 = time.time()

    # Starting standings from played matches.
    base_rows = {r.team: r for r in compute_table(table_matches, teams)}

    # Precompute CDFs for the remaining regular fixtures.
    rem: list[tuple[str, str, list]] = []
    for fx in remaining_fixtures:
        cells = matchup_cells(fx["home"], fx["away"])
        if cells is None:
            continue
        rem.append((fx["home"], fx["away"], build_cdf(cells)))

    # Precompute CDFs for all ordered team pairs (liguilla legs, both venues).
    pair_cdf: dict[tuple[str, str], list] = {}
    for h in teams:
        for a in teams:
            if h == a:
                continue
            cells = matchup_cells(h, a)
            if cells is not None:
                pair_cdf[(h, a)] = build_cdf(cells)

    reach = {t: {r: 0 for r in REACH_ROUNDS} for t in teams}
    seed_rates = {t: {s: 0 for s in range(1, 9)} for t in teams}
    rng = random.Random(seed)

    for _ in range(n_sims):
        # Copy starting standings.
        pts = {t: r.points for t, r in base_rows.items()}
        gd = {t: r.gd for t, r in base_rows.items()}
        gf = {t: r.gf for t, r in base_rows.items()}
        for h, a, cdf in rem:
            hs, as_ = sample_cdf(cdf, rng.random())
            gf[h] += hs; gf[a] += as_
            gd[h] += hs - as_; gd[a] += as_ - hs
            if hs > as_:
                pts[h] += 3
            elif hs < as_:
                pts[a] += 3
            else:
                pts[h] += 1; pts[a] += 1

        order = sorted(teams, key=lambda t: (-pts[t], -gd[t], -gf[t], rng.random()))
        seeds = order[:8]
        seed_of = {t: i + 1 for i, t in enumerate(order)}
        for i, t in enumerate(seeds):
            seed_rates[t][i + 1] += 1
            reach[t]["liguilla"] += 1
            reach[t]["quarter_final"] += 1

        # Quarter-finals.
        qf_winners = []
        for hi, lo in QF_CROSS:
            high, low = seeds[hi], seeds[lo]
            adv_high = sim_series(rng, pair_cdf[(low, high)], pair_cdf[(high, low)])
            qf_winners.append(high if adv_high else low)
        for w in qf_winners:
            reach[w]["semi_final"] += 1

        # Re-seed semis by general-table position.
        sf = reseed_semifinals(qf_winners, seed_of)
        sf_winners = []
        for s in sf:
            adv_high = sim_series(rng, pair_cdf[(s.low, s.high)], pair_cdf[(s.high, s.low)])
            sf_winners.append(s.high if adv_high else s.low)
        for w in sf_winners:
            reach[w]["final"] += 1

        # Final (aggregate tie → ET/pens ≈ coin flip).
        fin = build_final(sf_winners, seed_of)
        champ_high = sim_series(rng, pair_cdf[(fin.low, fin.high)],
                                pair_cdf[(fin.high, fin.low)], final_tie_prob=final_tie_prob)
        champ = fin.high if champ_high else fin.low
        reach[champ]["champion"] += 1

    reach_p = {t: {r: reach[t][r] / n_sims for r in REACH_ROUNDS} for t in teams}
    seed_p = {t: {s: seed_rates[t][s] / n_sims for s in range(1, 9)} for t in teams}
    table_now = compute_table(table_matches, teams)
    proj_qf = build_quarterfinals([r.team for r in table_now][:8])

    return LiguillaProjection(
        n_sims=n_sims, table_now=table_now, reach=reach_p, seed_rates=seed_p,
        projected_qf=proj_qf, elapsed_seconds=time.time() - t0,
    )
