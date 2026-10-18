from __future__ import annotations

from dataclasses import replace
import json
import hashlib
import math
from pathlib import Path
import platform

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import average_precision_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
import sklearn

from .config import Protocol
from .dataset import sha256


def feature_columns(frame, modality):
    prefixes = {"eeg": ("eeg_",), "hmd": ("hmd_",), "fusion": ("eeg_", "hmd_")}[modality]
    names = [c for c in frame.columns if c.startswith(prefixes) and "__lag" in c]
    if not names:
        raise ValueError(f"no {modality} causal features")
    return names


def split_subjects(subjects, test_subject, seed, fraction):
    available = sorted(set(map(str, subjects)) - {str(test_subject)})
    if len(available) < 4:
        raise ValueError("at least 5 total subjects required for fit/calibration/test separation")
    rng = np.random.default_rng(seed)
    shuffled = rng.permutation(available)
    ncal = min(len(available) - 3, max(1, math.ceil(len(available) * fraction)))
    calibration = sorted(shuffled[:ncal].tolist())
    fit = sorted(shuffled[ncal:].tolist())
    assert not (set(fit) & set(calibration) or str(test_subject) in fit + calibration)
    return fit, calibration


def fit_regressor(kind, params, seed, quantile=None):
    if kind == "ridge":
        return make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True),
                             StandardScaler(), Ridge(alpha=params["alpha"]))
    options = dict(max_iter=100, learning_rate=0.05, early_stopping=False,
                   random_state=seed, **params)
    if quantile is None:
        return HistGradientBoostingRegressor(loss="squared_error", **options)
    return HistGradientBoostingRegressor(loss="quantile", quantile=quantile, **options)


def choose_parameters(kind, X, y, groups, seed):
    grid = ([{"alpha": 1.0}, {"alpha": 100.0}] if kind == "ridge" else
            [{"max_leaf_nodes": 7, "l2_regularization": 10.0},
             {"max_leaf_nodes": 15, "l2_regularization": 1.0}])
    splitter = GroupKFold(n_splits=min(3, len(np.unique(groups))))
    scores = []
    for params in grid:
        errors = []
        for train, validation in splitter.split(X, y, groups):
            model = fit_regressor(kind, params, seed)
            model.fit(X[train], y[train])
            predicted = model.predict(X[validation])
            # Subject macro MAE prevents long recordings dominating selection.
            for subject in np.unique(groups[validation]):
                mask = groups[validation] == subject
                errors.append(float(np.mean(np.abs(y[validation][mask] - predicted[mask]))))
        scores.append({"parameters": params, "inner_subject_mae": float(np.mean(errors))})
    return min(scores, key=lambda item: item["inner_subject_mae"])["parameters"], scores


def calibration_radius(scores, alpha):
    scores = np.asarray(scores, dtype=float)
    if not len(scores) or not np.isfinite(scores).all():
        raise ValueError("invalid calibration residuals")
    rank = math.ceil((len(scores) + 1) * (1 - alpha))
    return float(np.partition(scores, rank - 1)[rank - 1]) if rank <= len(scores) else float("inf")


def apply_warning_policy(frame, cfg, *, gated=True):
    """Count distinct forecast updates, not CSV heartbeats or Unity frames."""
    alarms = np.zeros(len(frame), dtype=int)
    for _, positions in frame.groupby(["subject", "session"], sort=False).indices.items():
        positions = np.asarray(positions)
        positions = positions[np.argsort(frame.iloc[positions].timestamp_s.to_numpy())]
        count, previous, last_alarm = 0, -np.inf, -np.inf
        for pos in positions:
            row = frame.iloc[pos]
            if not np.isclose(row.timestamp_s - previous, cfg.window_s, atol=1e-5):
                count = 0
            value = row.delta_lower if gated else row.delta_pred
            eligible = row.quality >= cfg.min_quality and value >= cfg.event_delta - 1e-8
            count = count + 1 if eligible else 0
            if count >= cfg.consecutive_windows and row.timestamp_s - last_alarm >= cfg.cooldown_s:
                alarms[pos] = 1
                last_alarm = row.timestamp_s
                count = 0
            previous = row.timestamp_s
    return alarms


def _event_metrics(frame, alarm_column, cfg):
    event_count, matched_count, false_count, alarm_count, redundant, leads = 0, 0, 0, 0, 0, []
    for _, session in frame.groupby(["subject", "session"]):
        session = session.sort_values("timestamp_s")
        times = session.timestamp_s.to_numpy()
        positive = session.event.to_numpy(dtype=bool)
        crossing = session.event_time_s.to_numpy()
        events = []
        for i in range(len(session)):
            if positive[i] and (i == 0 or not positive[i - 1] or not np.isclose(times[i] - times[i - 1], cfg.window_s)):
                j = i
                while j + 1 < len(session) and positive[j + 1] and np.isclose(times[j + 1] - times[j], cfg.window_s):
                    j += 1
                events.append(float(np.nanmin(crossing[i:j + 1])))
        event_count += len(events)
        used = set()
        for alarm_index in np.flatnonzero(session[alarm_column].to_numpy(dtype=bool)):
            alarm = times[alarm_index]
            alarm_count += 1
            candidates = [i for i, event in enumerate(events) if i not in used and 0 < event - alarm <= cfg.horizon_s + 1e-8]
            if candidates:
                index = min(candidates, key=lambda i: events[i])
                used.add(index)
                leads.append(events[index] - alarm)
                matched_count += 1
            elif not positive[alarm_index]:
                false_count += 1
            else:
                redundant += 1
    minutes = len(frame) * cfg.window_s / 60
    return {
        "event_episodes": event_count, "matched_events": matched_count,
        "event_recall": matched_count / event_count if event_count else np.nan,
        "alarms": alarm_count, "false_alarms": false_count,
        "redundant_alarms": redundant,
        "false_alarms_per_min": false_count / minutes if minutes else np.nan,
        "median_lead_s": float(np.median(leads)) if leads else np.nan,
    }


def subject_metrics(predictions, cfg):
    records = []
    for (model, seed, subject), frame in predictions.groupby(["model", "seed", "subject"], sort=True):
        for policy in ("raw", "gated"):
            observed, estimate = frame.future_peak.to_numpy(), frame.future_pred.to_numpy()
            delta = frame.delta_target.to_numpy()
            interval_valid = np.isfinite(frame.delta_lower) & np.isfinite(frame.delta_upper)
            coverage = ((delta >= frame.delta_lower) & (delta <= frame.delta_upper))[interval_valid]
            records.append({
                "model": model, "seed": seed, "subject": subject, "policy": policy,
                "windows": len(frame), "positive_windows": int(frame.event.sum()),
                "mae": float(np.mean(np.abs(observed - estimate))),
                "rmse": float(np.sqrt(np.mean((observed - estimate) ** 2))),
                "average_precision": float(average_precision_score(frame.event, frame.delta_pred)) if frame.event.nunique() > 1 else np.nan,
                "delta_interval_coverage": float(coverage.mean()) if len(coverage) else np.nan,
                "delta_interval_width": float((frame.delta_upper - frame.delta_lower)[interval_valid].mean()) if interval_valid.any() else np.nan,
                **_event_metrics(frame, "alarm_" + policy, cfg),
            })
    return pd.DataFrame(records)


def validate_dataset(frame, cfg):
    if frame.duplicated(["subject", "session", "timestamp_s"]).any():
        raise ValueError("duplicate subject/session/prediction time")
    if not np.allclose(frame.feature_end_s, frame.timestamp_s):
        raise ValueError("feature end must equal decision time")
    if not np.allclose(frame.forecast_end_s - frame.timestamp_s, cfg.horizon_s):
        raise ValueError("forecast horizon does not match the protocol")
    if "protocol_hash" in frame and set(frame.protocol_hash) != {cfg.fingerprint}:
        raise ValueError("prepared table and evaluation protocol differ")
    if frame.data_kind.nunique() != 1:
        raise ValueError("mixing public and synthetic rows is prohibited")
    if frame.subject.nunique() < 5:
        raise ValueError("at least 5 subjects required for grouped model selection/calibration/test")
    if (frame.feature_start_s > frame.feature_end_s).any():
        raise ValueError("invalid feature provenance")


def run_experiment(input_path, output_dir, cfg, *, seeds=None, models=None, resume=False):
    frame = pd.read_csv(input_path, dtype={"subject": str, "session": str})
    validate_dataset(frame, cfg)
    seeds = list(seeds if seeds is not None else cfg.seeds)
    models = list(models or ["oracle_rating_persistence", "time_hgb", "fusion_state", "hmd_ridge", "eeg_ridge", "fusion_ridge", "fusion_hgb", "fusion_cqr"])
    known = {"oracle_rating_persistence", "time_hgb", "fusion_state", "hmd_ridge", "eeg_ridge", "fusion_ridge", "fusion_hgb", "fusion_cqr"}
    if set(models) - known:
        raise ValueError("unknown model names")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    implementation_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    identity = {"input_sha256": sha256(Path(input_path)), "evaluation_sha256": implementation_hash,
                "protocol": cfg.to_dict(), "seeds": seeds,
                "models": models, "data_kind": frame.data_kind.iloc[0]}
    metadata_path = output_dir / "run.json"
    if metadata_path.exists():
        saved = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not resume or saved["identity"] != json.loads(json.dumps(identity)):
            raise ValueError("output run exists; --resume requires exactly matching data/config/models/seeds")
    else:
        metadata_path.write_text(json.dumps({"identity": identity, "python": platform.python_version(),
                                            "sklearn": sklearn.__version__, "numpy": np.__version__}, indent=2), encoding="utf-8")
    outputs, splits = [], []
    for seed in seeds:
        for subject in sorted(frame.subject.unique()):
            fit_subjects, calibration_subjects = split_subjects(frame.subject, subject, seed, cfg.calibration_fraction)
            fit = frame[frame.subject.isin(fit_subjects)]
            cal = frame[frame.subject.isin(calibration_subjects)]
            test = frame[frame.subject == subject]
            split_path = output_dir / f"split_{seed}_{subject}.json"
            record = (json.loads(split_path.read_text(encoding="utf-8")) if resume and split_path.exists() else
                      {"seed": seed, "test_subject": subject, "fit_subjects": fit_subjects,
                       "calibration_subjects": calibration_subjects, "model_selection": {}})
            for model_name in models:
                path = output_dir / f"pred_{seed}_{subject}_{model_name}.csv"
                if resume and path.exists():
                    outputs.append(pd.read_csv(path, dtype={"subject": str, "session": str}))
                    continue
                result = test[["subject", "session", "timestamp_s", "forecast_end_s", "current_rating", "future_peak", "delta_target", "event", "event_time_s", "quality", "data_kind"]].copy()
                if model_name == "oracle_rating_persistence":
                    result["future_pred"] = test.current_rating.to_numpy()
                    result["delta_pred"] = 0.0
                    result["delta_lower"], result["delta_upper"] = np.nan, np.nan
                    result["uses_live_rating"] = True
                else:
                    modality, suffix = model_name.rsplit("_", 1)
                    columns = ["timestamp_s"] if modality == "time" else feature_columns(frame, modality)
                    Xfit, Xcal, Xtest = [part[columns].to_numpy(dtype=float) for part in (fit, cal, test)]
                    kind = "ridge" if suffix == "ridge" else "hgb"
                    training_level = fit.current_rating.to_numpy() if suffix == "state" else fit.future_peak.to_numpy()
                    params, search = choose_parameters(kind, Xfit, training_level, fit.subject.to_numpy(), seed)
                    record["model_selection"][model_name] = {"parameters": params, "inner_group_scores": search}
                    level_model = fit_regressor(kind, params, seed)
                    level_model.fit(Xfit, training_level)
                    result["future_pred"] = np.clip(level_model.predict(Xtest), 0, 1)
                    if suffix == "state":
                        result["delta_pred"] = 0.0
                        result["delta_lower"], result["delta_upper"] = np.nan, np.nan
                        result["uses_live_rating"] = False
                        result["model"], result["seed"] = model_name, seed
                        result["alarm_raw"], result["alarm_gated"] = 0, 0
                        result.to_csv(path, index=False)
                        outputs.append(result)
                        print(f"seed={seed} test={subject} {model_name}: n={len(test)}", flush=True)
                        continue
                    delta_models = {}
                    for key, q in (("lower", cfg.interval_alpha / 2), ("pred", 0.5), ("upper", 1 - cfg.interval_alpha / 2)):
                        if suffix != "cqr" and key != "pred":
                            continue
                        delta_model = fit_regressor(kind, params, seed, q if suffix == "cqr" else None)
                        delta_model.fit(Xfit, fit.delta_target.to_numpy())
                        delta_models[key] = delta_model
                    if suffix == "cqr":
                        # Sorting fixes quantile crossing before calibration, at test too.
                        cal_quantiles = np.sort(np.column_stack([delta_models[k].predict(Xcal) for k in ("lower", "pred", "upper")]), axis=1)
                        test_quantiles = np.sort(np.column_stack([delta_models[k].predict(Xtest) for k in ("lower", "pred", "upper")]), axis=1)
                        scores = np.maximum.reduce([cal_quantiles[:, 0] - cal.delta_target.to_numpy(),
                                                    cal.delta_target.to_numpy() - cal_quantiles[:, 2], np.zeros(len(cal))])
                        radius = calibration_radius(scores, cfg.interval_alpha)
                        lower, point, upper = test_quantiles.T
                    else:
                        point = delta_models["pred"].predict(Xtest)
                        radius = calibration_radius(np.abs(delta_models["pred"].predict(Xcal) - cal.delta_target.to_numpy()), cfg.interval_alpha)
                        lower, upper = point.copy(), point.copy()
                    result["delta_pred"] = np.clip(point, 0, 1)
                    result["delta_lower"] = np.clip(lower - radius, 0, 1)
                    result["delta_upper"] = np.clip(upper + radius, 0, 1)
                    result["uses_live_rating"] = False
                    record["model_selection"][model_name]["calibration_radius"] = radius
                    record["model_selection"][model_name]["feature_count"] = len(columns)
                result["model"], result["seed"] = model_name, seed
                result = result.reset_index(drop=True)
                result["alarm_raw"] = apply_warning_policy(result, cfg, gated=False)
                result["alarm_gated"] = apply_warning_policy(result, cfg, gated=True)
                result.to_csv(path, index=False)
                outputs.append(result)
                print(f"seed={seed} test={subject} {model_name}: n={len(test)}", flush=True)
            splits.append(record)
            (output_dir / f"split_{seed}_{subject}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    predictions = pd.concat(outputs, ignore_index=True)
    predictions.to_csv(output_dir / "predictions.csv", index=False)
    subject_metrics(predictions, cfg).to_csv(output_dir / "subject_metrics.csv", index=False)
    (output_dir / "split_manifest.json").write_text(json.dumps(splits, indent=2), encoding="utf-8")
    return predictions
