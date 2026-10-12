"""Create windowed EEG PSD features from the preprocessed NPZ file."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np


def band_power(frequencies: np.ndarray, power: np.ndarray, low: float, high: float) -> float:
    mask = (frequencies >= low) & (frequencies < high)
    integrate = getattr(np, "trapezoid", np.trapz)
    return float(integrate(power[mask], frequencies[mask])) if np.any(mask) else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--output", default="data/eeg_features.csv")
    parser.add_argument("--window", type=float, default=3.0)
    parser.add_argument("--step", type=float, default=1.0)
    args = parser.parse_args()

    bundle = np.load(args.input, allow_pickle=False)
    data = np.asarray(bundle["data"], dtype=float)
    timestamps = np.asarray(bundle["timestamps"], dtype=float)
    channels = [str(channel) for channel in bundle["channels"]]
    sfreq = float(bundle["sfreq"])
    labels = np.asarray(bundle["labels"], dtype=float) if "labels" in bundle else np.full(len(data), np.nan)
    quality = np.asarray(bundle["sample_quality"], dtype=float) if "sample_quality" in bundle else np.ones(len(data))
    subject = str(bundle["subject"]) if "subject" in bundle else "unknown"
    session = str(bundle["session"]) if "session" in bundle else "unknown"

    window_samples = max(4, int(round(args.window * sfreq)))
    step_samples = max(1, int(round(args.step * sfreq)))
    if len(data) < window_samples:
        raise SystemExit("input is shorter than the requested feature window")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["timestamp_s", "subject", "session", "label", "eeg_quality"]
    for channel in channels:
        for band in ("theta", "alpha", "beta"):
            fieldnames.append(f"eeg_{channel}_{band}_rel")
    rows = []
    for start in range(0, len(data) - window_samples + 1, step_samples):
        stop = start + window_samples
        segment = data[start:stop]
        frequency = np.fft.rfftfreq(window_samples, d=1.0 / sfreq)
        spectrum = np.abs(np.fft.rfft(segment - np.mean(segment, axis=0), axis=0)) ** 2
        total = np.sum(spectrum[(frequency >= 1.0) & (frequency < 40.0)], axis=0) + 1e-12
        row = {
            "timestamp_s": f"{timestamps[start]:.9f}",
            "subject": subject,
            "session": session,
            "label": "" if not np.isfinite(labels[start:stop]).any() else str(int(np.nanmean(labels[start:stop]) >= 0.5)),
            "eeg_quality": f"{float(np.nanmean(quality[start:stop])):.6f}",
        }
        for channel_index, channel in enumerate(channels):
            for band, low, high in (("theta", 4.0, 8.0), ("alpha", 8.0, 13.0), ("beta", 13.0, 30.0)):
                row[f"eeg_{channel}_{band}_rel"] = f"{band_power(frequency, spectrum[:, channel_index], low, high) / total[channel_index]:.8g}"
        rows.append(row)

    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} EEG feature windows to {output}")


if __name__ == "__main__":
    main()
