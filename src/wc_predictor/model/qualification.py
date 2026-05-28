"""Group-stage qualification context for the World Cup 2026 quiniela.

After jornadas 1 and 2 the group table is known. This module computes the
standings with the official FIFA 2026 tiebreakers and, for each jornada-3
fixture, classifies what the match is actually worth: which teams already have
their top-2 finish locked, which can no longer reach it, whether the match is a
dead rubber, and whether a draw sends both teams through.

FORMAT 2026 (12 groups, 32 → 48 teams): the top 2 of each group advance PLUS the
8 best third-placed teams. A team knocked out of the top 2 is therefore NOT
necessarily out of the tournament — it can still chase a best-third spot. Only a
team locked into LAST place (4th) is mathematically eliminated, since 4th never
qualifies. We cannot decide the best-third race from a single group (it needs all
12 tables at once), so this module is deliberately conservative:

  - A team is treated as having "nothing at stake" (decided) only when it is
    SECURED top-2 (definitely through) or LOCKED LAST (definitely out).
  - A team that can still finish 3rd is `TOP2_ELIMINATED` for the top-2 race but
    is still PLAYING for a best-third spot, so its J3 match is NOT a dead rubber.

This fixes the pre-2026 bug where any top2_secured-vs-top2_eliminated pairing was
flagged a dead rubber even though the "eliminated" side was fighting for 3rd.

`pipeline.generate_picks` consumes this so a J3 game between two already-decided
teams is not predicted with the same confidence as a win-or-go-home decider.

FIFA 2026 group tiebreakers, applied in order:
  1. Points.
  2. Head-to-head among the teams still tied: points, then goal difference,
     then goals scored, counting only matches between those teams.
  3. Goal difference across all group matches.
  4. Goals scored across all group matches.
  5. Disciplinary (fair-play) points  -- not modelled: no card data available.
  6. FIFA ranking                      -- approximated by Elo rating.

Steps 5-6 are rare. When steps 1-4 leave teams tied this module falls back to
Elo (a strong FIFA-ranking proxy) and finally team name, so the order is always
deterministic. Head-to-head is applied once across the whole tied block; FIFA's
recursive re-application to surviving sub-ties is omitted (a rare edge case).
"""
from __future__ import annotations

from dataclasses import dataclass


# Per-team top-2 classification for a jornada-3 fixture.
TOP2_SECURED = "top2_secured"        # finishes top 2 regardless of any J3 result
TOP2_POSSIBLE = "top2_possible"      # top 2 still depends on J3 results
TOP2_ELIMINATED = "top2_eliminated"  # cannot finish top 2 (may still chase 3rd place)

# (home_points, away_points) for a win / draw / loss of one match.
_WDL = ((3, 0), (1, 1), (0, 3))


def _is_played(m: dict) -> bool:
    return m.get("home_score") not in (None, "") and m.get("away_score") not in (None, "")


@dataclass
class TeamRecord:
    team: str
    played: int = 0
    points: int = 0
    gf: int = 0
    ga: int = 0

    @property
    def gd(self) -> int:
        return self.gf - self.ga


@dataclass
class StakesContext:
    group: str
    home: str
    away: str
    home_status: str
    away_status: str
    dead_rubber: bool       # neither team's ADVANCEMENT depends on this match
    mutual_draw_safe: bool  # a draw sends both teams through to top 2
    note: str
    # 2026 best-third awareness: a team out of the top 2 can still chase a
    # qualifying 3rd-place spot. False only when the team is locked into last.
    home_chasing_third: bool = False
    away_chasing_third: bool = False


def _resolve_block(block: list[TeamRecord], played: list[dict],
                   elos: dict[str, float]) -> list[TeamRecord]:
    """Order a set of teams tied on points using the FIFA head-to-head rules."""
    teams = {r.team for r in block}
    mini: dict[str, list[int]] = {t: [0, 0, 0] for t in teams}  # [points, gf, ga]
    for m in played:
        h, a = m["home"], m["away"]
        if h in teams and a in teams:
            hs, as_ = int(m["home_score"]), int(m["away_score"])
            mini[h][1] += hs
            mini[h][2] += as_
            mini[a][1] += as_
            mini[a][2] += hs
            if hs > as_:
                mini[h][0] += 3
            elif hs < as_:
                mini[a][0] += 3
            else:
                mini[h][0] += 1
                mini[a][0] += 1

    def key(r: TeamRecord):
        mp, mgf, mga = mini[r.team]
        return (-mp, -(mgf - mga), -mgf, -r.gd, -r.gf,
                -elos.get(r.team, 1500.0), r.team)

    return sorted(block, key=key)


def compute_standings(group_teams, matches, elos=None) -> list[TeamRecord]:
    """Return the group table, best team first, with FIFA 2026 tiebreakers.

    `matches` may hold any subset of the group's fixtures; only played ones
    (both scores present) count, so the function works mid-group too.
    """
    elos = elos or {}
    recs = {t: TeamRecord(team=t) for t in group_teams}
    played = [m for m in matches
              if _is_played(m) and m["home"] in recs and m["away"] in recs]
    for m in played:
        hs, as_ = int(m["home_score"]), int(m["away_score"])
        h, a = recs[m["home"]], recs[m["away"]]
        h.played += 1
        a.played += 1
        h.gf += hs
        h.ga += as_
        a.gf += as_
        a.ga += hs
        if hs > as_:
            h.points += 3
        elif hs < as_:
            a.points += 3
        else:
            h.points += 1
            a.points += 1

    ordered = sorted(
        recs.values(),
        key=lambda r: (-r.points, -r.gd, -r.gf, -elos.get(r.team, 1500.0), r.team),
    )
    result: list[TeamRecord] = []
    i = 0
    while i < len(ordered):
        j = i
        while j < len(ordered) and ordered[j].points == ordered[i].points:
            j += 1
        block = ordered[i:j]
        result.extend(_resolve_block(block, played, elos) if len(block) > 1 else block)
        i = j
    return result


def _top2_status_in_combo(points: dict[str, int], team: str) -> str:
    """'in' if the team is certainly top-2 in this points table, 'out' if
    certainly not, 'amb' if it sits exactly on the 2nd/3rd boundary (a tie that
    only goal difference could break)."""
    ranked = sorted(points.values(), reverse=True)
    second, third = ranked[1], ranked[2]
    p = points[team]
    if p > third:
        return "in"
    if p < second:
        return "out"
    return "amb"


def _build_note(home: str, away: str, home_status: str, away_status: str,
                dead_rubber: bool, mutual_draw_safe: bool,
                home_chasing_third: bool = False,
                away_chasing_third: bool = False) -> str:
    chasing = {home: home_chasing_third, away: away_chasing_third}
    if dead_rubber:
        note = ("Partido sin nada en juego para la clasificación: ambas "
                "selecciones ya tienen decidida su suerte antes de jugarlo.")
    elif home_status == TOP2_POSSIBLE and away_status == TOP2_POSSIBLE:
        note = "Partido decisivo: el resultado define quién avanza en el top-2."
    else:
        bits = []
        for team, status in ((home, home_status), (away, away_status)):
            if status == TOP2_SECURED:
                bits.append(f"{team} ya tiene asegurado el top-2")
            elif status == TOP2_ELIMINATED:
                if chasing[team]:
                    bits.append(f"{team} quedó fuera del top-2 pero sigue peleando "
                                f"un puesto de mejor tercero")
                else:
                    bits.append(f"{team} ya está eliminado (no alcanza ni el mejor tercero)")
            else:
                bits.append(f"{team} todavía se juega el top-2")
        note = "; ".join(bits) + "."
    if mutual_draw_safe and not dead_rubber:
        note += (" Un empate clasifica a las dos al top-2: ojo con un empate "
                 "de conveniencia.")
    return note


def j3_stakes(group, group_teams, played_j12, j3_home, j3_away, elos=None):
    """Classify a jornada-3 fixture, or return None if the table isn't ready.

    `played_j12` must contain the four completed jornada-1 and jornada-2
    matches of the group; before they all exist this returns None (no-op, so
    the picks pipeline degrades gracefully pre-tournament).

    Top-2 status is decided by enumerating the nine win/draw/loss combinations
    of the group's two remaining J3 matches. A team is `TOP2_SECURED` only when
    it lands top-2 on points in every combination, and `TOP2_ELIMINATED` only
    when it never does — ties that hinge on goal difference stay `POSSIBLE`, so
    the classification never over-claims.
    """
    if len(group_teams) != 4:
        return None
    played = [m for m in played_j12 if _is_played(m)
              and m["home"] in group_teams and m["away"] in group_teams]
    if len(played) < 4:
        return None
    others = [t for t in group_teams if t not in (j3_home, j3_away)]
    if len(others) != 2:
        return None
    o1, o2 = others

    base = {r.team: r.points for r in compute_standings(group_teams, played, elos)}

    counts = {t: {"in": 0, "out": 0, "amb": 0} for t in group_teams}
    # `last`: number of combos in which the team is strictly LAST (>=3 teams above
    # it on points). Locked-last == eliminated for sure, since 4th never qualifies.
    last_counts = {t: 0 for t in group_teams}
    draw_status = {j3_home: [], j3_away: []}
    for ha, aa in _WDL:            # this fixture: j3_home vs j3_away
        for hb, ab in _WDL:        # the group's other J3 fixture: o1 vs o2
            pts = dict(base)
            pts[j3_home] += ha
            pts[j3_away] += aa
            pts[o1] += hb
            pts[o2] += ab
            for t in group_teams:
                counts[t][_top2_status_in_combo(pts, t)] += 1
                if sum(1 for other in pts.values() if other > pts[t]) >= 3:
                    last_counts[t] += 1
            if (ha, aa) == (1, 1):
                draw_status[j3_home].append(_top2_status_in_combo(pts, j3_home))
                draw_status[j3_away].append(_top2_status_in_combo(pts, j3_away))

    def classify(t: str) -> str:
        c = counts[t]
        if c["in"] == 9:
            return TOP2_SECURED
        if c["out"] == 9:
            return TOP2_ELIMINATED
        return TOP2_POSSIBLE

    home_status = classify(j3_home)
    away_status = classify(j3_away)

    # 2026 best-third format: out of the top 2 but NOT locked into last place ==
    # still chasing a qualifying 3rd-place spot, so the match still matters.
    def chasing_third(t: str, status: str) -> bool:
        return status == TOP2_ELIMINATED and last_counts[t] < 9

    home_chasing_third = chasing_third(j3_home, home_status)
    away_chasing_third = chasing_third(j3_away, away_status)

    # A team's advancement is DECIDED only when it is secured top-2 (in for sure)
    # or locked last (out for sure). Top-2-eliminated-but-chasing-3rd is NOT
    # decided. Dead rubber requires both teams decided.
    def decided(t: str, status: str) -> bool:
        return status == TOP2_SECURED or last_counts[t] == 9
    dead_rubber = decided(j3_home, home_status) and decided(j3_away, away_status)

    mutual_draw_safe = (all(s == "in" for s in draw_status[j3_home])
                        and all(s == "in" for s in draw_status[j3_away]))

    return StakesContext(
        group=group,
        home=j3_home,
        away=j3_away,
        home_status=home_status,
        away_status=away_status,
        dead_rubber=dead_rubber,
        mutual_draw_safe=mutual_draw_safe,
        note=_build_note(j3_home, j3_away, home_status, away_status,
                         dead_rubber, mutual_draw_safe,
                         home_chasing_third, away_chasing_third),
        home_chasing_third=home_chasing_third,
        away_chasing_third=away_chasing_third,
    )
