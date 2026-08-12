"""Render the per-house boleto (ligamx_boleto_{round}.json) to a self-contained,
theme-aware HTML. The stake column is the hero: it reflects the user's real
bankroll per house, split into $20 units — NOT the raw Kelly stakes shown in the
picks HTML.

Usage: python scripts/render_boleto_html.py j4
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROUND = sys.argv[1] if len(sys.argv) > 1 else "j4"
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "outputs" / f"ligamx_boleto_{ROUND}.json"
OUT = ROOT / "outputs" / f"ligamx_boleto_{ROUND}.html"

data = json.loads(SRC.read_text())

HOUSE_META = {
    "betway": {"label": "Betway", "hue": "#0aa64f"},
    "caliente": {"label": "Caliente", "hue": "#e2231a"},
}


def outcome_label(bet: dict) -> tuple[str, str]:
    """(badge, team) — the pick as the user reads it on the app."""
    sel = bet["selection"]
    if sel == "1":
        return "1", bet["home"]
    if sel == "2":
        return "2", bet["away"]
    return "X", "Empate"


def clv_class(clv: float) -> str:
    if clv > 0:
        return "pos"
    if clv <= -0.10:
        return "neg-strong"
    return "neg"


def house_card(key: str, house: dict) -> str:
    meta = HOUSE_META.get(key, {"label": key.title(), "hue": "#6b7280"})
    bets = house["bets"]
    total = sum(b["stake_mxn"] for b in bets)
    budget = house["budget_mxn"]
    rows = []
    for b in bets:
        badge, team = outcome_label(b)
        clv = b["clv_entry"]
        rows.append(f"""
      <tr>
        <td class="match">{b['home']} <span class="vs">vs</span> {b['away']}</td>
        <td class="pick"><span class="badge badge-{badge.lower()}">{badge}</span><span class="team">{team}</span></td>
        <td class="num price">{b['price']:.2f}</td>
        <td class="num stake">${int(b['stake_mxn'])}</td>
        <td class="num clv {clv_class(clv)}">{clv*100:+.1f}%</td>
      </tr>""")
    return f"""
    <section class="ticket" style="--house: {meta['hue']};">
      <header class="ticket-head">
        <div class="house">
          <span class="house-dot"></span>
          <h2>{meta['label']}</h2>
        </div>
        <div class="budget">
          <span class="budget-total">${int(total)}</span>
          <span class="budget-sub">de ${int(budget)} · {len(bets)} predicciones</span>
        </div>
      </header>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Partido</th><th>Pick</th><th class="num">Cuota</th>
              <th class="num">Apuesta</th><th class="num">CLV</th>
            </tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
          <tfoot>
            <tr>
              <td colspan="3" class="foot-label">Total desplegado</td>
              <td class="num stake foot-total">${int(total)}</td>
              <td></td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>"""


cards = "\n".join(house_card(k, v) for k, v in data["houses"].items())
grand_total = sum(sum(b["stake_mxn"] for b in h["bets"]) for h in data["houses"].values())
budget_total = sum(h["budget_mxn"] for h in data["houses"].values())
as_of = data.get("as_of", "")
try:
    ts = datetime.fromisoformat(as_of.replace("Z", "+00:00")).astimezone(timezone.utc)
    stamp = ts.strftime("%Y-%m-%d %H:%M UTC")
except Exception:
    stamp = as_of

html = f"""<title>Boleto por casa · J4</title>
<style>
  :root {{
    --bg: #f4f2ec;
    --panel: #fbfaf6;
    --ink: #1a1c20;
    --ink-soft: #565a62;
    --line: #e2ddd1;
    --line-strong: #cfc8b7;
    --accent: #157a4e;
    --pos: #157a4e;
    --neg: #9a7b1d;
    --neg-strong: #b0431f;
    --badge-1-bg: #dceee2; --badge-1-ink: #12603c;
    --badge-x-bg: #efe6cf; --badge-x-ink: #86611a;
    --badge-2-bg: #e4e6ec; --badge-2-ink: #3f4658;
    --shadow: 0 1px 2px rgba(24,22,16,.05), 0 8px 24px -12px rgba(24,22,16,.22);
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #14161a;
      --panel: #1c1f25;
      --ink: #eceae4;
      --ink-soft: #9aa0aa;
      --line: #2b2f36;
      --line-strong: #3a3f48;
      --accent: #3fb87e;
      --pos: #3fb87e;
      --neg: #d1a63f;
      --neg-strong: #e0764a;
      --badge-1-bg: #17352a; --badge-1-ink: #6fd6a3;
      --badge-x-bg: #362e18; --badge-x-ink: #e0bd6b;
      --badge-2-bg: #262b36; --badge-2-ink: #aeb6c6;
      --shadow: 0 1px 2px rgba(0,0,0,.3), 0 10px 30px -14px rgba(0,0,0,.6);
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #14161a; --panel: #1c1f25; --ink: #eceae4; --ink-soft: #9aa0aa;
    --line: #2b2f36; --line-strong: #3a3f48; --accent: #3fb87e; --pos: #3fb87e;
    --neg: #d1a63f; --neg-strong: #e0764a;
    --badge-1-bg: #17352a; --badge-1-ink: #6fd6a3;
    --badge-x-bg: #362e18; --badge-x-ink: #e0bd6b;
    --badge-2-bg: #262b36; --badge-2-ink: #aeb6c6;
    --shadow: 0 1px 2px rgba(0,0,0,.3), 0 10px 30px -14px rgba(0,0,0,.6);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    line-height: 1.5; -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 960px; margin: 0 auto; padding: clamp(20px, 4vw, 48px); }}
  .masthead {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 16px; border-bottom: 2px solid var(--ink); padding-bottom: 14px; }}
  .masthead h1 {{ font-size: clamp(1.5rem, 4vw, 2.1rem); margin: 0; letter-spacing: -.02em; font-weight: 800; }}
  .masthead .jornada {{ color: var(--accent); }}
  .masthead .stamp {{ margin-left: auto; font-size: .78rem; color: var(--ink-soft); font-variant-numeric: tabular-nums; }}
  .lede {{ margin: 16px 0 6px; color: var(--ink-soft); max-width: 62ch; }}
  .grand {{ display: flex; align-items: baseline; gap: 10px; margin: 22px 0 4px; font-variant-numeric: tabular-nums; }}
  .grand b {{ font-size: 1.4rem; font-weight: 800; }}
  .grand span {{ color: var(--ink-soft); font-size: .9rem; }}
  .tickets {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 20px; margin-top: 20px; }}
  .ticket {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow); overflow: hidden; }}
  .ticket-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 18px; border-bottom: 1px solid var(--line); }}
  .house {{ display: flex; align-items: center; gap: 9px; }}
  .house-dot {{ width: 11px; height: 11px; border-radius: 50%; background: var(--house); box-shadow: 0 0 0 3px color-mix(in srgb, var(--house) 20%, transparent); }}
  .house h2 {{ margin: 0; font-size: 1.15rem; font-weight: 800; letter-spacing: -.01em; }}
  .budget {{ text-align: right; line-height: 1.15; }}
  .budget-total {{ display: block; font-size: 1.5rem; font-weight: 800; font-variant-numeric: tabular-nums; }}
  .budget-sub {{ font-size: .72rem; color: var(--ink-soft); text-transform: uppercase; letter-spacing: .04em; }}
  .table-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
  th {{ text-align: left; font-size: .68rem; text-transform: uppercase; letter-spacing: .06em; color: var(--ink-soft); font-weight: 700; padding: 10px 8px; border-bottom: 1px solid var(--line); }}
  td {{ padding: 11px 8px; border-bottom: 1px solid var(--line); vertical-align: middle; }}
  th:first-child, td:first-child {{ padding-left: 18px; }}
  th:last-child, td:last-child {{ padding-right: 18px; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .match {{ font-weight: 600; }}
  .match .vs {{ color: var(--ink-soft); font-weight: 400; font-size: .82em; margin: 0 2px; }}
  .pick {{ white-space: nowrap; }}
  .badge {{ display: inline-block; min-width: 20px; text-align: center; font-weight: 800; font-size: .75rem; padding: 2px 6px; border-radius: 5px; margin-right: 7px; }}
  .badge-1 {{ background: var(--badge-1-bg); color: var(--badge-1-ink); }}
  .badge-x {{ background: var(--badge-x-bg); color: var(--badge-x-ink); }}
  .badge-2 {{ background: var(--badge-2-bg); color: var(--badge-2-ink); }}
  .team {{ font-weight: 600; }}
  .price {{ color: var(--ink-soft); }}
  .stake {{ font-weight: 800; font-size: 1rem; }}
  .clv {{ font-size: .82rem; }}
  .clv.pos {{ color: var(--pos); }}
  .clv.neg {{ color: var(--neg); }}
  .clv.neg-strong {{ color: var(--neg-strong); }}
  tfoot td {{ border-bottom: none; border-top: 2px solid var(--line-strong); padding-top: 12px; }}
  .foot-label {{ text-transform: uppercase; font-size: .7rem; letter-spacing: .05em; color: var(--ink-soft); font-weight: 700; }}
  .foot-total {{ font-size: 1.1rem; }}
  .note {{ margin-top: 26px; padding: 16px 18px; border: 1px solid var(--line); border-left: 3px solid var(--neg); border-radius: 10px; background: var(--panel); font-size: .88rem; color: var(--ink-soft); }}
  .note b {{ color: var(--ink); }}
  .legend {{ margin-top: 14px; font-size: .78rem; color: var(--ink-soft); display: flex; flex-wrap: wrap; gap: 6px 18px; }}
</style>

<div class="wrap">
  <header class="masthead">
    <h1>Boleto por casa · <span class="jornada">Liga MX J4</span></h1>
    <span class="stamp">Cuotas {stamp}</span>
  </header>

  <p class="lede">Tu presupuesto <b>completo</b> desplegado en cada casa a su propio precio: un pick 1X2 por partido, mínimo $20 por predicción, en unidades de $20. Esto es lo que apuestas de verdad — la columna <b>Apuesta</b> ya respeta tu bankroll y el mínimo, no el ¼-Kelly crudo.</p>

  <div class="grand">
    <b>${int(grand_total)}</b><span>desplegados de ${int(budget_total)} · {sum(len(h['bets']) for h in data['houses'].values())} predicciones en 2 casas</span>
  </div>

  <div class="tickets">
    {cards}
  </div>

  <div class="legend">
    <span><b>1</b> gana local &nbsp; <b>X</b> empate &nbsp; <b>2</b> gana visita</span>
    <span><b>Cuota</b> = momio decimal de esa casa</span>
    <span><b>CLV</b> = ventaja vs. la línea justa (casi todo arranca ≤ 0)</span>
  </div>

  <div class="note">
    <b>Honestidad:</b> es acción medida sobre tu roll, <b>no un boleto +EV</b>. La mayoría de los picks arranca con CLV ≤ 0 — el mercado les gana en precio. El valor no es ganar esta jornada (eso sería varianza de un par de longshots) sino medir el CLV real a lo largo del torneo. Las {sum(len(h['bets']) for h in data['houses'].values())} apuestas ya quedaron registradas en el ledger con casa, precio y stake reales.
  </div>
</div>
"""

OUT.write_text(html)
print(f"wrote {OUT} ({len(html)} bytes)")
print(f"grand total ${int(grand_total)} of ${int(budget_total)}")
