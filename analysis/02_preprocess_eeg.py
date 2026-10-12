"""Check, filter and serialize raw EEG into a reproducible NPZ file."""

from __future__ import annotations

import argparse
import csv
import json
import warnings
from pathlib import Path

import numpy as np

from common import as_float, find_prefix_columns, find_column, read_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--output", default="data/preprocessed_eeg.npz")
    parser.add_argument("--sfreq", type=float, default=0.0, help="Override sampling rate; otherwise infer it from timestamp_s.")
    parser.add_argument("--low", type=float, default=1.0)
    parser.add_argument("--high", type=float, default=40.0)
    parser.add_argument("--notch", type=float, default=50.0)
    args = parser.parse_args()

    columns, rows = read_rows(args.input)
    time_column = find_column(columns, "timestamp_s", "timestamp", "time_s", "unity_time_s")
    channels = find_prefix_columns(columns, ("ch", "eeg_"))
    if time_column is None or not channels:
        raise SystemExit("input must contain timestamp_s/timestamp and channel columns beginning with ch or eeg_")

    timestamps = np.asarray([as_float(row.get(time_column)) for row in rows], dtype=float)
    raw_data = np.asarray([[as_float(row.get(channel)) for channel in channels] for row in rows], dtype=float)
    valid_time = np.isfinite(timestamps)
    timestamps = timestamps[valid_time]
    data = raw_data[valid_time]
    if len(timestamps) < 4:
        raise SystemExit("not enough timestamped EEG samples")

    sfreq = args.sfreq
    if sfreq <= 0:
        dt = np.nanmedian(np.diff(timestamps))
        sfreq = 1.0 / dt if np.isfinite(dt) and dt > 0 else 0.0
    if sfreq <= 0:
        raise SystemExit("could not infer sampling rate; pass --sfreq")

    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    data = data - np.mean(data, axis=0, keepdims=True)
    try:
        from scipy import signal

        nyquist = sfreq / 2.0
        high = min(args.high, nyquist * 0.95)
        if high > args.low:
            b, a = signal.butter(4, [args.low / nyquist, high / nyquist], btype="band")
            data = signal.filtfilt(b, a, data, axis=0)
        if args.notch < nyquist:
            b, a = signal.iirnotch(args.notch / nyquist, 30.0)
            data = signal.filtfilt(b, a, data, axis=0)
    except ImportError:
        warnings.warn("scipy is unavailable; only de-meaning was applied")

    quality = np.mean(np.isfinite(raw_data), axis=1)[valid_time]
    labels = np.asarray([as_float(row.get("label")) for row in rows], dtype=float)[valid_time] if "label" in columns else np.full(len(data), np.nan)
    subject = next((row.get("subject", "unknown") for row in rows if row.get("subject")), "unknown")
    session = next((row.get("session", "unknown") for row in rows if row.get("session")), "unknown")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        data=data,
        timestamps=timestamps,
        channels=np.asarray(channels),
        sfreq=np.asarray(sfreq),
        sample_quality=quality[: len(data)],
        labels=labels[: len(data)],
        subject=np.asarray(subject),
        session=np.asarray(session),
        metadata=json.dumps({"low_hz": args.low, "high_hz": args.high, "notch_hz": args.notch}),
    )
    print(f"wrote {len(data)} samples, {len(channels)} channels, sfreq={sfreq:.4g} Hz to {output}")


if __name__ == "__main__":
    main()
