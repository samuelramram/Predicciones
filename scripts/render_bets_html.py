#!/usr/bin/env python3
"""Render el boleto de apuestas Liga MX a un HTML self-contained y theme-aware.

Uso: python scripts/render_bets_html.py j3
Lee outputs/ligamx_bets_{round}.json y escribe outputs/ligamx_bets_{round}.html.
Detecta el modo: 'deployment' (boleto mixto que despliega el roll) o el boleto de
valor disciplinado (default).
"""
import json
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

ROUND = sys.argv[1] if len(sys.argv) > 1 else "j3"
ROOT = Path(__file__).resolve().parents[1]

doc = json.loads((ROOT / f"outputs/ligamx_bets_{ROUND}.json").read_text())
books_doc = json.loads((ROOT / "data/ligamx/books.json").read_text())

bets = doc["bets"]
p = doc["params"]
bankroll = p["bankroll"]
mode = doc.get("mode", "value")
caliente_as_of = books_doc.get("manual", {}).get("caliente", {}).get("as_of", "")
min_stake = p.get("min_stake", 0) or 0
updated = datetime.now(timezone.utc).astimezone().strftime("%d %b %Y, %H:%M")


def pct(x, sign=False):
    return f"{x*100:+.1f}%" if sign else f"{x*100:.1f}%"


def home_of(match):
    return match.split(" vs ")[0]


def team_for(b):
    """Nombre del equipo/selección para un pick 1X2."""
    sel = b["selection"]
    if sel == "1":
        return b.get("home") or home_of(b["match"])
    if sel == "2":
        return b.get("away") or b["match"].split(" vs ")[1]
    return "Empate"


CSS = """
:root {
  --bg: #f6f5f1; --panel: #ffffff; --ink: #16181d; --muted: #6b7280;
  --line: #e6e3dc; --accent: #b8860b; --accent-soft: #f3ead2;
  --pos: #1f8a54; --pos-soft: #e4f2ea; --neg: #b23b3b; --neg-soft: #f6e7e5;
  --mono: ui-monospace, "SF Mono", "SFMono-Regular", Menlo, Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #101216; --panel: #191c22; --ink: #eceef2; --muted: #99a0ad;
    --line: #2a2e37; --accent: #e0b34a; --accent-soft: #2c2718;
    --pos: #46c383; --pos-soft: #16281f; --neg: #e07a72; --neg-soft: #2b1a19;
  }
}
:root[data-theme="light"] {
  --bg: #f6f5f1; --panel: #ffffff; --ink: #16181d; --muted: #6b7280;
  --line: #e6e3dc; --accent: #b8860b; --accent-soft: #f3ead2;
  --pos: #1f8a54; --pos-soft: #e4f2ea; --neg: #b23b3b; --neg-soft: #f6e7e5;
}
:root[data-theme="dark"] {
  --bg: #101216; --panel: #191c22; --ink: #eceef2; --muted: #99a0ad;
  --line: #2a2e37; --accent: #e0b34a; --accent-soft: #2c2718;
  --pos: #46c383; --pos-soft: #16281f; --neg: #e07a72; --neg-soft: #2b1a19;
}
* { box-sizing: border-box; }
body { margin: 0; }
.wrap { font-family: var(--sans); background: var(--bg); color: var(--ink);
  min-height: 100vh; padding: 28px 18px 64px; line-height: 1.5; }
.container { max-width: 960px; margin: 0 auto; }
.eyebrow { font-size: 12px; letter-spacing: .16em; text-transform: uppercase;
  color: var(--accent); font-weight: 700; margin: 0 0 6px; }
h1 { font-size: clamp(26px, 5vw, 38px); margin: 0 0 8px; letter-spacing: -.02em; text-wrap: balance; }
.freshness { color: var(--muted); font-size: 13px; display: flex; flex-wrap: wrap; gap: 4px 16px; margin-top: 10px; }
.freshness b { color: var(--ink); font-weight: 600; }
.verdict { margin: 26px 0; background: var(--panel); border: 1px solid var(--line);
  border-radius: 14px; overflow: hidden; }
.verdict-top { display: flex; flex-wrap: wrap; gap: 20px 40px; padding: 22px 24px; border-bottom: 1px solid var(--line); }
.big { display: flex; flex-direction: column; }
.big .n { font-family: var(--mono); font-size: 34px; font-weight: 700; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
.big .n.accent { color: var(--accent); }
.big .n.pos { color: var(--pos); }
.big .l { font-size: 12.5px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
.verdict-note { padding: 18px 24px; font-size: 14.5px; color: var(--ink); background: var(--accent-soft); }
.verdict-note b { font-weight: 700; }
.pick { margin: 0; padding: 20px 24px; border-top: 1px solid var(--line); }
.pick-head { font-size: 12px; letter-spacing: .12em; text-transform: uppercase; color: var(--pos); font-weight: 700; margin-bottom: 10px; }
.pick-body { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 18px; }
.pick-team { font-size: 22px; font-weight: 700; }
.pick-meta { color: var(--muted); font-size: 14px; margin-left: 10px; }
.pick-nums { display: flex; gap: 26px; }
.stat { display: flex; flex-direction: column; }
.stat .k { font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
.stat .v { font-family: var(--mono); font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
.stat .v.pos { color: var(--pos); }
.stat .u { font-size: 11px; color: var(--muted); }
.tablecard { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }
.tablecard h2 { font-size: 15px; margin: 0; padding: 16px 20px; border-bottom: 1px solid var(--line); letter-spacing: -.01em; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; min-width: 680px; }
thead th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .06em;
  color: var(--muted); font-weight: 600; padding: 10px 12px; border-bottom: 1px solid var(--line);
  white-space: nowrap; background: var(--panel); }
thead th.num { text-align: right; }
tbody td { padding: 11px 12px; border-bottom: 1px solid var(--line); white-space: nowrap; }
tbody tr:last-child td { border-bottom: none; }
.num { font-family: var(--mono); text-align: right; font-variant-numeric: tabular-nums; }
.match { font-weight: 600; }
.muted { color: var(--muted); }
.price { font-weight: 700; }
.stake { font-weight: 700; }
.book { text-transform: capitalize; color: var(--muted); }
.tag { font-family: var(--mono); font-size: 11px; color: var(--muted); border: 1px solid var(--line); border-radius: 4px; padding: 0 4px; margin-left: 6px; }
.clv.pos { color: var(--pos); font-weight: 700; }
.clv.neg { color: var(--neg); }
.row-good { background: var(--pos-soft); }
.star { color: var(--pos); margin-left: 6px; }
.bar { height: 8px; border-radius: 4px; background: var(--accent); opacity: .85; min-width: 6px; }
.foot { margin-top: 22px; font-size: 13px; color: var(--muted); line-height: 1.6; }
.foot p { margin: 0 0 10px; }
.foot b { color: var(--ink); }
.foot code { font-family: var(--mono); font-size: 12px; background: var(--accent-soft); padding: 1px 5px; border-radius: 4px; color: var(--ink); }
.legend { display: flex; gap: 18px; flex-wrap: wrap; margin: 14px 0 4px; font-size: 12.5px; color: var(--muted); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.dot.pos { background: var(--pos); } .dot.neg { background: var(--neg); }
"""


def render_deployment():
    total = doc.get("total_stake_mxn", sum(b["stake_mxn"] for b in bets))
    npos = sum(1 for b in bets if b["clv_entry"] > 0)
    budget = p.get("budget_frac", 0)
    max_stake = max((b["stake_mxn"] for b in bets), default=1) or 1

    rows = []
    for b in bets:
        good = b["clv_entry"] > 0
        clv_cls = "pos" if good else "neg"
        star = '<span class="star" title="Le gana al cierre">&#9733;</span>' if good else ""
        barw = int(round(b["stake_mxn"] / max_stake * 100))
        rows.append(f"""
      <tr class="{'row-good' if good else ''}">
        <td class="match">{escape(b['match'])}{star}</td>
        <td>{escape(b['selection'])} <b>{escape(team_for(b))}</b></td>
        <td class="num">{pct(b['model_prob'])}</td>
        <td class="num muted">{pct(b['fair_prob'])}</td>
        <td class="num">{pct(b['edge'], sign=True)}</td>
        <td class="num price">{b['price']:.2f}</td>
        <td class="book">{escape(b['book'] or '-')}</td>
        <td class="num stake">${b['stake_mxn']:.0f}</td>
        <td style="width:90px"><div class="bar" style="width:{barw}%"></div></td>
        <td class="num clv {clv_cls}">{pct(b['clv_entry'], sign=True)}</td>
      </tr>""")

    top = max(bets, key=lambda b: b["stake_mxn"])
    hero = f"""
      <div class="pick">
        <div class="pick-head">La apuesta ancla (más peso)</div>
        <div class="pick-body">
          <div class="pick-main">
            <span class="pick-team">{escape(team_for(top))}</span>
            <span class="pick-meta">{escape(top['match'])}</span>
          </div>
          <div class="pick-nums">
            <div class="stat"><span class="k">Momio</span><span class="v">{top['price']:.2f}</span><span class="u">{escape(top['book'] or '-')}</span></div>
            <div class="stat"><span class="k">Stake</span><span class="v">${top['stake_mxn']:.0f}</span><span class="u">de ${bankroll:.0f}</span></div>
            <div class="stat"><span class="k">CLV</span><span class="v {'pos' if top['clv_entry']>0 else ''}">{pct(top['clv_entry'], sign=True)}</span><span class="u">vs cierre</span></div>
          </div>
        </div>
      </div>"""

    return f"""<title>Boleto Liga MX &middot; Jornada 3</title>
<style>{CSS}</style>
<div class="wrap"><div class="container">
  <p class="eyebrow">Liga MX &middot; Apertura 2026 &middot; Boleto de experimento</p>
  <h1>Boleto de despliegue &mdash; Jornada 3</h1>
  <div class="freshness">
    <span>Casas: <b>Caliente + Betway</b></span>
    <span>Caliente al <b>{escape(caliente_as_of)}</b></span>
    <span>Betway / l&iacute;nea justa: <b>refrescado hoy</b></span>
    <span>Bankroll: <b>${bankroll:.0f}</b> &middot; m&iacute;nimo <b>${min_stake:.0f}</b>/apuesta</span>
  </div>

  <div class="verdict">
    <div class="verdict-top">
      <div class="big"><span class="n">${total:.0f}</span><span class="l">Total a jugar</span></div>
      <div class="big"><span class="n accent">{total/bankroll*100:.0f}%</span><span class="l">Del bankroll en juego</span></div>
      <div class="big"><span class="n">{len(bets)}</span><span class="l">Apuestas (1 por partido)</span></div>
      <div class="big"><span class="n pos">{npos}</span><span class="l">Con CLV+ (le ganan al cierre)</span></div>
    </div>
    <div class="verdict-note">
      Este es el boleto de <b>experimento</b>: pone el <b>{total/bankroll*100:.0f}%</b> de tu roll a
      trabajar con un pick por partido, m&aacute;s stake donde el modelo ve m&aacute;s ventaja y en lo
      que le gana al cierre. <b>Ojo:</b> {len(bets)-npos} de {len(bets)} picks tienen CLV negativo &mdash;
      el mercado les gana. Es acci&oacute;n medida sobre el roll, <b>no</b> un boleto +EV; el CLV de
      cada uno queda registrado para ver, al final del torneo, si el modelo ten&iacute;a raz&oacute;n.
    </div>
    {hero}
  </div>

  <div class="tablecard">
    <h2>El boleto &mdash; {len(bets)} partidos, ordenado por stake</h2>
    <div class="scroll">
      <table>
        <thead><tr>
          <th>Partido</th><th>Pick</th>
          <th class="num">Modelo</th><th class="num">Justo</th><th class="num">Edge</th>
          <th class="num">Momio</th><th>Casa</th><th class="num">Stake</th>
          <th></th><th class="num">CLV</th>
        </tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
  </div>

  <div class="legend">
    <span><span class="dot pos"></span> CLV+ : el precio le gana al cierre</span>
    <span><span class="dot neg"></span> CLV&minus; : el mercado se movi&oacute; en contra</span>
  </div>

  <div class="foot">
    <p><b>C&oacute;mo se reparti&oacute;.</b> Cada juego arranca con el mismo peso base (acci&oacute;n en los 9),
    y sube el stake si el precio le gana al cierre (CLV+) o si el modelo ve m&aacute;s ventaja. Por eso
    <b>{escape(team_for(top))}</b> &mdash; la &uacute;nica con CLV+ &mdash; se lleva el stake m&aacute;s alto. Todo
    redondeado a m&uacute;ltiplos de ${min_stake:.0f} para que sea copy-paste en la app.</p>
    <p><b>La verdad inc&oacute;moda.</b> El disciplinado dir&iacute;a apostar solo la de {escape(team_for(top))}
    (la &uacute;nica +CLV) y nada m&aacute;s. Desplegar el {total/bankroll*100:.0f}% del roll es tu decisi&oacute;n de
    experimento: diversi&oacute;n + datos, sabiendo que la mayor&iacute;a de estos picks empiezan detr&aacute;s de la
    l&iacute;nea. El ledger (<code>ligamx_clv</code>) mide el CLV real jornada a jornada.</p>
    <p style="opacity:.7">Actualizado {updated}. Momios decimales. Stakes en MXN.</p>
  </div>
</div></div>
"""


def render_value():
    clv_pos = [b for b in bets if b["clv_entry"] > 0]
    clv_pos_stake = sum(b["stake_mxn"] for b in clv_pos)
    n_matches = len({b["match"] for b in bets})
    SEL = {"Over": "M&aacute;s de 2.5", "Under": "Menos de 2.5"}

    rows = []
    for b in sorted(bets, key=lambda x: (-x["clv_entry"], -x["edge"])):
        good = b["clv_entry"] > 0
        clv_cls = "pos" if good else "neg"
        sel = b["selection"]
        sel_txt = SEL.get(sel, sel)
        if b["market"] == "1X2" and sel in ("1", "2"):
            team = home_of(b["match"]) if sel == "1" else b["match"].split(" vs ")[1]
            sel_txt = f'{escape(team)} <span class="tag">{sel}</span>'
        star = '<span class="star">&#9733;</span>' if good else ""
        stake_cell = f"${b['stake_mxn']:.0f}" if good else '<span class="muted">&mdash;</span>'
        rows.append(f"""
      <tr class="{'row-good' if good else ''}">
        <td class="match">{escape(b['match'])}{star}</td>
        <td>{escape(b['market'])}</td><td>{sel_txt}</td>
        <td class="num">{pct(b['model_prob'])}</td>
        <td class="num muted">{pct(b['fair_prob'])}</td>
        <td class="num">{pct(b['edge'])}</td>
        <td class="num price">{b['price']:.2f}</td>
        <td class="book">{escape(b['book'])}</td>
        <td class="num stake">{stake_cell}</td>
        <td class="num clv {clv_cls}">{pct(b['clv_entry'], sign=True)}</td>
      </tr>""")

    pick = clv_pos[0] if clv_pos else None
    hero = (f"""
      <div class="pick"><div class="pick-head">La &uacute;nica que apostar&iacute;a</div>
        <div class="pick-body">
          <div class="pick-main"><span class="pick-team">{escape(team_for(pick) if pick['market']=='1X2' else pick['selection'])}</span>
            <span class="pick-meta">{escape(pick['match'])}</span></div>
          <div class="pick-nums">
            <div class="stat"><span class="k">Momio</span><span class="v">{pick['price']:.2f}</span><span class="u">{escape(pick['book'])}</span></div>
            <div class="stat"><span class="k">Stake</span><span class="v">${pick['stake_mxn']:.0f}</span><span class="u">de ${bankroll:.0f}</span></div>
            <div class="stat"><span class="k">CLV</span><span class="v pos">{pct(pick['clv_entry'], sign=True)}</span><span class="u">vs cierre</span></div>
          </div></div></div>""" if pick else
            '<div class="pick"><span class="muted">Ninguna apuesta le gana al cierre.</span></div>')

    return f"""<title>Apuestas Liga MX &middot; Jornada 3</title>
<style>{CSS}</style>
<div class="wrap"><div class="container">
  <p class="eyebrow">Liga MX &middot; Apertura 2026 &middot; M&oacute;dulo de valor</p>
  <h1>Boleto de apuestas &mdash; Jornada 3</h1>
  <div class="freshness">
    <span>Casas: <b>Caliente + Betway</b></span>
    <span>Caliente al <b>{escape(caliente_as_of)}</b></span>
    <span>Bankroll: <b>${bankroll:.0f}</b> &middot; m&iacute;nimo <b>${min_stake:.0f}</b>/apuesta</span>
  </div>
  <div class="verdict">
    <div class="verdict-top">
      <div class="big"><span class="n">{len(bets)}</span><span class="l">Se&ntilde;ales de edge &ge;3%</span></div>
      <div class="big"><span class="n accent">{len(clv_pos)}</span><span class="l">Le ganan al cierre (CLV+)</span></div>
      <div class="big"><span class="n">${clv_pos_stake:.0f}</span><span class="l">A jugar en total</span></div>
    </div>
    <div class="verdict-note">La prueba no es el edge, es el <b>CLV</b>. Solo <b>{len(clv_pos)} de {len(bets)}</b>
      le gana al cierre &mdash; esa es la &uacute;nica con stake. El resto va al ledger, no se apuesta.</div>
    {hero}
  </div>
  <div class="tablecard"><h2>Boleto completo &mdash; {len(bets)} se&ntilde;ales en {n_matches} partidos</h2>
    <div class="scroll"><table>
      <thead><tr><th>Partido</th><th>Mercado</th><th>Selecci&oacute;n</th>
        <th class="num">Modelo</th><th class="num">Justo</th><th class="num">Edge</th>
        <th class="num">Momio</th><th>Casa</th><th class="num">Stake</th><th class="num">CLV</th></tr></thead>
      <tbody>{''.join(rows)}</tbody></table></div></div>
  <p style="opacity:.7;font-size:13px;color:var(--muted);margin-top:18px">Actualizado {updated}. Momios decimales. Stakes en MXN.</p>
</div></div>
"""


html = render_deployment() if mode == "deployment" else render_value()
out = ROOT / f"outputs/ligamx_bets_{ROUND}.html"
out.write_text(html)
print("wrote", out, f"({mode})")
