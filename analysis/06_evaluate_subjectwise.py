"""Aggregate prediction metrics per subject/session group."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from common import as_float, read_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="predictions.csv from 05_train_baselines.py")
    parser.add_argument("--output", default="data/subjectwise_results.csv")
    args = parser.parse_args()

    try:
        import numpy as np
        from sklearn.metrics import balanced_accuracy_score, f1_score, mean_absolute_error, mean_squared_error
    except ImportError as error:
        raise SystemExit("install analysis/requirements.txt before evaluation") from error

    _, rows = read_rows(args.input)
    grouped = {}
    for row in rows:
        key = (row.get("source", ""), row.get("model", ""), row.get("group", ""))
        grouped.setdefault(key, []).append(row)

    output_rows = []
    for (source, model, group), group_rows in sorted(grouped.items()):
        actual = np.asarray([as_float(row.get("y_true")) for row in group_rows], dtype=float)
        predicted = np.asarray([as_float(row.get("y_pred")) for row in group_rows], dtype=float)
        valid = np.isfinite(actual) & np.isfinite(predicted)
        actual, predicted = actual[valid], predicted[valid]
        if len(actual) == 0:
            continue
        is_binary = set(np.unique(actual)).issubset({0.0, 1.0})
        result = {"source": source, "model": model, "group": group, "windows": len(actual)}
        if is_binary:
            result["balanced_accuracy"] = balanced_accuracy_score(actual, predicted >= 0.5)
            result["f1"] = f1_score(actual, predicted >= 0.5, zero_division=0)
        result["mae"] = mean_absolute_error(actual, predicted)
        result["rmse"] = mean_squared_error(actual, predicted) ** 0.5
        output_rows.append(result)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["source", "model", "group", "windows", "balanced_accuracy", "f1", "mae", "rmse"]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output_rows)
    print(f"wrote {len(output_rows)} subjectwise rows to {output}")


if __name__ == "__main__":
    main()
