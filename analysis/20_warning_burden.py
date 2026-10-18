"""Hypothetical warning-hold occupancy, restricted to monitored windows.

This is an operational replay calculation, not observed locomotion time or
an estimate of a physiological intervention effect.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from forecasting.dataset import sha256


def active_seconds(times, alarms, window_s, hold_s):
    times = np.asarray(times, dtype=float)
    alarm_times = times[np.asarray(alarms, dtype=bool)]
    if not len(alarm_times):
        return 0.0
    if len(times) > 1 and np.any(np.diff(times) < window_s - 1e-8):
        raise ValueError("Occupancy assumes non-overlapping decision windows")
    last = np.searchsorted(alarm_times, times, side="right") - 1
    usable = last >= 0
    remaining = alarm_times[last[usable]] + hold_s - times[usable]
    return float(np.clip(remaining, 0, window_s).sum())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_directory")
    parser.add_argument("--output", required=True)
    parser.add_argument("--hold-seconds", type=float, default=10)
    args = parser.parse_args()
    if args.hold_seconds <= 0:
        raise ValueError("Hold time must be positive")
    root, output = Path(args.run_directory), Path(args.output)
    metadata = json.loads((root / "run.json").read_text(encoding="utf-8"))
    identity = metadata["identity"]
    frame = pd.read_csv(root / "predictions.csv", dtype={"subject": str, "session": str})
    policies = {c.removeprefix("alarm_"): c for c in ("alarm_raw", "alarm_gated", "alarm") if c in frame}
    records = []
    window = identity["protocol"]["window_s"]
    for (model, seed, subject), part in frame.groupby(["model", "seed", "subject"]):
        for policy, column in policies.items():
            duration = sum(active_seconds(group.timestamp_s, group[column], window, args.hold_seconds)
                           for _, group in ((key, group.sort_values("timestamp_s")) for key, group in part.groupby("session")))
            records.append({"model": model, "seed": seed, "subject": subject, "policy": policy,
                            "active_seconds": duration, "monitored_seconds": len(part)*window,
                            "active_fraction": duration/(len(part)*window)})
    result = pd.DataFrame(records)
    summary = result.groupby(["model", "policy", "subject"]).active_fraction.mean().groupby(["model", "policy"]).mean().reset_index()
    output.mkdir(parents=True, exist_ok=True)
    result.to_csv(output / "warning_burden_by_subject.csv", index=False)
    summary.to_csv(output / "warning_burden_summary.csv", index=False)
    lines = ["# Hypothetical warning occupancy", "",
             f"Hold: {args.hold_seconds:g}s; only {window:g}s monitored decision cells count in the denominator. Missing periods are not interpolated.",
             "This is a replay-state calculation before controller smoothing and actuation. It is not observed slowing, time lost, or symptom improvement.", "",
             "| Model | Policy | Warning active fraction |", "|---|---|---:|"]
    for row in summary.itertuples():
        lines.append(f"| {row.model} | {row.policy} | {row.active_fraction:.4f} |")
    (output / "warning_burden.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    (output / "warning_burden_provenance.json").write_text(json.dumps({"run_sha256": sha256(root / "run.json"),
        "predictions_sha256": sha256(root / "predictions.csv"), "source_sha256": sha256(Path(__file__)),
        "window_s": window, "hold_s": args.hold_seconds, "data_kind": identity["data_kind"]}, indent=2), encoding="utf-8")
    print(summary.to_string(index=False))
