from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd


def paired_subject_bootstrap(metrics, model, baseline="oracle_rating_persistence", n=2000, seed=7):
    means = metrics[metrics.policy == "gated"].groupby(["model", "subject"]).mae.mean().unstack(0)
    if model not in means or baseline not in means:
        return None
    pairs = means[[model, baseline]].dropna()
    differences = (pairs[model] - pairs[baseline]).to_numpy()
    if len(differences) < 2:
        return None
    draws = np.random.default_rng(seed).choice(differences, size=(n, len(differences)), replace=True).mean(axis=1)
    return {"model": model, "baseline": baseline, "subjects": len(differences),
            "mae_difference": float(differences.mean()), "ci_low": float(np.quantile(draws, 0.025)),
            "ci_high": float(np.quantile(draws, 0.975))}


def make_report(directory: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    metrics = pd.read_csv(directory / "subject_metrics.csv", dtype={"subject": str})
    predictions = pd.read_csv(directory / "predictions.csv", dtype={"subject": str, "session": str})
    metadata = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    kind = metadata["identity"]["data_kind"]
    # First average seeds within each held-out subject, then macro-average subjects.
    columns = ["mae", "rmse", "average_precision", "delta_interval_coverage", "delta_interval_width",
               "event_recall", "false_alarms_per_min", "median_lead_s", "alarms"]
    by_subject = metrics.groupby(["model", "policy", "subject"])[columns].mean()
    summary = by_subject.groupby(["model", "policy"])[columns].mean().reset_index()
    counts = by_subject.groupby(["model", "policy"]).agg(subjects=("mae", "count"), event_subjects=("event_recall", "count")).reset_index()
    summary = summary.merge(counts, on=["model", "policy"])
    summary.to_csv(directory / "summary.csv", index=False)
    pooled = predictions.groupby(["model", "seed"])[["future_peak", "future_pred"]].apply(
        lambda f: pd.Series({"window_weighted_mae": np.abs(f.future_peak - f.future_pred).mean(),
                             "windows": len(f)})).reset_index()
    pooled.to_csv(directory / "window_weighted_metrics.csv", index=False)
    comparisons = [r for baseline in ("oracle_rating_persistence", "fusion_state", "hmd_ridge", "time_hgb")
                   for model in predictions.model.unique() if model != baseline
                   if (r := paired_subject_bootstrap(metrics, model, baseline)) is not None]
    (directory / "paired_mae_bootstrap.json").write_text(json.dumps(comparisons, indent=2), encoding="utf-8")
    lines = ["# Forecast experiment report", "", f"Data kind: **{kind.upper()}**.", "",
             "Synthetic runs verify software only. Public runs are retrospective prediction experiments, not evidence of symptom mitigation.", "",
             "Scores are macro-averaged across held-out subjects after averaging seeds within each subject.", "",
             "| Model | Policy | MAE | AP | Event recall | False alarms/min | Lead (s) | Interval coverage |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in summary.itertuples():
        fmt = lambda x: f"{x:.4f}" if np.isfinite(x) else "NA"
        lines.append(f"| {row.model} | {row.policy} | {fmt(row.mae)} | {fmt(row.average_precision)} | {fmt(row.event_recall)} | {fmt(row.false_alarms_per_min)} | {fmt(row.median_lead_s)} | {fmt(row.delta_interval_coverage)} |")
    lines += ["", "`oracle_rating_persistence` observes the current self-rating; it is a rating-available comparator, not a passive sensor-only model.",
              "`paired_mae_bootstrap.json` additionally compares sensor forecasts with estimated-state persistence, HMD alone, and time alone. These descriptive intervals are not adjusted for multiple comparisons.",
              "Intervals use pooled residuals from calibration subjects disjoint from training and test. Temporal dependence and distribution shift preclude a claimed distribution-free coverage guarantee.",
              "Event recall merges consecutive positive target windows into one episode. Lead time is measured on matched emitted alerts; all-event recall and false alarms must be read alongside it.",
              "Quality measures data completeness, not validated EEG artifact rejection. No effect size for reducing discomfort can be inferred from replay."]
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    figures = directory / "figures"
    figures.mkdir(exist_ok=True)
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    display_names = {"eeg_ridge": "EEG Ridge", "fusion_cnn_lstm": "CNN-LSTM", "fusion_cqr": "Fusion CQR",
                     "fusion_hgb": "Fusion HGB", "fusion_ridge": "Fusion Ridge", "fusion_state": "State estimate held",
                     "hmd_ridge": "HMD Ridge", "oracle_rating_persistence": "Rating persistence*", "time_hgb": "Time HGB"}
    prefix = "SYNTHETIC SOFTWARE CHECK: " if kind != "public" else ""
    mae = metrics[metrics.policy == "gated"].groupby(["model", "subject"]).mae.mean().unstack(0)
    fig, ax = plt.subplots(figsize=(8, 4))
    for i, name in enumerate(mae.columns):
        values = mae[name].dropna().to_numpy()
        ax.scatter(np.full(len(values), i), values, alpha=.65, s=20)
        ax.scatter([i], [np.mean(values)], marker="_", c="black", s=230, zorder=5)
    ax.set_xticks(range(len(mae.columns)), [display_names.get(c, c) for c in mae.columns], rotation=30, ha="right")
    ax.set_ylabel("Held-out subject MAE (future peak rating)")
    ax.set_title(prefix + "Forecast error across held-out participants")
    fig.text(.98, .01, "* Requires a current self-report; not a passive sensor model", ha="right", fontsize=7)
    fig.tight_layout(rect=(0, .04, 1, 1))
    for suffix in ("png", "pdf"):
        fig.savefig(figures / f"subject_mae.{suffix}", dpi=200)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4))
    selected_names = {"fusion_hgb", "fusion_cqr", "fusion_cnn_lstm"}
    collisions = {}
    for row in summary[summary.model.isin(selected_names)].itertuples():
        color, marker = ("tab:blue", "o") if row.policy == "raw" else ("tab:orange", "s")
        ax.scatter(row.false_alarms_per_min, row.event_recall, c=color, marker=marker, s=55)
        key = (round(row.false_alarms_per_min, 1), round(row.event_recall, 2))
        offset = collisions.get(key, 0)
        collisions[key] = offset + 1
        ax.annotate(f"{display_names.get(row.model, row.model)} ({row.policy})", (row.false_alarms_per_min, row.event_recall),
                    xytext=(7, 8 + 12 * offset), textcoords="offset points", fontsize=7,
                    arrowprops={"arrowstyle": "-", "color": color, "lw": .5})
    ax.set(xlabel="False emitted warnings per monitored minute", ylabel="Event episode recall",
           title=prefix + "Warning cost and event coverage")
    ax.set_ylim(-.05, 1.08)
    xmax = summary[summary.model.isin(selected_names)].false_alarms_per_min.max()
    ax.set_xlim(-.01, max(.05, xmax * 1.8 + .02))
    fig.tight_layout()
    for suffix in ("png", "pdf"):
        fig.savefig(figures / f"warning_tradeoff.{suffix}", dpi=200)
    plt.close(fig)
    example = predictions[predictions.model == "fusion_cqr"]
    if len(example):
        trajectory = example.groupby(["subject", "session", "seed"]).event.sum().idxmax()
        subject, session, seed = trajectory
        example = example[(example.subject == subject) & (example.session == session) & (example.seed == seed)].sort_values("timestamp_s")
        fig, axes = plt.subplots(2, 1, figsize=(8, 5), sharex=True)
        t = example.timestamp_s.to_numpy()
        horizon = metadata["identity"]["protocol"]["horizon_s"]
        groups = np.split(np.arange(len(t)), np.flatnonzero(np.diff(t) > metadata["identity"]["protocol"]["window_s"] + 1e-8) + 1)
        for i, indices in enumerate(groups):
            part = example.iloc[indices]
            label = (lambda value: value if i == 0 else None)
            axes[0].plot(t[indices], part.future_peak, color="tab:blue", label=label(f"Observed next-{horizon:g}s peak"))
            axes[0].plot(t[indices], part.future_pred, color="tab:orange", label=label("Sensor forecast"))
            axes[1].fill_between(t[indices], part.delta_lower, part.delta_upper, color="tab:blue", alpha=.25, label=label("Calibrated delta interval"))
            axes[1].plot(t[indices], part.delta_target, color="tab:orange", label=label("Observed increase"))
        axes[0].set_ylabel("Self-report score")
        axes[0].legend(fontsize=8)
        for alarm in t[example.alarm_gated.astype(bool)]:
            axes[1].axvline(alarm, color="red", alpha=.5)
        axes[1].set(xlabel="Decision time (s)", ylabel="Future increase")
        axes[1].legend(fontsize=8)
        axes[0].set_title(f"{prefix}Example: participant {subject}, {session}, seed {seed}")
        fig.text(.99, .01, "Illustration chosen by largest event-window count; gaps are not interpolated", ha="right", fontsize=7)
        fig.tight_layout(rect=(0, .03, 1, 1))
        for suffix in ("png", "pdf"):
            fig.savefig(figures / f"example_forecast.{suffix}", dpi=200)
        plt.close(fig)
    return summary
