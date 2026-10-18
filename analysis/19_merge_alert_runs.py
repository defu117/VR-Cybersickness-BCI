"""Validate separate-seed exploratory runs and archive aggregates only."""
import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from forecasting.config import Protocol
from forecasting.dataset import sha256
from forecasting.evaluation import _event_metrics, split_subjects, validate_dataset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", required=True)
    parser.add_argument("--parts", nargs="+", required=True, help="seed=directory")
    parser.add_argument("--output", required=True)
    parser.add_argument("--archive")
    args = parser.parse_args()
    frame = pd.read_csv(args.features, dtype={"subject": str, "session": str})
    subjects = sorted(frame.subject.unique())
    parts, manifests, identities = [], [], []
    expected_models = None
    seeds = []
    shared_identity = None
    for argument in args.parts:
        seed_text, directory = argument.split("=", 1)
        seed, root = int(seed_text), Path(directory)
        if seed in seeds:
            raise ValueError("Duplicate seed")
        seeds.append(seed)
        identity = json.loads((root / "run.json").read_text(encoding="utf-8"))
        if seed not in identity["seeds"] or identity["input_sha256"] != sha256(Path(args.features)):
            raise ValueError("Input or seed mismatch")
        shared = {key: value for key, value in identity.items() if key != "seeds"}
        if shared_identity is not None and shared != shared_identity:
            raise ValueError("Source/config mismatch across parts")
        shared_identity = shared
        cfg = Protocol(**identity["protocol"])
        validate_dataset(frame, cfg)
        if identity["data_kind"] != "public":
            raise ValueError("This archival analysis requires public data")
        settings = identity["settings"]
        models = {"event_fixed_0p5"} | {"event_budget_" + str(b).replace(".", "p") for b in settings["false_alarm_budgets_per_min"]}
        expected_models = models
        for subject in subjects:
            fold = pd.read_csv(root / f"alert_{seed}_{subject}.csv", dtype={"subject": str, "session": str})
            manifest = json.loads((root / f"split_{seed}_{subject}.json").read_text(encoding="utf-8"))
            fit, cal = split_subjects(subjects, subject, seed, cfg.calibration_fraction)
            if (manifest["test_subject"] != subject or manifest["seed"] != seed
                    or manifest["fit_subjects"] != fit or manifest["calibration_subjects"] != cal):
                raise ValueError("Unexpected subject split")
            reference = frame[frame.subject == subject].sort_values(["session", "timestamp_s"])
            if set(fold.model) != models or set(fold.seed) != {seed} or set(fold.subject) != {subject}:
                raise ValueError("Incomplete or unexpected fold identity")
            for _, trajectory in fold.groupby("model"):
                trajectory = trajectory.sort_values(["session", "timestamp_s"])
                if len(trajectory) != len(reference) or trajectory.session.tolist() != reference.session.tolist():
                    raise ValueError("Missing or duplicated test windows")
                for column in ("timestamp_s", "event", "event_time_s", "quality"):
                    if not np.allclose(trajectory[column], reference[column], equal_nan=True):
                        raise ValueError("Test windows or labels differ from canonical table")
            parts.append(fold)
            manifests.append(manifest)
        identities.append({"seed": seed, "source_directory": str(root), "run_sha256": sha256(root / "run.json")})
    predictions = pd.concat(parts, ignore_index=True)
    expected = set(itertools.product(expected_models, seeds, subjects))
    if set(predictions.groupby(["model", "seed", "subject"]).groups) != expected:
        raise ValueError("Incomplete exploratory grid")
    records = []
    for (model, seed, subject), part in predictions.groupby(["model", "seed", "subject"]):
        records.append({"model": model, "seed": seed, "subject": subject,
                        "average_precision": average_precision_score(part.event, part.score) if part.event.nunique() > 1 else np.nan,
                        **_event_metrics(part, "alarm", cfg)})
    metrics = pd.DataFrame(records)
    columns = ["average_precision", "event_recall", "false_alarms_per_min", "median_lead_s", "alarms"]
    summary = metrics.groupby(["model", "subject"])[columns].mean().groupby("model").mean()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(output / "predictions.csv", index=False)
    identity = {**shared_identity, "seeds": seeds, "subjects": subjects, "models": sorted(expected_models)}
    (output / "run.json").write_text(json.dumps({"identity": identity, "parts": identities,
                                                   "merge_source_sha256": sha256(Path(__file__))}, indent=2), encoding="utf-8")
    (output / "split_manifest.json").write_text(json.dumps(manifests, indent=2), encoding="utf-8")
    metrics.to_csv(output / "subject_metrics.csv", index=False)
    summary.to_csv(output / "summary.csv")
    diagnostics = []
    for budget in identity["settings"]["false_alarm_budgets_per_min"]:
        name = "event_budget_" + str(budget).replace(".", "p")
        cal_rates = [record["chosen_policies"][name]["false_alarms_per_min"] for record in manifests]
        if max(cal_rates) > budget + 1e-9:
            raise ValueError("Calibration threshold violates its empirical constraint")
        heldout = metrics[metrics.model == name]
        diagnostics.append({"policy": name, "calibration_budget": budget,
                            "calibration_max_macro_fa": max(cal_rates), "heldout_folds": len(heldout),
                            "heldout_folds_above_budget": int((heldout.false_alarms_per_min > budget + 1e-9).sum()),
                            "heldout_fold_max_fa": heldout.false_alarms_per_min.max()})
    pd.DataFrame(diagnostics).to_csv(output / "budget_transfer_diagnostic.csv", index=False)
    lines = ["# Exploratory direct-event classification", "",
             "Specified after observing the negative v1 result. These results require independent validation.",
             "Scores are class-weighted rankings, not calibrated probabilities. Budgets constrain calibration subjects empirically; they are not guarantees on unseen users.",
             "Single-window confirmation and a 12-second cooldown are used. Seeds are averaged within participants before participant macro averaging.", "",
             "| Policy | Event AP | Episode recall | False warnings/min | Mean of participant median lead (s) |",
             "|---|---:|---:|---:|---:|"]
    for row in summary.itertuples():
        fmt = lambda x: f"{x:.4f}" if np.isfinite(x) else "NA"
        lines.append(f"| {row.Index} | {fmt(row.average_precision)} | {fmt(row.event_recall)} | {fmt(row.false_alarms_per_min)} | {fmt(row.median_lead_s)} |")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.archive:
        import shutil
        archive = Path(args.archive)
        archive.mkdir(parents=True, exist_ok=True)
        for name in ("run.json", "split_manifest.json", "subject_metrics.csv", "summary.csv", "report.md", "budget_transfer_diagnostic.csv"):
            shutil.copy2(output / name, archive / name)
    print(f"Validated {len(expected)} policy/seed/participant combinations")
    print(summary.to_string())


if __name__ == "__main__":
    main()
