"""Mercados más allá del marcador, todos derivados de la MISMA matriz de marcadores.

Un bot que ya tiene P(h-a) para cada marcador puede "apostar" a cualquier mercado
de goles sin otro modelo: basta sumar las celdas correctas.

- 1X2, Over/Under N.5, Ambos anotan (BTTS).
- Hándicap asiático: líneas enteras (push devuelve), medias y de cuarto (la
  apuesta se parte en dos mitades, p. ej. −0.75 = ½ a −0.5 + ½ a −1.0).

Medición, en dos capas:
- Calibración: Brier binario ``(p − y)²`` por mercado sí/no (uniforme 0.5 → 0.25).
- Dinero ficticio: :class:`MarketBankroll`, una apuesta plana por partido y
  mercado al lado de mayor valor esperado, contra el precio promedio de cierre.

Las props de jugadores (goleador, tarjetas) quedan para la fase 2: sin una fuente
de alineaciones + momios históricos no hay cómo medirlas honestamente.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


def p_1x2(cells: list[dict]) -> tuple[float, float, float]:
    p1 = sum(c["prob"] for c in cells if c["h"] > c["a"])
    px = sum(c["prob"] for c in cells if c["h"] == c["a"])
    p2 = sum(c["prob"] for c in cells if c["h"] < c["a"])
    s = p1 + px + p2
    return p1 / s, px / s, p2 / s


def p_over(cells: list[dict], line: float = 2.5) -> float:
    """P(total goals > line). Use half-lines (2.5, 3.5…) — no push."""
    return sum(c["prob"] for c in cells if c["h"] + c["a"] > line)


def p_btts(cells: list[dict]) -> float:
    return sum(c["prob"] for c in cells if c["h"] > 0 and c["a"] > 0)


def _ah_components(line: float) -> list[float]:
    """Quarter lines split into two half-stakes; others are a single line."""
    q = round(line * 4)
    if q % 2:  # x.25 / x.75
        return [(q - 1) / 4, (q + 1) / 4]
    return [q / 4]


def ah_return(goal_diff: int, line: float, price: float) -> float:
    """Gross return per 1 unit staked on the side whose handicap is ``line``,
    where ``goal_diff`` is that side's goals minus the opponent's.
    Win → price, push → 1, loss → 0; quarter lines average two halves."""
    comps = _ah_components(line)
    total = 0.0
    for l in comps:
        m = goal_diff + l
        total += price if m > 1e-9 else (1.0 if abs(m) <= 1e-9 else 0.0)
    return total / len(comps)


def ah_expected_returns(cells: list[dict], home_line: float,
                        price_home: float, price_away: float) -> dict[str, float]:
    """Expected gross return per unit for each AH side. ``home_line`` is the
    handicap applied to the home team (Football-Data ``AHCh``); the away side
    gets −home_line."""
    eh = ea = 0.0
    for c in cells:
        gd = c["h"] - c["a"]
        eh += c["prob"] * ah_return(gd, home_line, price_home)
        ea += c["prob"] * ah_return(-gd, -home_line, price_away)
    return {"home": eh, "away": ea}


def binary_brier(p: float, happened: bool) -> float:
    return (p - (1.0 if happened else 0.0)) ** 2


def binary_logloss(p: float, happened: bool, eps: float = 1e-9) -> float:
    return -math.log(max(p if happened else 1.0 - p, eps))


def logpool_binary(ps: list[float], ws: list[float]) -> float:
    """Weighted geometric pooling of yes/no probabilities (same rule as the 1X2
    blend), renormalized over the two outcomes."""
    tw = sum(ws)
    ly = sum(w / tw * math.log(max(p, 1e-9)) for p, w in zip(ps, ws))
    ln = sum(w / tw * math.log(max(1 - p, 1e-9)) for p, w in zip(ps, ws))
    y, n = math.exp(ly), math.exp(ln)
    return y / (y + n)


@dataclass
class MarketBankroll:
    """Apuesta plana ficticia en UN mercado: por partido, el lado con mayor valor
    esperado (retorno esperado − 1) si supera ``min_edge``."""
    market: str
    start: float = 1000.0
    stake: float = 10.0
    min_edge: float = 0.0
    balance: float = field(init=False)
    n_bets: int = 0
    staked: float = 0.0
    wins: int = 0
    profits: list = field(default_factory=list)  # per match (0 when no bet) — paired tests

    def __post_init__(self) -> None:
        self.balance = self.start

    def settle(self, expected: dict[str, float], realized: dict[str, float]) -> float | None:
        """``expected``: side → expected gross return per unit (p·price for simple
        markets). ``realized``: side → actual gross return per unit. Returns the
        match profit, or None when no bet was placed (a push returns 0.0)."""
        side, ev = max(expected.items(), key=lambda kv: kv[1])
        if ev - 1.0 <= self.min_edge or self.balance < self.stake:
            self.profits.append(0.0)
            return None
        profit = self.stake * (realized[side] - 1.0)
        self.n_bets += 1
        self.staked += self.stake
        self.wins += realized[side] > 1.0
        self.balance += profit
        self.profits.append(profit)
        return profit

    @property
    def roi(self) -> float:
        return (self.balance - self.start) / self.staked if self.staked else 0.0

    def summary(self) -> dict:
        return {"market": self.market, "bets": self.n_bets, "wins": self.wins,
                "balance": round(self.balance, 2), "roi": round(self.roi, 4)}


def simple_market(p_sides: dict[str, float], prices: dict[str, float],
                  winner: str) -> tuple[dict[str, float], dict[str, float]]:
    """(expected, realized) gross returns for a market that pays price-or-zero."""
    expected = {s: p_sides[s] * prices[s] for s in p_sides}
    realized = {s: (prices[s] if s == winner else 0.0) for s in p_sides}
    return expected, realized
