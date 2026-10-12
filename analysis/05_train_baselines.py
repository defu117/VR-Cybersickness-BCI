"""Compare HMD-only, EEG-only and fusion baselines with grouped validation."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from common import as_float, find_prefix_columns, read_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--output", default="data/model_results.csv")
    parser.add_argument("--predictions", default="data/predictions.csv")
    parser.add_argument("--task", choices=("classification", "regression"), default="classification")
    parser.add_argument("--quality-threshold", type=float, default=0.5)
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()

    try:
        import pandas as pd
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression, Ridge
        from sklearn.metrics import (balanced_accuracy_score, f1_score, mean_absolute_error,
                                     mean_squared_error, roc_auc_score)
        from sklearn.model_selection import GroupKFold
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as error:
        raise SystemExit("install analysis/requirements.txt before training baselines") from error

    frame = pd.read_csv(args.input)
    if "label" not in frame:
        raise SystemExit("feature CSV needs a label column")
    label = pd.to_numeric(frame["label"], errors="coerce")
    valid = label.notna()
    frame = frame.loc[valid].reset_index(drop=True)
    y = label.loc[valid].to_numpy(dtype=float)
    groups = frame.get("subject", frame.get("session", pd.Series(np.arange(len(frame))))).fillna("unknown").astype(str).to_numpy()
    hmd_columns = [column for column in find_prefix_columns(list(frame.columns), ("hmd_",))
                   if pd.to_numeric(frame[column], errors="coerce").notna().mean() >= 0.5]
    eeg_columns = [column for column in find_prefix_columns(list(frame.columns), ("eeg_",))
                   if pd.to_numeric(frame[column], errors="coerce").notna().mean() >= 0.5]
    if not hmd_columns and not eeg_columns:
        raise SystemExit("no hmd_ or eeg_ feature columns found")

    feature_sets = {"hmd_only": hmd_columns, "eeg_only": eeg_columns, "fusion": hmd_columns + eeg_columns}
    quality_column = "eeg_quality" if "eeg_quality" in frame.columns else None
    if quality_column:
        feature_sets["fusion_quality_gate"] = hmd_columns + eeg_columns
    unique_groups = np.unique(groups)
    if len(unique_groups) < 2:
        raise SystemExit("at least two subject/session groups are required for grouped validation")
    splitter = GroupKFold(n_splits=min(args.folds, len(unique_groups)))
    results = []
    predictions = []
    for source, columns in feature_sets.items():
        subset = frame
        subset_y = y
        subset_groups = groups
        if source == "fusion_quality_gate" and quality_column:
            quality = pd.to_numeric(frame[quality_column], errors="coerce").fillna(0.0).to_numpy()
            keep = quality >= args.quality_threshold
            subset = frame.loc[keep].reset_index(drop=True)
            subset_y = y[keep]
            subset_groups = groups[keep]
        if not columns or len(subset) < 2 or len(np.unique(subset_groups)) < 2:
            continue

        X = subset[columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        if args.task == "classification":
            models = {
                "logistic": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(max_iter=1000)),
                "random_forest": make_pipeline(SimpleImputer(strategy="median"), RandomForestClassifier(n_estimators=200, random_state=7, class_weight="balanced")),
            }
        else:
            models = {
                "ridge": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=1.0)),
                "random_forest": make_pipeline(SimpleImputer(strategy="median"), RandomForestRegressor(n_estimators=200, random_state=7)),
            }

        subset_unique_groups = np.unique(subset_groups)
        if len(subset_unique_groups) < 2:
            continue
        subset_splitter = GroupKFold(n_splits=min(args.folds, len(subset_unique_groups)))
        for model_name, model in models.items():
            fold_values = []
            for train, test in subset_splitter.split(X, subset_y, subset_groups):
                model.fit(X[train], subset_y[train])
                predicted = model.predict(X[test])
                probability = model.predict_proba(X[test])[:, 1] if hasattr(model, "predict_proba") else predicted
                if args.task == "classification":
                    balanced = balanced_accuracy_score(subset_y[test], predicted)
                    f1 = f1_score(subset_y[test], predicted, zero_division=0)
                    try:
                        auroc = roc_auc_score(subset_y[test], probability)
                    except ValueError:
                        auroc = float("nan")
                    fold_values.append((balanced, f1, auroc))
                    for index, actual, estimate, score in zip(test, subset_y[test], predicted, probability):
                        predictions.append({"source": source, "model": model_name, "group": subset_groups[index], "timestamp_s": subset.iloc[index].get("timestamp_s", ""), "y_true": actual, "y_pred": estimate, "probability": score})
                else:
                    fold_values.append((mean_absolute_error(subset_y[test], predicted), mean_squared_error(subset_y[test], predicted) ** 0.5, float("nan")))
                    for index, actual, estimate in zip(test, subset_y[test], predicted):
                        predictions.append({"source": source, "model": model_name, "group": subset_groups[index], "timestamp_s": subset.iloc[index].get("timestamp_s", ""), "y_true": actual, "y_pred": estimate, "probability": estimate})
            mean_values = np.nanmean(np.asarray(fold_values, dtype=float), axis=0)
            if args.task == "classification":
                results.append({"source": source, "model": model_name, "balanced_accuracy": mean_values[0], "f1": mean_values[1], "auroc": mean_values[2]})
            else:
                results.append({"source": source, "model": model_name, "mae": mean_values[0], "rmse": mean_values[1]})

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result_fields = list(results[0]) if results else ["source", "model"]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=result_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    prediction_path = Path(args.predictions)
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_fields = ["source", "model", "group", "timestamp_s", "y_true", "y_pred", "probability"]
    with prediction_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=prediction_fields)
        writer.writeheader()
        writer.writerows(predictions)
    print(f"wrote {len(results)} model rows to {output} and {len(predictions)} predictions to {prediction_path}")


if __name__ == "__main__":
    main()
