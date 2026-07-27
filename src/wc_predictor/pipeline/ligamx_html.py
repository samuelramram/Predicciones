"""Self-contained HTML renderer for the Liga MX picks — the view the user reads.

The Markdown/JSON outputs don't render well on GitHub or in chat; this produces a
single theme-aware, mobile-first HTML *fragment* (a scoped ``<style>`` block plus
content, no ``<html>``/``<head>``/``<body>``) so it can be published straight to a
Claude Artifact or opened in any browser. Everything is inline — no external
fonts, scripts or images (the Artifact CSP blocks them anyway).

Three page kinds share one design system (`_CSS`):
  - ``render_jornada`` — a regular-season boleto, ticket-first.
  - ``render_liguilla`` — two-legged series with an advancement bar per tie.
  - ``render_projection`` — the Monte-Carlo table of reach probabilities.

Design: the *boleto* is the hero (it's the thing you copy into the pool), so it's
styled like a printed ticket — monospace scorelines, perforated edge. State is
encoded in form, not just number: an EV meter per pick, a stacked 1X2 bar,
amber ABSTAIN / indigo contrarian chips, two-sided advancement bars. Neutrals
carry a slight field-green bias; semantic colours (good/warn/contrarian) are
separate from the accent. Both light and dark themes are first-class.
"""
from __future__ import annotations

import html
from datetime import datetime

# --- design system ------------------------------------------------------------
_CSS = """
.lmx *{box-sizing:border-box}
.lmx{
  --paper:#fbfcfa; --ink:#16211b; --muted:#5d6b62; --line:#e4e8e3;
  --panel:#ffffff; --panel-2:#f4f6f3;
  --field:#1f8a5b; --field-ink:#0f5535;
  --good:#1f8a5b; --warn:#bd7d16; --contra:#5866c9; --bad:#c14b3f;
  --home:#1f8a5b; --draw:#9aa39c; --away:#5866c9;
  --radius:14px; --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  color:var(--ink); background:var(--paper); font-family:var(--sans);
  line-height:1.5; font-size:15px; -webkit-font-smoothing:antialiased;
  padding:clamp(16px,4vw,40px); max-width:1080px; margin:0 auto;
}
@media (prefers-color-scheme:dark){.lmx{
  --paper:#0f1512; --ink:#e8ede9; --muted:#94a49a; --line:#26302b;
  --panel:#151d19; --panel-2:#1b2521;
  --field:#3fb079; --field-ink:#8fe0b8;
  --good:#3fb079; --warn:#e0a53c; --contra:#8b97e8; --bad:#e0715f;
  --home:#3fb079; --draw:#7f8a83; --away:#8b97e8;
}}
.lmx[data-theme="dark"],:root[data-theme="dark"] .lmx{
  --paper:#0f1512; --ink:#e8ede9; --muted:#94a49a; --line:#26302b;
  --panel:#151d19; --panel-2:#1b2521;
  --field:#3fb079; --field-ink:#8fe0b8;
  --good:#3fb079; --warn:#e0a53c; --contra:#8b97e8; --bad:#e0715f;
  --home:#3fb079; --draw:#7f8a83; --away:#8b97e8;
}
:root[data-theme="light"] .lmx{
  --paper:#fbfcfa; --ink:#16211b; --muted:#5d6b62; --line:#e4e8e3;
  --panel:#ffffff; --panel-2:#f4f6f3; --field:#1f8a5b;
  --home:#1f8a5b; --draw:#9aa39c; --away:#5866c9;
}
.lmx-eyebrow{font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;
  color:var(--field-ink);font-weight:700}
.lmx h1{font-size:clamp(1.6rem,4.5vw,2.3rem);margin:.15em 0 .1em;
  letter-spacing:-.02em;text-wrap:balance;font-weight:800}
.lmx h2{font-size:1.15rem;margin:2rem 0 .8rem;letter-spacing:-.01em;font-weight:750}
.lmx .sub{color:var(--muted);font-size:.92rem}
.lmx .pills{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 4px}
.lmx .pill{display:inline-flex;align-items:center;gap:6px;font-size:.76rem;
  padding:4px 10px;border-radius:999px;background:var(--panel-2);
  border:1px solid var(--line);color:var(--muted);font-variant-numeric:tabular-nums}
.lmx .pill b{color:var(--ink);font-weight:650}
.lmx .warnbar{margin:14px 0;padding:12px 14px;border-radius:12px;
  background:color-mix(in srgb,var(--warn) 12%,var(--panel));
  border:1px solid color-mix(in srgb,var(--warn) 40%,var(--line));font-size:.9rem}

/* ticket / boleto */
.lmx .ticket{background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius);padding:6px 0;margin:18px 0 8px;overflow:hidden;
  box-shadow:0 1px 0 var(--line),0 8px 24px -18px rgba(0,0,0,.4)}
.lmx .ticket-h{display:flex;justify-content:space-between;align-items:baseline;
  padding:14px 20px 10px;border-bottom:1px dashed var(--line)}
.lmx .ticket-h .t{font-weight:750;letter-spacing:.02em}
.lmx .ticket-h .m{font-family:var(--mono);font-size:.8rem;color:var(--muted)}
.lmx .brow{display:grid;grid-template-columns:22px 1fr auto;gap:12px;
  align-items:center;padding:11px 20px;border-bottom:1px dashed var(--line)}
.lmx .brow:last-child{border-bottom:0}
.lmx .brow .n{font-family:var(--mono);font-size:.8rem;color:var(--muted)}
.lmx .brow .teams{font-size:.95rem;min-width:0}
.lmx .brow .teams .vs{color:var(--muted);font-size:.82rem;margin:0 6px}
.lmx .brow .score{font-family:var(--mono);font-size:1.15rem;font-weight:700;
  letter-spacing:.06em;text-align:right;font-variant-numeric:tabular-nums}
.lmx .brow .meta{display:flex;gap:8px;align-items:center;justify-content:flex-end;
  margin-top:2px}
.lmx .ticket-f{padding:12px 20px;color:var(--muted);font-size:.82rem;
  font-variant-numeric:tabular-nums;display:flex;justify-content:space-between;
  flex-wrap:wrap;gap:8px}

/* chips */
.lmx .chip{font-size:.68rem;padding:1px 7px;border-radius:6px;font-weight:650;
  letter-spacing:.02em;white-space:nowrap}
.lmx .chip.abst{background:color-mix(in srgb,var(--warn) 18%,transparent);
  color:var(--warn);border:1px solid color-mix(in srgb,var(--warn) 40%,transparent)}
.lmx .chip.con{background:color-mix(in srgb,var(--contra) 16%,transparent);
  color:var(--contra);border:1px solid color-mix(in srgb,var(--contra) 40%,transparent)}
.lmx .chip.o1{background:color-mix(in srgb,var(--home) 16%,transparent);color:var(--home)}
.lmx .chip.oX{background:color-mix(in srgb,var(--draw) 22%,transparent);color:var(--ink)}
.lmx .chip.o2{background:color-mix(in srgb,var(--away) 16%,transparent);color:var(--away)}

/* match cards */
.lmx .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
  gap:14px}
.lmx .card{background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius);padding:16px 16px 14px}
.lmx .card .ch{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.lmx .card .names{font-weight:700;font-size:1rem;letter-spacing:-.01em}
.lmx .card .cx{font-family:var(--mono);font-size:.76rem;color:var(--muted)}
.lmx .pick{display:flex;align-items:baseline;gap:8px;margin:8px 0 2px}
.lmx .pick .s{font-family:var(--mono);font-size:1.5rem;font-weight:750;
  letter-spacing:.04em}
.lmx .pick .ev{font-size:.8rem;color:var(--muted);font-variant-numeric:tabular-nums}
.lmx .bar1x2{display:flex;height:7px;border-radius:4px;overflow:hidden;margin:10px 0 4px;
  background:var(--panel-2)}
.lmx .bar1x2 span{display:block}
.lmx .bar1x2 .h{background:var(--home)} .lmx .bar1x2 .d{background:var(--draw)}
.lmx .bar1x2 .a{background:var(--away)}
.lmx .lbl3{display:flex;justify-content:space-between;font-size:.72rem;
  color:var(--muted);font-variant-numeric:tabular-nums}
.lmx .rows{margin:10px 0 0;border-top:1px solid var(--line);padding-top:8px}
.lmx .r{display:flex;justify-content:space-between;font-size:.82rem;padding:2px 0;
  font-variant-numeric:tabular-nums}
.lmx .r span:first-child{color:var(--muted)}
.lmx .tops{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.lmx .tops code{font-family:var(--mono);font-size:.72rem;background:var(--panel-2);
  border:1px solid var(--line);border-radius:5px;padding:1px 6px}
.lmx .why{margin-top:10px;font-size:.82rem;color:var(--muted);
  border-left:2px solid var(--field);padding-left:10px}
.lmx .meter{height:5px;border-radius:3px;background:var(--panel-2);margin-top:6px;
  overflow:hidden}
.lmx .meter i{display:block;height:100%;background:var(--good)}

/* liguilla series */
.lmx .serie{background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius);padding:16px;margin-bottom:14px}
.lmx .serie .sh{display:flex;justify-content:space-between;align-items:baseline;
  gap:10px;flex-wrap:wrap}
.lmx .serie .tie{font-size:.76rem;color:var(--muted)}
.lmx .adv{margin:12px 0 4px}
.lmx .adv .lab{display:flex;justify-content:space-between;font-size:.82rem;
  font-weight:650;font-variant-numeric:tabular-nums}
.lmx .adv .track{display:flex;height:10px;border-radius:6px;overflow:hidden;
  margin-top:5px;background:var(--panel-2)}
.lmx .adv .track .hi{background:var(--field)}
.lmx .adv .track .lo{background:color-mix(in srgb,var(--away) 70%,var(--panel-2))}
.lmx .legs{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px}
@media (max-width:520px){.lmx .legs{grid-template-columns:1fr}}
.lmx .leg{background:var(--panel-2);border:1px solid var(--line);border-radius:10px;
  padding:10px 12px}
.lmx .leg .lg{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;
  color:var(--field-ink);font-weight:700}
.lmx .leg .lm{font-size:.86rem;margin-top:3px}
.lmx .leg .ls{font-family:var(--mono);font-size:1.15rem;font-weight:700;margin-top:4px;
  font-variant-numeric:tabular-nums}

/* projection table */
.lmx .twrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--radius)}
.lmx table{border-collapse:collapse;width:100%;font-size:.86rem}
.lmx th,.lmx td{padding:9px 12px;text-align:right;font-variant-numeric:tabular-nums;
  white-space:nowrap}
.lmx th:nth-child(2),.lmx td:nth-child(2){text-align:left}
.lmx thead th{position:sticky;top:0;background:var(--panel-2);color:var(--muted);
  font-weight:650;font-size:.74rem;letter-spacing:.04em;text-transform:uppercase;
  border-bottom:1px solid var(--line)}
.lmx tbody tr{border-bottom:1px solid var(--line)}
.lmx tbody tr:last-child{border-bottom:0}
.lmx tbody tr.in{background:color-mix(in srgb,var(--field) 6%,transparent)}
.lmx .pb{position:relative;min-width:120px}
.lmx .pb .fill{position:absolute;left:0;top:0;bottom:0;
  background:color-mix(in srgb,var(--field) 26%,transparent);border-radius:0}
.lmx .pb span{position:relative}
.lmx .foot{margin-top:26px;color:var(--muted);font-size:.78rem;
  border-top:1px solid var(--line);padding-top:12px}
.lmx a{color:var(--field-ink)}

/* stat tiles (CLV) */
.lmx .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:12px;margin:16px 0}
.lmx .tile{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  padding:16px}
.lmx .tile .k{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.lmx .tile .v{font-size:1.9rem;font-weight:800;letter-spacing:-.02em;margin-top:4px;
  font-variant-numeric:tabular-nums}
.lmx .tile .n{font-size:.76rem;color:var(--muted);margin-top:2px}
.lmx .pos{color:var(--good)} .lmx .neg{color:var(--bad)}
.lmx .verdict{margin:6px 0 2px;padding:12px 14px;border-radius:12px;font-size:.92rem;
  background:var(--panel-2);border:1px solid var(--line)}
"""

_OUT = {"1": "h", "X": "d", "2": "a"}


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _shell(title: str, body: str) -> str:
    return f'<style>{_CSS}</style>\n<main class="lmx">\n{body}\n</main>'


def _pills(items: list[tuple[str, str]]) -> str:
    return ('<div class="pills">'
            + "".join(f'<span class="pill">{_e(k)} <b>{_e(v)}</b></span>' for k, v in items)
            + "</div>")


def _bar1x2(p1: float, px: float, p2: float) -> str:
    a, b, c = round(p1 * 100), round(px * 100), round(p2 * 100)
    return (f'<div class="bar1x2"><span class="h" style="width:{a}%"></span>'
            f'<span class="d" style="width:{b}%"></span>'
            f'<span class="a" style="width:{c}%"></span></div>'
            f'<div class="lbl3"><span>1 {a}%</span><span>X {b}%</span><span>2 {c}%</span></div>')


_MKT_ES = {"1X2": "1X2", "O/U 2.5": "Total 2.5"}
_SEL_ES = {"1": "Local", "X": "Empate", "2": "Visita", "Over": "Más 2.5", "Under": "Menos 2.5"}


def _bets_table(bets: list[dict], bankroll: float) -> str:
    rows = []
    for b in bets:
        m = _e(b["match"].replace(" vs ", " · "))
        sel = _e(_SEL_ES.get(b["selection"], b["selection"]))
        clv = b.get("clv_entry", 0.0)
        clv_col = "var(--good)" if clv > 0 else "var(--bad)"
        rows.append(
            f'<tr><td style="text-align:left">{m}</td>'
            f'<td style="text-align:left">{_e(_MKT_ES.get(b["market"], b["market"]))} · {sel}</td>'
            f'<td>{b["model_prob"]*100:.0f}%</td><td>{b["fair_prob"]*100:.0f}%</td>'
            f'<td><b>{b["edge"]*100:+.1f}%</b></td>'
            f'<td>{b["price"]:.2f}</td><td style="text-align:left">{_e(b.get("book") or "—")}</td>'
            f'<td>${b["stake_mxn"]:.0f}</td><td>{b["ev"]*100:+.0f}%</td>'
            f'<td style="color:{clv_col}"><b>{clv*100:+.1f}%</b></td></tr>')
    return ('<div class="twrap"><table><thead><tr>'
            '<th style="text-align:left">Partido</th><th style="text-align:left">Apuesta</th>'
            '<th>Modelo</th><th>Justo</th><th>Edge</th><th>Precio</th>'
            '<th style="text-align:left">Casa</th><th>Stake</th><th>EV</th><th>CLV</th>'
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')


def render_bets_section(bets_payload: dict) -> str:
    """The 'Apuestas de valor' block appended to the boleto.

    Split by **CLV at entry**, not by edge. A big model-vs-market edge is the
    WEAKEST reason to bet (the model is not sharper than 45 books); the price
    beating the sharp no-vig line is the only market-verifiable one. So the
    playable band is `clv_entry > 0` and everything else is measurement.
    """
    bets = bets_payload.get("bets", [])
    params = bets_payload.get("params", {})
    bankroll = params.get("bankroll", 500)
    books = params.get("books") or []
    own_only = params.get("own_books_only", False)
    scope = (f'Precios de <b>tus casas</b> ({_e(", ".join(books))}).' if own_only and books
             else 'Precios del <b>mejor de ~45 casas</b> — incluye casas donde quizá no tengas cuenta.')
    if not bets:
        return ('<h2>Apuestas de valor</h2>'
                f'<div class="sub">{scope} Nada clarea el filtro esta jornada. Eso es sano — '
                'contra un book afilado casi siempre es así. La ventaja real está en la quiniela.</div>')

    play = [b for b in bets if b.get("clv_entry", 0.0) > 0]
    flag = [b for b in bets if b.get("clv_entry", 0.0) <= 0]
    play_stake = sum(b["stake_mxn"] for b in play)
    worst = min((b.get("clv_entry", 0.0) for b in flag), default=0.0)
    avg_clv = sum(b.get("clv_entry", 0.0) for b in bets) / len(bets)

    L = ['<h2>Apuestas de valor</h2>',
         '<div class="warnbar"><b>La prueba que manda es el CLV, no el edge.</b> El modelo '
         '<b>no es más afilado que el mercado</b> (Brier ~0.55 vs ~0.23), así que un edge grande '
         'contra 45 casas casi siempre es <b>error del modelo</b>. Lo único verificable es si '
         '<b>tu precio le gana a la línea justa</b> (CLV &gt; 0): ahí la casa te está pagando de '
         'más, lo diga lo que diga el modelo. ' + scope +
         f' CLV promedio de esta jornada: <b>{avg_clv*100:+.1f}%</b>. '
         'Reglas: ¼-Kelly, tope 2%/apuesta, registra el CLV.</div>']

    L.append('<h3 style="margin:16px 0 6px;font-size:1rem">Jugable '
             '<span style="color:var(--muted);font-weight:500;font-size:.85rem">'
             f'· CLV &gt; 0 · {len(play)} apuesta{"s" if len(play) != 1 else ""} · '
             f'stake ${play_stake:.0f} ({play_stake/bankroll*100:.0f}% del bankroll)</span></h3>')
    if play:
        L.append(_bets_table(play, bankroll))
    else:
        L.append('<div class="sub"><b>Nada jugable.</b> Ningún precio disponible le gana a la '
                 'línea justa: arrancas por debajo del precio verdadero en todas '
                 f'(la menos mala, {worst*100:+.1f}%). Apostar aquí es pagar el vig con pasos '
                 'extra. Lo correcto es <b>no apostar esta jornada</b> y mandar el boleto al '
                 'ledger de CLV como medición.</div>')
    if flag:
        L.append('<h3 style="margin:18px 0 6px;font-size:1rem">Solo medición ⚠ '
                 '<span style="color:var(--muted);font-weight:500;font-size:.85rem">'
                 f'· CLV ≤ 0 · {len(flag)} · el modelo las quiere, el precio no las respalda</span></h3>')
        L.append(_bets_table(flag, bankroll))
    L.append('<div class="foot">Modelo = probabilidad independiente (Poisson+Elo, SIN el mercado '
             'en el blend). Justo = consenso de las ~45 casas del feed, devigado (la referencia '
             'afilada; no se restringe a tus casas aunque el precio sí). Edge = modelo − justo. '
             '<b>CLV = precio / precio justo − 1</b>, el margen con el que entras. Mercados que '
             'cotiza el feed de Liga MX: 1X2 y Total 2.5. Caliente no está en la API — sus precios '
             'se capturan a mano en <code>data/ligamx/books.json</code> y caducan por jornada.</div>')
    return "\n".join(L)


# --- jornada boleto -----------------------------------------------------------
def render_jornada(payload: dict, bets: dict | None = None) -> str:
    picks = sorted(payload.get("picks", []),
                   key=lambda p: (p.get("date") or "", p.get("home") or ""))
    rules = payload.get("rules", {})
    pe = rules.get("points_exact", 2)
    label = payload.get("round", "").upper()
    total_ev = sum(p["ev"] for p in picks)
    max_pts = len(picks) * pe
    abst = sum(1 for p in picks if p.get("abstain"))
    con = sum(1 for p in picks if p.get("contrarian_actionable"))
    with_odds = sum(1 for p in picks if p.get("odds_n_books"))

    pills = [("Partidos", str(len(picks))),
             ("EV total", f"{total_ev:.2f} / {max_pts}")]
    if payload.get("elo_as_of"):
        pills.append(("Elo", payload["elo_as_of"]))
    pills.append(("Mercado", f"{with_odds}/{len(picks)}"))
    if payload.get("odds_as_of"):
        pills.append(("Odds", payload["odds_as_of"]))

    head = (f'<div class="lmx-eyebrow">Liga MX · Apertura</div>'
            f'<h1>Boleto — Jornada {_e(label.replace("J",""))}</h1>'
            f'<div class="sub">Marcador EV-óptimo por partido · scoring {pe} exacto / '
            f'{rules.get("points_1x2",1)} 1X2, excluyente a 90\'.</div>'
            + _pills(pills))
    if not with_odds:
        head += ('<div class="warnbar">Sin línea de mercado en el blend (2 vías, Poisson+Elo). '
                 'Corre <code>ingest.ligamx_odds</code> para sumar las casas — es la señal '
                 'más fuerte del boleto.</div>')

    # Ticket
    brows = []
    for i, p in enumerate(picks, 1):
        chips = []
        chips.append(f'<span class="chip o{p["pick_1x2"] if p["pick_1x2"]!="X" else "X"}">'
                     f'{_e(p["pick_1x2"])}</span>')
        if p.get("abstain"):
            chips.append('<span class="chip abst">ABSTAIN</span>')
        if p.get("contrarian_actionable"):
            chips.append(f'<span class="chip con">◆ {_e(p["contrarian_pick_exact"])}</span>')
        real = f' · real {_e(p["actual"])}' if p.get("actual") else ""
        brows.append(
            f'<div class="brow"><div class="n">{i:02d}</div>'
            f'<div class="teams"><b>{_e(p["home"])}</b><span class="vs">vs</span>'
            f'{_e(p["away"])}<div class="meta">{"".join(chips)}'
            f'<span class="cx" style="color:var(--muted);font-size:.72rem">EV {p["ev"]:.2f}{real}</span>'
            f'</div></div>'
            f'<div class="score">{_e(p["pick_exact"])}</div></div>')
    ticket = (f'<div class="ticket"><div class="ticket-h"><span class="t">TU BOLETO · {_e(label)}</span>'
              f'<span class="m">{len(picks)} partidos</span></div>'
              + "".join(brows)
              + f'<div class="ticket-f"><span>EV total {total_ev:.2f} / {max_pts} máx '
              f'({total_ev/max_pts*100:.0f}% del techo)</span>'
              f'<span>{abst}★ abstain · {con}◆ contrarian</span></div></div>')

    # Match cards
    cards = []
    for p in picks:
        outc = {"1": p["p_home_win"], "X": p["p_draw"], "2": p["p_away_win"]}
        ev_frac = max(0.0, min(1.0, p["ev"] / pe))
        tops = "".join(f'<code>{_e(c["score"])} {c["prob"]*100:.0f}%</code>'
                       for c in p.get("top_5_scores", [])[:5])
        con_line = ""
        if p.get("contrarian_differs"):
            tag = "◆ accionable" if p.get("contrarian_actionable") else "costo alto"
            con_line = (f'<div class="r"><span>Contrarian</span><span>{_e(p["contrarian_pick_exact"])} '
                        f'[{_e(p["contrarian_pick_1x2"])}] · {tag}</span></div>')
        odds_line = ""
        if p.get("odds_n_books"):
            odds_line = (f'<div class="r"><span>Mercado ({p["odds_n_books"]} casas)</span>'
                         f'<span>{p["odds_p1"]*100:.0f}/{p["odds_px"]*100:.0f}/{p["odds_p2"]*100:.0f}</span></div>')
        alt = int(p.get("altitude_m") or 0)
        alt_s = f" · {alt} m" if alt else ""
        cards.append(
            f'<div class="card"><div class="ch"><span class="names">{_e(p["home"])} · {_e(p["away"])}</span>'
            f'<span class="cx">J{_e(p.get("jornada"))}{alt_s}</span></div>'
            f'<div class="pick"><span class="s">{_e(p["pick_exact"])}</span>'
            f'<span class="ev">EV {p["ev"]:.2f} · P(exacto) {p.get("p_exact",0)*100:.0f}%</span></div>'
            f'<div class="meter"><i style="width:{ev_frac*100:.0f}%"></i></div>'
            + _bar1x2(outc["1"], outc["X"], outc["2"]) +
            f'<div class="rows">'
            f'<div class="r"><span>Goles esperados (λ)</span><span>{p["lambda_home"]:.2f} — {p["lambda_away"]:.2f}</span></div>'
            f'<div class="r"><span>Elo</span><span>{p["elo_home"]:.0f} vs {p["elo_away"]:.0f}</span></div>'
            f'{odds_line}{con_line}</div>'
            f'<div class="tops">{tops}</div></div>')

    bets_section = render_bets_section(bets) if bets is not None else ""
    body = (head + ticket
            + '<h2>Cómo leer</h2>'
            '<div class="sub">El <b>boleto</b> es lo que copias a la quiniela. Cada tarjeta '
            'abre el porqué: el medidor verde es la fuerza del EV (0→techo), la barra es 1 / X / 2, '
            'y ◆ marca el contrarian barato si vas atrás en el pool.</div>'
            + bets_section
            + f'<h2>Fichas por partido</h2><div class="cards">{"".join(cards)}</div>'
            + f'<div class="foot">Generado {_e(datetime.utcnow().strftime("%Y-%m-%d %H:%M"))}Z · '
            'modelo Poisson·Dixon-Coles + Elo + mercado. Cada leg se puntúa a 90\'.</div>')
    return _shell(f"Boleto {label}", body)


# --- liguilla series ----------------------------------------------------------
def render_liguilla(payload: dict) -> str:
    series = payload.get("series", [])
    label = payload.get("round_label", "Liguilla")
    projected = payload.get("projected")
    pills = [("Series", str(len(series))), ("Formato", "ida y vuelta · 90'")]
    if payload.get("elo_as_of"):
        pills.append(("Elo", payload["elo_as_of"]))
    head = (f'<div class="lmx-eyebrow">Liga MX · Liguilla</div>'
            f'<h1>{_e(label)}</h1>'
            f'<div class="sub">Cada serie son dos partidos; el pool puntúa cada leg a 90\' '
            f'como cualquier jornada. La barra muestra quién avanza en el global.</div>'
            + _pills(pills))
    if projected:
        head += ('<div class="warnbar">⚠ <b>Bracket proyectado</b> desde la tabla actual — '
                 'los cruces reales aún no se definen. Fija <code>data/ligamx/liguilla.json</code> '
                 'cuando termine el rol regular para recalcular con los cruces oficiales.</div>')

    blocks = []
    for s in series:
        hi_pct = round(s["adv_high"] * 100)
        lo_pct = 100 - hi_pct
        legs = []
        for lg in s["legs"]:
            legs.append(
                f'<div class="leg"><div class="lg">{_e(lg["leg"])}</div>'
                f'<div class="lm">{_e(lg["home"])} <span style="color:var(--muted)">vs</span> {_e(lg["away"])}</div>'
                f'<div class="ls">{_e(lg["pick_exact"])} <span style="font-size:.7rem;color:var(--muted)">'
                f'[{_e(lg["pick_1x2"])}] EV {lg["ev"]:.2f}</span></div></div>')
        blocks.append(
            f'<div class="serie"><div class="sh">'
            f'<span class="names" style="font-weight:750;font-size:1.05rem">'
            f'{_e(s["high"])} <span style="color:var(--muted);font-size:.8rem">({s["high_seed"]}º)</span> '
            f'vs {_e(s["low"])} <span style="color:var(--muted);font-size:.8rem">({s["low_seed"]}º)</span></span>'
            f'<span class="tie">Global empatado → {_e(s["tie_rule"])}</span></div>'
            f'<div class="adv"><div class="lab"><span>{_e(s["high"])} {hi_pct}%</span>'
            f'<span>{lo_pct}% {_e(s["low"])}</span></div>'
            f'<div class="track"><span class="hi" style="width:{hi_pct}%"></span>'
            f'<span class="lo" style="width:{lo_pct}%"></span></div></div>'
            f'<div class="legs">{"".join(legs)}</div></div>')

    body = head + "".join(blocks) + (
        '<div class="foot">Cuartos: 1-8, 2-7, 3-6, 4-5. Las semifinales se resiembran por '
        'posición en la tabla general (mejor vs peor). Global empatado: avanza el mejor '
        'sembrado en cuartos y semis; en la final, tiempos extra y penales.</div>')
    return _shell(label, body)


# --- CLV ledger ---------------------------------------------------------------
def render_clv(stats: dict, entries: list[dict]) -> str:
    def _sign(v):
        return "pos" if (v or 0) > 0 else ("neg" if (v or 0) < 0 else "")

    clv = stats.get("avg_clv_pct")
    beat = stats.get("pct_beat_close")
    roi = stats.get("roi_pct")
    n, nclosed, nset = stats["n"], stats["n_closed"], stats["n_settled"]

    _closed = [e for e in entries if e.get("close_price") is not None]
    same_snapshot = bool(_closed) and all(e["close_price"] == e["entry_price"] for e in _closed)
    verdict = ("Registra más jornadas con línea de cierre para un veredicto sólido."
               if clv is None or nclosed < 10
               else "CLV ≈0: el cierre se capturó en el mismo instante que el registro. Corre "
                    "`ligamx_clv close` cerca del kickoff (tras refrescar odds) para medir el "
                    "movimiento de línea real."
               if same_snapshot and abs(clv) < 0.05
               else "Edge REAL: el modelo le gana a la línea de cierre a lo largo del torneo."
               if clv > 0 else
               "Sin edge medible: el mercado te gana. Concentra la energía en la quiniela.")

    evc = stats.get("avg_ev_close_pct")
    tiles = [
        ("CLV promedio", f"{clv:+.2f}%" if clv is not None else "—", _sign(clv),
         f"{nclosed} con cierre · precio vs cierre"),
        ("Le gana al cierre", f"{beat:.0f}%" if beat is not None else "—",
         "pos" if (beat or 0) >= 50 else "neg" if beat is not None else "",
         f"de {nclosed} apuestas"),
        ("EV vs justa", f"{evc:+.2f}%" if evc is not None else "—", _sign(evc),
         "tu precio vs la prob. sharp"),
        ("ROI realizado", f"{roi:+.1f}%" if roi is not None else "—", _sign(roi),
         (f"{nset} liq · ${stats['profit_mxn']:+.0f}" if nset else f"{n} en el ledger")),
    ]
    tile_html = "".join(
        f'<div class="tile"><div class="k">{_e(k)}</div>'
        f'<div class="v {c}">{_e(v)}</div><div class="n">{_e(nn)}</div></div>'
        for k, v, c, nn in tiles)

    # per-market
    def _mkt_row(m, s):
        clv_td = (f'<td class="{_sign(s["avg_clv_pct"])}">{s["avg_clv_pct"]:+.2f}%</td>'
                  if s["avg_clv_pct"] is not None else '<td>—</td>')
        roi_td = (f'<td>{s["roi_pct"]:+.1f}%</td>' if s["roi_pct"] is not None else '<td>—</td>')
        return (f'<tr><td style="text-align:left">{_e(_MKT_ES.get(m, m))}</td>'
                f'<td>{s["n"]}</td>{clv_td}{roi_td}</tr>')
    mkt_rows = "".join(_mkt_row(m, s) for m, s in stats.get("by_market", {}).items())

    def _row(e):
        edge = (e["model_prob"] - e["entry_fair_prob"]) * 100
        clv_e = (e["entry_price"] / e["close_price"] - 1) * 100 if e.get("close_price") else None
        clv_c = f'<td class="{_sign(clv_e)}">{clv_e:+.1f}%</td>' if clv_e is not None else '<td>—</td>'
        res = e.get("result")
        res_c = ('<span class="chip o1">W</span>' if res == "win"
                 else '<span class="chip o2">L</span>' if res == "loss"
                 else '—')
        pnl = f'{e["profit_mxn"]:+.0f}' if e.get("profit_mxn") is not None else "—"
        return (f'<tr><td>{_e(e["round"].upper())}</td>'
                f'<td style="text-align:left">{_e(e["match"].replace(" vs "," · "))}</td>'
                f'<td style="text-align:left">{_e(_MKT_ES.get(e["market"],e["market"]))} '
                f'{_e(_SEL_ES.get(e["selection"],e["selection"]))}</td>'
                f'<td>{e["model_prob"]*100:.0f}%</td><td>{edge:+.1f}%</td>'
                f'<td>{e["entry_price"]:.2f}</td>'
                f'<td>{("%.2f"%e["close_price"]) if e.get("close_price") else "—"}</td>'
                f'{clv_c}<td>{res_c}</td><td>{pnl}</td></tr>')

    led_rows = "".join(_row(e) for e in entries)

    body = (f'<div class="lmx-eyebrow">Liga MX · Apuestas</div>'
            f'<h1>Ledger de CLV</h1>'
            f'<div class="sub">La línea de cierre es la estimación más afilada del mercado. Si '
            f'apuestas consistentemente a mejor precio que el cierre, tu edge es real — gane o '
            f'pierda cada apuesta suelta. El CLV converge mucho más rápido que el P&amp;L.</div>'
            f'<div class="tiles">{tile_html}</div>'
            f'<div class="verdict"><b>Veredicto:</b> {_e(verdict)}</div>'
            f'<h2>Por mercado</h2>'
            f'<div class="twrap"><table><thead><tr><th style="text-align:left">Mercado</th>'
            f'<th>n</th><th>CLV</th><th>ROI</th></tr></thead><tbody>{mkt_rows}</tbody></table></div>'
            f'<h2>Bitácora</h2>'
            f'<div class="twrap"><table><thead><tr><th>Ronda</th>'
            f'<th style="text-align:left">Partido</th><th style="text-align:left">Apuesta</th>'
            f'<th>Modelo</th><th>Edge</th><th>Precio</th><th>Cierre</th><th>CLV</th>'
            f'<th>Res</th><th>P&amp;L</th></tr></thead><tbody>{led_rows}</tbody></table></div>'
            f'<div class="foot">CLV = precio de entrada × prob. justa de cierre − 1 (EV al cierre). '
            f'Positivo ⇒ le ganaste a la línea afilada. Corre <code>ligamx_clv close</code> cerca '
            f'del kickoff (tras refrescar odds) para llenar la columna de cierre.</div>')
    return _shell("Ledger CLV", body)


# --- projection ---------------------------------------------------------------
def render_projection(payload: dict) -> str:
    table = payload.get("table", [])
    n = payload.get("n_sims", 0)
    pills = [("Simulaciones", f"{n:,}"), ("Jugados", str(table[0]["played"] if table else 0)),
             ("Equipos", str(len(table)))]
    if payload.get("elo_as_of"):
        pills.append(("Elo", payload["elo_as_of"]))
    head = (f'<div class="lmx-eyebrow">Liga MX · Liguilla</div>'
            f'<h1>Proyección del torneo</h1>'
            f'<div class="sub">Monte-Carlo del resto de la temporada → tabla final → siembra → '
            f'bracket. Cuando faltan muchas jornadas, manda la <b>fuerza del modelo</b>, no los '
            f'puntos de hoy.</div>' + _pills(pills))

    def cell(v):
        pct = v * 100
        w = min(100, pct)
        show = f"{pct:.0f}%" if pct >= 1 else (f"{pct:.1f}%" if pct > 0.05 else "—")
        return (f'<td class="pb"><span class="fill" style="width:{w:.0f}%"></span>'
                f'<span>{show}</span></td>')

    rows = []
    for r in table:
        rc = r["reach"]
        cls = ' class="in"' if rc["liguilla"] >= 0.5 else ""
        rows.append(
            f'<tr{cls}><td>{r["pos"]}</td><td>{_e(r["team"])}</td>'
            f'<td>{r["played"]}</td><td>{r["points"]}</td><td>{r["gd"]:+d}</td>'
            + cell(rc["liguilla"]) + cell(rc["semi_final"]) + cell(rc["final"])
            + cell(rc["champion"]) + "</tr>")

    proj_qf = payload.get("projected_qf", [])
    qf = ""
    if proj_qf:
        items = "".join(
            f'<div class="leg"><div class="lg">Cuartos</div>'
            f'<div class="lm"><b>{s["high_seed"]}º</b> {_e(s["high"])} '
            f'<span style="color:var(--muted)">vs</span> <b>{s["low_seed"]}º</b> {_e(s["low"])}</div></div>'
            for s in proj_qf)
        qf = (f'<h2>Bracket proyectado (chalk)</h2>'
              f'<div class="legs" style="grid-template-columns:repeat(auto-fill,minmax(220px,1fr))">{items}</div>')

    body = (head +
            '<h2>Probabilidad de alcanzar cada ronda</h2>'
            '<div class="twrap"><table><thead><tr>'
            '<th>#</th><th>Equipo</th><th>J</th><th>Pts</th><th>DG</th>'
            '<th>Liguilla</th><th>Semis</th><th>Final</th><th>Campeón</th>'
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'
            + qf +
            '<div class="foot">Las filas resaltadas proyectan ≥50% de meterse a la liguilla. '
            'Barras = probabilidad de alcanzar esa ronda al menos una vez en la simulación.</div>')
    return _shell("Proyección liguilla", body)
