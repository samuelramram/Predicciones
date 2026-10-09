"""Sellado de boletos: nadie (ni un bot, ni Samuel) cambia un pick después del deadline.

Cada boleto se guarda como un registro con:
    round, bot, picks, sealed_at, prev_hash, hash

``hash`` es SHA-256 del JSON canónico de todo lo demás, y ``prev_hash`` encadena
cada registro con el anterior del libro (append-only). Editar un pick viejo rompe
su hash; borrar o reordenar registros rompe la cadena. :func:`verify_chain` lo
detecta, y :func:`sealed_before` confirma que el boleto se selló antes del primer
partido de la jornada.

El libro vive en ``data/liga/ledger.jsonl`` (una línea por boleto) y se versiona:
el historial de git es una segunda capa de evidencia.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from wc_predictor.liga.paths import ledger_path

LEDGER = ledger_path()  # data/liga/ledger.jsonl, or $LIGA_HOME/ledger.jsonl on the VPS
GENESIS = "0" * 64


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def seal(round_id: str, bot: str, picks: list[dict], prev_hash: str = GENESIS,
         sealed_at: str | None = None) -> dict:
    """Build a sealed record. ``picks``: [{match_id|home/away, pick_1x2, pick_exact, ...}]."""
    # Deep copy: a caller mutating its pick dicts after sealing must not
    # silently rewrite the sealed record (nor the other way around).
    picks = sorted(copy.deepcopy(picks), key=lambda p: _canonical({k: p.get(k) for k in ("match_id", "home", "away")}))
    record = {
        "round": round_id,
        "bot": bot,
        "picks": picks,
        "sealed_at": sealed_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prev_hash": prev_hash,
    }
    record["hash"] = _digest(record)
    return record


def verify(record: dict) -> bool:
    return record.get("hash") == _digest(record)


def verify_chain(records: list[dict]) -> tuple[bool, str]:
    """(ok, reason). Checks every hash and the prev_hash linkage, in order."""
    prev = GENESIS
    for i, r in enumerate(records):
        if not verify(r):
            return False, f"registro {i} ({r.get('round')}/{r.get('bot')}): hash no coincide — fue editado"
        if r.get("prev_hash") != prev:
            return False, f"registro {i} ({r.get('round')}/{r.get('bot')}): cadena rota — falta o se movió un registro"
        prev = r["hash"]
    return True, f"{len(records)} boletos íntegros"


def sealed_before(record: dict, first_kickoff_iso: str) -> bool:
    """True if the ticket was sealed strictly before the first kickoff of the round."""
    def _ts(s: str) -> datetime:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return _ts(record["sealed_at"]) < _ts(first_kickoff_iso)


def read_ledger(path: Path = LEDGER) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append(round_id: str, bot: str, picks: list[dict], path: Path = LEDGER,
           sealed_at: str | None = None) -> dict:
    """Seal a ticket and append it to the ledger, chained to the last record.

    Refuses to append on a broken chain (fix the ledger first) and refuses a
    second ticket for the same (round, bot): a re-seal would be a pick change."""
    records = read_ledger(path)
    ok, why = verify_chain(records)
    if not ok:
        raise ValueError(f"Libro corrupto, no se agrega nada: {why}")
    if any(r["round"] == round_id and r["bot"] == bot for r in records):
        raise ValueError(f"{bot} ya selló su boleto de {round_id}; no se puede cambiar.")
    rec = seal(round_id, bot, picks, prev_hash=records[-1]["hash"] if records else GENESIS,
               sealed_at=sealed_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(_canonical(rec) + "\n")
    return rec
