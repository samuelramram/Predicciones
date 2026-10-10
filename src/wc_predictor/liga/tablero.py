"""Tablero semanal de la liga: cómo le fue a todos y cuánta feria (ficticia) trae cada bot.

Lee el libro sellado y los resultados (como el Árbitro) y arma un HTML para el
teléfono más un resumen en texto para Telegram:

- **Puntos** de quiniela por jornada de todos (Samuel incluido) y el mano a mano
  con z pareado.
- **Cartera** de cada bot: arranca en 1,000 y cada apuesta de valor sellada mueve
  10 unidades al momio sellado. Saldo jornada por jornada.
- **Por qué**: para cada bot se comparan tres números en la misma moneda:
  lo que el bot ESPERABA ganar (su ventaja sellada), lo que valían esas apuestas
  según la **línea de cierre** (CLV: el mercado ya con toda la información) y lo que
  de verdad salió. Si el cierre se movió en su contra, la ventaja era imaginaria;
  si le ganó al cierre y aun así perdió, fue varianza. El z dice cuánto de la
  diferencia entre "lo justo al cierre" y "lo que salió" es suerte.

``--auto`` es para la automatización diaria: manda tablero cuando una jornada
ya tiene TODOS sus resultados y no se ha reportado, y los lunes aunque falte algo.

Run:
    python -m wc_predictor.liga.tablero               # genera $LIGA_HOME/tablero/tablero.html
    python -m wc_predictor.liga.tablero --auto        # solo si hay novedad
"""
from __future__ import annotations

import argparse
import html
import itertools
import json
import math
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from wc_predictor.liga import arbitro, seal
from wc_predictor.liga.paths import liga_home

START = 1000.0
STAKE = arbitro.STAKE
MX = ZoneInfo("America/Mexico_City")
MARKET_NAME = {"1x2": "1X2", "ou25": "Over/Under 2.5", "ah": "Hándicap asiático"}
BOT_ORDER = ("samuel", "calibrado", "estadistico", "borrego", "reportero")
BOT_BLURB = {
    "calibrado": "modelo + 90% mercado en Europa (55% en Liga MX)",
    "estadistico": "modelo puro, no ve el mercado",
    "borrego": "copia al mercado",
    "reportero": "calibrado + noticias que investiga Claudio",
}


# ── apuestas ─────────────────────────────────────────────────────────────────
def _fair(q_side: float, q_other: float) -> float:
    """Devigged probability of one side of a two-way price."""
    a, b = 1 / q_side, 1 / q_other
    return a / (a + b)


def closing_prob(bet: dict, res: dict) -> float | None:
    """Fair probability of the sealed side at the CLOSE, or None if the closing
    line is missing (Liga MX has no totals) or moved to another AH line."""
    m, side = bet["market"], bet["side"]
    if m == "1x2":
        p = res.get({"1": "fair_p1", "X": "fair_px", "2": "fair_p2"}[side])
    elif m == "ou25":
        po = res.get("fair_over25")
        p = None if po in (None, "") else (po if side == "over2.5" else 1 - po)
    elif m == "ah":
        who, line = side.split()
        cl, qh, qa = res.get("ah_line"), res.get("avg_ahh"), res.get("avg_aha")
        if cl in (None, "") or not qh or not qa:
            return None
        if abs((cl if who == "home" else -cl) - float(line)) > 1e-9:
            return None
        p = _fair(qh, qa) if who == "home" else _fair(qa, qh)
    else:
        return None
    return float(p) if p not in (None, "") else None


def bet_row(bet: dict, pick: dict, res: dict) -> dict:
    hs, as_ = res["home_score"], res["away_score"]
    profit = arbitro.settle_bet(bet, hs, as_)
    pc = closing_prob(bet, res)
    clv = None if pc is None else bet["price"] * pc - 1
    return {"round": pick["round"], "league": pick["league"], "date": pick["date"],
            "match": f"{pick['home']}–{pick['away']}", "result": f"{hs}-{as_}",
            "market": bet["market"], "side": bet["side"], "price": bet["price"],
            "edge": bet.get("edge", 0.0), "p_close": pc, "clv": clv, "profit": profit}


def side_label(b: dict, match: str) -> str:
    home, away = match.split("–")
    if b["market"] == "1x2":
        return {"1": f"gana {home}", "X": "empate", "2": f"gana {away}"}[b["side"]]
    if b["market"] == "ou25":
        return "más de 2.5 goles" if b["side"] == "over2.5" else "menos de 2.5 goles"
    who, line = b["side"].split()
    return f"{home if who == 'home' else away} {line}"


def bet_reason(b: dict) -> str:
    """One line: what the bot saw, what the close said, what happened."""
    pm = (1 + b["edge"]) / b["price"]
    txt = f"momio {b['price']:.2f}; el bot veía +{b['edge']:.1%} de ventaja"
    if b["market"] != "ah":
        txt += f" (le daba {pm:.0%})"
    if b["clv"] is not None:
        txt += (f"; al cierre lo justo era {b['p_close']:.0%} → "
                + ("le ganó a la línea" if b["clv"] > 0 else "el mercado se le fue en contra")
                + f" (CLV {b['clv']:+.0%})")
    return txt


# ── armado ───────────────────────────────────────────────────────────────────
def build(records: list[dict], results: list[dict], today: date | None = None) -> dict:
    today = today or datetime.now(MX).date()
    idx = arbitro.results_index(results)
    picks = arbitro.collect(records)
    first_date: dict[str, str] = {}
    seen: dict[str, dict[tuple, bool]] = defaultdict(dict)          # round → match → ¿tiene resultado?
    pts: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    bets: dict[str, list[dict]] = defaultdict(list)
    n_bets_pending: dict[str, int] = defaultdict(int)
    for who, ps in picks.items():
        for p in ps.values():
            rnd = p["round"]
            first_date[rnd] = min(first_date.get(rnd, p["date"]), p["date"])
            res = arbitro.find_result(idx, p)
            seen[rnd][(p["league"], p["home"], p["away"], p["date"])] = res is not None
            if res is None:
                n_bets_pending[who] += len(p.get("value_bets", []))
                continue
            hs, as_ = res["home_score"], res["away_score"]
            pts[who][rnd].append(arbitro.score_actual(hs, as_, p["pick_1x2"], p["pick_exact"], arbitro.RULES))
            for b in p.get("value_bets", []):
                bets[who].append(bet_row(b, {**p, "round": rnd}, res))
    status = {r: [sum(m.values()), len(m)] for r, m in seen.items()}
    rounds = sorted(first_date, key=lambda r: (first_date[r], r))
    who_all = sorted(picks, key=lambda w: (BOT_ORDER.index(w) if w in BOT_ORDER else 99, w))

    table = arbitro.build_table(arbitro.score(picks, idx))
    people = []
    for w in who_all:
        per = {r: sum(pts[w].get(r, [])) for r in rounds}
        nm = sum(len(v) for v in pts[w].values())
        ex = sum(1 for v in pts[w].values() for x in v if x >= arbitro.RULES.points_exact)
        mm = table["mano_a_mano"].get(w, {})
        people.append({"who": w, "per_round": per, "points": sum(per.values()), "n": nm,
                       "exactos": ex, "vs_samuel": mm.get("samuel_menos_bot"), "z": mm.get("z"),
                       "mm_n": mm.get("n")})

    wallets = []
    for w in who_all:
        if w in arbitro.HUMANS:
            continue
        bs = bets[w]
        series, bal = [], START
        for r in rounds:
            bal += sum(b["profit"] for b in bs if b["round"] == r)
            series.append(round(bal, 1))
        wallets.append({"who": w, "balance": round(bal, 1), "series": series,
                        "last_change": round(series[-1] - (series[-2] if len(series) > 1 else START), 1)
                        if series else 0.0,
                        "pending_bets": n_bets_pending[w], **explain(bs)})
    latest = [r for r in rounds if status[r][0]]
    return {"generated": datetime.now(MX).strftime("%Y-%m-%d %H:%M"), "today": today.isoformat(),
            "rounds": [{"id": r, "date": first_date[r], "done": status[r][0], "total": status[r][1]}
                       for r in rounds],
            "latest": latest[-1] if latest else None,
            "people": people, "wallets": wallets, "vs_calibrado": table.get("vs_calibrado", {})}


def explain(bs: list[dict]) -> dict:
    """Money breakdown + the three-way comparison expected / close / actual."""
    out: dict = {"n": len(bs), "profit": round(sum(b["profit"] for b in bs), 1)}
    out["roi"] = out["profit"] / (STAKE * len(bs)) if bs else 0.0
    out["wins"] = sum(1 for b in bs if b["profit"] > 0)
    by_mkt: dict[str, list[float]] = defaultdict(list)
    by_lg: dict[str, list[float]] = defaultdict(list)
    for b in bs:
        by_mkt[b["market"]].append(b["profit"])
        by_lg["Liga MX" if b["league"] == "MX" else "Europa"].append(b["profit"])
    out["by_market"] = {m: {"n": len(v), "profit": round(sum(v), 1)} for m, v in by_mkt.items()}
    out["by_league"] = {m: {"n": len(v), "profit": round(sum(v), 1)} for m, v in by_lg.items()}
    out["expected"] = round(STAKE * sum(b["edge"] for b in bs), 1)
    wc = [b for b in bs if b["clv"] is not None]
    out["n_clv"] = len(wc)
    out["clv"] = sum(b["clv"] for b in wc) / len(wc) if wc else None
    out["beat_close"] = sum(1 for b in wc if b["clv"] > 0)
    out["close_expected"] = round(STAKE * sum(b["clv"] for b in wc), 1)
    out["actual_on_clv"] = round(sum(b["profit"] for b in wc), 1)
    var = sum((STAKE * b["price"]) ** 2 * min(max(b["p_close"], 0.01), 0.99)
              * (1 - min(max(b["p_close"], 0.01), 0.99)) for b in wc)
    out["luck_z"] = ((out["actual_on_clv"] - out["close_expected"]) / math.sqrt(var)) if var > 0 else None
    ranked = sorted(bs, key=lambda b: b["profit"])
    out["worst"] = ranked[:3]
    out["best"] = [b for b in ranked[::-1][:3] if b["profit"] > 0]
    out["verdict"] = verdict(out)
    return out


def verdict(e: dict) -> list[str]:
    if not e["n"]:
        return ["No apostó: no encontró ningún precio que según él valiera la pena."]
    v = []
    if e["n"] < 30:
        v.append(f"Muestra chica ({e['n']} apuestas): todavía es casi puro volado; "
                 "el veredicto serio sale con cientos.")
    if e["clv"] is not None and e["n_clv"] >= 3:
        if e["clv"] < -0.01:
            v.append(f"Compra caro: al cierre el mercado se movió en su contra (CLV promedio "
                     f"{e['clv']:+.1%}, solo {e['beat_close']} de {e['n_clv']} le ganaron a la línea). "
                     f"Esperaba ganar {e['expected']:+.0f}; lo justo al cierre era {e['close_expected']:+.0f}. "
                     "Su ventaja era el modelo creyéndose de más.")
        elif e["clv"] > 0.01:
            v.append(f"Le gana a la línea de cierre (CLV promedio {e['clv']:+.1%}, "
                     f"{e['beat_close']} de {e['n_clv']}): eso es la señal de una ventaja real. "
                     "Si va perdiendo, es varianza; a la larga eso paga.")
        else:
            v.append(f"Compra al precio justo (CLV {e['clv']:+.1%}): no le gana ni le pierde al mercado; "
                     "a la larga se lo come el margen de la casa.")
    if e["n_clv"] < e["n"]:
        v.append(f"{e['n'] - e['n_clv']} apuestas todavía sin momio de cierre (llega cuando Football-Data "
                 "publique el partido); su CLV entra en el siguiente tablero.")
    if e["luck_z"] is not None and e["n_clv"] >= 3:
        diff = e["actual_on_clv"] - e["close_expected"]
        tag = "con suerte" if diff > 0 else "salado"
        if abs(e["luck_z"]) < 2:
            v.append(f"Salió {diff:+.0f} contra lo justo: dentro de lo que da la suerte (z {e['luck_z']:+.1f}).")
        else:
            v.append(f"Salió {diff:+.0f} contra lo justo: anda {tag} de verdad (z {e['luck_z']:+.1f}).")
    if e["by_market"]:
        m, d = min(e["by_market"].items(), key=lambda kv: kv[1]["profit"])
        if d["profit"] < 0:
            v.append(f"Donde más se le fue la feria: {MARKET_NAME[m]} ({d['profit']:+.0f} en {d['n']} apuestas).")
    return v


# ── salida ───────────────────────────────────────────────────────────────────
def render_md(d: dict) -> str:
    rl = d["latest"] or "—"
    lines = [f"Tablero de la liga · {d['today']} (última jornada con resultados: {rl})", ""]
    lines.append("Puntos (quiniela):")
    for p in sorted(d["people"], key=lambda p: -p["points"]):
        z = f" · Samuel {p['vs_samuel']:+g} vs él (z {p['z']})" if p["vs_samuel"] is not None else ""
        lines.append(f"- {p['who']}: {p['points']} pts en {p['n']} partidos, {p['exactos']} exactos{z}")
    lines += ["", "Feria ficticia (arrancaron con 1,000; 10 por apuesta):"]
    for w in sorted(d["wallets"], key=lambda w: -w["balance"]):
        clv = f", CLV {w['clv']:+.1%}" if w["clv"] is not None else ""
        lines.append(f"- {w['who']}: {w['balance']:,.0f} ({w['last_change']:+.0f} la última jornada; "
                     f"{w['n']} apuestas, ROI {w['roi']:+.1%}{clv})")
        lines += [f"    · {t}" for t in w["verdict"]]
    pend = [r for r in d["rounds"] if r["done"] < r["total"]]
    if pend:
        lines += ["", "Pendientes: " + ", ".join(f"{r['id']} ({r['total'] - r['done']} sin resultado)"
                                                for r in pend)]
    return "\n".join(lines) + "\n"


def _e(x) -> str:
    return html.escape(str(x))


def _money(x: float) -> str:
    return f"{x:+,.0f}"


def _chart(d: dict) -> str:
    """Bankroll lines, one per bot, inline SVG."""
    labels = [r["id"].split("-", 2)[-1] for r in d["rounds"]]
    ws = d["wallets"]
    if not ws or not labels:
        return ""
    vals = [START] + [v for w in ws for v in w["series"]]
    lo, hi = min(vals), max(vals)
    pad = max(10.0, (hi - lo) * 0.15)
    lo, hi = lo - pad, hi + pad
    W, H, L, R, T, B = 360, 210, 40, 74, 10, 24
    n = len(labels) + 1
    xs = [L + i * (W - L - R) / max(n - 1, 1) for i in range(n)]

    def y(v): return T + (hi - v) * (H - T - B) / (hi - lo)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Saldo de cada bot por jornada">']
    for t in (lo + pad, START, hi - pad):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/>'
                   f'<text x="{L - 6}" y="{y(t) + 4:.1f}" class="ax" text-anchor="end">{t:,.0f}</text>')
    for i, lab in enumerate(["inicio"] + labels):
        out.append(f'<text x="{xs[i]:.1f}" y="{H - 8}" class="ax" text-anchor="middle">{_e(lab)}</text>')
    # end labels: push apart so close balances don't overlap
    ly = {k: y(w["series"][-1]) + 4 for k, w in enumerate(ws)}
    order = sorted(ly, key=ly.get)
    for a, b in itertools.pairwise(order):
        ly[b] = max(ly[b], ly[a] + 13)
    for k, w in enumerate(ws):
        pts = [START] + w["series"]
        path = " ".join(f"{'M' if i == 0 else 'L'}{xs[i]:.1f},{y(v):.1f}" for i, v in enumerate(pts))
        out.append(f'<path d="{path}" class="ln c{k}"/>')
        out.append(f'<circle cx="{xs[-1]:.1f}" cy="{y(pts[-1]):.1f}" r="4" class="dot c{k}"/>')
        out.append(f'<text x="{xs[-1] + 8:.1f}" y="{ly[k]:.1f}" class="lab c{k}">{_e(w["who"])}</text>')
    out.append("</svg>")
    return "".join(out)


def _bets_list(title: str, bs: list[dict]) -> str:
    if not bs:
        return ""
    li = "".join(
        f'<li><b class="{"pos" if b["profit"] > 0 else "neg"}">{_money(b["profit"])}</b> '
        f'{_e(b["match"])} {_e(b["result"])} · {_e(side_label(b, b["match"]))}'
        f'<br><span class="mut">{_e(bet_reason(b))}</span></li>' for b in bs)
    return f"<h4>{title}</h4><ul class='bets'>{li}</ul>"


def render_html(d: dict, demo: bool = False) -> str:
    rounds = d["rounds"]
    heads = "".join(f"<th>{_e(r['id'].split('-', 2)[-1])}</th>" for r in rounds)
    prow = ""
    for p in sorted(d["people"], key=lambda p: -p["points"]):
        cells = "".join(f"<td>{p['per_round'][r['id']]}</td>" for r in rounds)
        mm = (f"{p['vs_samuel']:+g} <span class='mut'>(z {p['z']})</span>"
              if p["vs_samuel"] is not None else "—")
        me = " class='me'" if p["who"] in arbitro.HUMANS else ""
        prow += (f"<tr{me}><td>{_e(p['who'])}</td>{cells}<td><b>{p['points']}</b></td>"
                 f"<td>{p['exactos']}</td><td>{p['n']}</td><td>{mm}</td></tr>")
    cards = ""
    for k, w in enumerate(sorted(d["wallets"], key=lambda w: -w["balance"])):
        clv = f"{w['clv']:+.1%}" if w["clv"] is not None else "—"
        mk = "".join(f"<li>{_e(MARKET_NAME[m])}: <b class='{'pos' if v['profit'] >= 0 else 'neg'}'>"
                     f"{_money(v['profit'])}</b> <span class='mut'>({v['n']})</span></li>"
                     for m, v in w["by_market"].items()) or "<li class='mut'>sin apuestas resueltas</li>"
        lg = " · ".join(f"{_e(m)} {_money(v['profit'])}" for m, v in w["by_league"].items())
        why = "".join(f"<li>{_e(t)}</li>" for t in w["verdict"])
        k2 = [x["who"] for x in d["wallets"]].index(w["who"])
        cards += f"""
<section class="card">
  <div class="top"><span class="sw c{k2}"></span><h3>{_e(w['who'])}</h3>
    <span class="mut">{_e(BOT_BLURB.get(w['who'], ''))}</span></div>
  <div class="kpis">
    <div><small>Saldo</small><b class="big">{w['balance']:,.0f}</b></div>
    <div><small>Última jornada</small><b class="{'pos' if w['last_change'] >= 0 else 'neg'}">{_money(w['last_change'])}</b></div>
    <div><small>ROI</small><b>{w['roi']:+.1%}</b></div>
    <div><small>CLV</small><b>{clv}</b></div>
  </div>
  <p class="mut">{w['n']} apuestas resueltas, {w['wins']} ganadas · {w['pending_bets']} por resolver{(' · ' + lg) if lg else ''}</p>
  <div class="trio">
    <div><small>Esperaba</small><b>{_money(w['expected'])}</b></div>
    <div><small>Justo al cierre</small><b>{_money(w['close_expected'])}</b></div>
    <div><small>Salió</small><b>{_money(w['profit'])}</b></div>
  </div>
  <h4>Por qué</h4><ul class="why">{why}</ul>
  <h4>Por mercado</h4><ul class="mk">{mk}</ul>
  {_bets_list('Las que más dolieron', [b for b in w['worst'] if b['profit'] < 0])}
  {_bets_list('Las que más pagaron', w['best'])}
</section>"""
    vc = "".join(f"<li><b>{_e(k)}</b> vs calibrado en {v['n']} partidos: {v['puntos']:+g} pts (z {v['z_puntos']}),"
                 f" Brier {v['brier_1x2']:+.4f} (z {v['z_brier']})</li>" for k, v in d["vs_calibrado"].items())
    pend = [r for r in rounds if r["done"] < r["total"]]
    pend_txt = ("<p class='mut'>Pendientes de resultado: " + ", ".join(
        f"{_e(r['id'])} ({r['total'] - r['done']})" for r in pend) + ". Football-Data publica con días de rezago.</p>"
                ) if pend else ""
    banner = ("<div class='demo'>DEMO: resultados SIMULADOS para ver el diseño. "
              "Ningún número de esta página es real.</div>") if demo else ""
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tablero de la liga</title>
<style>
:root{{--bg:#f6f5f1;--fg:#1d1d1b;--mut:#6b6a66;--card:#fff;--line:#e3e1da;--pos:#1a7f4b;--neg:#c0392b;
--c0:#2f6fdf;--c1:#e07b00;--c2:#8e44ad;--c3:#16a085;--c4:#c0392b}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#151514;--fg:#ecebe6;--mut:#9c9a93;
--card:#1f1f1d;--line:#34332f;--pos:#4cc38a;--neg:#ff7b6b;--c0:#6c9cff;--c1:#ffa94d;--c2:#c38df0;--c3:#4fd1b5;--c4:#ff7b6b}}}}
:root[data-theme="dark"]{{--bg:#151514;--fg:#ecebe6;--mut:#9c9a93;--card:#1f1f1d;--line:#34332f;--pos:#4cc38a;
--neg:#ff7b6b;--c0:#6c9cff;--c1:#ffa94d;--c2:#c38df0;--c3:#4fd1b5;--c4:#ff7b6b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:20px 16px 48px}}
h1{{font-size:24px;margin:0 0 4px}}h2{{font-size:18px;margin:28px 0 10px}}h3{{margin:0;font-size:17px}}
h4{{margin:14px 0 6px;font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}}
.mut{{color:var(--mut)}}.pos{{color:var(--pos)}}.neg{{color:var(--neg)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:12px 0}}
.top{{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}}
.sw{{width:12px;height:12px;border-radius:50%;display:inline-block;align-self:center}}
.kpis,.trio{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0 4px}}
.trio{{grid-template-columns:repeat(3,1fr);background:var(--bg);border-radius:10px;padding:10px}}
.kpis small,.trio small{{display:block;color:var(--mut);font-size:12px}}.big{{font-size:22px}}
ul{{margin:0;padding-left:18px}}.bets li,.why li{{margin:4px 0}}.mk{{display:flex;gap:14px;flex-wrap:wrap;padding:0;list-style:none}}
.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}tr.me td{{font-weight:600}}
svg{{width:100%;height:auto;display:block}}.grid{{stroke:var(--line)}}.ax{{fill:var(--mut);font-size:10px}}
.ln{{fill:none;stroke-width:2.5}}.lab{{font-size:11px;font-weight:600}}
{"".join(f".ln.c{i}{{stroke:var(--c{i})}}.dot.c{i},.lab.c{i}{{fill:var(--c{i})}}.sw.c{i}{{background:var(--c{i})}}" for i in range(5))}
.demo{{background:var(--neg);color:#fff;padding:10px 12px;border-radius:10px;font-weight:600;margin-bottom:12px}}
@media (max-width:520px){{.kpis{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main>
{banner}
<h1>¿Cómo nos fue?</h1>
<p class="mut">Corte {_e(d['generated'])} · última jornada con resultados: {_e(d['latest'] or '—')}</p>

<h2>Puntos de quiniela</h2>
<div class="card scroll"><table><thead><tr><th>quién</th>{heads}<th>total</th><th>exactos</th><th>partidos</th><th>Samuel − él</th></tr></thead>
<tbody>{prow}</tbody></table>
<p class="mut">"Samuel − él" cuenta solo los partidos que jugó Samuel. Con |z| menor a 2 la diferencia todavía puede ser suerte.</p></div>

<h2>La feria (ficticia)</h2>
<div class="card">{_chart(d)}
<p class="mut">Cada bot arrancó con 1,000 y pone 10 en cada apuesta donde cree ver valor, al momio que selló antes del partido.</p></div>
{cards}
{"<h2>Contra el calibrado</h2><div class='card'><ul>" + vc + "</ul></div>" if vc else ""}
{pend_txt}
<p class="mut">Cómo leer el "por qué": <b>Esperaba</b> es la ventaja que el bot creyó tener; <b>Justo al cierre</b>
es lo que valían esas mismas apuestas con el momio final, cuando el mercado ya sabe todo; <b>Salió</b> es lo que pasó.
Ganarle al cierre de forma consistente es la única señal seria de ventaja; lo demás es suerte de corto plazo.</p>
</main></body></html>"""


# ── automatización ───────────────────────────────────────────────────────────
def _state_path():
    return liga_home() / "tablero" / "enviados.json"


def should_send(d: dict, state: dict, today: date) -> tuple[bool, list[str]]:
    """New fully-resulted rounds → send. Mondays → send if anything has results
    and nothing went out today."""
    done = [r["id"] for r in d["rounds"] if r["total"] and r["done"] == r["total"]]
    new = [r for r in done if r not in state.get("rounds", [])]
    if new:
        return True, new
    if today.weekday() == 0 and d["latest"] and state.get("last") != today.isoformat():
        return True, []
    return False, []


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--auto", action="store_true",
                    help="solo genera si hay jornada nueva completa (o es lunes)")
    args = ap.parse_args(argv)
    records = seal.read_ledger(seal.LEDGER)
    ok, why = seal.verify_chain(records)
    if not ok:
        raise SystemExit(f"Libro corrupto, no armo tablero: {why}")
    today = datetime.now(MX).date()
    d = build(records, arbitro.load_results(), today)
    out = liga_home() / "tablero"
    out.mkdir(parents=True, exist_ok=True)
    state = json.loads(_state_path().read_text(encoding="utf-8")) if _state_path().exists() else {}
    if args.auto:
        send, new = should_send(d, state, today)
        if not send:
            print("SIN NOVEDAD: ninguna jornada nueva con todos sus resultados.")
            return
        state["rounds"] = sorted(set(state.get("rounds", [])) | set(new))
        state["last"] = today.isoformat()
        _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    page = out / f"tablero-{today.isoformat()}.html"
    page.write_text(render_html(d), encoding="utf-8")
    (out / "tablero.html").write_text(render_html(d), encoding="utf-8")
    (out / "tablero.json").write_text(json.dumps(d, indent=2, ensure_ascii=False, default=str),
                                      encoding="utf-8")
    md = render_md(d)
    (out / "tablero.md").write_text(md, encoding="utf-8")
    print(f"TABLERO: {page}")
    print(md)


if __name__ == "__main__":
    main()
