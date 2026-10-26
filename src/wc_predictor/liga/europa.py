"""Modelo y bots para las ligas top de Europa (mismo motor que Liga MX).

Un ajuste Poisson·Dixon-Coles + Elo POR LIGA (los equipos de ligas distintas casi
no se cruzan, así que un modelo conjunto no aprendería nada extra), sin altitud
ni knobs de Mundial. Cada bot sale de la misma matriz de marcadores y con ella
"apuesta" en todos los mercados de :mod:`wc_predictor.liga.markets`:

- ``estadistico``: Poisson + Elo, no ve el mercado.
- ``calibrado``: además mezcla el mercado (1X2 y Over 2.5) con ``blend_odds_weight``.
- ``borrego``: el mercado puro (peso 1.0); la forma del marcador la pone Poisson.

"Top-3" de una liga = los 3 mejores Elo entre los equipos de la temporada; el
archivo ``data/europa/top_override.json`` puede fijarlos a mano.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace

import numpy as np

from wc_predictor.config import DATA_DIR, ModelConfig
from wc_predictor.leagues import LIGAMX_APERTURA_PROFILE
from wc_predictor.liga.markets import logpool_binary, p_btts, p_over
from wc_predictor.model.blend import blend_three_sources
from wc_predictor.model.implied import _probs_np, anchor_lambdas, implied_lambdas  # noqa: F401
from wc_predictor.model.poisson_dc import predict_lambdas
from wc_predictor.ratings.elo import elo_to_1x2_probs
from wc_predictor.scoring.quiniela import build_score_matrix, optimize_pick_from_cells

TOP_OVERRIDE = DATA_DIR / "europa" / "top_override.json"

# Liga MX knobs with the Liga-MX-specific tuning undone (altitude, its strong
# localía): Elo home bonus and the Poisson:Elo split go back to the defaults.
#
# Market weight 0.9, measured (europa_backtest, 3,736 matches 2024-07 → 2026-09,
# paired vs 0.55): Brier 1X2 improves monotonically with market weight —
# 0.55 → 0.5797, 0.75 → 0.5777 (z=−5.0), 0.9 → 0.5767 (z=−4.3), pure market
# 0.5763. European closing lines are efficient; the model mostly adds noise.
# 0.9 keeps a sliver of model for the score shape and the pool picks.
_BASE = ModelConfig()
EUROPA_MODEL = replace(
    LIGAMX_APERTURA_PROFILE.model,
    altitude_penalty_per_1000m=0.0,
    elo_home_bonus=_BASE.elo_home_bonus,
    blend_poisson_weight=_BASE.blend_poisson_weight,
    blend_elo_weight=_BASE.blend_elo_weight,
    blend_odds_weight=0.9,
)
RULES = LIGAMX_APERTURA_PROFILE.rules  # same pool scoring: 2 exacto / 1 resultado

# xG weight in the Poisson target (Understat): target = 0.25·goals + 0.75·xG.
# Measured on the walk-forward backtest with PRE-match odds (3,736 matches,
# 2024-07 → 2026-09, paired vs goals-only): the market-free bot improves
# Brier 1X2 0.5891 → 0.5865 (z=−3.3), O/U 0.2435 → 0.2409 (z=−2.9), BTTS
# 0.2477 → 0.2456 (z=−2.6); 0.75 beats 0.5 on 1X2 (z=−2.0); pure xG (1.0) adds
# nothing more. The market-following bots don't move (the line already prices xG).
XG_WEIGHT = 0.75


@dataclass(frozen=True)
class BotView:
    """Everything a bot believes about one match."""
    cells: list
    probs: tuple[float, float, float]
    p_over25: float
    p_btts: float
    pick_1x2: str
    pick_exact: str


def _weights(mcfg, odds_w: float) -> tuple[float, float, float]:
    share = mcfg.blend_poisson_weight / (mcfg.blend_poisson_weight + mcfg.blend_elo_weight)
    rem = 1.0 - odds_w
    return rem * share, rem * (1.0 - share), odds_w


def bot_view(home: str, away: str, fit, elos: dict[str, float], mcfg,
             market_1x2: tuple[float, float, float] | None = None,
             market_over25: float | None = None, odds_w: float = 0.0,
             anchor: bool = True) -> BotView | None:
    """One bot's view. ``odds_w=0`` → estadistico; ``blend_odds_weight`` →
    calibrado; ``1.0`` → borrego. ``anchor=False`` keeps the model's goal rates
    (A/B of the totals anchoring). Returns None if a team has no strengths."""
    if home not in fit.strengths or away not in fit.strengths:
        return None
    lh, la = predict_lambdas(fit.strengths[home], fit.strengths[away], fit.mu, fit.gamma,
                             host="home")
    elo_p = elo_to_1x2_probs(elos.get(home, 1500.0), elos.get(away, 1500.0), mcfg.elo_home_bonus)
    use_mkt = market_1x2 is not None and odds_w > 0
    if use_mkt and anchor and market_over25 is not None:
        # Pull the goal rates toward the market's (geometric blend), so the whole
        # score grid — not only the 1X2 marginals — reflects the market.
        lh, la = anchor_lambdas(lh, la, market_1x2, market_over25, mcfg.dc_rho, odds_w)
    pcells, pp1, ppx, pp2, pmass, pmax = build_score_matrix(lh, la, mcfg)
    w_po, w_el, w_od = _weights(mcfg, odds_w if use_mkt else 0.0)
    if odds_w >= 1.0 and use_mkt:
        w_po = w_el = 1e-9  # pure market marginals; the Poisson grid only shapes the score
    cells, p1, px, p2 = blend_three_sources(pcells, (pp1, ppx, pp2), elo_p,
                                            market_1x2 if use_mkt else None,
                                            w_poisson=w_po, w_elo=w_el, w_odds=w_od)
    po = p_over(cells, 2.5)
    if market_over25 is not None and odds_w > 0:
        po = market_over25 if odds_w >= 1.0 else logpool_binary(
            [po, market_over25], [1.0 - odds_w, odds_w])
    pick = optimize_pick_from_cells(cells, p1, px, p2, pmass, pmax, RULES, mcfg)
    return BotView(cells=cells, probs=(p1, px, p2), p_over25=po, p_btts=p_btts(cells),
                   pick_1x2=pick.pick_1x2, pick_exact=pick.pick_exact)


def market_view(market_1x2: tuple[float, float, float], market_over25: float | None,
                mcfg) -> BotView:
    """A bot's view of a match the per-league model can't price: a UEFA cup tie
    between clubs of different leagues (the league fits share no scale). The goal
    rates are implied from the market (1X2 + Over 2.5; without a total, a typical
    cup total of 2.75 goals → P(Over 2.5) ≈ 0.53), and the 1X2 is the market's."""
    target_over = market_over25 if market_over25 is not None else 0.53
    lh, la = implied_lambdas(market_1x2[0], market_1x2[2], target_over, mcfg.dc_rho)
    pcells, pp1, ppx, pp2, pmass, pmax = build_score_matrix(lh, la, mcfg)
    cells, p1, px, p2 = blend_three_sources(pcells, (pp1, ppx, pp2), (pp1, ppx, pp2), market_1x2,
                                            w_poisson=1e-9, w_elo=1e-9, w_odds=1.0)
    pick = optimize_pick_from_cells(cells, p1, px, p2, pmass, pmax, RULES, mcfg)
    return BotView(cells=cells, probs=(p1, px, p2),
                   p_over25=market_over25 if market_over25 is not None else p_over(cells, 2.5),
                   p_btts=p_btts(cells), pick_1x2=pick.pick_1x2, pick_exact=pick.pick_exact)


# The Odds API spells clubs out; Football-Data abbreviates. Pairs the fuzzy match
# can't settle on its own ("Inter Milan" looks as much like Milan as like Inter).
CUP_ALIASES = {
    "Inter Milan": "Inter", "AC Milan": "Milan", "AS Roma": "Roma", "Atalanta BC": "Atalanta",
    "Atlético Madrid": "Ath Madrid", "Athletic Bilbao": "Ath Bilbao", "Real Sociedad": "Sociedad",
    "Real Betis": "Betis", "Espanyol": "Espanol", "Paris Saint Germain": "Paris SG",
    "RC Lens": "Lens", "Olympique Marseille": "Marseille", "Olympique Lyonnais": "Lyon",
    "AS Monaco": "Monaco", "OGC Nice": "Nice", "Manchester City": "Man City",
    "Manchester United": "Man United", "Newcastle United": "Newcastle",
    "Tottenham Hotspur": "Tottenham", "Nottingham Forest": "Nott'm Forest",
    "Borussia Dortmund": "Dortmund", "Bayer Leverkusen": "Leverkusen",
    "Eintracht Frankfurt": "Ein Frankfurt", "VfB Stuttgart": "Stuttgart",
    "SC Freiburg": "Freiburg", "TSG Hoffenheim": "Hoffenheim", "1. FC Union Berlin": "Union Berlin",
    "Borussia Monchengladbach": "M'gladbach", "VfL Wolfsburg": "Wolfsburg",
}


def cup_team_name(name: str, known: set[str]) -> str:
    """Odds API club name → the Football-Data name of the same club, when it plays
    in one of the 5 leagues (``known``); otherwise the name as given (Benfica,
    PSV…). The fuzzy fallback compares whole folded names (≥0.85): the prefix-
    tolerant matcher of the results feed is too loose here ("LASK" ⊂ "La Coruna")."""
    from difflib import SequenceMatcher

    from wc_predictor.ingest.liga_results import fold
    if name in known:
        return name
    alias = CUP_ALIASES.get(name)
    if alias in known:
        return alias
    f = " ".join(fold(name))
    scored = sorted(((SequenceMatcher(None, f, " ".join(fold(k))).ratio(), k) for k in known),
                    reverse=True)
    if scored and scored[0][0] >= 0.85 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.05):
        return scored[0][1]
    return name


def top_teams(elos: dict[str, float], season_teams: set[str], n: int = 3,
              league: str | None = None, override: dict | None = None) -> list[str]:
    """Top-n by Elo among this season's teams, unless the override pins them."""
    if override and league and override.get(league):
        return list(override[league])
    ranked = sorted(season_teams, key=lambda t: elos.get(t, 1500.0), reverse=True)
    return ranked[:n]


def load_override() -> dict:
    if TOP_OVERRIDE.exists():
        return json.loads(TOP_OVERRIDE.read_text(encoding="utf-8"))
    return {}


# --------------------------------------------------------------- model variants
# Experiments measured in europa_backtest (see docs/europa_liga.md). Each one is
# opt-in so the production path only changes once the backtest says so.

def season_turnover(season_teams: dict[str, set[str]]) -> dict[str, tuple[set[str], set[str]]]:
    """season → (promoted newcomers, relegated leavers) vs the previous season."""
    order = sorted(season_teams)
    out = {}
    for prev, cur in zip(order, order[1:]):
        out[cur] = (season_teams[cur] - season_teams[prev], season_teams[prev] - season_teams[cur])
    return out


def replay_promoted(rows: list[dict], mcfg, turnover: dict) -> dict[str, float]:
    """Elo replay where each promoted club starts its season at the average
    rating of the clubs that went down (instead of 1500 = league average, or a
    stale rating from years ago)."""
    from wc_predictor.ratings.elo import EloMatch, update_elo
    elos: dict[str, float] = {}
    season = None
    for r in rows:
        if r["season"] != season:
            season = r["season"]
            new, gone = turnover.get(season, (set(), set()))
            gone_r = [elos[t] for t in gone if t in elos]
            if new and gone_r:
                start = sum(gone_r) / len(gone_r)
                for t in new:
                    elos[t] = start
        update_elo(elos, EloMatch(r["home"], r["away"], int(r["home_score"]), int(r["away_score"]),
                                  bool(r["neutral"]), r["tournament"]), mcfg)
    return elos


def promoted_prior(fit, turnover: dict, season: str) -> dict[str, tuple[float, float]] | None:
    """Ridge center for this season's newcomers = mean (attack, defense) of the
    clubs they replaced, taken from an earlier fit that still has them."""
    if fit is None:
        return None
    new, gone = turnover.get(season, (set(), set()))
    g = [fit.strengths[t] for t in gone if t in fit.strengths]
    if not new or not g:
        return None
    att = sum(s.attack for s in g) / len(g)
    dfn = sum(s.defense for s in g) / len(g)
    return {t: (att, dfn) for t in new}


def with_xg(rows: list[dict], xg_idx: dict, xg_weight: float) -> list[dict]:
    """Copy of rows whose Poisson target mixes goals and xG:
    target = (1 − w)·goals + w·xG. Rows without xG keep their goals."""
    from wc_predictor.ingest.understat_xg import lookup
    out = []
    for r in rows:
        x = lookup(xg_idx, r["league"], r["home"], r["away"], r["date"])
        if x is None:
            out.append(r)
            continue
        out.append({**r,
                    "home_target": (1 - xg_weight) * r["home_score"] + xg_weight * x["xg_home"],
                    "away_target": (1 - xg_weight) * r["away_score"] + xg_weight * x["xg_away"]})
    return out
