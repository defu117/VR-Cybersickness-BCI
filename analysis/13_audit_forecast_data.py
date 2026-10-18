"""Publish aggregate data-audit evidence without redistributing raw recordings."""
import argparse
import json
from pathlib import Path
import pandas as pd

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("features")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    features = Path(args.features)
    audit = json.loads(features.with_suffix(".audit.json").read_text(encoding="utf-8"))
    frame = pd.read_csv(features, dtype={"subject": str, "session": str})
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    records = pd.DataFrame(audit["recordings"])
    safe = [c for c in records if c != "files"]
    records[safe].to_csv(output / "recording_audit.csv", index=False)
    subjects = frame.groupby("subject").agg(windows=("event", "size"), positive_windows=("event", "sum"),
                                             sessions=("session", "nunique"), max_rating=("future_peak", "max")).reset_index()
    subjects.to_csv(output / "subject_data_counts.csv", index=False)
    exclusions = records.loc[records.status == "excluded", ["recording", "reason"]]
    exclusions.to_csv(output / "exclusions.csv", index=False)
    summary = {"data_kind": audit["data_kind"], "protocol_hash": audit["protocol_hash"],
               "recordings_seen": len(records), "records_excluded": len(exclusions),
               "recordings_with_forecasts": int((records.get("forecast_windows", 0).fillna(0) > 0).sum()),
               "subjects": len(subjects), "forecast_windows": len(frame),
               "positive_windows": int(frame.event.sum()), "positive_fraction": float(frame.event.mean()),
               "subjects_with_positive_windows": int((subjects.positive_windows > 0).sum()),
               "minimum_windows_in_subject": int(subjects.windows.min()), "protocol": audit["protocol"]}
    (output / "data_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    text = ["# Public-data audit", "", f"Protocol: `{audit['protocol_hash']}`. Data kind: `{audit['data_kind']}`.", "",
            f"Inspected {len(records)} recordings; {len(exclusions)} excluded. Retained {len(frame)} forecasting windows from {len(subjects)} participants.",
            f"Positive target windows: {int(frame.event.sum())}/{len(frame)} ({frame.event.mean():.2%}). These are not independent symptom episodes.", "",
            "| Subject | Windows | Positive windows | Sessions |",
            "|---|---:|---:|---:|"]
    text += [f"| {r.subject} | {r.windows} | {r.positive_windows} | {r.sessions} |" for r in subjects.itertuples()]
    text += ["", "Very short participant traces remain visible. A macro average gives each participant equal weight even when the available number of windows differs greatly.",
             "Check recording_audit.csv for exclusions, clock behavior, discarded startup buffer counts, and rating ranges. Raw recordings and per-sample EEG are not included here."]
    (output / "data_audit.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
