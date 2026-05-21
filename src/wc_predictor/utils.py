"""Reproducibility helpers: file hashing, config hashing, git introspection.

Lifted from the Liga MX `utils.py` and trimmed. Used by the pipeline to write a
fingerprint JSON next to every output round.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def file_sha256(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        return "FILE_NOT_FOUND"
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()


def config_hash(cfg: Any, length: int = 12) -> str:
    """Short stable hash of any dataclass-like config."""
    if is_dataclass(cfg):
        payload = asdict(cfg)
    else:
        payload = cfg
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:length]


def git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return None


def git_dirty() -> bool | None:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"], stderr=subprocess.DEVNULL
        ).decode()
        return bool(out.strip())
    except Exception:
        return None
