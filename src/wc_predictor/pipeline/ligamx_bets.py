"""Value bets for a Liga MX jornada: model (no-odds) vs the market.

Compares the model's INDEPENDENT probability (Poisson+Elo, odds NOT in the
blend) against the de-vigged book price, and flags +EV bets with a conservative
¼-Kelly stake capped per bet. Line-shopping: the price shown is the BEST across
books. Markets: 1X2 + Over/Under 2.5.

This is a MEASUREMENT tool, not a tipster: the goal is to recover the Claude
spend, not to chase. The quiniela (vs 30 humans) is the real edge; here the
opponent is a book with vig, so the edges are thin and discipline is the point.

Run (needs odds_markets.json from ingest.ligamx_odds + a fit):
    python -m wc_predictor.pipeline.ligamx_bets --round j2 --bankroll 500
    python -m wc_predictor.pipeline.ligamx_bets --round j2 --edge 0.04 --kelly 0.25 --max-stake 0.02
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

from wc_predictor.betting.value import find_value_bets, ev_per_unit, over_under_probs
from wc_predictor.ingest.ligamx_odds import load_books_config
from wc_predictor.config import OUTPUTS_DIR
from wc_predictor.pipeline.ligamx import (
    FIXTURES_JSON,
    LIGAMX_DIR,
    PROFILE,
    ELO_JSON,
    STRENGTHS_JSON,
    load_team_altitudes,
    predict_fixture,
)
from wc_predictor.model.poisson_dc import load_fit

ODDS_MARKETS_JSON = LIGAMX_DIR / "odds_markets.json"

# Mínimo por defecto de la casa (Caliente/Betway aceptan desde $20 MXN). Con un
# bankroll de experimento ($500) los stakes de ¼-Kelly caen en $3–$10, por
# debajo de lo que la app deja apostar; se redondean a múltiplos del mínimo para
# que el boleto salga jugable y copy-paste.
DEFAULT_MIN_STAKE = 20.0


def played_stake_mxn(kelly_frac: float, bankroll: float, min_stake: float = 0.0) -> float:
    """El stake que DE VERDAD se apuesta, redondeado a algo que la casa acepta.

    Kelly da el tamaño ideal (`kelly_frac * bankroll`), pero la app no toma $8.
    Con `min_stake` > 0 se piso-redondea a múltiplos del mínimo (mínimo 1 unidad),
    así el boleto sale en $20/$40/… listos para copiar. Con `min_stake` = 0 es el
    Kelly crudo (comportamiento anterior)."""
    raw = kelly_frac * bankroll
    if min_stake <= 0:
        return round(raw, 2)
    units = max(1, round(raw / min_stake))
    return float(units * min_stake)


def _load_model_and_round(round_spec: str):
    """(fit, elos, altitudes, markets, selected_fixtures) o None si faltan datos.
    Compartido por el boleto de valor y el de despliegue para no cargar dos veces."""
    if not STRENGTHS_JSON.exists() or not ODDS_MARKETS_JSON.exists():
        return None
    fit = load_fit(STRENGTHS_JSON)
    elos = {r["team"]: r["elo"]
            for r in json.loads(ELO_JSON.read_text(encoding="utf-8"))["teams"]}
    altitudes = load_team_altitudes()
    markets = json.loads(ODDS_MARKETS_JSON.read_text(encoding="utf-8"))["matches"]
    fx_doc = json.loads(FIXTURES_JSON.read_text(encoding="utf-8"))

    spec = round_spec.strip().lower()
    if spec in ("all", ""):
        selected = fx_doc["matches"]
    elif spec.startswith("j") and spec[1:].isdigit():
        n = int(spec[1:])
        selected = [m for m in fx_doc["matches"] if m.get("jornada") == n]
    else:
        return None
    return fit, elos, altitudes, markets, selected


def compute_bets(round_spec: str, edge_min: float = 0.03, kelly_mult: float = 0.25,
                 max_stake: float = 0.02, total_line: float = 2.5,
                 own_books_only: bool = True, require_clv: bool = False) -> list:
    """The value bets for a round (sorted by edge desc). Returns [] when there is
    no market file or nothing clears the edge gate. Pure of printing/serialization
    so both the CLI and the boleto renderer can reuse it. Requires a fit +
    odds_markets.json; the model view is INDEPENDENT (odds=None) by construction."""
    mcfg, rules = PROFILE.model, PROFILE.rules
    loaded = _load_model_and_round(round_spec)
    if loaded is None:
        return []
    fit, elos, altitudes, markets, selected = loaded

    all_bets = []
    for fx in selected:
        market = markets.get(f"{fx['home']}|{fx['away']}")
        if market is None:
            continue
        p = predict_fixture(fx, fit, elos, altitudes, mcfg, rules, odds=None)
        if "error" in p:
            continue
        model_1x2 = (p["p_home_win"], p["p_draw"], p["p_away_win"])
        all_bets.extend(find_value_bets(
            f"{fx['home']} vs {fx['away']}", model_1x2, p["_cells"], market,
            edge_min=edge_min, kelly_mult=kelly_mult, max_stake=max_stake,
            total_line=total_line, own_books_only=own_books_only,
            require_clv=require_clv,
        ))
    all_bets.sort(key=lambda b: -b.edge)
    return all_bets


def deployment_ticket(round_spec: str, bankroll: float = 500.0, budget_frac: float = 0.9,
                      min_stake: float = DEFAULT_MIN_STAKE, total_line: float = 2.5) -> list[dict]:
    """Boleto de EXPERIMENTO: un pick 1X2 por partido de la ronda, con stakes que
    despliegan ~`budget_frac` del bankroll. Distinto del boleto de valor: aquí el
    objetivo no es la disciplina de CLV sino poner la mayor parte del roll a
    trabajar sobre la opinión del modelo, juego por juego.

    - Pick por partido: la selección 1X2 de mayor EV a precio de MIS casas (aterriza
      en el lado de valor donde lo hay, y en el favorito donde no).
    - Peso MIXTO: base igual por juego (acción en los 9) + bonus si el precio le gana
      al cierre (CLV+) + bonus por la ventaja del modelo. Así el CLV+ y los partidos
      con más edge se llevan más stake sin dejar ninguno fuera.
    - Stakes redondeados a múltiplos del mínimo jugable de la casa.

    OJO: casi todos estos picks tienen CLV negativo (el mercado les gana). Esto es
    acción medida sobre el roll, no un boleto +EV. Para el disciplinado, la ruta de
    valor con --require-clv. El CLV de cada pick queda registrado igual."""
    mcfg, rules = PROFILE.model, PROFILE.rules
    loaded = _load_model_and_round(round_spec)
    if loaded is None:
        return []
    fit, elos, altitudes, markets, selected = loaded

    picks = []
    for fx in selected:
        market = markets.get(f"{fx['home']}|{fx['away']}")
        if market is None:
            continue
        p = predict_fixture(fx, fit, elos, altitudes, mcfg, rules, odds=None)
        if "error" in p:
            continue
        probs = {"1": p["p_home_win"], "X": p["p_draw"], "2": p["p_away_win"]}
        h2h = market.get("h2h") or {}
        fair, avail = h2h.get("fair") or {}, h2h.get("best_available") or {}
        best = None
        for sel in ("1", "X", "2"):
            a = avail.get(sel) or {}
            price = a.get("price")
            if not price:
                continue
            ev = ev_per_unit(probs[sel], float(price))
            if best is None or ev > best["ev"]:
                fp = float(fair.get(sel, 0.0) or 0.0)
                best = {
                    "match": f"{fx['home']} vs {fx['away']}",
                    "home": fx["home"], "away": fx["away"], "selection": sel,
                    "model_prob": round(probs[sel], 4), "fair_prob": round(fp, 4),
                    "edge": round(probs[sel] - fp, 4), "price": float(price),
                    "book": a.get("book"), "ev": round(ev, 4),
                    "clv_entry": round(float(price) * fp - 1.0 if fp else 0.0, 4),
                }
        if best is not None:
            picks.append(best)

    if not picks:
        return []

    def weight(b: dict) -> float:
        w = 1.0                                     # base: acción en cada juego
        if b["clv_entry"] > 0:
            w += 1.0                                # premia lo que le gana al cierre
        w += 4.0 * max(0.0, b["edge"])              # más stake donde el modelo ve más ventaja
        return w

    total_w = sum(weight(b) for b in picks) or 1.0
    budget_mxn = budget_frac * bankroll
    for b in picks:
        raw_frac = (budget_mxn * weight(b) / total_w) / bankroll
        b["weight"] = round(weight(b), 3)
        b["stake_mxn"] = played_stake_mxn(raw_frac, bankroll, min_stake)
    picks.sort(key=lambda b: (-b["weight"], -b["stake_mxn"]))
    return picks


def _house_ou_candidate(fx: dict, market: dict, cells: list[dict],
                        house: str, total_line: float) -> dict | None:
    """Best-value Over/Under pick for one match at ONE house, or None. Unlike the
    1X2 leg (deployed on every priced match as measured action), a totals leg only
    joins the boleto when the model sees genuine value at that house's price —
    positive edge vs the sharp fair line AND +EV — so the ticket never funds an
    arbitrary O/U. Same CLV bookkeeping as the 1X2 leg."""
    totals = market.get("totals") or {}
    t = totals.get(f"{total_line}") or totals.get(f"{total_line:.1f}")
    if not t:
        return None
    fair = t.get("fair") or {}
    by_book = t.get("by_book") or {}
    p_over, p_under = over_under_probs(cells, total_line)
    best = None
    for label, mp, key in (("Over", p_over, "over"), ("Under", p_under, "under")):
        price = (by_book.get(key) or {}).get(house)
        if not price:
            continue
        price = float(price)
        fp = float(fair.get(key, 0.0) or 0.0)
        edge = mp - fp
        ev = ev_per_unit(mp, price)
        if edge <= 0 or ev <= 0:            # only real value joins the boleto
            continue
        if best is None or ev > best["ev"]:
            best = {
                "match": f"{fx['home']} vs {fx['away']}",
                "home": fx["home"], "away": fx["away"],
                "selection": label, "market": f"O/U {total_line}", "house": house,
                "model_prob": round(mp, 4), "fair_prob": round(fp, 4),
                "edge": round(edge, 4), "price": price, "ev": round(ev, 4),
                "clv_entry": round(price * fp - 1.0 if fp else 0.0, 4),
            }
    return best


def _house_candidates(round_spec: str, house: str, total_line: float,
                      include_totals: bool = False) -> list[dict]:
    """Best-EV 1X2 pick per match priced at ONE house (`house`), model view
    INDEPENDENT of odds. Skips matches the house doesn't quote. Used by the
    per-house boleto — the price is what you'd actually get at that house, not the
    line-shopped best across all my books.

    With `include_totals`, each match may ALSO contribute an Over/Under leg (at the
    same house's price) when the model sees value there — so the boleto carries the
    totals action the value ticket surfaces, not just the 1X2 per game."""
    mcfg, rules = PROFILE.model, PROFILE.rules
    loaded = _load_model_and_round(round_spec)
    if loaded is None:
        return []
    fit, elos, altitudes, markets, selected = loaded
    picks = []
    for fx in selected:
        market = markets.get(f"{fx['home']}|{fx['away']}")
        if market is None:
            continue
        p = predict_fixture(fx, fit, elos, altitudes, mcfg, rules, odds=None)
        if "error" in p:
            continue
        probs = {"1": p["p_home_win"], "X": p["p_draw"], "2": p["p_away_win"]}
        h2h = market.get("h2h") or {}
        fair = h2h.get("fair") or {}
        house_px = (h2h.get("by_book") or {}).get(house) or {}
        best = None
        for sel in ("1", "X", "2"):
            price = house_px.get(sel)
            if not price:
                continue
            ev = ev_per_unit(probs[sel], float(price))
            if best is None or ev > best["ev"]:
                fp = float(fair.get(sel, 0.0) or 0.0)
                best = {
                    "match": f"{fx['home']} vs {fx['away']}",
                    "home": fx["home"], "away": fx["away"], "selection": sel,
                    "market": "1X2", "house": house,
                    "model_prob": round(probs[sel], 4), "fair_prob": round(fp, 4),
                    "edge": round(probs[sel] - fp, 4), "price": float(price),
                    "ev": round(ev, 4),
                    "clv_entry": round(float(price) * fp - 1.0 if fp else 0.0, 4),
                }
        if best is not None:
            picks.append(best)
        if include_totals:
            ou = _house_ou_candidate(fx, market, p["_cells"], house, total_line)
            if ou is not None:
                picks.append(ou)
    return picks


def per_house_ticket(round_spec: str, house_budgets: dict[str, float],
                     min_stake: float = DEFAULT_MIN_STAKE,
                     total_line: float = 2.5, include_totals: bool = False) -> dict:
    """Boleto POR CASA: para cada casa, reparte SU presupuesto completo entre su
    mejor pick 1X2 por partido (a SU precio), con piso `min_stake` por predicción.

    El presupuesto se despliega en unidades de `min_stake` (la casa no toma $8):
    ``unidades = round(presupuesto/min_stake)``. Si hay unidades para todos los
    partidos, cada pick arranca en una unidad y las sobrantes van a los de mayor
    peso; si el presupuesto no alcanza para todos, entran los de mayor peso primero.

    Peso = base igual + bonus si el precio le gana al cierre (CLV+) + bonus por la
    ventaja del modelo — la misma lógica del boleto de despliegue, pero por casa.
    OJO: casi todos los picks arrancan con CLV≤0; esto es acción medida, no un
    boleto +EV. El CLV real queda registrable en el ledger (log-boleto)."""
    def weight(b: dict) -> float:
        w = 1.0
        if b["clv_entry"] > 0:
            w += 1.0
        w += 4.0 * max(0.0, b["edge"])
        return w

    houses = {}
    for house, budget in house_budgets.items():
        cands = _house_candidates(round_spec, house, total_line, include_totals)
        # Floor, never round up: the boleto must NEVER exceed the stated budget.
        # A remainder below min_stake simply can't be placed (the house won't take it).
        units_total = int(budget // min_stake) if min_stake > 0 else 0
        if not cands or units_total <= 0:
            houses[house] = {"budget_mxn": budget, "bets": [], "total_stake_mxn": 0.0,
                             "n_matches_priced": len(cands)}
            continue
        for b in cands:
            b["weight"] = round(weight(b), 3)
        # Rank by weight; if the budget can't cover every match, keep the strongest.
        cands.sort(key=lambda b: (-b["weight"], -b["ev"]))
        chosen = cands[:units_total] if units_total < len(cands) else cands
        # One unit each, then hand the remaining units to the highest-weight picks.
        units = {id(b): 1 for b in chosen}
        remaining = units_total - len(chosen)
        ranked = sorted(chosen, key=lambda b: (-b["weight"], -b["ev"]))
        i = 0
        while remaining > 0 and ranked:
            units[id(ranked[i % len(ranked)])] += 1
            remaining -= 1
            i += 1
        for b in chosen:
            b["stake_mxn"] = float(units[id(b)] * min_stake)
        chosen.sort(key=lambda b: (-b["stake_mxn"], -b["weight"]))
        houses[house] = {
            "budget_mxn": budget,
            "bets": chosen,
            "total_stake_mxn": sum(b["stake_mxn"] for b in chosen),
            "n_matches_priced": len(cands),
            "n_positive_clv": sum(1 for b in chosen if b["clv_entry"] > 0),
        }
    return {
        "as_of": datetime.utcnow().isoformat() + "Z", "round": round_spec.strip().lower(),
        "mode": "per_house", "min_stake": min_stake, "total_line": total_line,
        "include_totals": include_totals, "houses": houses,
    }


def run_per_house(round_spec: str, house_budgets: dict[str, float],
                  min_stake: float, total_line: float, log_ledger: bool = False,
                  include_totals: bool = False) -> dict:
    """Imprime + versiona el boleto por casa; opcionalmente lo registra en el
    ledger de CLV con el precio y la casa REALES (no la medición all-books)."""
    spec = round_spec.strip().lower()
    payload = per_house_ticket(spec, house_budgets, min_stake, total_line, include_totals)
    for house, data in payload["houses"].items():
        print(f"\nBoleto {house.upper()} {spec} — presupuesto ${data['budget_mxn']:.0f} · "
              f"mínimo ${min_stake:.0f}/predicción")
        bets = data["bets"]
        if not bets:
            print(f"  {house} no cotiza ningún partido de esta ronda (o presupuesto < mínimo).")
            continue
        print(f"  {'Partido':<26} {'Pick':<20} {'modelo':>7} {'justo':>6} "
              f"{'edge':>6} {'precio':>7} {'stake':>7} {'CLV':>7}")
        for b in bets:
            if b.get("market", "1X2") != "1X2":       # O/U leg: label with the line
                pick_lbl = f"{b['selection']} {b['market'].split()[-1]}"[:20]
            else:
                side = b["home"] if b["selection"] == "1" else (
                    b["away"] if b["selection"] == "2" else "Empate")
                pick_lbl = f"{b['selection']} {side}"[:20]
            print(f"  {b['match']:<26} {pick_lbl:<20} {b['model_prob']*100:>6.1f}% "
                  f"{b['fair_prob']*100:>5.1f}% {b['edge']*100:>+5.1f}% {b['price']:>7.2f} "
                  f"${b['stake_mxn']:>5.0f} {b['clv_entry']*100:>+6.1f}%")
        leftover = data["budget_mxn"] - data["total_stake_mxn"]
        left_note = (f" · sobran ${leftover:.0f} (< ${min_stake:.0f}, no colocable)"
                     if leftover >= 0.5 else "")
        print(f"  {len(bets)} predicciones · stake total ${data['total_stake_mxn']:.0f} "
              f"· {data.get('n_positive_clv', 0)} con CLV+{left_note}")
    print("\n  ⚠ La mayoría arranca con CLV≤0: es acción medida sobre tu roll, NO un "
          "boleto +EV. El CLV real de cada pick se mide en el ledger a lo largo del torneo.")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUTPUTS_DIR / f"ligamx_boleto_{spec}.json"
    dst.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {dst}")
    if log_ledger:
        from wc_predictor.pipeline.ligamx_clv import log_boleto
        n = log_boleto(payload)
        print(f"  registradas {n} apuestas REALES en el ledger de CLV (casa + precio + stake que apostaste)")
    return payload


def deployment_payload(round_spec: str, bankroll: float = 500.0, budget_frac: float = 0.9,
                       min_stake: float = DEFAULT_MIN_STAKE, total_line: float = 2.5) -> dict:
    """JSON del boleto de despliegue (mixto), listo para renderizar/versionar."""
    picks = deployment_ticket(round_spec, bankroll, budget_frac, min_stake, total_line)
    return {
        "as_of": datetime.utcnow().isoformat() + "Z", "round": round_spec.strip().lower(),
        "mode": "deployment",
        "params": {"bankroll": bankroll, "budget_frac": budget_frac, "min_stake": min_stake,
                   "total_line": total_line, "books": load_books_config().get("available") or []},
        "bets": picks,
        "total_stake_mxn": sum(b["stake_mxn"] for b in picks),
    }


def bets_payload(round_spec: str, bankroll: float = 500.0, edge_min: float = 0.03,
                 kelly_mult: float = 0.25, max_stake: float = 0.02,
                 total_line: float = 2.5, own_books_only: bool = True,
                 require_clv: bool = False, min_stake: float = 0.0) -> dict | None:
    """JSON-serializable bets bundle for a round, or None if no market file."""
    if not ODDS_MARKETS_JSON.exists():
        return None
    bets = compute_bets(round_spec, edge_min, kelly_mult, max_stake, total_line,
                        own_books_only=own_books_only, require_clv=require_clv)
    return {
        "as_of": datetime.utcnow().isoformat() + "Z", "round": round_spec.strip().lower(),
        "params": {"bankroll": bankroll, "edge_min": edge_min, "kelly_mult": kelly_mult,
                   "max_stake": max_stake, "total_line": total_line, "min_stake": min_stake,
                   "own_books_only": own_books_only, "require_clv": require_clv,
                   "books": load_books_config().get("available") or []},
        "bets": [
            {"match": b.match, "market": b.market, "selection": b.selection,
             "model_prob": round(b.model_prob, 4), "fair_prob": round(b.fair_prob, 4),
             "edge": round(b.edge, 4), "price": b.price, "book": b.book,
             "ev": round(b.ev, 4), "stake_frac": round(b.kelly_stake, 4),
             # stake_mxn = lo que DE VERDAD apuestas (redondeado al mínimo jugable);
             # stake_kelly_mxn = el tamaño ideal de Kelly, para referencia.
             "stake_mxn": played_stake_mxn(b.kelly_stake, bankroll, min_stake),
             "stake_kelly_mxn": round(b.kelly_stake * bankroll, 2),
             "clv_entry": round(b.clv_entry, 4), "beats_fair": b.beats_fair,
             "is_available": b.is_available}
            for b in bets
        ],
    }


def run_deployment(spec: str, bankroll: float, budget_frac: float,
                   min_stake: float, total_line: float) -> None:
    """Imprime + versiona el boleto de despliegue (mixto): un pick por partido,
    ~budget_frac del bankroll. Ruta separada del boleto de valor disciplinado."""
    picks = deployment_ticket(spec, bankroll, budget_frac, min_stake, total_line)
    print(f"\nBoleto de DESPLIEGUE {spec} — bankroll ${bankroll:.0f} · "
          f"objetivo {budget_frac:.0%} del roll · mínimo ${min_stake:.0f}/apuesta")
    print("  un pick 1X2 por partido · peso mixto (base + CLV+ + ventaja del modelo)")
    if not picks:
        print("  Sin partidos con precio en mis casas para esta ronda.")
        return
    print(f"  {'Partido':<26} {'Pick':<20} {'modelo':>7} {'justo':>6} "
          f"{'edge':>6} {'precio':>7} {'casa':<10} {'stake':>7} {'CLV':>7}")
    for b in picks:
        side = b["home"] if b["selection"] == "1" else (
            b["away"] if b["selection"] == "2" else "Empate")
        pick_lbl = f"{b['selection']} {side}"[:20]
        print(f"  {b['match']:<26} {pick_lbl:<20} {b['model_prob']*100:>6.1f}% "
              f"{b['fair_prob']*100:>5.1f}% {b['edge']*100:>+5.1f}% {b['price']:>7.2f} "
              f"{(b['book'] or '-'):<10} ${b['stake_mxn']:>5.0f} {b['clv_entry']*100:>+6.1f}%")
    total = sum(b["stake_mxn"] for b in picks)
    npos = sum(1 for b in picks if b["clv_entry"] > 0)
    print(f"\n  {len(picks)} apuestas · stake total ${total:.0f} "
          f"({total/bankroll*100:.0f}% del bankroll) · {npos} con CLV+")
    print("  ⚠ la mayoría tiene CLV≤0: esto es acción medida sobre el roll, NO un boleto "
          "+EV. El disciplinado es --require-clv. El CLV de cada pick queda registrado.")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUTPUTS_DIR / f"ligamx_bets_{spec}.json"
    dst.write_text(json.dumps(
        deployment_payload(spec, bankroll, budget_frac, min_stake, total_line),
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {dst}")


def run(round_spec: str, bankroll: float, edge_min: float, kelly_mult: float,
        max_stake: float, total_line: float, own_books_only: bool = True,
        require_clv: bool = False, min_stake: float = 0.0, budget: float = 0.0) -> None:
    if not STRENGTHS_JSON.exists():
        raise SystemExit(f"Falta {STRENGTHS_JSON}. Corre `pipeline.ligamx fit` primero.")
    if not ODDS_MARKETS_JSON.exists():
        raise SystemExit(f"Falta {ODDS_MARKETS_JSON}. Corre `ingest.ligamx_odds` primero.")
    spec = round_spec.strip().lower()
    if budget and budget > 0:
        run_deployment(spec, bankroll, budget, min_stake, total_line)
        return
    all_bets = compute_bets(spec, edge_min, kelly_mult, max_stake, total_line,
                            own_books_only=own_books_only, require_clv=require_clv)
    books = load_books_config().get("available") or []

    min_note = f" · mínimo ${min_stake:.0f}/apuesta" if min_stake > 0 else ""
    print(f"\nApuestas de valor {spec} — bankroll ${bankroll:.0f} · "
          f"edge≥{edge_min:.0%} · ¼-Kelly×{kelly_mult} · tope {max_stake:.0%}/apuesta{min_note}")
    if own_books_only and books:
        print(f"  precios restringidos a MIS casas: {', '.join(books)} "
              f"(sin esto el line-shopping usa casas sin cuenta)")
    if not all_bets:
        print("  Sin valor: el modelo no le gana al mercado en ningún mercado cubierto. "
              "(Eso es sano — casi siempre es así vs un book afilado.)")
    else:
        print(f"  {'Partido':<26} {'Mercado':<9} {'Sel':<5} {'modelo':>7} {'justo':>6} "
              f"{'edge':>6} {'precio':>7} {'casa':<12} {'a jugar':>8} {'EV':>6} {'CLV':>7}")
        for b in all_bets:
            stake_mxn = played_stake_mxn(b.kelly_stake, bankroll, min_stake)
            print(f"  {b.match:<26} {b.market:<9} {b.selection:<5} "
                  f"{b.model_prob*100:>6.1f}% {b.fair_prob*100:>5.1f}% {b.edge*100:>5.1f}% "
                  f"{b.price:>7.2f} {(b.book or '-'):<12} "
                  f"${stake_mxn:>6.0f} {b.ev*100:>+5.1f}% {b.clv_entry*100:>+6.1f}%")
        total_stake = sum(played_stake_mxn(b.kelly_stake, bankroll, min_stake) for b in all_bets)
        print(f"\n  {len(all_bets)} apuestas · stake total ${total_stake:.0f} "
              f"({total_stake/bankroll*100:.1f}% del bankroll)")
        if min_stake > 0 and not require_clv:
            neg = [b for b in all_bets if b.clv_entry <= 0]
            if neg:
                print(f"  nota: {len(neg)} de estas tienen CLV≤0 (el mercado les gana). "
                      f"Para el boleto realmente jugable agrega --require-clv.")
        big = [b for b in all_bets if b.edge >= 0.08]
        if big:
            print(f"\n  ⚠ {len(big)} apuesta(s) con edge ≥8%: contra un mercado de ~20+ "
                  f"casas, un edge así casi siempre es ERROR DEL MODELO, no valor real "
                  f"(el backtest sin odds solo le gana ~8% a un baseline trivial → el "
                  f"modelo NO es más afilado que el mercado). Trátalas como medición, "
                  f"no como certeza; registra el CLV y sube --edge si dudas.")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUTPUTS_DIR / f"ligamx_bets_{spec}.json"
    dst.write_text(json.dumps(
        bets_payload(spec, bankroll, edge_min, kelly_mult, max_stake, total_line,
                     own_books_only=own_books_only, require_clv=require_clv,
                     min_stake=min_stake),
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {dst}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Apuestas de valor Liga MX.")
    parser.add_argument("--round", default="all", help="j1..j17 | all")
    parser.add_argument("--bankroll", type=float, default=500.0, help="bankroll en MXN.")
    parser.add_argument("--edge", type=float, default=0.03, help="edge mínimo (modelo − justo).")
    parser.add_argument("--kelly", type=float, default=0.25, help="fracción de Kelly (¼ por defecto).")
    parser.add_argument("--max-stake", type=float, default=0.02, help="tope de stake por apuesta.")
    parser.add_argument("--min-stake", type=float, default=DEFAULT_MIN_STAKE,
                        help=f"mínimo por apuesta que acepta la casa en MXN (default "
                             f"${DEFAULT_MIN_STAKE:.0f}); el stake se redondea a múltiplos de "
                             f"esto para que el boleto sea jugable. 0 = Kelly crudo.")
    parser.add_argument("--budget", type=float, default=0.0,
                        help="MODO DESPLIEGUE: fracción del bankroll a poner en juego "
                             "(ej. 0.9 = 90%%). Reparte un pick 1X2 por partido con peso "
                             "mixto (base + CLV+ + ventaja). Acción medida, NO boleto +EV. "
                             "0 = boleto de valor disciplinado (default).")
    parser.add_argument("--budget-betway", type=float, default=0.0,
                        help="MODO POR CASA: presupuesto en MXN a desplegar COMPLETO en Betway "
                             "(un pick 1X2 por partido a precio de Betway, mínimo $20/predicción). "
                             "Combínalo con --budget-caliente para el boleto de la jornada.")
    parser.add_argument("--budget-caliente", type=float, default=0.0,
                        help="MODO POR CASA: presupuesto en MXN a desplegar COMPLETO en Caliente.")
    parser.add_argument("--log-boleto", action="store_true",
                        help="registra el boleto POR CASA en el ledger de CLV con la casa y el "
                             "precio REALES que apostaste (no la medición all-books).")
    parser.add_argument("--total-line", type=float, default=2.5, help="línea de O/U a evaluar.")
    parser.add_argument("--all-books", dest="own_books_only", action="store_false", default=True,
                        help="cotiza contra las 45 casas del feed en vez de las de "
                             "books.json (útil para medir el edge del modelo, NO para apostar: "
                             "son precios de casas donde no tengo cuenta).")
    parser.add_argument("--require-clv", action="store_true",
                        help="solo apuestas cuyo precio LE GANA a la línea justa afilada "
                             "(CLV positivo al entrar) — la disciplina del plan, ahora exigible.")
    parser.add_argument("--house-totals", action="store_true",
                        help="MODO POR CASA: además del pick 1X2 por partido, agrega una pierna "
                             "de Over/Under (a precio de la casa) cuando el modelo ve valor real "
                             "ahí — así el boleto lleva la acción de totals, no solo el 1X2.")
    args = parser.parse_args(argv)
    house_budgets = {}
    if args.budget_betway > 0:
        house_budgets["betway"] = args.budget_betway
    if args.budget_caliente > 0:
        house_budgets["caliente"] = args.budget_caliente
    if house_budgets:
        if not ODDS_MARKETS_JSON.exists():
            raise SystemExit(f"Falta {ODDS_MARKETS_JSON}. Corre `ingest.ligamx_odds` primero.")
        run_per_house(args.round, house_budgets, args.min_stake, args.total_line,
                      log_ledger=args.log_boleto, include_totals=args.house_totals)
        return
    run(args.round, args.bankroll, args.edge, args.kelly, args.max_stake, args.total_line,
        own_books_only=args.own_books_only, require_clv=args.require_clv,
        min_stake=args.min_stake, budget=args.budget)


if __name__ == "__main__":
    main()
