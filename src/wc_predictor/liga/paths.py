"""Dónde vive la liga en vivo.

En el repo (default) el libro y las jornadas viven bajo ``data/``. En el VPS,
Claudio trabaja en su workspace de OpenClaw y la liga vive aparte del clon del
repo (que el Utilero resetea): se apunta con la variable ``LIGA_HOME``.
"""
from __future__ import annotations

import os
from pathlib import Path

from wc_predictor.config import DATA_DIR


def liga_home() -> Path:
    env = os.environ.get("LIGA_HOME")
    return Path(env) if env else DATA_DIR / "liga"


def ledger_path() -> Path:
    return liga_home() / "ledger.jsonl"


def rounds_dir() -> Path:
    env = os.environ.get("LIGA_HOME")
    return Path(env) / "rounds" if env else DATA_DIR / "europa" / "rounds"


def tabla_dir() -> Path:
    return liga_home() / "tabla"
