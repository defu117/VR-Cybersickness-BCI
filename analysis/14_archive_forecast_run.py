"""Copy completed public-data aggregates into the reviewable paper workspace."""
import argparse
import itertools
import json
from pathlib import Path
import shutil
import pandas as pd

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_directory")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root, output = Path(args.run_directory), Path(args.output)
    meta = json.loads((root / "run.json").read_text(encoding="utf-8"))
    identity = meta["identity"]
    if identity["data_kind"] != "public":
        raise SystemExit("Synthetic runs cannot be archived as paper results")
    predictions = pd.read_csv(root / "predictions.csv", dtype={"subject": str, "session": str})
    if "subjects" not in identity:
        raise SystemExit("Archive the validated merged run, whose manifest contains canonical subjects")
    expected = set(itertools.product(identity["models"], identity["seeds"], identity["subjects"]))
    found = set(predictions.groupby(["model", "seed", "subject"]).groups)
    if found != expected:
        raise SystemExit("Incomplete model/seed/subject grid")
    output.mkdir(parents=True, exist_ok=True)
    for name in ("run.json", "subject_metrics.csv", "summary.csv", "window_weighted_metrics.csv", "report.md", "paired_mae_bootstrap.json", "split_manifest.json"):
        shutil.copy2(root / name, output / name)
    shutil.copytree(root / "figures", output / "figures", dirs_exist_ok=True)
    print(f"Archived complete public experiment: {len(expected)} model/seed/participant combinations to {output}")
