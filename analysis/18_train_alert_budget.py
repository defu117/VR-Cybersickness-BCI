"""Exploratory direct-event classification with calibration-only alert budgets.

Defined after the v1 warning failure. Results are exploratory and require
independent validation before confirmatory efficacy or novelty claims.
"""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score
from threadpoolctl import threadpool_limits

from forecasting.config import Protocol
from forecasting.dataset import sha256
from forecasting.evaluation import feature_columns, split_subjects, validate_dataset, _event_metrics
from forecasting.alerts import score_alerts


def per_subject_metrics(frame, cfg):
    records = []
    for subject, part in frame.groupby("subject"):
        records.append({"subject": subject, **_event_metrics(part, "alarm", cfg)})
    return pd.DataFrame(records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("features")
    parser.add_argument("--output", required=True)
    parser.add_argument("--protocol", default="configs/forecast_v1.json")
    parser.add_argument("--alert-config", default="configs/alert_budget_exploratory_v2.json")
    parser.add_argument("--seeds", nargs="+", type=int, default=[7, 19, 42])
    args = parser.parse_args()
    cfg = Protocol.load(args.protocol)
    settings = json.loads(Path(args.alert_config).read_text(encoding="utf-8"))
    frame = pd.read_csv(args.features, dtype={"subject": str, "session": str})
    validate_dataset(frame, cfg)
    columns = feature_columns(frame, "fusion")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    identity = {"input_sha256": sha256(Path(args.features)), "protocol": cfg.to_dict(), "settings": settings,
                "seeds": args.seeds, "data_kind": frame.data_kind.iloc[0], "source_sha256": sha256(Path(__file__)),
                "alert_rule_sha256": sha256(Path(__file__).parent / "forecasting" / "alerts.py"),
                "metrics_sha256": sha256(Path(__file__).parent / "forecasting" / "evaluation.py")}
    meta_path = output / "run.json"
    if meta_path.exists() and json.loads(meta_path.read_text(encoding="utf-8")) != json.loads(json.dumps(identity)):
        raise ValueError("Different run identity")
    meta_path.write_text(json.dumps(identity, indent=2), encoding="utf-8")
    predictions = []
    for seed in args.seeds:
        for subject in sorted(frame.subject.unique()):
            started = time.perf_counter()
            prediction_path = output / f"alert_{seed}_{subject}.csv"
            split_path = output / f"split_{seed}_{subject}.json"
            if prediction_path.exists() and split_path.exists():
                predictions.append(pd.read_csv(prediction_path, dtype={"subject": str, "session": str}))
                continue
            fit_subjects, cal_subjects = split_subjects(frame.subject, subject, seed, cfg.calibration_fraction)
            fit = frame[frame.subject.isin(fit_subjects)]
            cal = frame[frame.subject.isin(cal_subjects)].reset_index(drop=True)
            test = frame[frame.subject == subject].reset_index(drop=True)
            if fit.event.nunique() < 2:
                cal_scores, test_scores = np.zeros(len(cal)), np.zeros(len(test))
            else:
                model = HistGradientBoostingClassifier(
                    max_iter=settings["max_iter"], max_leaf_nodes=settings["max_leaf_nodes"],
                    l2_regularization=settings["l2_regularization"], learning_rate=settings["learning_rate"],
                    class_weight="balanced", early_stopping=False, random_state=seed)
                model.fit(fit[columns].to_numpy(), fit.event.to_numpy())
                # Weighted classifier output is a ranking score, not a claim of calibrated probability.
                cal_scores = model.predict_proba(cal[columns].to_numpy())[:, 1]
                test_scores = model.predict_proba(test[columns].to_numpy())[:, 1]
            candidates = np.unique(np.r_[np.quantile(cal_scores, np.linspace(0, 1, settings["threshold_grid_quantiles"])), 1.01])
            names = ["subject", "session", "timestamp_s", "event", "event_time_s", "quality", "data_kind"]
            cal_meta, test_meta = cal[names], test[names]
            search = []
            for threshold in candidates:
                selected = cal_meta.copy()
                selected["alarm"] = score_alerts(cal_meta, cal_scores, threshold, settings["cooldown_s"], cfg.min_quality)
                metrics = per_subject_metrics(selected, cfg)
                recall = metrics.event_recall.mean()
                search.append({"threshold": float(threshold), "recall": float(recall) if np.isfinite(recall) else 0.0,
                               "false_alarms_per_min": float(metrics.false_alarms_per_min.mean())})
            policies = {"event_fixed_0p5": settings["fixed_score_threshold"]}
            chosen = {}
            for budget in settings["false_alarm_budgets_per_min"]:
                feasible = [r for r in search if r["false_alarms_per_min"] <= budget + 1e-9]
                if cal.event.sum() == 0:
                    best = next(r for r in search if r["threshold"] > 1)
                else:
                    best = min(feasible, key=lambda r: (-r["recall"], r["false_alarms_per_min"], -r["threshold"]))
                name = "event_budget_" + str(budget).replace(".", "p")
                policies[name] = best["threshold"]
                chosen[name] = best
            fold_parts = []
            for name, threshold in policies.items():
                selected = test[names].copy()
                selected["score"], selected["threshold"] = test_scores, threshold
                selected["model"], selected["seed"] = name, seed
                selected["alarm"] = score_alerts(test_meta, test_scores, threshold, settings["cooldown_s"], cfg.min_quality)
                fold_parts.append(selected)
            fold = pd.concat(fold_parts, ignore_index=True)
            fold.to_csv(prediction_path, index=False)
            split_path.write_text(json.dumps({"test_subject": subject, "seed": seed, "fit_subjects": fit_subjects,
                                              "calibration_subjects": cal_subjects, "chosen_policies": chosen,
                                              "calibration_positive_windows": int(cal.event.sum()), "threshold_search": search}, indent=2), encoding="utf-8")
            predictions.append(fold)
            print(f"exploratory event model seed={seed} subject={subject}, seconds={time.perf_counter()-started:.2f}", flush=True)
    result = pd.concat(predictions, ignore_index=True)
    result.to_csv(output / "predictions.csv", index=False)
    records = []
    for (model_name, seed, subject), part in result.groupby(["model", "seed", "subject"]):
        records.append({"model": model_name, "seed": seed, "subject": subject,
                        "average_precision": average_precision_score(part.event, part.score) if part.event.nunique() > 1 else np.nan,
                        **_event_metrics(part, "alarm", cfg)})
    metrics = pd.DataFrame(records)
    metrics.to_csv(output / "subject_metrics.csv", index=False)
    numeric = ["average_precision", "event_recall", "false_alarms_per_min", "median_lead_s", "alarms"]
    summary = metrics.groupby(["model", "subject"])[numeric].mean().groupby("model").mean()
    summary.to_csv(output / "summary.csv")
    text = ["# Exploratory event-warning result", "", "Defined after observing the v1 negative result; requires independent validation.",
            "Scores from the class-weighted classifier are not calibrated probabilities. False-alarm budgets constrain calibration subjects empirically, not unseen-user error rates.", "",
            "| Policy | Event AP | Event recall | False warnings/min | Mean of subject median lead (s) |",
            "|---|---:|---:|---:|---:|"]
    for r in summary.itertuples():
        fmt = lambda v: f"{v:.4f}" if np.isfinite(v) else "NA"
        text.append(f"| {r.Index} | {fmt(r.average_precision)} | {fmt(r.event_recall)} | {fmt(r.false_alarms_per_min)} | {fmt(r.median_lead_s)} |")
    (output / "report.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    print(summary.to_string())


if __name__ == "__main__":
    with threadpool_limits(limits=2):
        main()
