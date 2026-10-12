"""Inspect a raw EEG or Unity CSV without modifying it."""

from __future__ import annotations

import argparse
import math
from collections import Counter

from common import as_float, find_prefix_columns, read_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    args = parser.parse_args()

    columns, rows = read_rows(args.input)
    print(f"rows: {len(rows)}")
    print(f"columns ({len(columns)}): {', '.join(columns)}")
    print(f"EEG-like columns: {', '.join(find_prefix_columns(columns, ('ch', 'eeg_'))) or 'none'}")
    for column in columns:
        values = [as_float(row.get(column)) for row in rows]
        finite = [value for value in values if math.isfinite(value)]
        if not finite:
            continue
        print(f"{column}: finite={len(finite)}/{len(values)} min={min(finite):.5g} max={max(finite):.5g} mean={sum(finite) / len(finite):.5g}")
    for column in ("subject", "session", "label", "marker", "condition"):
        if column in columns:
            print(f"{column} values: {Counter(row.get(column, '') for row in rows).most_common(10)}")


if __name__ == "__main__":
    main()
