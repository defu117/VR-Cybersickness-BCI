"""Align HMD/Unity rows to EEG feature windows by nearest timestamp."""

from __future__ import annotations

import argparse
import bisect
import csv
from pathlib import Path

from common import as_float, find_column, read_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hmd", required=True)
    parser.add_argument("--eeg", required=True)
    parser.add_argument("--output", default="data/aligned_features.csv")
    parser.add_argument("--max-delta", type=float, default=0.5)
    args = parser.parse_args()

    hmd_columns, hmd_rows = read_rows(args.hmd)
    eeg_columns, eeg_rows = read_rows(args.eeg)
    hmd_time = find_column(hmd_columns, "unity_time_s", "timestamp_s", "timestamp")
    eeg_time = find_column(eeg_columns, "timestamp_s", "unity_time_s", "timestamp")
    if hmd_time is None or eeg_time is None:
        raise SystemExit("both inputs need timestamp_s, timestamp or unity_time_s")

    hmd_pairs = sorted((as_float(row.get(hmd_time)), row) for row in hmd_rows)
    hmd_times = [pair[0] for pair in hmd_pairs]
    hmd_feature_columns = [column for column in hmd_columns if column not in {"row_type", hmd_time}]
    output_rows = []
    for eeg_row in eeg_rows:
        timestamp = as_float(eeg_row.get(eeg_time))
        if not hmd_times or timestamp != timestamp:
            continue
        index = bisect.bisect_left(hmd_times, timestamp)
        candidates = [max(0, min(len(hmd_times) - 1, candidate)) for candidate in (index - 1, index)]
        best = min(candidates, key=lambda candidate: abs(hmd_times[candidate] - timestamp))
        if abs(hmd_times[best] - timestamp) > args.max_delta:
            continue
        merged = dict(eeg_row)
        for column in hmd_feature_columns:
            merged[f"hmd_{column}"] = hmd_pairs[best][1].get(column, "")
        merged["hmd_time_delta_s"] = f"{hmd_times[best] - timestamp:.9f}"
        output_rows.append(merged)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(eeg_columns) + [f"hmd_{column}" for column in hmd_feature_columns] + ["hmd_time_delta_s"]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output_rows)
    print(f"aligned {len(output_rows)} windows to {output}")


if __name__ == "__main__":
    main()
