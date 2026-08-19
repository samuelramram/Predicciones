"""Render ONE self-contained, theme-aware HTML that carries BOTH the quiniela
(marcadores por partido) and the per-house betting boleto (stakes reales, con
O/U cuando la casa lo cotiza y hay valor). Reads:

    outputs/ligamx_picks_{round}.json   — la quiniela (pick de marcador + 1X2)
    outputs/ligamx_boleto_{round}.json  — el boleto por casa (stakes + mercados)

Usage: python scripts/render_jornada_html.py j4
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROUND = (sys.argv[1] if len(sys.argv) > 1 else "j4").lower()
ROOT = Path(__file__).resolve().parent.parent
PICKS = json.loads((ROOT / "outputs" / f"ligamx_picks_{ROUND}.json").read_text())
BOLETO = json.loads((ROOT / "outputs" / f"ligamx_boleto_{ROUND}.json").read_text())
OUT = ROOT / "outputs" / f"ligamx_{ROUND}.html"

HOUSE_HUE = {"betway": "#0aa64f", "caliente": "#e2231a"}
JNUM = ROUND[1:] if ROUND.startswith("j") else ROUND


def fmt_stamp(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(
            timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso


def clv_class(clv: float) -> str:
    if clv > 0:
        return "pos"
    if clv <= -0.10:
        return "neg-strong"
    return "neg"


# ── Quiniela section ─────────────────────────────────────────────────────────
def quiniela_rows() -> str:
    rows = []
    for p in PICKS["picks"]:
        h, a = p["home"], p["away"]
        sel = p["pick_1x2"]
        team = h if sel == "1" else (a if sel == "2" else "Empate")
        p1, px, p2 = p["p_home_win"], p["p_draw"], p["p_away_win"]
        contrarian = p.get("pool_swapped") or p.get("contrarian_actionable")
        chip = ('<span class="chip">◆ contrarian</span>' if contrarian else "")
        rows.append(f"""
      <tr>
        <td class="match"><span class="teams">{h} <span class="vs">vs</span> {a}</span>
            <span class="meta">J{JNUM} · {p['date']}</span></td>
        <td class="score">{p['pick_exact']}{chip}</td>
        <td class="pick"><span class="badge badge-{sel.lower()}">{sel}</span><span class="team">{team}</span></td>
        <td class="probcell">
          <div class="tri" role="img" aria-label="1 {p1*100:.0f}%, X {px*100:.0f}%, 2 {p2*100:.0f}%">
            <span class="seg seg1" style="width:{p1*100:.1f}%"></span>
            <span class="seg segx" style="width:{px*100:.1f}%"></span>
            <span class="seg seg2" style="width:{p2*100:.1f}%"></span>
          </div>
          <div class="trilabels"><span>{p1*100:.0f}</span><span>{px*100:.0f}</span><span>{p2*100:.0f}</span></div>
        </td>
        <td class="num ev">{p['ev']:.2f}</td>
      </tr>""")
    return "".join(rows)


ev_total = sum(p["ev"] for p in PICKS["picks"])
n_contra = sum(1 for p in PICKS["picks"] if p.get("pool_swapped") or p.get("contrarian_actionable"))


# ── Boleto section ───────────────────────────────────────────────────────────
def outcome_label(b: dict) -> tuple[str, str, str]:
    """(badge, text, market_kind) as the user reads it on the app."""
    m = b.get("market", "1X2")
    sel = b["selection"]
    if m != "1X2":                              # O/U leg
        return sel[0].upper(), f"{sel} {m.split()[-1]}", "ou"
    if sel == "1":
        return "1", b["home"], "1x2"
    if sel == "2":
        return "2", b["away"], "1x2"
    return "X", "Empate", "1x2"


def house_card(key: str, house: dict) -> str:
    hue = HOUSE_HUE.get(key, "#6b7280")
    bets = house["bets"]
    total = sum(b["stake_mxn"] for b in bets)
    budget = house["budget_mxn"]
    n_ou = sum(1 for b in bets if b.get("market", "1X2") != "1X2")
    if not bets:                        # house has no priced matches yet (e.g. Caliente manual)
        return f"""
    <section class="ticket ticket-pending" style="--house: {hue};">
      <header class="ticket-head">
        <div class="house"><span class="house-dot"></span><h3>{key.title()}</h3></div>
        <div class="budget"><span class="budget-total">${int(budget)}</span>
          <span class="budget-sub">pendiente</span></div>
      </header>
      <div class="pending-note">Falta capturar los precios de <b>{key.title()}</b> para esta jornada
      (no está en el feed de odds; se toman de la app). Mándame las capturas y lo completo.</div>
    </section>"""
    ou_note = f'<span class="ou-count">{n_ou} O/U</span>' if n_ou else '<span class="ou-count muted">sin O/U en el feed</span>'
    rows = []
    for b in bets:
        badge, text, kind = outcome_label(b)
        clv = b["clv_entry"]
        rows.append(f"""
      <tr>
        <td class="match">{b['home']} <span class="vs">vs</span> {b['away']}</td>
        <td class="pick"><span class="badge badge-{badge.lower()} {'badge-ou' if kind=='ou' else ''}">{badge}</span><span class="team">{text}</span></td>
        <td class="num price">{b['price']:.2f}</td>
        <td class="num stake">${int(b['stake_mxn'])}</td>
        <td class="num clv {clv_class(clv)}">{clv*100:+.1f}%</td>
      </tr>""")
    return f"""
    <section class="ticket" style="--house: {hue};">
      <header class="ticket-head">
        <div class="house"><span class="house-dot"></span><h3>{key.title()}</h3>{ou_note}</div>
        <div class="budget"><span class="budget-total">${int(total)}</span>
          <span class="budget-sub">de ${int(budget)} · {len(bets)} preds</span></div>
      </header>
      <div class="table-wrap"><table class="bets">
        <thead><tr><th>Partido</th><th>Pick</th><th class="num">Cuota</th><th class="num">Apuesta</th><th class="num">CLV</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
        <tfoot><tr><td colspan="3" class="foot-label">Total desplegado</td><td class="num stake foot-total">${int(total)}</td><td></td></tr></tfoot>
      </table></div>
    </section>"""


cards = "\n".join(house_card(k, v) for k, v in BOLETO["houses"].items())
grand = sum(sum(b["stake_mxn"] for b in h["bets"]) for h in BOLETO["houses"].values())
budget_total = sum(h["budget_mxn"] for h in BOLETO["houses"].values())
n_bets = sum(len(h["bets"]) for h in BOLETO["houses"].values())
n_pos_clv = sum(1 for h in BOLETO["houses"].values() for b in h["bets"] if b["clv_entry"] > 0)
pending = [k.title() for k, h in BOLETO["houses"].items() if not h["bets"]]

# Honesty note, built from the data (not hardcoded to one jornada).
_clv_line = (f"las {n_pos_clv} con CLV+ son las únicas donde el precio te favorece hoy"
             if n_pos_clv else "ninguna arranca con CLV+ (el mercado les gana el precio a todas)")
_pending_line = (f" Falta capturar los precios de {', '.join(pending)} para esta jornada "
                 f"(no está en el feed; se toma de la app) — mándame las capturas y lo completo."
                 if pending else "")
HONESTY = (f"<b>Honestidad:</b> las apuestas son acción medida sobre tu roll, <b>no un boleto +EV</b>. "
           f"La mayoría arranca con CLV ≤ 0 — el mercado les gana en precio; {_clv_line}. El valor no es "
           f"ganar esta jornada sino medir el CLV real a lo largo del torneo.{_pending_line} Las {n_bets} "
           f"apuestas cargadas quedaron registradas en el ledger con casa, precio y stake reales.")

elo_as_of = PICKS.get("elo_as_of", "?")
odds_stamp = fmt_stamp(BOLETO.get("as_of", ""))

html = f"""<title>Liga MX J{JNUM} · Quiniela y Boleto</title>
<style>
  :root {{
    --bg:#f4f2ec; --panel:#fbfaf6; --ink:#1a1c20; --ink-soft:#565a62;
    --line:#e4dfd3; --line-strong:#cfc8b7; --accent:#157a4e;
    --pos:#157a4e; --neg:#9a7b1d; --neg-strong:#b0431f;
    --seg1:#2f8f5f; --segx:#c9a233; --seg2:#5b6472;
    --b1-bg:#dceee2; --b1-ink:#12603c; --bx-bg:#efe6cf; --bx-ink:#86611a;
    --b2-bg:#e4e6ec; --b2-ink:#3f4658; --bou-bg:#dde7f0; --bou-ink:#2c5975;
    --shadow:0 1px 2px rgba(24,22,16,.05), 0 10px 26px -14px rgba(24,22,16,.22);
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg:#14161a; --panel:#1c1f25; --ink:#eceae4; --ink-soft:#9aa0aa;
      --line:#2b2f36; --line-strong:#3a3f48; --accent:#3fb87e;
      --pos:#3fb87e; --neg:#d1a63f; --neg-strong:#e0764a;
      --seg1:#3fb87e; --segx:#d9b64a; --seg2:#7b8494;
      --b1-bg:#17352a; --b1-ink:#6fd6a3; --bx-bg:#362e18; --bx-ink:#e0bd6b;
      --b2-bg:#262b36; --b2-ink:#aeb6c6; --bou-bg:#1e3341; --bou-ink:#8fc3e0;
      --shadow:0 1px 2px rgba(0,0,0,.3), 0 12px 30px -16px rgba(0,0,0,.6);
    }}
  }}
  :root[data-theme="dark"] {{
    --bg:#14161a; --panel:#1c1f25; --ink:#eceae4; --ink-soft:#9aa0aa;
    --line:#2b2f36; --line-strong:#3a3f48; --accent:#3fb87e;
    --pos:#3fb87e; --neg:#d1a63f; --neg-strong:#e0764a;
    --seg1:#3fb87e; --segx:#d9b64a; --seg2:#7b8494;
    --b1-bg:#17352a; --b1-ink:#6fd6a3; --bx-bg:#362e18; --bx-ink:#e0bd6b;
    --b2-bg:#262b36; --b2-ink:#aeb6c6; --bou-bg:#1e3341; --bou-ink:#8fc3e0;
    --shadow:0 1px 2px rgba(0,0,0,.3), 0 12px 30px -16px rgba(0,0,0,.6);
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); line-height:1.5;
    font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased; }}
  .wrap {{ max-width:980px; margin:0 auto; padding:clamp(20px,4vw,48px); }}
  .masthead {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:6px 16px;
    border-bottom:2px solid var(--ink); padding-bottom:14px; }}
  .masthead h1 {{ font-size:clamp(1.5rem,4vw,2.2rem); margin:0; letter-spacing:-.02em; font-weight:800; }}
  .masthead .j {{ color:var(--accent); }}
  .masthead .stamp {{ margin-left:auto; font-size:.76rem; color:var(--ink-soft);
    font-variant-numeric:tabular-nums; text-align:right; }}
  h2.sec {{ font-size:1.15rem; font-weight:800; letter-spacing:-.01em; margin:34px 0 4px;
    display:flex; align-items:baseline; gap:10px; }}
  h2.sec .tag {{ font-size:.7rem; font-weight:700; text-transform:uppercase; letter-spacing:.05em;
    color:var(--accent); border:1px solid color-mix(in srgb,var(--accent) 40%,transparent);
    border-radius:20px; padding:2px 9px; }}
  .sec-note {{ color:var(--ink-soft); font-size:.9rem; margin:2px 0 14px; max-width:64ch; }}
  .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:14px;
    box-shadow:var(--shadow); overflow:hidden; }}
  .table-wrap {{ overflow-x:auto; }}
  table {{ width:100%; border-collapse:collapse; font-size:.9rem; }}
  th {{ text-align:left; font-size:.67rem; text-transform:uppercase; letter-spacing:.06em;
    color:var(--ink-soft); font-weight:700; padding:11px 8px; border-bottom:1px solid var(--line); }}
  td {{ padding:11px 8px; border-bottom:1px solid var(--line); vertical-align:middle; }}
  th:first-child, td:first-child {{ padding-left:18px; }}
  th:last-child, td:last-child {{ padding-right:18px; }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .match .teams {{ font-weight:600; display:block; }}
  .match .vs {{ color:var(--ink-soft); font-weight:400; font-size:.82em; margin:0 3px; }}
  .match .meta {{ font-size:.72rem; color:var(--ink-soft); }}
  .score {{ font-weight:800; font-size:1.15rem; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .chip {{ display:inline-block; margin-left:8px; font-size:.62rem; font-weight:700; vertical-align:middle;
    text-transform:uppercase; letter-spacing:.04em; color:var(--accent);
    border:1px solid color-mix(in srgb,var(--accent) 35%,transparent); border-radius:20px; padding:1px 7px; }}
  .pick {{ white-space:nowrap; }}
  .badge {{ display:inline-block; min-width:20px; text-align:center; font-weight:800; font-size:.75rem;
    padding:2px 6px; border-radius:5px; margin-right:7px; }}
  .badge-1 {{ background:var(--b1-bg); color:var(--b1-ink); }}
  .badge-x {{ background:var(--bx-bg); color:var(--bx-ink); }}
  .badge-2 {{ background:var(--b2-bg); color:var(--b2-ink); }}
  .badge-o, .badge-u {{ background:var(--bou-bg); color:var(--bou-ink); }}
  .team {{ font-weight:600; }}
  .probcell {{ min-width:120px; }}
  .tri {{ display:flex; height:8px; border-radius:5px; overflow:hidden; background:var(--line);
    box-shadow:inset 0 0 0 1px var(--line); }}
  .seg {{ display:block; height:100%; }}
  .seg1 {{ background:var(--seg1); }} .segx {{ background:var(--segx); }} .seg2 {{ background:var(--seg2); }}
  .trilabels {{ display:flex; justify-content:space-between; font-size:.62rem; color:var(--ink-soft);
    font-variant-numeric:tabular-nums; margin-top:3px; }}
  .ev {{ font-weight:700; }}
  tfoot td {{ border-bottom:none; }}
  .quiniela-foot {{ display:flex; flex-wrap:wrap; gap:6px 18px; padding:12px 18px; font-size:.82rem;
    color:var(--ink-soft); border-top:2px solid var(--line-strong); background:var(--panel); }}
  .quiniela-foot b {{ color:var(--ink); }}
  /* Boleto */
  .grand {{ display:flex; align-items:baseline; gap:10px; margin:8px 0 2px; font-variant-numeric:tabular-nums; }}
  .grand b {{ font-size:1.35rem; font-weight:800; }}
  .grand span {{ color:var(--ink-soft); font-size:.88rem; }}
  .tickets {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(330px,1fr)); gap:18px; margin-top:14px; }}
  .ticket-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px;
    padding:14px 16px; border-bottom:1px solid var(--line); }}
  .house {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
  .house-dot {{ width:11px; height:11px; border-radius:50%; background:var(--house);
    box-shadow:0 0 0 3px color-mix(in srgb,var(--house) 20%,transparent); }}
  .house h3 {{ margin:0; font-size:1.1rem; font-weight:800; }}
  .ou-count {{ font-size:.66rem; font-weight:700; text-transform:uppercase; letter-spacing:.04em;
    color:var(--bou-ink); background:var(--bou-bg); border-radius:20px; padding:2px 8px; }}
  .ou-count.muted {{ color:var(--ink-soft); background:var(--line); }}
  .budget {{ text-align:right; line-height:1.15; }}
  .budget-total {{ display:block; font-size:1.4rem; font-weight:800; font-variant-numeric:tabular-nums; }}
  .budget-sub {{ font-size:.7rem; color:var(--ink-soft); text-transform:uppercase; letter-spacing:.04em; }}
  table.bets .stake {{ font-weight:800; font-size:1rem; }}
  table.bets .price {{ color:var(--ink-soft); }}
  .clv {{ font-size:.82rem; }}
  .clv.pos {{ color:var(--pos); font-weight:700; }} .clv.neg {{ color:var(--neg); }} .clv.neg-strong {{ color:var(--neg-strong); }}
  table.bets tfoot td {{ border-top:2px solid var(--line-strong); padding-top:12px; }}
  .foot-label {{ text-transform:uppercase; font-size:.68rem; letter-spacing:.05em; color:var(--ink-soft); font-weight:700; }}
  .foot-total {{ font-size:1.05rem; font-weight:800; }}
  .note {{ margin-top:22px; padding:16px 18px; border:1px solid var(--line); border-left:3px solid var(--neg);
    border-radius:10px; background:var(--panel); font-size:.88rem; color:var(--ink-soft); }}
  .note b {{ color:var(--ink); }}
  .ticket {{ background:var(--panel); border:1px solid var(--line); border-radius:14px; box-shadow:var(--shadow); overflow:hidden; }}
  .ticket-pending {{ border-style:dashed; box-shadow:none; }}
  .pending-note {{ padding:16px 18px; font-size:.86rem; color:var(--ink-soft); line-height:1.5; }}
  .pending-note b {{ color:var(--house); }}
  .legend {{ margin-top:12px; font-size:.76rem; color:var(--ink-soft); display:flex; flex-wrap:wrap; gap:5px 18px; }}
</style>

<div class="wrap">
  <header class="masthead">
    <h1>Liga MX · <span class="j">Jornada {JNUM}</span></h1>
    <span class="stamp">Elo al {elo_as_of}<br>Cuotas {odds_stamp}</span>
  </header>

  <h2 class="sec">La quiniela <span class="tag">2 pts exacto · 1 pt 1X2</span></h2>
  <p class="sec-note">Marcador EV-óptimo por partido (objetivo pool). La barra es P(1&nbsp;/&nbsp;X&nbsp;/&nbsp;2); ◆ marca los swaps contrarian para diferenciarte del pool.</p>
  <div class="panel">
    <div class="table-wrap"><table>
      <thead><tr><th>Partido</th><th>Marcador</th><th>1X2</th><th>Prob 1 · X · 2</th><th class="num">EV</th></tr></thead>
      <tbody>{quiniela_rows()}</tbody>
    </table></div>
    <div class="quiniela-foot">
      <span><b>{len(PICKS['picks'])}</b> partidos</span>
      <span>EV total <b>{ev_total:.2f}</b> / {len(PICKS['picks'])*2} máx</span>
      <span><b>{n_contra}</b> swaps contrarian ◆</span>
    </div>
  </div>

  <h2 class="sec">Apuestas por casa <span class="tag">tu dinero real</span></h2>
  <p class="sec-note">Tu presupuesto <b>completo</b> por casa, un pick por partido más O/U donde la casa lo cotiza y hay valor. Mínimo $20 en unidades de $20 — la columna <b>Apuesta</b> ya respeta tu bankroll, no el ¼-Kelly crudo.</p>
  <div class="grand"><b>${int(grand)}</b><span>desplegados de ${int(budget_total)} · {n_bets} predicciones · {n_pos_clv} con CLV+{' · ' + ', '.join(pending) + ' pendiente' if pending else ''}</span></div>
  <div class="tickets">{cards}</div>

  <div class="legend">
    <span><b>1</b> local · <b>X</b> empate · <b>2</b> visita · <b>O/U</b> goles</span>
    <span><b>Cuota</b> = momio decimal de la casa</span>
    <span><b>CLV</b> = ventaja vs. línea justa (positivo = le ganas al precio)</span>
  </div>

  <div class="note">{HONESTY}</div>
</div>
"""

OUT.write_text(html)
print(f"wrote {OUT} ({len(html)} bytes) · quiniela {len(PICKS['picks'])} · boleto ${int(grand)}/${int(budget_total)} · {n_bets} bets")
