"""Generate a small EEG-like CSV for testing the complete offline pipeline."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/synthetic_eeg.csv")
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--sfreq", type=float, default=128.0)
    parser.add_argument("--channels", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    count = int(args.duration * args.sfreq)
    time = np.arange(count, dtype=float) / args.sfreq
    # Smooth blocks provide a deterministic but non-clinical target for smoke tests.
    risk = np.clip(0.15 + 0.65 * (np.sin(time / 11.0) + 1.0) / 2.0, 0.0, 1.0)
    labels = (risk >= 0.5).astype(int)
    data = []
    for channel in range(args.channels):
        theta = np.sin(2 * np.pi * (5.5 + channel * 0.05) * time)
        alpha = 0.8 * np.sin(2 * np.pi * 10.0 * time + channel * 0.2)
        beta = 0.3 * np.sin(2 * np.pi * 20.0 * time)
        artifact = 0.25 * risk * np.sin(2 * np.pi * 1.2 * time + channel)
        data.append(theta * (0.6 + risk) + alpha + beta + artifact + 0.15 * rng.standard_normal(count))
    matrix = np.asarray(data).T

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp_s", "subject", "session", "label", *[f"ch{i + 1:02d}" for i in range(args.channels)]])
        for index, timestamp in enumerate(time):
            writer.writerow([
                f"{timestamp:.6f}",
                "synthetic_subject",
                "synthetic_session",
                int(labels[index]),
                *[f"{matrix[index, channel]:.8f}" for channel in range(args.channels)],
            ])
    print(f"wrote {count} samples, {args.channels} channels to {output}")


if __name__ == "__main__":
    main()
