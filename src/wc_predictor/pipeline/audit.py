"""Auditoría del codebase WC2026: fuente única de verdad, imports canónicos y consistencia.

Equivalente al `auditar_fuente_modelo.py` del legacy Liga MX, adaptado al módulo WC2026.

Run:
    python -m wc_predictor.pipeline.audit
    python -m wc_predictor.pipeline.audit --save   # guarda en outputs/audit_report.txt

Checks:
  1. Fuente única: QuinielaRules / ModelConfig / DEFAULT_CONFIG siempre de config.py.
  2. Fuente única: score_actual, optimize_pick* siempre de scoring.quiniela.
  3. Fuente única: predict_lambdas / fit_dc_model siempre de model.poisson_dc.
  4. Sin constantes hardcodeadas: no hay points_exact=N, dc_rho=N, ev_abstain_gap=N
     fuera de config.py.
  5. Fingerprint coverage: cada script de pipeline que tiene main() genera fingerprint.
  6. Determinismo: random.Random siempre se inicializa con seed explícito.
  7. No hay redefinición local del EV optimizer.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src" / "wc_predictor"
CONFIG_MODULE = "wc_predictor.config"

# Symbols that must always be imported from their canonical home.
CANONICAL_IMPORTS: dict[str, str] = {
    "QuinielaRules":         "wc_predictor.config",
    "ModelConfig":           "wc_predictor.config",
    "RunConfig":             "wc_predictor.config",
    "DEFAULT_CONFIG":        "wc_predictor.config",
    "score_actual":          "wc_predictor.scoring.quiniela",
    "optimize_pick":         "wc_predictor.scoring.quiniela",
    "optimize_pick_from_cells": "wc_predictor.scoring.quiniela",
    "build_score_matrix":    "wc_predictor.scoring.quiniela",
    "predict_lambdas":       "wc_predictor.model.poisson_dc",
    "fit_dc_model":          "wc_predictor.model.poisson_dc",
    "load_fit":              "wc_predictor.model.poisson_dc",
}

# Patterns that should not appear outside config.py (hardcoded scoring constants).
HARDCODED_PATTERNS: list[tuple[str, str]] = [
    (r"\bpoints_exact\s*=\s*\d",  "points_exact hardcoded (use QuinielaRules.points_exact)"),
    (r"\bpoints_1x2\s*=\s*\d",    "points_1x2 hardcoded (use QuinielaRules.points_1x2)"),
    (r"\bdc_rho\s*=\s*-",         "dc_rho hardcoded (use ModelConfig.dc_rho)"),
    (r"\bev_abstain_gap\s*=\s*",  "ev_abstain_gap hardcoded (use ModelConfig.ev_abstain_gap)"),
    (r"\bcontrarian_max_ev_sacrifice\s*=\s*",
     "contrarian_max_ev_sacrifice hardcoded (use ModelConfig.contrarian_max_ev_sacrifice)"),
    (r"\bpool_participants\s*=\s*\d", "pool_participants hardcoded (use QuinielaRules.pool_participants)"),
]

# Production pipeline scripts expected to generate fingerprints for reproducibility.
# backtest.py is excluded: it runs on historical data and its outputs are not submitted.
PIPELINE_SCRIPTS_WITH_FINGERPRINT = {"generate_picks.py"}


@dataclass
class Finding:
    severity: str   # "ERROR" | "WARNING" | "INFO"
    file: str
    line: int
    message: str


@dataclass
class AuditResult:
    findings: list[Finding] = field(default_factory=list)
    n_files: int = 0
    n_errors: int = 0
    n_warnings: int = 0

    def add(self, severity: str, file: str, line: int, message: str) -> None:
        self.findings.append(Finding(severity, file, line, message))
        if severity == "ERROR":
            self.n_errors += 1
        elif severity == "WARNING":
            self.n_warnings += 1

    @property
    def passed(self) -> bool:
        return self.n_errors == 0


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _collect_py_files() -> list[Path]:
    files = sorted(SRC_ROOT.rglob("*.py"))
    # Also audit the tests.
    test_dir = REPO_ROOT / "tests"
    if test_dir.exists():
        files += sorted(test_dir.rglob("*.py"))
    return files


def _check_canonical_imports(path: Path, result: AuditResult) -> None:
    """Parse the AST and verify each imported symbol comes from its canonical module."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        result.add("ERROR", _relative(path), e.lineno or 0, f"SyntaxError: {e}")
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                name = alias.name
                if name not in CANONICAL_IMPORTS:
                    continue
                expected_mod = CANONICAL_IMPORTS[name]
                actual_mod = node.module
                # Allow partial matches for relative imports inside the same package.
                if actual_mod != expected_mod and not actual_mod.endswith(expected_mod.split(".")[-1]):
                    result.add(
                        "ERROR", _relative(path), node.lineno,
                        f"'{name}' imported from '{actual_mod}' — should be '{expected_mod}'",
                    )


def _check_hardcoded_constants(path: Path, result: AuditResult) -> None:
    """Flag lines that assign scoring/model constants inline instead of reading from config."""
    # config.py defines the constants; audit.py mentions them in pattern strings.
    if path.name in {"config.py", "audit.py"}:
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for pattern, message in HARDCODED_PATTERNS:
            if re.search(pattern, stripped):
                result.add("WARNING", _relative(path), lineno, message)


def _check_fingerprint_coverage(path: Path, result: AuditResult) -> None:
    """Pipeline scripts that have a main() should generate a fingerprint."""
    if path.name not in PIPELINE_SCRIPTS_WITH_FINGERPRINT:
        return
    text = path.read_text(encoding="utf-8")
    if "def main(" not in text:
        return
    if "fingerprint" not in text:
        result.add(
            "WARNING", _relative(path), 0,
            "Pipeline script with main() has no fingerprint output — reproducibility gap",
        )


def _check_random_seeding(path: Path, result: AuditResult) -> None:
    """Warn on calls to random.random() / random.choice() that bypass a seeded RNG."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Detect module-level random calls (not via a seeded random.Random instance).
        if re.search(r"\brandom\.(random|choice|shuffle|randint|uniform)\s*\(", stripped):
            # Allow calls that come from a local RNG variable (e.g. `rng.random()`).
            if not re.search(r"\b\w+\.(random|choice|shuffle|randint|uniform)\s*\(", stripped):
                result.add(
                    "WARNING", _relative(path), lineno,
                    "Unseeded random call — use random.Random(seed) for reproducibility",
                )


def _check_ev_redefinition(path: Path, result: AuditResult) -> None:
    """Flag any file that defines a function named optimize_pick or score_actual
    outside the canonical quiniela module."""
    canonical = SRC_ROOT / "scoring" / "quiniela.py"
    if path == canonical:
        return
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in {"optimize_pick", "score_actual", "build_score_matrix"}:
                result.add(
                    "ERROR", _relative(path), node.lineno,
                    f"Function '{node.name}' redefined outside quiniela.py — "
                    "violates single-source-of-truth for EV logic",
                )


def run_audit() -> AuditResult:
    result = AuditResult()
    files = _collect_py_files()
    result.n_files = len(files)

    for path in files:
        _check_canonical_imports(path, result)
        _check_hardcoded_constants(path, result)
        _check_fingerprint_coverage(path, result)
        _check_random_seeding(path, result)
        _check_ev_redefinition(path, result)

    return result


def _format_report(result: AuditResult) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    lines = [
        "=" * 70,
        f"AUDITORÍA WC2026 — {ts}",
        f"Archivos auditados: {result.n_files}",
        f"Errores: {result.n_errors}   Advertencias: {result.n_warnings}",
        "=" * 70,
    ]

    if not result.findings:
        lines.append("✓ Sin hallazgos — codebase cumple todas las invariantes.")
    else:
        by_severity = {"ERROR": [], "WARNING": [], "INFO": []}
        for f in result.findings:
            by_severity[f.severity].append(f)

        for sev in ("ERROR", "WARNING", "INFO"):
            bucket = by_severity[sev]
            if not bucket:
                continue
            lines.append(f"\n{'─'*40}")
            lines.append(f"{sev}S ({len(bucket)})")
            lines.append("─" * 40)
            for f in bucket:
                loc = f"{f.file}:{f.line}" if f.line else f.file
                lines.append(f"  [{sev}] {loc}")
                lines.append(f"         {f.message}")

    lines.append("\n" + "=" * 70)
    status = "PASÓ" if result.passed else "FALLÓ"
    lines.append(f"RESULTADO: {status}")
    lines.append("=" * 70)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Audit WC2026 codebase for consistency.")
    parser.add_argument("--save", action="store_true",
                        help="Save report to outputs/audit_report.txt")
    args = parser.parse_args()

    result = run_audit()
    report = _format_report(result)
    print(report)

    if args.save:
        from wc_predictor.config import OUTPUTS_DIR
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        dst = OUTPUTS_DIR / "audit_report.txt"
        dst.write_text(report, encoding="utf-8")
        print(f"\nReporte guardado en {dst}")

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
