"""Label-informed policy ceiling diagnostic. Never a deployable predictor."""
import argparse
from dataclasses import replace
from pathlib import Path
import pandas as pd
from forecasting.config import Protocol
from forecasting.evaluation import apply_warning_policy, subject_metrics

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("features")
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="configs/forecast_v1.json")
    parser.add_argument("--horizon", type=float)
    args = parser.parse_args()
    cfg = Protocol.load(args.config)
    if args.horizon is not None:
        cfg = replace(cfg, horizon_s=args.horizon)
    base = pd.read_csv(args.features, dtype={"subject": str, "session": str})
    base = base[["subject", "session", "timestamp_s", "future_peak", "delta_target", "event", "event_time_s", "quality"]]
    diagnostics = []
    for confirmations in (1, 2):
        selected = base.copy()
        selected["future_pred"] = selected.future_peak
        selected["delta_pred"] = selected.delta_target
        selected["delta_lower"], selected["delta_upper"] = selected.delta_target, selected.delta_target
        selected["model"], selected["seed"] = "ORACLE_FUTURE_LABELS_POLICY_DIAGNOSTIC", 0
        policy = replace(cfg, consecutive_windows=confirmations)
        selected["alarm_raw"] = apply_warning_policy(selected, policy, gated=False)
        selected["alarm_gated"] = apply_warning_policy(selected, policy, gated=True)
        metrics = subject_metrics(selected, policy)
        metrics = metrics[metrics.policy == "gated"].copy()
        metrics["confirmation_windows"] = confirmations
        diagnostics.append(metrics)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    result = pd.concat(diagnostics, ignore_index=True)
    result.to_csv(output / "oracle_policy_diagnostic.csv", index=False)
    summary = result.groupby("confirmation_windows")[["event_recall", "false_alarms_per_min", "median_lead_s"]].mean()
    summary.to_csv(output / "oracle_policy_summary.csv")
    print("Uses future labels by design; diagnoses policy limits, not predictive performance.")
    print(summary.to_string())
