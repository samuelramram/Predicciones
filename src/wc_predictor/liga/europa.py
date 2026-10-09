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


def _probs_np(lh: float, la: float, rho: float, n: int = 11) -> tuple[float, float, float, float]:
    """(p1, px, p2, p_over2.5) of a Poisson·DC grid, vectorized (fast inner loop)."""
    from math import exp, lgamma, log
    k = np.arange(n)
    lf = np.array([lgamma(i + 1) for i in range(n)])
    ph = np.exp(k * log(lh) - lh - lf)
    pa = np.exp(k * log(la) - la - lf)
    m = np.outer(ph, pa)
    m[0, 0] *= 1 - lh * la * rho
    m[0, 1] *= 1 + lh * rho
    m[1, 0] *= 1 + la * rho
    m[1, 1] *= 1 - rho
    m /= m.sum()
    tot = k[:, None] + k[None, :]
    return (float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum()),
            float(m[tot > 2.5].sum()))


def implied_lambdas(p1: float, p2: float, p_over25: float, rho: float,
                    start: tuple[float, float] = (1.4, 1.1)) -> tuple[float, float]:
    """Goal rates whose Poisson·DC grid best reproduces the market's home/away
    win and Over 2.5 probabilities. 1X2 alone can't tell a 1-0 favourite from a
    4-1 one; the total pins the goal environment, so the handicap distribution
    of the market-following bots stays consistent with the market's AH line."""
    from scipy.optimize import minimize

    def loss(x):
        q1, _, q2, qo = _probs_np(exp(x[0]), exp(x[1]), rho)
        return (q1 - p1) ** 2 + (q2 - p2) ** 2 + (qo - p_over25) ** 2

    from math import exp, log
    r = minimize(loss, [log(start[0]), log(start[1])], method="Nelder-Mead",
                 options={"xatol": 1e-4, "fatol": 1e-9, "maxiter": 400})
    return exp(r.x[0]), exp(r.x[1])


def bot_view(home: str, away: str, fit, elos: dict[str, float], mcfg,
             market_1x2: tuple[float, float, float] | None = None,
             market_over25: float | None = None, odds_w: float = 0.0) -> BotView | None:
    """One bot's view. ``odds_w=0`` → estadistico; ``blend_odds_weight`` →
    calibrado; ``1.0`` → borrego. Returns None if a team has no strengths."""
    if home not in fit.strengths or away not in fit.strengths:
        return None
    lh, la = predict_lambdas(fit.strengths[home], fit.strengths[away], fit.mu, fit.gamma,
                             host="home")
    elo_p = elo_to_1x2_probs(elos.get(home, 1500.0), elos.get(away, 1500.0), mcfg.elo_home_bonus)
    use_mkt = market_1x2 is not None and odds_w > 0
    if use_mkt and market_over25 is not None:
        # Pull the goal rates toward the market's (geometric blend), so the whole
        # score grid — not only the 1X2 marginals — reflects the market.
        mh, ma = implied_lambdas(market_1x2[0], market_1x2[2], market_over25, mcfg.dc_rho,
                                 start=(lh, la))
        w = min(odds_w, 1.0)
        lh, la = lh ** (1 - w) * mh ** w, la ** (1 - w) * ma ** w
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
