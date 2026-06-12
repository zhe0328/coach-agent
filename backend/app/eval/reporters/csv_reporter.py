"""CSV report writers for eval harness runs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.eval.paths import resolve_output_dir


def write_agent_report_csv(
    records: list[dict],
    *,
    output_dir: str | Path | None = None,
    filename: str = "coach_agent_report_new.csv",
) -> Path:
    out_dir = resolve_output_dir(output_dir)
    output_path = out_dir / filename
    pd.DataFrame(records).to_csv(output_path, index=False, encoding="utf-8-sig")
    return output_path
