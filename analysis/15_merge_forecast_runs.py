"""Merge independent seed/model processes only after a complete result grid."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from forecasting.config import Protocol
from forecasting.evaluation import subject_metrics
from forecasting.dataset import sha256

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--parts", nargs="+", required=True, help="seed=run_directory pairs")
    parser.add_argument("--output", required=True)
    parser.add_argument("--features", required=True)
    args = parser.parse_args()
    check_columns = ["subject", "session", "timestamp_s", "future_peak", "event", "event_time_s", "quality"]
    reference = pd.read_csv(args.features, usecols=check_columns, dtype={"subject": str, "session": str})
    required_subjects = set(reference.subject)
    outputs, sources, split_records = [], [], []
    identity = None
    model_sets, seeds = [], []
    for spec in args.parts:
        seed_text, directory_text = spec.split("=", 1)
        seed, directory = int(seed_text), Path(directory_text)
        metadata = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        current = metadata["identity"]
        if current["input_sha256"] != sha256(Path(args.features)):
            raise SystemExit("Canonical feature table does not match source run")
        common = {k: current[k] for k in ("input_sha256", "protocol", "data_kind")}
        if identity is None:
            identity = common
        elif identity != common:
            raise SystemExit("Mismatched input/protocol/data kind across source runs")
        if seed not in current["seeds"]:
            raise SystemExit("Requested seed not configured in source run")
        files = sorted(directory.glob(f"pred_{seed}_*.csv"))
        if not files:
            raise SystemExit("No per-fold prediction files")
        frame = pd.concat([pd.read_csv(p, dtype={"subject": str, "session": str}) for p in files], ignore_index=True)
        if set(frame.model) != set(current["models"]) or set(frame.seed) != {seed}:
            raise SystemExit("Unexpected model or seed in source predictions")
        for model in current["models"]:
            subjects = set(frame[frame.model == model].subject)
            if subjects != required_subjects:
                raise SystemExit(f"Incomplete subjects for {model}, seed {seed}")
        for (_, subject), part in frame.groupby(["model", "subject"]):
            part = part.sort_values(["session", "timestamp_s"])
            target = reference[reference.subject == subject].sort_values(["session", "timestamp_s"])
            if len(part) != len(target) or part.session.tolist() != target.session.tolist():
                raise SystemExit("Source fold has missing or duplicated windows")
            for column in check_columns[2:]:
                if not np.allclose(part[column], target[column], equal_nan=True):
                    raise SystemExit(f"Source fold differs from canonical data: {column}")
        model_sets.append(set(current["models"]))
        seeds.append(seed)
        outputs.append(frame)
        sources.append({"seed": seed, "directory": directory_text, "metadata": metadata})
        split_records += [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob(f"split_{seed}_*.json"))]
    predictions = pd.concat(outputs, ignore_index=True)
    if predictions.duplicated(["model", "seed", "subject", "session", "timestamp_s"]).any():
        raise SystemExit("Overlapping source predictions")
    all_models = sorted(set.union(*model_sets))
    all_seeds = sorted(set(seeds))
    grid = predictions.groupby(["model", "seed"]).subject.nunique()
    expected_subjects = len(required_subjects)
    if len(grid) != len(all_models) * len(all_seeds) or (grid != expected_subjects).any():
        raise SystemExit("Merged model/seed/participant grid is incomplete")
    identity.update({"models": all_models, "seeds": all_seeds, "subjects": sorted(required_subjects)})
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "run.json").write_text(json.dumps({"identity": identity, "source_runs": sources,
                                                   "merge_source_sha256": sha256(Path(__file__))}, indent=2), encoding="utf-8")
    predictions.to_csv(output / "predictions.csv", index=False)
    cfg_values = dict(identity["protocol"])
    cfg_values["seeds"] = tuple(cfg_values["seeds"])
    subject_metrics(predictions, Protocol(**cfg_values)).to_csv(output / "subject_metrics.csv", index=False)
    (output / "split_manifest.json").write_text(json.dumps(split_records, indent=2), encoding="utf-8")
    print(f"Merged {len(predictions)} predictions, {len(all_models)} models, {len(all_seeds)} seeds, {expected_subjects} subjects")
