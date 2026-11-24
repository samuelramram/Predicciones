"""Presupuesto de créditos de The Odds API — compartido con otros proyectos.

La llave del plan gratis trae 500 créditos/mes y la usan VARIOS proyectos del
usuario. Cada llamada a ``/odds`` cobra ``#mercados × #regiones``; en nov 2026 el
mes llegó al día 24 con 430 usados (``ligamx_odds`` cobraba 6 por corrida y el
VPS pedía las copas UEFA a diario aunque no hubiera partidos).

Aquí solo hay endpoints que NO cobran (verificado: ``x-requests-last: 0``):
  - ``/v4/sports``                 → créditos restantes en los headers
  - ``/v4/sports/{sport}/events``  → calendario sin momios

Reglas que aplican los ingests:
  1. No pedir momios de una competencia sin partidos en la ventana próxima.
  2. Respetar una RESERVA: si quedan menos créditos que ``ODDS_API_RESERVE``
     (default 100), no se gasta salvo ``--force``. Los demás proyectos comen de ahí.
     La quiniela de Liga MX (``ligamx_odds``, 1 crédito por corrida) usa su propia
     reserva, 25 por default (``--reserve``): es el consumidor prioritario.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://api.the-odds-api.com/v4"
DEFAULT_RESERVE = 100


def reserve() -> int:
    try:
        return int(os.environ.get("ODDS_API_RESERVE", DEFAULT_RESERVE))
    except ValueError:
        return DEFAULT_RESERVE


def _get(url: str) -> tuple[object, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "predicciones/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8")), dict(r.headers)


def credits_left(key: str) -> int | None:
    """Créditos restantes del mes (endpoint gratis). None si no se pudo leer."""
    try:
        _, h = _get(f"{BASE}/sports/?apiKey={key}")
    except Exception:
        return None
    v = {k.lower(): x for k, x in h.items()}.get("x-requests-remaining")
    try:
        return int(float(v)) if v is not None else None
    except ValueError:
        return None


def upcoming_events(key: str, sport: str, hours: float = 72.0,
                    now: datetime | None = None) -> list[dict] | None:
    """Partidos de `sport` que arrancan en las próximas `hours` (endpoint gratis).
    None si la consulta falló (el llamador decide; por default no gasta)."""
    try:
        events, _ = _get(f"{BASE}/sports/{sport}/events?apiKey={key}")
    except Exception:
        return None
    return events_within(events, hours, now)


def events_within(events, hours: float, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    end = now + timedelta(hours=hours)
    out = []
    for e in events or []:
        try:
            t = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if now - timedelta(hours=3) <= t <= end:   # incluye los que van en juego
            out.append(e)
    return out


def can_spend(key: str, cost: int, force: bool = False, label: str = "",
              reserve_floor: int | None = None) -> bool:
    """True si gastar `cost` créditos deja intacta la reserva (o si `force`).
    `reserve_floor` sustituye la reserva global (p.ej. la quiniela, 1 crédito por
    corrida, usa una menor que las automatizaciones diarias)."""
    left = credits_left(key)
    res = reserve() if reserve_floor is None else reserve_floor
    if left is None:
        print(f"  {label}: no pude leer créditos restantes; no gasto (usa --force).")
        return force
    if left - cost < res and not force:
        print(f"  {label}: quedan {left} créditos y la reserva para otros proyectos es "
              f"{res} (ODDS_API_RESERVE); no gasto {cost}. --force para saltarla.")
        return False
    print(f"  {label}: gasto {cost} crédito(s); quedan {left} → ~{left - cost}.")
    return True
