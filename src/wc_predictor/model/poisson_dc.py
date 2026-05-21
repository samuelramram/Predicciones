"""Bivariate Poisson with Dixon-Coles correction, fit by MLE on intl match history.

Model:

    log(lambda_home) = mu + gamma * home_flag + attack[home] - defense[away]
    log(lambda_away) = mu                     + attack[away] - defense[home]

    home_flag = 1 if the match is not at a neutral venue, else 0.

    P(home_score=h, away_score=a | lambdas)
      = poisson(h | lambda_h) * poisson(a | lambda_a) * dc_correction(h, a, lh, la, rho)

Estimation:

- attack and defense are per-team latents. Identifiability comes from a mild L2
  ridge (acts as a zero-centered prior) plus an explicit sum-to-zero projection
  on attack at the end. Sufficient for prediction; we don't claim valid std
  errors here.
- rho is fixed at the Liga MX value (-0.10) by default — backtesting can sweep it
  later if calibration is off.
- Matches are recency-weighted with exponential half-life (default 730 days ≈ 2y),
  so 2014 friendlies count but recent qualifiers dominate.
- Optimizer: scipy.optimize.minimize with L-BFGS-B and an analytic-style numerical
  gradient (scipy default). 500 params, ~12k matches → converges in seconds.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path

import numpy as np

from wc_predictor.config import ModelConfig
from wc_predictor.scoring.quiniela import dc_correction


@dataclass
class TeamStrength:
    team: str
    attack: float
    defense: float
    n_matches: int


@dataclass
class FitResult:
    mu: float
    gamma: float
    rho: float
    strengths: dict[str, TeamStrength]
    n_matches: int
    n_teams: int
    half_life_days: int
    ridge_lambda: float
    converged: bool
    final_neg_log_lik: float

    def to_dict(self) -> dict:
        return {
            "mu": self.mu,
            "gamma": self.gamma,
            "rho": self.rho,
            "n_matches": self.n_matches,
            "n_teams": self.n_teams,
            "half_life_days": self.half_life_days,
            "ridge_lambda": self.ridge_lambda,
            "converged": self.converged,
            "final_neg_log_lik": self.final_neg_log_lik,
            "teams": {
                t: {"attack": round(s.attack, 4), "defense": round(s.defense, 4), "n_matches": s.n_matches}
                for t, s in sorted(self.strengths.items())
            },
        }


def _build_design(rows: list[dict], as_of: date, half_life_days: int) -> dict:
    """Vectorize matches: encode teams as integer indices, build weight array."""
    teams = sorted({r["home"] for r in rows} | {r["away"] for r in rows})
    idx = {t: i for i, t in enumerate(teams)}

    n = len(rows)
    home_idx = np.empty(n, dtype=np.int32)
    away_idx = np.empty(n, dtype=np.int32)
    home_goals = np.empty(n, dtype=np.float64)
    away_goals = np.empty(n, dtype=np.float64)
    home_flag = np.empty(n, dtype=np.float64)
    weights = np.empty(n, dtype=np.float64)

    decay = np.log(2) / half_life_days
    for i, r in enumerate(rows):
        home_idx[i] = idx[r["home"]]
        away_idx[i] = idx[r["away"]]
        home_goals[i] = r["home_score"]
        away_goals[i] = r["away_score"]
        home_flag[i] = 0.0 if r["neutral"] else 1.0
        d = datetime.fromisoformat(r["date"]).date()
        age_days = (as_of - d).days
        weights[i] = np.exp(-decay * max(age_days, 0))

    # Count training matches per team (for diagnostics)
    counts = np.zeros(len(teams), dtype=np.int64)
    np.add.at(counts, home_idx, 1)
    np.add.at(counts, away_idx, 1)

    return {
        "teams": teams,
        "idx": idx,
        "home_idx": home_idx,
        "away_idx": away_idx,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "home_flag": home_flag,
        "weights": weights,
        "match_count": counts,
    }


def _unpack_params(theta: np.ndarray, n_teams: int) -> tuple[float, float, np.ndarray, np.ndarray]:
    mu = theta[0]
    gamma = theta[1]
    attack = theta[2 : 2 + n_teams]
    defense = theta[2 + n_teams : 2 + 2 * n_teams]
    return mu, gamma, attack, defense


def _neg_log_lik(theta: np.ndarray, design: dict, rho: float, ridge_lambda: float) -> float:
    n_teams = len(design["teams"])
    mu, gamma, attack, defense = _unpack_params(theta, n_teams)

    home_idx = design["home_idx"]
    away_idx = design["away_idx"]
    h = design["home_goals"]
    a = design["away_goals"]
    w = design["weights"]
    hf = design["home_flag"]

    log_lh = mu + gamma * hf + attack[home_idx] - defense[away_idx]
    log_la = mu + attack[away_idx] - defense[home_idx]

    lh = np.exp(log_lh)
    la = np.exp(log_la)

    # Poisson log-likelihood (drop factorial constant — doesn't affect optimum)
    ll_match = h * log_lh - lh + a * log_la - la

    # Dixon-Coles correction for low scores. Vectorized for h, a in {0, 1}.
    mask_00 = (h == 0) & (a == 0)
    mask_10 = (h == 1) & (a == 0)
    mask_01 = (h == 0) & (a == 1)
    mask_11 = (h == 1) & (a == 1)

    dc = np.ones_like(ll_match)
    dc[mask_00] = np.maximum(1.0 - lh[mask_00] * la[mask_00] * rho, 1e-12)
    dc[mask_10] = np.maximum(1.0 + la[mask_10] * rho, 1e-12)
    dc[mask_01] = np.maximum(1.0 + lh[mask_01] * rho, 1e-12)
    dc[mask_11] = np.maximum(1.0 - rho, 1e-12)
    ll_match = ll_match + np.log(dc)

    weighted_ll = float(np.sum(w * ll_match))

    # Ridge penalty (zero-mean prior on team latents).
    penalty = ridge_lambda * float(np.sum(attack**2) + np.sum(defense**2))

    return -(weighted_ll - penalty)


def fit_dc_model(
    rows: list[dict],
    cfg: ModelConfig,
    as_of: date | None = None,
    half_life_days: int = 730,
    ridge_lambda: float = 1.0,
    rho: float | None = None,
    max_iter: int = 500,
    verbose: bool = True,
) -> FitResult:
    """Fit attack/defense/mu/gamma by weighted MLE with L2 ridge.

    Args:
        rows: dicts with date, home, away, home_score, away_score, neutral.
        cfg: ModelConfig (uses cfg.dc_rho if `rho` arg is None).
        as_of: reference date for recency weights. Default today (UTC).
        half_life_days: exponential decay half-life for match weights.
        ridge_lambda: L2 penalty on attack/defense (zero-mean prior).
        rho: Dixon-Coles rho. Default cfg.dc_rho.
        max_iter: optimizer iteration cap.
    """
    from scipy.optimize import minimize

    as_of = as_of or datetime.utcnow().date()
    rho_eff = cfg.dc_rho if rho is None else rho

    design = _build_design(rows, as_of, half_life_days)
    n_teams = len(design["teams"])
    if verbose:
        print(f"  fit: {len(rows)} matches, {n_teams} teams, half-life {half_life_days}d, "
              f"ridge={ridge_lambda}, rho={rho_eff}")

    # Initial params: mu = log(1.4) (league-avg home goals), gamma = 0.3, attack/defense = 0
    theta0 = np.zeros(2 + 2 * n_teams)
    theta0[0] = np.log(1.4)
    theta0[1] = 0.30

    result = minimize(
        _neg_log_lik,
        theta0,
        args=(design, rho_eff, ridge_lambda),
        method="L-BFGS-B",
        options={"maxiter": max_iter, "gtol": 1e-6},
    )
    if verbose:
        print(f"  optimizer: success={result.success}, iter={result.nit}, nfev={result.nfev}, nll={result.fun:.2f}")

    mu, gamma, attack, defense = _unpack_params(result.x, n_teams)

    # Re-center attack so sum=0 (push the mean into mu for interpretability).
    mean_att = float(np.mean(attack))
    attack = attack - mean_att
    mu = mu + mean_att
    # Same for defense (note: defense enters with NEGATIVE sign in lambda_home and lambda_away
    # similarly, so we shift to keep lambdas invariant).
    mean_def = float(np.mean(defense))
    defense = defense - mean_def
    mu = mu - mean_def  # because larger defense → smaller lambda; centering pushes the mean into mu with opposite sign

    strengths = {
        t: TeamStrength(
            team=t,
            attack=float(attack[i]),
            defense=float(defense[i]),
            n_matches=int(design["match_count"][i]),
        )
        for i, t in enumerate(design["teams"])
    }

    return FitResult(
        mu=float(mu),
        gamma=float(gamma),
        rho=float(rho_eff),
        strengths=strengths,
        n_matches=len(rows),
        n_teams=n_teams,
        half_life_days=half_life_days,
        ridge_lambda=ridge_lambda,
        converged=bool(result.success),
        final_neg_log_lik=float(result.fun),
    )


def predict_lambdas(
    home: TeamStrength,
    away: TeamStrength,
    mu: float,
    gamma: float,
    host: str | None = None,
) -> tuple[float, float]:
    """Convert fitted strengths into (lambda_home, lambda_away) for one match.

    The `host` arg captures the asymmetric WC case where, by openfootball's
    labeling convention, the host nation can appear as the AWAY column (e.g.
    "Czech Republic vs Mexico" at Estadio Azteca — Mexico is the host).
    The gamma boost is applied to whichever side is actually on home soil.

    host values:
        None    → fully neutral venue (no gamma boost)
        "home"  → home team is at their stadium (gamma → lambda_home)
        "away"  → away team is at their stadium (gamma → lambda_away)
    """
    home_boost = gamma if host == "home" else 0.0
    away_boost = gamma if host == "away" else 0.0
    lh = float(np.exp(mu + home_boost + home.attack - away.defense))
    la = float(np.exp(mu + away_boost + away.attack - home.defense))
    return lh, la


def save_fit(fit: FitResult, dst: Path, as_of: str | None = None) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    payload = fit.to_dict()
    if as_of:
        payload["as_of"] = as_of
    with dst.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def load_fit(src: Path) -> FitResult:
    with src.open(encoding="utf-8") as f:
        d = json.load(f)
    strengths = {
        t: TeamStrength(t, s["attack"], s["defense"], s["n_matches"])
        for t, s in d["teams"].items()
    }
    return FitResult(
        mu=d["mu"], gamma=d["gamma"], rho=d["rho"],
        strengths=strengths,
        n_matches=d["n_matches"], n_teams=d["n_teams"],
        half_life_days=d["half_life_days"], ridge_lambda=d["ridge_lambda"],
        converged=d["converged"], final_neg_log_lik=d["final_neg_log_lik"],
    )
