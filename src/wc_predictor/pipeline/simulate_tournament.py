"""Run the WC 2026 full-tournament Monte Carlo simulation.

Reads:
    data/processed/team_strengths.json
    data/wc2026/fixtures.json
    data/wc2026/venues.json
    data/historical/elo_current.json

Writes:
    outputs/tournament_sim.json   — full probability table per team
    outputs/tournament_sim.md     — human-readable report (sorted by P(champion))

Usage:
    python -m wc_predictor.pipeline.simulate_tournament
    python -m wc_predictor.pipeline.simulate_tournament --sims 50000
    python -m wc_predictor.pipeline.simulate_tournament --top 20
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from wc_predictor.config import DEFAULT_CONFIG, HISTORICAL_DIR, OUTPUTS_DIR, PROCESSED_DIR, WC_DIR
from wc_predictor.model.poisson_dc import load_fit
from wc_predictor.model.tournament_sim import (
    ROUND_LABELS,
    ROUNDS,
    TournamentSimResult,
    simulate_tournament,
)

# Spanish team names for the report (display only — data layer stays in English)
TEAM_ES: dict[str, str] = {
    "Mexico": "México", "South Africa": "Sudáfrica", "Czech Republic": "República Checa",
    "South Korea": "Corea del Sur", "Canada": "Canadá", "Switzerland": "Suiza",
    "Bosnia and Herzegovina": "Bosnia y Herzegovina", "Qatar": "Catar",
    "Brazil": "Brasil", "Scotland": "Escocia", "Morocco": "Marruecos", "Haiti": "Haití",
    "United States": "Estados Unidos", "Australia": "Australia", "Paraguay": "Paraguay",
    "Turkey": "Turquía", "Germany": "Alemania", "Ecuador": "Ecuador",
    "Ivory Coast": "Costa de Marfil", "Curaçao": "Curazao", "Netherlands": "Países Bajos",
    "Sweden": "Suecia", "Japan": "Japón", "Tunisia": "Túnez", "Belgium": "Bélgica",
    "Egypt": "Egipto", "Iran": "Irán", "New Zealand": "Nueva Zelanda", "Spain": "España",
    "Uruguay": "Uruguay", "Saudi Arabia": "Arabia Saudita", "Cape Verde": "Cabo Verde",
    "France": "Francia", "Senegal": "Senegal", "Norway": "Noruega", "Iraq": "Irak",
    "Argentina": "Argentina", "Austria": "Austria", "Algeria": "Argelia",
    "Jordan": "Jordania", "Portugal": "Portugal", "Colombia": "Colombia",
    "DR Congo": "RD Congo", "Uzbekistan": "Uzbekistán", "England": "Inglaterra",
    "Croatia": "Croacia", "Ghana": "Ghana", "Panama": "Panamá",
}


def _tes(name: str) -> str:
    return TEAM_ES.get(name, name)


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _write_markdown(result: TournamentSimResult, dst: Path, top_n: int | None) -> None:
    all_teams = [t for letter in sorted(result.groups) for t in result.groups[letter]]
    by_champion = sorted(all_teams, key=lambda t: -result.advance_rates[t]["champion"])
    teams_to_show = by_champion[:top_n] if top_n else by_champion

    lines: list[str] = []
    lines.append("# Simulación Monte Carlo · Mundial 2026\n")
    lines.append(
        f"_{result.n_sims:,} torneos simulados · "
        f"generado {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC · "
        f"tiempo: {result.elapsed_seconds:.1f}s_\n"
    )
    lines.append(
        "Probabilidades basadas en el modelo Poisson+Dixon-Coles "
        "mezclado con Elo (70/30), venue data para ventaja local.\n"
    )

    # Full probability table
    header_rounds = ["Clasifica", "R16", "QF", "SF", "Final", "Campeón"]
    col_w = 24
    lines.append("## Probabilidades por ronda\n")
    header = f"{'Selección':<{col_w}}" + "".join(f"{h:>9}" for h in header_rounds)
    lines.append("```")
    lines.append(header)
    lines.append("─" * len(header))
    prev_group = None
    for team in teams_to_show:
        gr = next(
            letter for letter, members in result.groups.items() if team in members
        )
        if gr != prev_group:
            if prev_group is not None:
                lines.append("")
            lines.append(f"  Grupo {gr}")
            prev_group = gr
        rates = result.advance_rates[team]
        row = f"  {_tes(team):<{col_w - 2}}"
        for rnd in ROUNDS:
            row += f"{_pct(rates[rnd]):>9}"
        lines.append(row)
    lines.append("─" * len(header))
    lines.append("```\n")

    # Top-8 champion contenders callout
    top8 = by_champion[:8]
    lines.append("## Favoritos al título (top 8)\n")
    lines.append("| Selección | Campeón | Final | Semifinal | Clasifica |")
    lines.append("|---|---|---|---|---|")
    for team in top8:
        r = result.advance_rates[team]
        lines.append(
            f"| **{_tes(team)}** | {_pct(r['champion'])} | {_pct(r['reach_final'])} | "
            f"{_pct(r['reach_sf'])} | {_pct(r['advance_group'])} |"
        )
    lines.append("")

    # Group finish distribution for all groups
    lines.append("## Distribución de posición por grupo\n")
    for letter in sorted(result.groups):
        teams_in_group = result.groups[letter]
        lines.append(f"### Grupo {letter}\n")
        lines.append("| Selección | 1.º | 2.º | 3.º | 4.º |")
        lines.append("|---|---|---|---|---|")
        for team in teams_in_group:
            gf = result.group_finish[team]
            lines.append(
                f"| {_tes(team)} | {_pct(gf[1])} | {_pct(gf[2])} | "
                f"{_pct(gf[3])} | {_pct(gf[4])} |"
            )
        lines.append("")

    dst.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="WC2026 full tournament Monte Carlo simulation."
    )
    parser.add_argument(
        "--sims", type=int, default=20_000,
        help="Number of tournament simulations (default: 20000)"
    )
    parser.add_argument(
        "--top", type=int, default=None,
        help="Show only top N teams by P(champion) in the probability table"
    )
    args = parser.parse_args()

    fit_src = PROCESSED_DIR / "team_strengths.json"
    if not fit_src.exists():
        raise SystemExit(
            f"Missing {fit_src}. Run `python -m wc_predictor.pipeline.fit_model` first."
        )

    print(f"Loading fit from {fit_src} ...")
    fit = load_fit(fit_src)
    print(f"  mu={fit.mu:.3f}  gamma={fit.gamma:.3f}  rho={fit.rho:.3f}  "
          f"({fit.n_teams} teams, {fit.n_matches} matches)")

    venues_src = WC_DIR / "venues.json"
    with venues_src.open(encoding="utf-8") as f:
        venues = json.load(f)["venues"]
    print(f"Loaded {len(venues)} venues")

    fixtures_src = WC_DIR / "fixtures.json"
    with fixtures_src.open(encoding="utf-8") as f:
        fixtures_doc = json.load(f)
    groups: dict[str, list[str]] = fixtures_doc["groups"]
    group_fixtures = [m for m in fixtures_doc["matches"] if m["stage"] == "group_stage"]
    print(f"Loaded {len(group_fixtures)} group-stage fixtures, {len(groups)} groups")

    elos_src = HISTORICAL_DIR / "elo_current.json"
    if not elos_src.exists():
        raise SystemExit(
            "Missing data/historical/elo_current.json. "
            "Run `python -m wc_predictor.pipeline.fit_elo` first."
        )
    with elos_src.open(encoding="utf-8") as f:
        elos_data = json.load(f)
    elos: dict[str, float] = {row["team"]: row["elo"] for row in elos_data["teams"]}
    print(f"Loaded Elo for {len(elos)} teams")

    cfg = DEFAULT_CONFIG.model

    print(f"\nRunning {args.sims:,} tournament simulations ...")
    result = simulate_tournament(
        groups=groups,
        group_fixtures=group_fixtures,
        fit=fit,
        elos=elos,
        venues=venues,
        cfg=cfg,
        n_sims=args.sims,
        seed=DEFAULT_CONFIG.seed,
    )
    print(f"  done in {result.elapsed_seconds:.1f}s\n")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    # Write JSON
    json_dst = OUTPUTS_DIR / "tournament_sim.json"
    with json_dst.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "as_of": datetime.utcnow().isoformat() + "Z",
                "n_sims": result.n_sims,
                "elapsed_seconds": round(result.elapsed_seconds, 2),
                "advance_rates": {
                    team: {rnd: round(p, 4) for rnd, p in rates.items()}
                    for team, rates in result.advance_rates.items()
                },
                "group_finish": {
                    team: {str(rank): round(p, 4) for rank, p in finish.items()}
                    for team, finish in result.group_finish.items()
                },
                "groups": result.groups,
            },
            f, indent=2, ensure_ascii=False,
        )
    print(f"  wrote {json_dst}")

    # Write Markdown
    md_dst = OUTPUTS_DIR / "tournament_sim.md"
    _write_markdown(result, md_dst, args.top)
    print(f"  wrote {md_dst}")

    # Print top-10 to console
    all_teams = [t for letter in sorted(result.groups) for t in result.groups[letter]]
    by_champ = sorted(all_teams, key=lambda t: -result.advance_rates[t]["champion"])
    print("TOP 10 FAVORITOS AL TÍTULO:")
    print(f"  {'Selección':<22} {'Campeón':>8} {'Final':>7} {'SF':>7} {'QF':>7} {'R16':>7} {'Clasifica':>10}")
    print("  " + "─" * 65)
    for team in by_champ[:10]:
        r = result.advance_rates[team]
        print(
            f"  {_tes(team):<22} "
            f"{_pct(r['champion']):>8} "
            f"{_pct(r['reach_final']):>7} "
            f"{_pct(r['reach_sf']):>7} "
            f"{_pct(r['reach_qf']):>7} "
            f"{_pct(r['reach_r16']):>7} "
            f"{_pct(r['advance_group']):>10}"
        )


if __name__ == "__main__":
    main()
