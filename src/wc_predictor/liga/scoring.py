"""Calificador de la liga: puntos de quiniela, calibración y bankroll ficticio.

Tres marcadores, porque miden cosas distintas:

- **Puntos de quiniela** — lo divertido y lo que paga el pool. Usa
  ``scoring.quiniela.score_actual`` (la función de verdad del pool; nunca se
  reimplementa la regla).
- **Brier y log-loss** — qué tan bien calibradas están las probabilidades 1X2.
  Brier aquí es la SUMA sobre las 3 clases: uniforme (1/3, 1/3, 1/3) = 0.667,
  perfecto = 0. (Ojo: algunas fuentes reportan el PROMEDIO por clase, que es esta
  cifra entre 3 — por eso un "0.23" puede ser casi el azar en esa otra escala.
  Comparar dos Brier exige la misma escala.)
- **Bankroll ficticio** — 1,000 Carto-pesos por bot, apuesta plana contra el
  precio PROMEDIO de cierre cuando el bot cree tener valor. Mide si la "ventaja"
  que el bot dice ver sobrevive a la línea real. Nunca es dinero real.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from wc_predictor.scoring.quiniela import score_actual

OUTCOMES = ("1", "X", "2")
UNIFORM_BRIER = 2.0 / 3.0


def outcome_of(home_score: int, away_score: int) -> str:
    return "X" if home_score == away_score else ("1" if home_score > away_score else "2")


def brier(probs: tuple[float, float, float], actual: str) -> float:
    """Multiclass Brier (sum over 1/X/2). 0 = perfect, 0.667 = uniform."""
    return sum((p - (1.0 if o == actual else 0.0)) ** 2 for p, o in zip(probs, OUTCOMES))


def log_loss(probs: tuple[float, float, float], actual: str, eps: float = 1e-9) -> float:
    return -math.log(max(probs[OUTCOMES.index(actual)], eps))


@dataclass
class Bankroll:
    """Apuesta plana ficticia: ``stake`` unidades al resultado de mayor valor
    esperado (p·precio − 1) cuando supera ``min_edge``; una apuesta por partido."""
    start: float = 1000.0
    stake: float = 10.0
    min_edge: float = 0.0
    balance: float = field(init=False)
    n_bets: int = 0
    staked: float = 0.0
    wins: int = 0

    def __post_init__(self) -> None:
        self.balance = self.start

    def choose(self, probs: tuple[float, float, float],
               prices: tuple[float, float, float]) -> tuple[str, float] | None:
        """(outcome, edge) of the best value bet, or None when nothing clears min_edge."""
        best = max(((o, p * q - 1.0) for o, p, q in zip(OUTCOMES, probs, prices)),
                   key=lambda t: t[1])
        return best if best[1] > self.min_edge else None

    def settle(self, probs, prices, actual: str) -> float:
        """Place (if any) and settle one match. Returns the profit of the match."""
        pick = self.choose(probs, prices)
        if pick is None or self.balance < self.stake:
            return 0.0
        outcome, _ = pick
        price = prices[OUTCOMES.index(outcome)]
        self.n_bets += 1
        self.staked += self.stake
        profit = self.stake * (price - 1.0) if outcome == actual else -self.stake
        self.wins += outcome == actual
        self.balance += profit
        return profit

    @property
    def roi(self) -> float:
        return (self.balance - self.start) / self.staked if self.staked else 0.0


@dataclass
class BotRecord:
    """Acumulado de un bot a lo largo de la liga."""
    name: str
    n: int = 0
    points: int = 0
    exactos: int = 0
    brier_sum: float = 0.0
    logloss_sum: float = 0.0
    bankroll: Bankroll = field(default_factory=Bankroll)
    match_points: list = field(default_factory=list)   # per-match, for paired tests
    match_brier: list = field(default_factory=list)

    def add(self, pick_1x2: str, pick_exact: str, probs, home_score: int, away_score: int,
            rules, prices=None) -> int:
        """Score one match. ``prices`` (closing 1X2) enables the fictitious bankroll."""
        actual = outcome_of(home_score, away_score)
        pts = score_actual(home_score, away_score, pick_1x2, pick_exact, rules)
        self.n += 1
        self.points += pts
        self.exactos += pts >= rules.points_exact
        b = brier(probs, actual)
        self.brier_sum += b
        self.match_points.append(pts)
        self.match_brier.append(b)
        self.logloss_sum += log_loss(probs, actual)
        if prices is not None:
            self.bankroll.settle(probs, prices, actual)
        return pts

    def summary(self) -> dict:
        n = max(self.n, 1)
        b = self.bankroll
        return {
            "bot": self.name, "n": self.n, "points": self.points,
            "pts_per_match": round(self.points / n, 3), "exactos": self.exactos,
            "brier": round(self.brier_sum / n, 4), "log_loss": round(self.logloss_sum / n, 4),
            "bankroll": round(b.balance, 2), "bets": b.n_bets, "bet_wins": b.wins,
            "roi": round(b.roi, 4),
        }


def table(records: list[BotRecord]) -> list[dict]:
    """Tabla de posiciones: puntos, luego exactos (desempate real del pool)."""
    return sorted((r.summary() for r in records),
                  key=lambda s: (s["points"], s["exactos"]), reverse=True)


def paired_diff(a: list[float], b: list[float]) -> dict:
    """Paired comparison of two bots on the SAME matches: mean(a−b), its standard
    error and z. |z| < 2 ≈ the gap is within what luck alone produces."""
    if len(a) != len(b) or len(a) < 2:
        raise ValueError("paired_diff needs two equal-length series (same matches).")
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    mean = sum(d) / n
    var = sum((x - mean) ** 2 for x in d) / (n - 1)
    se = math.sqrt(var / n)
    return {"n": n, "mean_diff": mean, "total_diff": sum(d), "se": se,
            "z": mean / se if se > 0 else 0.0}
