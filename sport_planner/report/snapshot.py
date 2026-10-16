"""Persist the previous report so each morning can say what changed."""

from __future__ import annotations

import json
from pathlib import Path

from ..models import Report

LATEST = "latest_report.json"


def save(report: Report, state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    p = state_dir / LATEST
    p.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    # keep a dated copy for a week of history
    (state_dir / f"report_{report.generated_at:%Y%m%d}.json").write_text(report.model_dump_json(), encoding="utf-8")
    return p


def load_previous(state_dir: Path) -> Report | None:
    p = state_dir / LATEST
    if not p.exists():
        return None
    try:
        return Report.model_validate(json.loads(p.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 — a corrupt snapshot must not break today's report
        return None
