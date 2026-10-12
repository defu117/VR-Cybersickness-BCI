"""Small dependency-light helpers shared by the EEG analysis scripts."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Iterable, Sequence


def read_rows(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        return fieldnames, list(reader)


def write_rows(path: str | Path, fieldnames: Sequence[str], rows: Iterable[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def as_float(value: object, default: float = math.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def find_column(columns: Sequence[str], *candidates: str) -> str | None:
    lowered = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def find_prefix_columns(columns: Sequence[str], prefixes: Sequence[str]) -> list[str]:
    return [column for column in columns if any(column.lower().startswith(p.lower()) for p in prefixes)]


def finite_fraction(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(math.isfinite(value) for value in values) / len(values)
