"""League profiles — the seed of the tournament-agnostic core.

The engine (Poisson+DC, Elo, blend, EV/pool optimizer, quiniela scorer) is the
same across tournaments; what changes between the World Cup and Liga MX is *data
and calibration*, not math. A :class:`LeagueProfile` bundles everything that
diverges so the pipeline can be pointed at a league by swapping one object
instead of forking the package.

Fase 0 introduces the abstraction and both profiles WITHOUT rewiring
``generate_picks`` yet (that pipeline is still hard-coded to the World Cup — the
coupling points are listed in ``docs/ligamx_apertura.md``). The Liga MX profile
is therefore a *specification* the Fase 1 refactor consumes, plus something the
data-scaffolding and docs can already reference by a single source of truth.

Design note — why the model overrides live here and not in ``config.py``:
``ModelConfig`` holds the World-Cup-calibrated defaults (they must stay put so
the 166 existing tests and the WC pipeline are untouched). Liga MX neutralises
the World-Cup-only knobs (host advantage, WC goal inflation, the
international-blowout mismatch ramp, the J3 group-qualification incentive) via
``dataclasses.replace`` on top of those defaults. The remaining Liga MX numbers
(goal environment, draw gates, mismatch) are PLACEHOLDERS to be fit in Fase 1
against real Liga MX history — see the inline TODOs.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from wc_predictor.config import DATA_DIR, ModelConfig, QuinielaRules


@dataclass(frozen=True)
class LeagueProfile:
    """Everything that differs between tournaments for the same engine.

    Attributes
    ----------
    key
        Stable slug used in paths / CLI (``wc2026``, ``ligamx_apertura``).
    display_name
        Human label for report headers.
    thesportsdb_league_id
        League id shared with the webapp so ``match_id`` and team names stay
        consistent (WC = 4429, Liga MX = 4350).
    season
        Season/edition label as TheSportsDB spells it.
    data_dirname
        Sub-directory of ``data/`` holding this league's versioned truth files.
    elo_source
        ``"international"`` (replay over martj42) or ``"replay_ligamx"`` (Elo
        computed locally by replay over the Liga MX match history). clubelo.com
        was the original plan but is HTTP-only and unreachable behind the HTTPS
        proxy, so Liga MX Elo is self-computed from the ingested history instead
        — cleaner and dependency-free. Selects which ratings ingest is used.
    neutral_venues
        World Cup fixtures are at neutral venues except for the host nations, so
        the "home" advantage is derived from the venue country (``host_only``).
        Liga MX always has a real home team, so localía applies per team on
        every match (``per_team``). ``home_advantage_mode`` names the strategy.
    home_advantage_mode
        ``"host_only"`` | ``"per_team"`` (see ``neutral_venues``).
    odds_sport_key
        The Odds API sport key (``soccer_fifa_world_cup`` /
        ``soccer_mexico_ligamx``).
    round_tokens
        Valid ``--round`` values for this league, documented for the CLI. WC
        uses group/knockout tokens; Liga MX uses ``j1``..``j17`` + liguilla.
    two_legged_rounds
        Rounds decided over two legs on aggregate (Liga MX liguilla). Empty for
        the WC (single-match knockouts). Drives the aggregate-scoreline logic
        the Fase 1 refactor adds.
    model
        The calibrated :class:`ModelConfig` for this league.
    rules
        The pool scoring rules (:class:`QuinielaRules`).
    """

    key: str
    display_name: str
    thesportsdb_league_id: int
    season: str
    data_dirname: str
    elo_source: str
    neutral_venues: bool
    home_advantage_mode: str
    odds_sport_key: str
    round_tokens: tuple[str, ...]
    two_legged_rounds: tuple[str, ...]
    model: ModelConfig = field(default_factory=ModelConfig)
    rules: QuinielaRules = field(default_factory=QuinielaRules)

    @property
    def data_dir(self) -> Path:
        return DATA_DIR / self.data_dirname


# --- World Cup 2026 -----------------------------------------------------------
# The status quo, expressed as a profile. Uses the ModelConfig / QuinielaRules
# defaults verbatim so behaviour is byte-for-byte identical to today.
WC2026_PROFILE = LeagueProfile(
    key="wc2026",
    display_name="Mundial FIFA 2026",
    thesportsdb_league_id=4429,
    season="2026",
    data_dirname="wc2026",
    elo_source="international",
    neutral_venues=True,
    home_advantage_mode="host_only",
    odds_sport_key="soccer_fifa_world_cup",
    round_tokens=(
        "all", "group_stage", "j1", "j2", "j3",
        "round_of_32", "round_of_16", "quarter_final",
        "semi_final", "third_place", "final",
    ),
    two_legged_rounds=(),
    model=ModelConfig(),
    rules=QuinielaRules(),
)


# --- Liga MX Apertura ---------------------------------------------------------
# Neutralise the World-Cup-only knobs so they can't silently distort Liga MX
# lambdas, then leave the genuinely-shared knobs (altitude, draw gates, ridge,
# grid) at their defaults pending the Fase 1 re-fit against Liga MX history.
_LIGAMX_MODEL = replace(
    ModelConfig(),
    # No neutral-venue host boost: localía is per-team in Liga MX and enters via
    # the Poisson+DC gamma, not a host multiplier.
    host_advantage_usa=1.0,
    host_advantage_mexico=1.0,
    host_advantage_canada=1.0,
    # WC group-stage goal inflation (~2.81 g/match) does NOT apply — Liga MX
    # runs ~2.53 g/match (legacy calibration doc). The Fase 1 fit targets real
    # Liga MX goals directly, so start neutral and re-measure goal_env_mult then.
    wc_lambda_inflation=1.0,
    # TODO(fase1): re-fit goal_env_mult against Liga MX (target ~2.53 g/match,
    # 57/43 home/away split, ~13% 0-0). 1.0 = neutral placeholder.
    goal_env_mult=1.0,
    # The international-blowout mismatch ramp was calibrated on WC 2018/2022
    # thrashings (Spain 7-0 Costa Rica, …); intra-league gaps in Liga MX are far
    # smaller. Push the threshold out so it effectively no-ops until re-fit.
    # TODO(fase1): recalibrate or drop mismatch for a single-league setting.
    mismatch_ratio_threshold=6.0,
    mismatch_strong_boost=1.0,
    mismatch_weak_damp=1.0,
    # J3 group-qualification incentive is a World-Cup group-format concept; Liga
    # MX regular-season jornadas have no group table, so this path is inert.
    qual_rotation_lambda_mult=1.0,
    # Altitude matters MORE in Liga MX than the WC (Toluca 2660 m, Azteca/CDMX
    # 2240 m, Pachuca 2400 m). Keep the penalty active; verify magnitude in fase1.
    altitude_penalty_per_1000m=0.04,
    # --- Fase 1b.2 re-fit against Liga MX history (ligamx_backtest walk-forward) ---
    # goal_env_mult stays 1.0: the WC default (1.20) corrected a group-stage
    # under-count, but the Liga MX fit trains on the league's OWN goals — measured
    # 2.84 g/match over 1028 matches (2023-2026) and the fit predicts ~2.86, so it
    # self-calibrates. No inflation needed (an extra multiplier here overshot).
    #
    # Home advantage and blend weights were tuned on the walk-forward backtest
    # (687 out-of-sample matches, rho profiled per week, baselines scored on the
    # SAME matches). Liga MX localía is strong (~47% home wins, plus altitude),
    # so a higher Elo home bonus and MORE Elo weight both help:
    #   default (hb80, 70/30 Poisson/Elo):  434 pts · 70 exactos · +9.0% vs 1-0
    #   tuned   (hb100, 60/40):              441 pts · 72 exactos · +10.8% vs 1-0
    # The gain replicated on both disjoint yearly segments (not a single-window
    # fluke). Re-run `python -m wc_predictor.pipeline.ligamx_backtest` after new
    # jornadas to confirm these still hold.
    elo_home_bonus=100.0,
    blend_poisson_weight=0.60,
    blend_elo_weight=0.40,
    # --- Liguilla calibration, measured on Liga MX playoff matches --------------
    # The `ko_*` knobs were calibrated on World Cup knockouts; re-measuring them
    # on 99 Liga MX playoff matches (2023-2026, isolated once the ingest started
    # keeping TheSportsDB's round) says the same physics applies here:
    #   goals/match   2.576 playoff vs 2.860 regular  → ratio 0.90
    #   draws at 90'  32.3% playoff vs 23.9% regular
    # So the goal damp stays at the WC's 0.90 (now on Liga MX evidence, not
    # inherited), and the draw gates stay lower for the liguilla — a third of
    # playoff legs finish level, which the regular-season gate cannot express.
    ko_goal_env_ratio=0.90,
    # Recency half-life: club rosters turn over every window, so a shorter decay
    # (365/540d) was the intuitive bet — but the walk-forward backtest says
    # otherwise. Swept {365, 540, 730, 1095}d on the same harness: 730d wins
    # (224 pts / 34 exactos / +14.9% vs 1-0) over 365/540/1095 (all 222 / +13.8%).
    # With only ~1000 matches of club history the extra data outweighs the
    # staleness, so keep the 730d default. Re-sweep when more seasons accumulate.
    half_life_days=730,
)

# Pool rules VERIFIED against the webapp (samuelramram/quinielacartoimagen), not
# copied from the World Cup:
#   - scoring: `points_awarded = 2` on an exact score, 1 on a correct 1X2,
#     mutually exclusive — same as the WC, confirmed in the leaderboard RPCs.
#   - tiebreak: `get_leaderboard` sorts `total_points DESC, exact_results DESC`,
#     so exactos are a real tiebreaker (already the engine's default).
#   - money: $200 entry + $50 per jornada played; the pot pays 80% to 1st and
#     20% to 2nd (`src/lib/ligaMxPricing.ts`). Second place paying a quarter of
#     first is what makes the optimizer's objective expected prize, not P(1st).
#   - the competition starts at Jornada 3 (migration
#     `20260721160000_ligamx_per_jornada_payments.sql` zeroes J1/J2), which is
#     why `ingest.ligamx_pool --start-round 3` is the documented default.
_LIGAMX_RULES = QuinielaRules(
    prize_shares=(0.8, 0.2),
    # Private pool, ~10-20 players (user-confirmed). Only used to size the
    # synthetic field BEFORE the first pool_standings.json export lands; after
    # that the real opponent count from the leaderboard wins.
    pool_participants=15,
    pool_buyin_mxn=200,
)

LIGAMX_APERTURA_PROFILE = LeagueProfile(
    key="ligamx_apertura",
    display_name="Liga MX — Apertura",
    thesportsdb_league_id=4350,
    season="2026-2027",
    data_dirname="ligamx",
    elo_source="replay_ligamx",
    neutral_venues=False,
    home_advantage_mode="per_team",
    odds_sport_key="soccer_mexico_ligamx",
    round_tokens=(
        "all",
        # 17 regular-season jornadas
        *(f"j{n}" for n in range(1, 18)),
        # Liguilla (Apertura 2026): the Play-In was scrapped — top-8 go straight
        # to two-legged quarters (1-8, 2-7, 3-6, 4-5), semis re-seeded by the
        # general table, then the final. All aggregate. See model/liguilla.py.
        "quarter_final", "semi_final", "final",
    ),
    # Every liguilla series is two-legged on aggregate.
    two_legged_rounds=("quarter_final", "semi_final", "final"),
    model=_LIGAMX_MODEL,
    rules=_LIGAMX_RULES,
)


PROFILES: dict[str, LeagueProfile] = {
    WC2026_PROFILE.key: WC2026_PROFILE,
    LIGAMX_APERTURA_PROFILE.key: LIGAMX_APERTURA_PROFILE,
}

DEFAULT_PROFILE_KEY = "wc2026"


def get_profile(key: str | None = None) -> LeagueProfile:
    """Return a profile by key (defaults to the World Cup — the current pipeline)."""
    k = key or DEFAULT_PROFILE_KEY
    try:
        return PROFILES[k]
    except KeyError:
        raise SystemExit(
            f"Unknown league profile {k!r}. Available: {', '.join(sorted(PROFILES))}."
        )
