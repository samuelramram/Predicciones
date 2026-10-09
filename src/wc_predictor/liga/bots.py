"""Los competidores de la liga y cómo pica cada uno.

Todos producen el mismo ``Ticket``: probabilidades 1X2 + boleto (1X2, marcador).
Así el calificador los trata igual y la comparación es justa.

| Bot          | Probabilidades                          | Boleto                             |
|--------------|-----------------------------------------|------------------------------------|
| estadistico  | Poisson·DC + Elo, SIN mercado           | optimizador de EV del repo         |
| calibrado    | el blend de producción (con mercado)    | optimizador de EV del repo         |
| borrego      | la línea justa de cierre (mercado puro) | favorito + marcador más común      |

``calibrado`` es lo que hoy produce ``pipeline.ligamx picks``; ``estadistico`` es el
mismo motor con el mercado apagado. La diferencia entre los dos ES el valor del
mercado en el blend — medible por fin con ``ingest.ligamx_fd_odds``.

Los bots con LLM (reportero, corazonudo) y el humano llegan después: solo tienen
que emitir un ``Ticket``.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from wc_predictor.liga.scoring import OUTCOMES, outcome_of


@dataclass(frozen=True)
class Ticket:
    pick_1x2: str
    pick_exact: str
    probs: tuple[float, float, float]  # (p1, px, p2), sums to 1


def _norm(p1: float, px: float, p2: float) -> tuple[float, float, float]:
    s = p1 + px + p2
    return p1 / s, px / s, p2 / s


def ticket_from_prediction(pred: dict) -> Ticket:
    """``pipeline.ligamx.predict_fixture`` output → Ticket (probs renormalized:
    the prediction rounds them to 3 decimals)."""
    return Ticket(pred["pick_1x2"], pred["pick_exact"],
                  _norm(pred["p_home_win"], pred["p_draw"], pred["p_away_win"]))


def typical_scores(rows: list[dict]) -> dict[str, str]:
    """Most frequent final score per outcome in ``rows`` (the training window).

    El Borrego no tiene modelo de goles: copia al favorito del mercado con el
    marcador que más se repite en la liga para ese resultado."""
    counts: dict[str, Counter] = {o: Counter() for o in OUTCOMES}
    for r in rows:
        counts[outcome_of(r["home_score"], r["away_score"])][f"{r['home_score']}-{r['away_score']}"] += 1
    fallback = {"1": "1-0", "X": "1-1", "2": "0-1"}
    return {o: (c.most_common(1)[0][0] if c else fallback[o]) for o, c in counts.items()}


def borrego_ticket(market: tuple[float, float, float], typical: dict[str, str]) -> Ticket:
    """Mercado puro: el favorito de la línea justa, con su marcador típico."""
    probs = _norm(*market)
    fav = OUTCOMES[max(range(3), key=lambda i: probs[i])]
    return Ticket(fav, typical[fav], probs)
