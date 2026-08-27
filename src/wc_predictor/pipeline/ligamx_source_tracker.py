"""Tracker de fuentes: ¿le gana el BLEND (55% mercado) al modelo solo y al mercado solo?

El backtest walk-forward mide la habilidad base SIN odds (no hay feed histórico de
odds de Liga MX), así que el peso del mercado (`blend_odds_weight`, hoy 0.55) es la
perilla que NO se puede validar en retrospectiva. Este tracker la mide EN VIVO: cada
jornada registra, por partido, el pick 1X2 de tres fuentes —

  * modelo solo  (Poisson+Elo, odds=None),
  * blend        (producción: modelo + mercado al 55%),
  * mercado solo (argmax de la línea devigada),

y al liquidar con resultados compara su acierto de 1X2 (y los puntos de quiniela
del modelo/blend, que sí pican marcador). En ~5-6 jornadas el acumulado dice si
conviene subirle o bajarle al mercado: si mercado-solo > blend, el mercado está
subponderado; si modelo-solo ≈ blend, las odds aportan poco.

Además fija un `congestion_flag` por equipo (de data/ligamx/congestion.json) para
MEDIR —no asumir— si los equipos con carga de Leagues Cup rinden por debajo de su
predicción. El efecto de descanso corto en el histórico de Liga MX midió ~0
(Δ −0.014 PPG, Δ −0.07 goles, no significativo), así que NO se cablea ninguna
penalización: se instrumenta y se decide con evidencia.

    python -m wc_predictor.pipeline.ligamx_source_tracker log --round j4
    python -m wc_predictor.pipeline.ligamx_source_tracker settle
    python -m wc_predictor.pipeline.ligamx_source_tracker report   # → outputs/ligamx_sources.html
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime

from wc_predictor.config import OUTPUTS_DIR
from wc_predictor.pipeline.ligamx import (FIXTURES_JSON, LIGAMX_DIR, _load_model,
                                          predict_fixture)
from wc_predictor.scoring.quiniela import score_actual

TRACKER_JSON = LIGAMX_DIR / "source_tracker.json"
ODDS_H2H_JSON = LIGAMX_DIR / "odds_h2h.json"
CONGESTION_JSON = LIGAMX_DIR / "congestion.json"

# Marcador imposible: deja que score_actual solo pueda otorgar el punto de 1X2
# (el mercado no predice marcador, así que no compite por exactos).
_NO_EXACT = "99-99"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _load_tracker() -> list[dict]:
    return _load(TRACKER_JSON).get("entries", []) if TRACKER_JSON.exists() else []


def _save_tracker(entries: list[dict]) -> None:
    TRACKER_JSON.write_text(json.dumps(
        {"updated_at": datetime.utcnow().isoformat() + "Z", "entries": entries},
        indent=2, ensure_ascii=False), encoding="utf-8")


def _congestion_for(round_spec: str) -> dict:
    """{team: True} de los equipos marcados con carga para esta ronda."""
    doc = _load(CONGESTION_JSON)
    return {t: True for t, v in (doc.get(round_spec) or {}).items() if v}


def _market_pick(p1: float, px: float, p2: float) -> str:
    return max((("1", p1), ("X", px), ("2", p2)), key=lambda kv: kv[1])[0]


def cmd_log(round_spec: str) -> None:
    spec = round_spec.strip().lower()
    fit, mcfg, rules, elos, altitudes = _load_model()
    fx_doc = json.loads(FIXTURES_JSON.read_text(encoding="utf-8"))
    odds = _load(ODDS_H2H_JSON).get("matches", {})
    if not odds:
        raise SystemExit("Falta odds_h2h.json (corre ingest.ligamx_odds): sin mercado no hay qué comparar.")
    congestion = _congestion_for(spec)

    n = spec[1:] if spec.startswith("j") and spec[1:].isdigit() else None
    selected = [m for m in fx_doc["matches"] if (n is None or m.get("jornada") == int(n))]

    entries = _load_tracker()
    have = {(e["round"], e["match"]) for e in entries}
    added = 0
    missing: list[str] = []
    for fx in selected:
        key = f"{fx['home']}|{fx['away']}"
        match = f"{fx['home']} vs {fx['away']}"
        if key not in odds:
            # No market line: the live snapshot only carries matches that have not
            # kicked off, so this is almost always a round logged too late. Those
            # rows can never be recovered (no historical odds feed), so surface the
            # gap instead of dropping it silently — a tracker that quietly logs 2
            # of 9 matches looks healthy while producing an unusable sample.
            if (spec, match) not in have:
                missing.append(match)
            continue
        if (spec, match) in have:
            continue
        p_model = predict_fixture(fx, fit, elos, altitudes, mcfg, rules, odds=None)
        p_blend = predict_fixture(fx, fit, elos, altitudes, mcfg, rules, odds=odds)
        if "error" in p_model or "error" in p_blend:
            continue
        o = odds[key]
        entries.append({
            "round": spec, "match": match, "home": fx["home"], "away": fx["away"],
            "commence_time": o.get("commence_time"),
            "model": {"pick": p_model["pick_1x2"], "exact": p_model["pick_exact"],
                      "p1": round(p_model["p_home_win"], 4), "px": round(p_model["p_draw"], 4),
                      "p2": round(p_model["p_away_win"], 4)},
            "blend": {"pick": p_blend["pick_1x2"], "exact": p_blend["pick_exact"],
                      "p1": round(p_blend["p_home_win"], 4), "px": round(p_blend["p_draw"], 4),
                      "p2": round(p_blend["p_away_win"], 4)},
            "market": {"pick": _market_pick(o["p1"], o["px"], o["p2"]),
                       "p1": round(o["p1"], 4), "px": round(o["px"], 4), "p2": round(o["p2"], 4)},
            "congested_home": bool(congestion.get(fx["home"])),
            "congested_away": bool(congestion.get(fx["away"])),
            "logged_at": datetime.utcnow().isoformat() + "Z",
            "result": None, "home_score": None, "away_score": None,
        })
        added += 1
    _save_tracker(entries)
    flagged = sum(1 for e in entries if e["round"] == spec and (e["congested_home"] or e["congested_away"]))
    print(f"Registrados {added} partidos de {spec} (3 fuentes c/u). "
          f"{flagged} con equipo marcado por congestión. Tracker: {len(entries)} entradas.")
    if missing:
        print(f"  ⚠ {len(missing)} partido(s) de {spec} SIN línea en el snapshot y por tanto "
              f"fuera del tracker para siempre (no hay feed histórico de odds): "
              f"{', '.join(missing[:4])}{' …' if len(missing) > 4 else ''}.")
        print(f"    Se registra al generar los picks; si ves esto, la ronda se logueó "
              f"después del kickoff.")


def cmd_settle() -> None:
    fx_doc = json.loads(FIXTURES_JSON.read_text(encoding="utf-8"))
    fx_by = {f"{m['home']} vs {m['away']}": m for m in fx_doc["matches"]}
    _, _, rules, _, _ = _load_model()
    entries = _load_tracker()
    n = 0
    for e in entries:
        if e["result"] is not None:
            continue
        fx = fx_by.get(e["match"])
        if not fx or fx.get("home_score") is None:
            continue
        hs, as_ = fx["home_score"], fx["away_score"]
        e["home_score"], e["away_score"] = hs, as_
        e["result"] = "1" if hs > as_ else ("2" if as_ > hs else "X")
        for src in ("model", "blend"):
            s = e[src]
            s["hit"] = s["pick"] == e["result"]
            s["points"] = score_actual(hs, as_, s["pick"], s["exact"], rules)
        m = e["market"]
        m["hit"] = m["pick"] == e["result"]
        m["points"] = score_actual(hs, as_, m["pick"], _NO_EXACT, rules)  # solo 1X2
        n += 1
    _save_tracker(entries)
    print(f"Liquidados {n} partidos con resultado conocido.")


def _agg(entries: list[dict]) -> dict:
    settled = [e for e in entries if e.get("result") is not None]
    out = {"n": len(settled), "sources": {}}
    for src in ("model", "blend", "market"):
        hits = sum(1 for e in settled if e[src].get("hit"))
        pts = sum(e[src].get("points", 0) for e in settled)
        exact = sum(1 for e in settled if src != "market"
                    and e[src].get("exact") == f"{e['home_score']}-{e['away_score']}")
        out["sources"][src] = {
            "hit_1x2": hits, "hit_rate": (hits / len(settled)) if settled else None,
            "points": pts, "exactos": exact,
        }
    # congestion split (por equipo-partido marcado): acierto del blend cuando el
    # LOCAL o VISITA venían con carga vs cuando no.
    cong = [e for e in settled if e["congested_home"] or e["congested_away"]]
    non = [e for e in settled if not (e["congested_home"] or e["congested_away"])]
    def rate(xs):
        return (sum(1 for e in xs if e["blend"].get("hit")) / len(xs)) if xs else None
    out["congestion"] = {"n_cong": len(cong), "n_non": len(non),
                         "blend_hit_cong": rate(cong), "blend_hit_non": rate(non)}
    return out


def cmd_report() -> None:
    entries = _load_tracker()
    if not entries:
        print("Tracker vacío. Corre `log --round jN` primero.")
        return
    a = _agg(entries)
    print(f"\nTracker de fuentes — {a['n']} partidos liquidados "
          f"({len(entries)} registrados)")
    if a["n"]:
        print(f"  {'fuente':<12}{'acierto 1X2':>13}{'puntos':>9}{'exactos':>9}")
        for src, lab in (("model", "modelo solo"), ("blend", "blend 55%"), ("market", "mercado solo")):
            s = a["sources"][src]
            hr = f"{s['hit_rate']*100:.1f}%" if s["hit_rate"] is not None else "—"
            ex = "n/a" if src == "market" else str(s["exactos"])
            print(f"  {lab:<12}{hr:>13}{s['points']:>9}{ex:>9}")
        best = max(a["sources"], key=lambda s: a["sources"][s]["hit_1x2"])
        verdict = ("aún pocos partidos — sigue registrando" if a["n"] < 27 else
                   "mercado-solo lidera → súbele peso al mercado (>0.55)" if best == "market" else
                   "modelo-solo lidera → bájale peso al mercado (<0.55)" if best == "model" else
                   "el blend lidera → 0.55 va bien")
        print(f"  Veredicto (1X2): {verdict}")
        c = a["congestion"]
        if c["n_cong"]:
            hc = f"{c['blend_hit_cong']*100:.0f}%" if c["blend_hit_cong"] is not None else "—"
            hn = f"{c['blend_hit_non']*100:.0f}%" if c["blend_hit_non"] is not None else "—"
            print(f"  Congestión: acierto del blend con carga {hc} (n={c['n_cong']}) "
                  f"vs sin carga {hn} (n={c['n_non']}) — se necesita n grande para leerlo")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "ligamx_sources.json").write_text(
        json.dumps({"stats": a, "entries": entries}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {OUTPUTS_DIR / 'ligamx_sources.json'}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Tracker de fuentes (modelo/blend/mercado) Liga MX.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("log", help="Registra las 3 fuentes de una ronda.")
    pl.add_argument("--round", required=True, help="j1..j17")
    sub.add_parser("settle", help="Liquida acierto 1X2 + puntos con resultados.")
    sub.add_parser("report", help="Acumulado por fuente + veredicto del peso del mercado.")
    args = p.parse_args(argv)
    if args.cmd == "log":
        cmd_log(args.round)
    elif args.cmd == "settle":
        cmd_settle()
    elif args.cmd == "report":
        cmd_report()


if __name__ == "__main__":
    main()
