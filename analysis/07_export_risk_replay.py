"""Export model predictions as the Unity CybersicknessRiskReplay format."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from common import as_float, read_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="predictions.csv or a table containing timestamp_s and risk")
    parser.add_argument("--output", default="data/risk_replay.csv")
    parser.add_argument("--source", default="replay")
    parser.add_argument("--model", default="", help="Only export rows from this model, if present")
    args = parser.parse_args()

    columns, rows = read_rows(args.input)
    if args.model and "model" in columns:
        rows = [row for row in rows if row.get("model") == args.model]
    if not rows:
        raise SystemExit("no rows available for replay")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp_s", "risk", "quality", "source"])
        for index, row in enumerate(rows):
            timestamp = as_float(row.get("timestamp_s"), float(index))
            risk = as_float(row.get("probability", row.get("risk", row.get("y_pred", 0.0))), 0.0)
            quality = as_float(row.get("quality", row.get("eeg_quality", 1.0)), 1.0)
            writer.writerow([f"{max(0.0, timestamp):.9f}", f"{min(1.0, max(0.0, risk)):.8f}", f"{min(1.0, max(0.0, quality)):.8f}", args.source])
    print(f"wrote {len(rows)} replay samples to {output}")


if __name__ == "__main__":
    main()
