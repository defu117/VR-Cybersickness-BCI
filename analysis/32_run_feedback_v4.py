"""Fixed, grouped, equal-information sparse-feedback feasibility evaluation."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import average_precision_score
from threadpoolctl import threadpool_limits

from forecasting.action import evaluate_actions
from forecasting.alerts import score_alerts
from forecasting.config import Protocol
from forecasting.dataset import sha256
from forecasting.evaluation import _event_metrics, split_subjects
from forecasting.feedback import FEEDBACK_COLUMNS, condition


def safe(value):
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [safe(v) for v in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    if isinstance(value, np.integer):
        return int(value)
    return value


def write_json(path, value):
    path.write_text(json.dumps(safe(value), indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def calibration_policy(cal, scores, config, action):
    """Only the primary feedback condition and calibration IDs enter search."""
    if not cal.event.any():
        return 1.01, [{"threshold": 1.01, "reason": "no_calibration_events"}]
    candidates = np.unique(np.r_[np.quantile(scores, np.linspace(0, 1, config["threshold_quantiles"])), 1.01])
    cfg = Protocol(event_delta=1., consecutive_windows=1)
    search, cache = [], {}
    for threshold in candidates:
        flags = score_alerts(cal, scores, threshold, action["cooldown_s"], action["min_quality"])
        key = flags.tobytes()
        if key not in cache:
            raw = cal[["subject", "session", "timestamp_s", "event", "event_time_s"]].assign(alarm=flags)
            fast_fa = float(np.mean([_event_metrics(part, "alarm", cfg)["false_alarms_per_min"]
                                     for _, part in raw.groupby("subject")]))
            if fast_fa > config["false_alarm_budget_per_min"] + 1e-9:
                cache[key] = {"false_alarms_per_min": fast_fa, "occupied_fraction": np.nan,
                              "usable_recall": np.nan, "event_recall": np.nan, "reason": "fails_false_alarm_budget"}
            else:
                cache[key] = evaluate_actions(cal, scores, threshold, action)
                if not np.isclose(cache[key]["false_alarms_per_min"], fast_fa, atol=1e-10):
                    raise ValueError("calibration_false_alarm_screen_disagrees_with_action_evaluation")
        search.append({"threshold": float(threshold), **cache[key]})
    feasible = [r for r in search if r["false_alarms_per_min"] <= config["false_alarm_budget_per_min"] + 1e-9
                and r["occupied_fraction"] <= config["occupancy_budget"] + 1e-9
                and np.isfinite(r["usable_recall"]) and r["usable_recall"] > 0]
    if not feasible:
        return 1.01, search
    chosen = min(feasible, key=lambda r: (-r["usable_recall"], r["false_alarms_per_min"], r["occupied_fraction"], -r["threshold"]))
    return chosen["threshold"], search


def verify_lock(root, dataset):
    path = root / "research/results/feedback_v4_lock.json"
    lock = json.loads(path.read_text(encoding="utf-8"))
    for relative, expected in lock["source_sha256"].items():
        if sha256(root / relative) != expected:
            raise ValueError("Frozen source changed: " + relative)
    for name, data in lock["data"].items():
        if sha256(root / data["path"]) != data["sha256"]:
            raise ValueError("Frozen prepared data changed: " + name)
    return lock, sha256(path)


def run(root, dataset, output, seeds):
    lock, lock_sha = verify_lock(root, dataset)
    config = json.loads((root / "analysis/configs/feedback_v4.json").read_text(encoding="utf-8"))
    action = json.loads((root / "analysis/configs/action_v3.json").read_text(encoding="utf-8"))
    action["minimum_usable_lead_s"] = 2.
    if not set(seeds) <= set(config["seeds"]):
        raise ValueError("seed_outside_frozen_protocol")
    frame = pd.read_csv(root / lock["data"][dataset]["path"], dtype={"subject": str, "session": str})
    if frame.duplicated(["subject", "session", "timestamp_s", "condition"]).any():
        raise ValueError("duplicate_condition_window")
    prefix = "motion_" if dataset == "secondary" else "hmd_"
    motion = [c for c in frame if c.startswith(prefix) and "__lag" in c]
    feature_sets = {"feedback_history_hgb": FEEDBACK_COLUMNS, "feedback_motion_hgb": [*FEEDBACK_COLUMNS, *motion]}
    forbidden = {"subject", "session", "current_rating", "future_peak", "event", "event_time_s", "condition"}
    if any(set(cols) & forbidden for cols in feature_sets.values()):
        raise ValueError("noncausal_or_identity_feature")
    output.mkdir(parents=True, exist_ok=True)
    identity = {"dataset": dataset, "freeze_sha256": lock_sha, "seeds": seeds,
                "feature_sets": feature_sets, "config": config, "action": action}
    run_path = output / "run.json"
    if run_path.exists() and json.loads(run_path.read_text(encoding="utf-8")) != identity:
        raise ValueError("Output already belongs to a different frozen run")
    write_json(run_path, identity)
    primary = condition(config["primary_interval_s"], config["primary_delay_s"])
    all_metrics = []
    for seed in seeds:
        for subject in sorted(frame.subject.unique()):
            start = time.perf_counter()
            stem = output / f"fold_{seed}_{subject}"
            complete = stem.with_suffix(".complete.json")
            if complete.exists():
                checks = json.loads(complete.read_text(encoding="utf-8"))
                for suffix, digest in checks.items():
                    if sha256(stem.with_suffix(suffix)) != digest:
                        raise ValueError("Incomplete or altered cached fold")
                all_metrics.append(pd.read_csv(stem.with_suffix(".metrics.csv"), dtype={"subject": str}))
                continue
            fit_ids, cal_ids = split_subjects(frame.subject, subject, seed, config["calibration_fraction"])
            if set(fit_ids) & set(cal_ids) or subject in fit_ids + cal_ids:
                raise ValueError("identifier_split_overlap")
            fit = frame[frame.subject.isin(fit_ids)].reset_index(drop=True)
            cal = frame[frame.subject.isin(cal_ids) & frame.condition.eq(primary)].reset_index(drop=True)
            test = frame[frame.subject.eq(subject)].reset_index(drop=True)
            counts = fit.groupby("subject").size()
            weights = fit.subject.map(1. / counts).to_numpy(copy=True)
            weights *= len(fit) / weights.sum()
            y_event = fit.event.to_numpy(int)
            class_weights = weights.copy()
            for value in (0, 1):
                mask = y_event == value
                if mask.any():
                    class_weights[mask] *= weights.sum() / (2 * weights[mask].sum())
            parameters = {**config["hgb"], "early_stopping": False, "random_state": seed}
            score_sets = {"last_report": np.zeros(len(test))}
            estimate_sets = {"last_report": test.fb_last.to_numpy()}
            thresholds = {"last_report": 1.01}
            searches, timings = {}, {}
            for model_name, columns in feature_sets.items():
                fit_started = time.perf_counter()
                reg = HistGradientBoostingRegressor(**parameters)
                reg.fit(fit[columns], fit.future_peak, sample_weight=weights)
                estimate_sets[model_name] = np.clip(reg.predict(test[columns]), 0., config["datasets"][dataset]["scale_max"])
                if len(np.unique(y_event)) == 2:
                    clf = HistGradientBoostingClassifier(**parameters)
                    clf.fit(fit[columns], y_event, sample_weight=class_weights)
                    cs = clf.predict_proba(cal[columns])[:, 1]
                    score_sets[model_name] = clf.predict_proba(test[columns])[:, 1]
                else:
                    constant = float(np.average(y_event, weights=weights))
                    cs = np.full(len(cal), constant)
                    score_sets[model_name] = np.full(len(test), constant)
                timings[model_name] = time.perf_counter() - fit_started
                thresholds[model_name], searches[model_name] = calibration_policy(cal, cs, config, action)
            metrics, predictions = [], []
            for model_name in ("last_report", "feedback_history_hgb", "feedback_motion_hgb"):
                for scenario, indices in test.groupby("condition", sort=True).indices.items():
                    part = test.iloc[indices].reset_index(drop=True)
                    scores, estimates = score_sets[model_name][indices], estimate_sets[model_name][indices]
                    _, detail, flags = evaluate_actions(part, scores, thresholds[model_name], action, True)
                    row = detail.iloc[0].to_dict()
                    row.update(dataset=dataset, model=model_name, seed=seed, subject=subject, condition=scenario,
                               windows=len(part), positive_windows=int(part.event.sum()),
                               mae=float(np.mean(abs(estimates - part.future_peak.to_numpy()))),
                               rmse=float(np.sqrt(np.mean((estimates - part.future_peak.to_numpy()) ** 2))),
                               average_precision=float(average_precision_score(part.event, scores)) if part.event.nunique() == 2 else np.nan,
                               threshold=thresholds[model_name], calibration_condition=primary,
                               false_budget_exceeded=row["false_alarms_per_min"] > config["false_alarm_budget_per_min"] + 1e-9,
                               occupancy_budget_exceeded=row["occupied_fraction"] > config["occupancy_budget"] + 1e-9)
                    metrics.append(row)
                    pred = part[["subject", "session", "timestamp_s", "condition", "future_peak", "event", "event_time_s",
                                 "fb_sample_s", "fb_request_s", "fb_arrival_s", "quality"]].copy()
                    pred["model"], pred["seed"] = model_name, seed
                    pred["estimate"], pred["score"], pred["alarm"] = estimates, scores, flags
                    predictions.append(pred)
            write_json(stem.with_suffix(".split.json"), {"test_subject": subject, "seed": seed, "fit_subjects": fit_ids,
                       "calibration_subjects": cal_ids, "feature_sets": feature_sets, "thresholds": thresholds,
                       "calibration_search": searches, "fit_seconds": timings,
                       "fit_rows": len(fit), "calibration_primary_rows": len(cal), "test_rows": len(test)})
            result = pd.DataFrame(metrics)
            result.to_csv(stem.with_suffix(".metrics.csv"), index=False)
            pd.concat(predictions, ignore_index=True).to_csv(stem.with_suffix(".predictions.csv"), index=False)
            write_json(complete, {suffix: sha256(stem.with_suffix(suffix)) for suffix in (".split.json", ".metrics.csv", ".predictions.csv")})
            all_metrics.append(result)
            print(f"{dataset} seed={seed} id={subject} completed={len(all_metrics)} elapsed_s={time.perf_counter()-start:.2f} thresholds={thresholds}", flush=True)
    pd.concat(all_metrics, ignore_index=True).to_csv(output / "metrics.csv", index=False)
    print(f"FINISHED {dataset}: {len(all_metrics)} folds", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=("original", "secondary"), required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[7, 19, 42])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    output = args.output or root / f"analysis/runs/feedback_v4_{args.dataset}"
    with threadpool_limits(limits=2):
        run(root, args.dataset, output, args.seeds)
