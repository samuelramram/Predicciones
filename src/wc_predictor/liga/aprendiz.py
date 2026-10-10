"""Aprendiz: el bot que reajusta solo cuánto le cree al modelo y cuánto al mercado.

El calibrado mezcla modelo y mercado con un peso FIJO (0.9 en Europa, 0.55 en Liga
MX), medido una vez en el backtest. El aprendiz arranca en ese mismo peso y cada
jornada lo vuelve a estimar con lo que ya pasó:

1. junta los partidos ya jugados donde hay pronóstico del modelo puro (el bot
   estadístico) y del mercado (la línea justa que copia el borrego);
2. busca el peso ``w`` que mejor habría pronosticado esos partidos, mezclando
   igual que el calibrado: p ∝ modelo^(1−w) · mercado^w (log-pool), y midiendo con
   log-loss;
3. NO salta a ese peso: lo encoge hacia el de producción según cuánta evidencia
   hay, ``w = prior + (w* − prior) · n / (n + K)``. Con 20 partidos casi no se mueve;
   con cientos manda la evidencia. Así no persigue rachas de una jornada.

Todo sale de datos sellados y resultados, así que es reproducible: misma historia →
mismo peso. El Árbitro lo mide contra el calibrado con z pareado.
"""
from __future__ import annotations

import math

OUTCOMES = ("1", "X", "2")
GRID = tuple(i / 40 for i in range(41))      # 0, 0.025, …, 1
K_SHRINK = 300                               # partidos para moverse "la mitad" hacia w*
WINDOW = 1500                                # los más recientes cuentan
W_MIN, W_MAX = 0.2, 1.0


def pool(model, market, w: float) -> tuple[float, float, float]:
    """Log-linear pool of two 1X2 distributions."""
    raw = [max(m, 1e-9) ** (1 - w) * max(q, 1e-9) ** w for m, q in zip(model, market)]
    s = sum(raw)
    return tuple(x / s for x in raw)


def log_loss_at(pairs, w: float) -> float:
    return -sum(math.log(pool(m, q, w)[o]) for m, q, o in pairs) / len(pairs)


def fit_weight(pairs: list[tuple], prior: float, k: float = K_SHRINK,
               window: int = WINDOW) -> dict:
    """pairs = [(model_p1x2, market_p1x2, outcome_index)], oldest first.
    → {"w", "w_star", "n", "ll_model", "ll_market", "ll_w"}."""
    pairs = pairs[-window:]
    n = len(pairs)
    if n == 0:
        return {"w": prior, "w_star": None, "n": 0}
    lls = {g: log_loss_at(pairs, g) for g in GRID}
    w_star = min(lls, key=lls.get)
    w = prior + (w_star - prior) * n / (n + k)
    w = min(W_MAX, max(W_MIN, w))
    return {"w": round(w, 3), "w_star": w_star, "n": n,
            "ll_model": round(lls[0.0], 4), "ll_market": round(lls[1.0], 4),
            "ll_prior": round(log_loss_at(pairs, prior), 4)}


def pairs_from_ledger(records: list[dict], results_idx: dict, prefix: str,
                      before: str | None = None) -> list[tuple]:
    """(estadistico p1x2, borrego p1x2 = fair market, outcome) for settled sealed
    matches of one competition (``eu-`` or ``mx-``), by date. ``before`` (ISO date)
    keeps only matches played before it."""
    from wc_predictor.liga import arbitro
    from wc_predictor.liga.scoring import outcome_of
    picks = arbitro.collect(records, prefix=(prefix,))
    est, mkt = picks.get("estadistico", {}), picks.get("borrego", {})
    out = []
    for key in sorted(set(est) & set(mkt), key=lambda k: k[3]):
        if before and key[3] >= before:
            continue
        res = arbitro.find_result(results_idx, est[key])
        if res is None or "p1x2" not in est[key] or "p1x2" not in mkt[key]:
            continue
        o = OUTCOMES.index(outcome_of(res["home_score"], res["away_score"]))
        out.append((tuple(est[key]["p1x2"]), tuple(mkt[key]["p1x2"]), o))
    return out


def learned_weight(prefix: str, prior: float, before: str | None = None) -> dict:
    """Weight for the next round of a competition, from the sealed ledger."""
    from wc_predictor.liga import arbitro, seal
    records = seal.read_ledger(seal.LEDGER)
    idx = arbitro.results_index(arbitro.load_results())
    info = fit_weight(pairs_from_ledger(records, idx, prefix, before), prior)
    info["prior"] = prior
    return info


def explain(info: dict) -> str:
    """One line for the round file / Telegram."""
    if not info.get("n"):
        return (f"aprendiz: sin partidos jugados todavía; arranca igual que el calibrado "
                f"({info['prior']:.0%} mercado).")
    return (f"aprendiz: {info['w']:.0%} mercado (calibrado {info['prior']:.0%}). Con {info['n']} "
            f"partidos el mejor peso habría sido {info['w_star']:.0%}; se mueve hacia ahí según la "
            f"evidencia. Log-loss modelo {info['ll_model']}, mercado {info['ll_market']}.")
