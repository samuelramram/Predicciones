#!/usr/bin/env python3
"""Render el boleto de apuestas Liga MX a un HTML self-contained y theme-aware.

Uso: python scripts/render_bets_html.py j3
Lee outputs/ligamx_bets_{round}.json y escribe outputs/ligamx_bets_{round}.html.
"""
import json
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

ROUND = sys.argv[1] if len(sys.argv) > 1 else "j3"
ROOT = Path(__file__).resolve().parents[1]

bets_doc = json.loads((ROOT / f"outputs/ligamx_bets_{ROUND}.json").read_text())
books_doc = json.loads((ROOT / "data/ligamx/books.json").read_text())

bets = bets_doc["bets"]
p = bets_doc["params"]
bankroll = p["bankroll"]
caliente_as_of = books_doc.get("manual", {}).get("caliente", {}).get("as_of", "")

# ---- derivadas ----
total_stake = sum(b["stake_mxn"] for b in bets)
clv_pos = [b for b in bets if b["clv_entry"] > 0]
clv_pos_stake = sum(b["stake_mxn"] for b in clv_pos)
n_matches = len({b["match"] for b in bets})

SEL_LABEL = {"1": "Local (1)", "X": "Empate (X)", "2": "Visita (2)",
             "Over": "Más de 2.5", "Under": "Menos de 2.5"}


def pct(x, sign=False):
    return f"{x*100:+.1f}%" if sign else f"{x*100:.1f}%"


def home_of(match):
    return match.split(" vs ")[0]


rows = []
for b in sorted(bets, key=lambda x: (-x["clv_entry"], -x["edge"])):
    clv = b["clv_entry"]
    good = clv > 0
    clv_cls = "pos" if good else "neg"
    sel = b["selection"]
    sel_txt = SEL_LABEL.get(sel, sel)
    if b["market"] == "1X2" and sel in ("1", "2"):
        team = home_of(b["match"]) if sel == "1" else b["match"].split(" vs ")[1]
        sel_txt = f'{escape(team)} <span class="tag">{sel}</span>'
    star = '<span class="star" title="Le gana al cierre">&#9733;</span>' if good else ""
    rows.append(f"""
      <tr class="{'row-good' if good else ''}">
        <td class="match">{escape(b['match'])}{star}</td>
        <td class="mkt">{escape(b['market'])}</td>
        <td class="sel">{sel_txt}</td>
        <td class="num">{pct(b['model_prob'])}</td>
        <td class="num muted">{pct(b['fair_prob'])}</td>
        <td class="num">{pct(b['edge'])}</td>
        <td class="num price">{b['price']:.2f}</td>
        <td class="book">{escape(b['book'])}</td>
        <td class="num stake">${b['stake_mxn']:.0f}</td>
        <td class="num">{pct(b['ev'], sign=True)}</td>
        <td class="num clv {clv_cls}">{pct(clv, sign=True)}</td>
      </tr>""")

pick = clv_pos[0] if clv_pos else None
if pick:
    pick_team = home_of(pick["match"]) if pick["selection"] == "1" else pick["match"].split(" vs ")[1]
    hero_pick = f"""
      <div class="pick">
        <div class="pick-head">La única que apostaría</div>
        <div class="pick-body">
          <div class="pick-main">
            <span class="pick-team">{escape(pick_team)}</span>
            <span class="pick-meta">gana &middot; {escape(pick['match'])}</span>
          </div>
          <div class="pick-nums">
            <div class="stat"><span class="k">Momio</span><span class="v">{pick['price']:.2f}</span><span class="u">{escape(pick['book'])}</span></div>
            <div class="stat"><span class="k">Stake</span><span class="v">${pick['stake_mxn']:.0f}</span><span class="u">de ${bankroll:.0f}</span></div>
            <div class="stat"><span class="k">CLV</span><span class="v pos">{pct(pick['clv_entry'], sign=True)}</span><span class="u">vs cierre</span></div>
          </div>
        </div>
      </div>"""
else:
    hero_pick = '<div class="pick empty">Ninguna apuesta le gana al cierre esta jornada.</div>'

updated = datetime.now(timezone.utc).astimezone().strftime("%d %b %Y, %H:%M")

HTML = f"""<title>Apuestas Liga MX &middot; Jornada 3</title>
<style>
:root {{
  --bg: #f6f5f1; --panel: #ffffff; --ink: #16181d; --muted: #6b7280;
  --line: #e6e3dc; --accent: #b8860b; --accent-soft: #f3ead2;
  --pos: #1f8a54; --pos-soft: #e4f2ea; --neg: #b23b3b; --neg-soft: #f6e7e5;
  --mono: ui-monospace, "SF Mono", "SFMono-Regular", Menlo, Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #101216; --panel: #191c22; --ink: #eceef2; --muted: #99a0ad;
    --line: #2a2e37; --accent: #e0b34a; --accent-soft: #2c2718;
    --pos: #46c383; --pos-soft: #16281f; --neg: #e07a72; --neg-soft: #2b1a19;
  }}
}}
:root[data-theme="light"] {{
  --bg: #f6f5f1; --panel: #ffffff; --ink: #16181d; --muted: #6b7280;
  --line: #e6e3dc; --accent: #b8860b; --accent-soft: #f3ead2;
  --pos: #1f8a54; --pos-soft: #e4f2ea; --neg: #b23b3b; --neg-soft: #f6e7e5;
}}
:root[data-theme="dark"] {{
  --bg: #101216; --panel: #191c22; --ink: #eceef2; --muted: #99a0ad;
  --line: #2a2e37; --accent: #e0b34a; --accent-soft: #2c2718;
  --pos: #46c383; --pos-soft: #16281f; --neg: #e07a72; --neg-soft: #2b1a19;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; }}
.wrap {{
  font-family: var(--sans); background: var(--bg); color: var(--ink);
  min-height: 100vh; padding: 28px 18px 64px; line-height: 1.5;
}}
.container {{ max-width: 940px; margin: 0 auto; }}
.eyebrow {{
  font-size: 12px; letter-spacing: .16em; text-transform: uppercase;
  color: var(--accent); font-weight: 700; margin: 0 0 6px;
}}
h1 {{ font-size: clamp(26px, 5vw, 38px); margin: 0 0 8px; letter-spacing: -.02em; text-wrap: balance; }}
.freshness {{ color: var(--muted); font-size: 13px; display: flex; flex-wrap: wrap; gap: 4px 16px; margin-top: 10px; }}
.freshness b {{ color: var(--ink); font-weight: 600; }}

.verdict {{
  margin: 26px 0; background: var(--panel); border: 1px solid var(--line);
  border-radius: 14px; overflow: hidden;
}}
.verdict-top {{
  display: flex; flex-wrap: wrap; gap: 20px 40px; padding: 22px 24px;
  border-bottom: 1px solid var(--line);
}}
.big {{ display: flex; flex-direction: column; }}
.big .n {{ font-family: var(--mono); font-size: 34px; font-weight: 700; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }}
.big .n.accent {{ color: var(--accent); }}
.big .l {{ font-size: 12.5px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }}
.verdict-note {{ padding: 18px 24px; font-size: 14.5px; color: var(--ink); background: var(--accent-soft); }}
.verdict-note b {{ font-weight: 700; }}

.pick {{ margin: 0; padding: 20px 24px; border-top: 1px solid var(--line); }}
.pick.empty {{ color: var(--muted); }}
.pick-head {{ font-size: 12px; letter-spacing: .12em; text-transform: uppercase; color: var(--pos); font-weight: 700; margin-bottom: 10px; }}
.pick-body {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 18px; }}
.pick-team {{ font-size: 22px; font-weight: 700; }}
.pick-meta {{ color: var(--muted); font-size: 14px; margin-left: 10px; }}
.pick-nums {{ display: flex; gap: 26px; }}
.stat {{ display: flex; flex-direction: column; }}
.stat .k {{ font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }}
.stat .v {{ font-family: var(--mono); font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }}
.stat .v.pos {{ color: var(--pos); }}
.stat .u {{ font-size: 11px; color: var(--muted); }}

.tablecard {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }}
.tablecard h2 {{ font-size: 15px; margin: 0; padding: 16px 20px; border-bottom: 1px solid var(--line); letter-spacing: -.01em; }}
.scroll {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; min-width: 720px; }}
thead th {{
  text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .06em;
  color: var(--muted); font-weight: 600; padding: 10px 12px; border-bottom: 1px solid var(--line);
  white-space: nowrap; background: var(--panel);
}}
tbody td {{ padding: 11px 12px; border-bottom: 1px solid var(--line); white-space: nowrap; }}
tbody tr:last-child td {{ border-bottom: none; }}
.num {{ font-family: var(--mono); text-align: right; font-variant-numeric: tabular-nums; }}
thead th.num {{ text-align: right; }}
.match {{ font-weight: 600; }}
.muted {{ color: var(--muted); }}
.price {{ font-weight: 700; }}
.book {{ text-transform: capitalize; color: var(--muted); }}
.tag {{ font-family: var(--mono); font-size: 11px; color: var(--muted); border: 1px solid var(--line); border-radius: 4px; padding: 0 4px; margin-left: 4px; }}
.clv.pos {{ color: var(--pos); font-weight: 700; }}
.clv.neg {{ color: var(--neg); }}
.row-good {{ background: var(--pos-soft); }}
.star {{ color: var(--pos); margin-left: 6px; }}

.foot {{ margin-top: 22px; font-size: 13px; color: var(--muted); line-height: 1.6; }}
.foot p {{ margin: 0 0 10px; }}
.foot b {{ color: var(--ink); }}
.foot code {{ font-family: var(--mono); font-size: 12px; background: var(--accent-soft); padding: 1px 5px; border-radius: 4px; color: var(--ink); }}
.legend {{ display: flex; gap: 18px; flex-wrap: wrap; margin: 14px 0 4px; font-size: 12.5px; color: var(--muted); }}
.legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
.dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
.dot.pos {{ background: var(--pos); }} .dot.neg {{ background: var(--neg); }}
</style>

<div class="wrap"><div class="container">
  <p class="eyebrow">Liga MX &middot; Apertura 2026 &middot; M&oacute;dulo de valor</p>
  <h1>Boleto de apuestas &mdash; Jornada 3</h1>
  <div class="freshness">
    <span>Casas: <b>Caliente + Betway</b></span>
    <span>Caliente al <b>{escape(caliente_as_of)}</b></span>
    <span>Betway / l&iacute;nea justa: <b>refrescado hoy</b> v&iacute;a The Odds API</span>
    <span>Bankroll: <b>${bankroll:.0f}</b> &middot; &frac14;-Kelly, tope 2%</span>
  </div>

  <div class="verdict">
    <div class="verdict-top">
      <div class="big"><span class="n">{len(bets)}</span><span class="l">Se&ntilde;ales de edge &ge;3%</span></div>
      <div class="big"><span class="n accent">{len(clv_pos)}</span><span class="l">Le ganan al cierre (CLV+)</span></div>
      <div class="big"><span class="n">${clv_pos_stake:.0f}</span><span class="l">Stake apostable</span></div>
      <div class="big"><span class="n muted">${total_stake:.0f}</span><span class="l">Si picaras todo el edge</span></div>
    </div>
    <div class="verdict-note">
      La prueba no es el edge (el modelo <b>no</b> le gana al mercado a la larga), es el
      <b>CLV</b>: si tu precio le gana a la l&iacute;nea justa afilada de ~20+ casas.
      Esta jornada, <b>solo 1 de {len(bets)}</b> se&ntilde;ales pasa esa prueba. El resto es
      ruido de modelo &mdash; medici&oacute;n para el ledger, no dinero a la mesa.
    </div>
    {hero_pick}
  </div>

  <div class="tablecard">
    <h2>Boleto completo &mdash; {len(bets)} se&ntilde;ales en {n_matches} partidos (ordenado por CLV)</h2>
    <div class="scroll">
      <table>
        <thead><tr>
          <th>Partido</th><th>Mercado</th><th>Selecci&oacute;n</th>
          <th class="num">Modelo</th><th class="num">Justo</th><th class="num">Edge</th>
          <th class="num">Momio</th><th>Casa</th><th class="num">Stake</th>
          <th class="num">EV</th><th class="num">CLV</th>
        </tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
  </div>

  <div class="legend">
    <span><span class="dot pos"></span> CLV+ : el precio le gana al cierre &mdash; apostable</span>
    <span><span class="dot neg"></span> CLV&minus; : el mercado se movi&oacute; en contra &mdash; no apostar</span>
  </div>

  <div class="foot">
    <p><b>Por qu&eacute; casi todo es rojo.</b> El backtest sin odds solo le gana ~8% a un
    baseline trivial: el modelo <b>no</b> es m&aacute;s afilado que el mercado. Un edge de
    8&ndash;16% contra 20+ casas es casi siempre error del modelo, no valor real. Por eso
    el corte es el CLV, no el edge.</p>
    <p><b>Qu&eacute; har&iacute;a yo.</b> Apostar la de Quer&eacute;taro (${pick['stake_mxn']:.0f} a {pick['price']:.2f} en {escape(pick['book'])}) y registrar
    el resto en el ledger de CLV sin poner dinero &mdash; para medir si el edge es real a lo
    largo del torneo. El siguiente paso es <b>cerrar</b> las l&iacute;neas cerca del kickoff y
    <b>liquidar</b> con resultados (<code>ligamx_clv close / settle / report</code>).</p>
    <p style="opacity:.7">Actualizado {updated}. Momios decimales. Stakes en MXN.</p>
  </div>
</div></div>
"""

out = ROOT / f"outputs/ligamx_bets_{ROUND}.html"
out.write_text(HTML)
print("wrote", out)
