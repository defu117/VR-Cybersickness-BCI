"""Require the full frozen grid, archive ID-level evidence and paired intervals."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parent / ".tmp/matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from forecasting.dataset import read_table, sha256
from forecasting.alerts import score_alerts
from forecasting.evaluation import split_subjects
from forecasting.feedback import FEEDBACK_COLUMNS, condition
from forecasting.secondary import identity, read_recording

MODELS = ["last_report", "feedback_history_hgb", "feedback_motion_hgb"]
METRICS = ["mae", "rmse", "average_precision", "event_recall", "usable_recall", "false_alarms_per_min",
           "occupied_fraction", "median_lead_s", "median_usable_lead_s", "intensity_s"]


def audit_report(root, dataset):
    folder = root / f"research/results/feedback_v4_audit/{dataset}"
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    records = pd.read_csv(folder / "recordings.csv")
    retained = records[records.status.eq("included")]
    available = pd.read_csv(folder / "availability.csv")
    native = "0–20 FMS" if dataset == "secondary" else "0–1 连续评分"
    missing = retained[retained.numeric_missing_rows.gt(0)]
    resolution = []
    for row in retained.itertuples():
        if dataset == "secondary":
            values = read_recording(root / "analysis/data/raw/ryu2026/Dataset" / row.file).iloc[:420].rating.to_numpy(float)
        else:
            values = read_table(root / "analysis/data/raw/juliete" / row.file,
                                duplicate_last=True, startup_eeg_rate=300., startup_limit_s=5.).Rating.to_numpy(float)
        changes = np.abs(np.diff(values))
        nonzero = changes[changes > 1e-12]
        resolution.append({"subject": row.subject, "session": row.session, "stored_scores": len(values),
                           "unique_stored_values": len(np.unique(values)),
                           "fraction_on_0p1_grid": float(np.isclose(values / .1, np.rint(values / .1), atol=1e-6, rtol=0).mean()),
                           "fraction_on_1p0_grid": float(np.isclose(values, np.rint(values), atol=1e-6, rtol=0).mean()),
                           "min_nonzero_stored_change": float(nonzero.min()) if len(nonzero) else np.nan})
    pd.DataFrame(resolution).to_csv(folder / "rating_resolution.csv", index=False)
    prepared = pd.read_csv(root / f"analysis/data/processed/feedback_v4/{dataset}.csv",
                           usecols=["subject", "session", "timestamp_s", "condition", "event", "fb_age_s", "feedback_interval_s", "feedback_delay_s"],
                           dtype={"subject": str, "session": str})
    nominal_gap = 1.5 if dataset == "secondary" else 1.
    prepared["stale_beyond_nominal_cycle"] = prepared.fb_age_s > prepared.feedback_interval_s + prepared.feedback_delay_s + nominal_gap + 1e-8
    staleness = prepared.groupby(["subject", "condition"]).agg(windows=("timestamp_s", "size"),
                     stale_windows=("stale_beyond_nominal_cycle", "sum"), mean_feedback_age_s=("fb_age_s", "mean"),
                     max_feedback_age_s=("fb_age_s", "max"))
    staleness.to_csv(folder / "feedback_staleness.csv")
    prepared = prepared[prepared.condition.eq("i30_d3")]
    retention = []
    for row in retained.itertuples():
        selected = prepared[prepared.session.eq(row.session)]
        nominal = len(np.arange(9., row.rating_last_s - 6. + 1e-8, 3.)) if dataset == "secondary" else np.nan
        retention.append({"subject": row.subject, "session": row.session, "retained_windows": len(selected),
                          "positive_windows": int(selected.event.sum()), "valid_monitor_s": len(selected) * 3.,
                          "motion_unchecked_nominal_grid_windows": nominal,
                          "retained_fraction_of_nominal_grid": len(selected) / nominal if nominal > 0 else np.nan})
    pd.DataFrame(retention).to_csv(folder / "window_retention.csv", index=False)
    collisions = []
    if dataset == "secondary":
        attributes = []
        for row in retained.itertuples():
            attr = identity(read_recording(root / "analysis/data/raw/ryu2026/Dataset" / row.file))
            attributes.append({"subject": row.subject, "gender": attr[0], "age": attr[1], "mssq": attr[2]})
        attributes = pd.DataFrame(attributes).drop_duplicates()
        for _, part in attributes.groupby(["gender", "age", "mssq"]):
            if len(part) > 1:
                collisions.append({"matching_attribute_group": len(collisions) + 1,
                                   "identifier_count": len(part), "identifiers": "|".join(sorted(part.subject))})
    pd.DataFrame(collisions, columns=["matching_attribute_group", "identifier_count", "identifiers"]).to_csv(folder / "attribute_collisions.csv", index=False)
    duplicate_files = records[records.file_sha256.duplicated(keep=False)]
    duplicate_files[["subject", "session", "file", "status", "file_sha256"]].to_csv(folder / "byte_duplicate_files.csv", index=False)
    text = [f"# {dataset} 数据及反馈审计", "", "日期：2026-10-19。", "",
            f"审计 {summary['raw_records_audited']} 段源记录；保留 {summary['included_recordings']} 段、"
            f"{summary['included_identifiers']} 个作者编号、每条件 {summary['windows_per_condition']} 个窗口，共 9 条件。", "",
            f"原生尺度：{native}。完整的原始评分目标、越阈时刻和历史运动特征均已重算核对。",
            "原候选窗口未因本轮审计改变；参与者真实身份与跨编号别名仍无法独立确认。", "",
            f"入选记录中有 {len(missing)} 段包含局部缺失数值样本；只使用历史完整且已重算的窗口，不填补缺失运动。",
            f"模拟请求缺失合计 {int(available.missing_requests.sum())} 次（9 条件重复计数，不是真实自报次数）。",
            "评分保存间隔、可观察值变化间隔和持平段均记录在 recordings.csv；值变化不能恢复真实按钮报告事件。", "",
            "## 纳排和身份", "",
            "同一作者编号全部记录整组划分；属性冲突/无法确认则整组排除。未通过属性相同、时钟重置或行数猜测身份。",
            "规范化序列未发现跨编号精确重复；这一阴性检查不能排除非精确重复、重新编号或同一人的不同记录。", "",
            "## 缺失、时钟和反馈到达", "",
            "评分仅取请求时刻之前、最大允许间隔内的最近原始值；不插值、不读取未来报告。",
            "预测只使用到达时刻不晚于预测时刻的报告，保留采样、请求、到达和年龄三类时间信息。",
            "缺失请求不会刷新旧报告；旧值可以长期保持，其年龄和缺失次数单列。9 条件使用同一窗口交集。",
            "第一源以毫秒接收时钟转秒、按既有规则处理启动缓存和重复时间；非启动重置排除。第二源保留前 420 数据行与原生秒。", "",
            "## 排除原因", ""]
    text.extend(f"- {reason}：{count} 段。" for reason, count in summary["exclusion_reasons"].items())
    if dataset == "original":
        off_grid = sum(row["fraction_on_0p1_grid"] < 1 - 1e-6 for row in resolution)
        text += ["", "## 导出评分的分辨率", "",
                 f"{len(resolution)} 段入选记录中有 {off_grid} 段出现不在 0.1 网格上的连续导出值。",
                 "作者论文描述的报告档位与公开导出值并不完全对应；缺少按钮/控制器更新事件，无法判断各次连续数值变化的来源。",
                 "本分析保留原生导出值与预定 0.1 增量标签，不强行量化为离散档位，也不将数值变化频率视为主动报告频率。"]
    if collisions:
        text += ["", "## 待确认的跨编号属性重合", ""]
        text.extend(f"- {row['identifiers']} 的已观察性别、年龄和 MSSQ 相同。" for row in collisions)
        text += ["属性重合不足以推断身份；按冻结协议不合并、不重标编号。这些编号是否为别名仍需作者确认，因而不能将按编号留组等同于独立认证的按真实参与者留组。"]
    text += ["", "逐记录清单：recordings.csv；排除记录：exclusions.csv；逐编号计数：identifier_counts.csv；",
             "模拟请求与缺失统计：availability.csv；条件反馈年龄：condition_availability.csv；量表数值分辨率：rating_resolution.csv。", "",
             "评分按公开导出值保留，不依据量表名称强制取整，也不把连续小变化解释为独立报告次数。",
             "window_retention.csv 列出逐记录有效窗口与监测时长；第二源另报运动质量筛选前、仅按时间支持计算的候选网格比例，不能当作人群代表性。",
             "feedback_staleness.csv 标记因缺失请求等原因超过一个名义周期的旧反馈。按冻结规则继续保留这些窗口，年龄作为输入，不依据结果追加排除。",
             "模拟到达与实际用户反应不同，不能推断报告负担或症状减轻。"]
    (folder / "report_zh.md").write_text("\n".join(text) + "\n", encoding="utf-8")


def collect(root, dataset, folders, output, config, lock_sha):
    data = pd.read_csv(root / f"analysis/data/processed/feedback_v4/{dataset}.csv", dtype={"subject": str, "session": str})
    prefix = "motion_" if dataset == "secondary" else "hmd_"
    motion = [c for c in data if c.startswith(prefix) and "__lag" in c]
    features = {"feedback_history_hgb": FEEDBACK_COLUMNS, "feedback_motion_hgb": [*FEEDBACK_COLUMNS, *motion]}
    expected_action = json.loads((root / "analysis/configs/action_v3.json").read_text(encoding="utf-8"))
    ids = sorted(data.subject.unique())
    scenarios = sorted(data.condition.unique())
    metrics, splits, searches = [], [], []
    evidence = {}
    for seed in config["seeds"]:
        folder = folders[seed]
        run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        if run["freeze_sha256"] != lock_sha or run["dataset"] != dataset or seed not in run["seeds"]:
            raise ValueError("part_run_identity_mismatch")
        if run["config"] != config or run["action"] != expected_action or run["feature_sets"] != features:
            raise ValueError("part_parameters_or_feature_allowlist_mismatch")
        for subject in ids:
            stem = folder / f"fold_{seed}_{subject}"
            done = json.loads(stem.with_suffix(".complete.json").read_text(encoding="utf-8"))
            for suffix, expected in done.items():
                if sha256(stem.with_suffix(suffix)) != expected:
                    raise ValueError("fold_artifact_hash_mismatch")
            split = json.loads(stem.with_suffix(".split.json").read_text(encoding="utf-8"))
            fit_ids, cal_ids = split_subjects(ids, subject, seed, config["calibration_fraction"])
            if (split["fit_subjects"] != fit_ids or split["calibration_subjects"] != cal_ids or
                    split["test_subject"] != subject or split["seed"] != seed):
                raise ValueError("split_not_frozen_grouping_rule")
            if split["feature_sets"] != features:
                raise ValueError("fold_feature_allowlist_mismatch")
            current = pd.read_csv(stem.with_suffix(".metrics.csv"), dtype={"subject": str})
            if (len(current) != len(MODELS) * len(scenarios) or
                    current.duplicated(["model", "condition"]).any() or
                    set(current.model) != set(MODELS) or set(current.condition) != set(scenarios) or
                    set(current.subject) != {subject} or set(current.seed) != {seed}):
                raise ValueError("incomplete_metric_grid")
            predictions = pd.read_csv(stem.with_suffix(".predictions.csv"), dtype={"subject": str, "session": str})
            expected = data[data.subject.eq(subject)]
            for name in MODELS:
                pred = predictions[predictions.model.eq(name)]
                merged = pred.merge(expected, on=["subject", "session", "timestamp_s", "condition"], suffixes=("_saved", "_input"), validate="one_to_one")
                if len(pred) != len(expected) or len(merged) != len(expected):
                    raise ValueError("heldout_prediction_window_grid_mismatch")
                for column in ("future_peak", "event", "event_time_s", "fb_sample_s", "fb_request_s", "fb_arrival_s"):
                    if not np.allclose(merged[column + "_saved"], merged[column + "_input"], equal_nan=True):
                        raise ValueError("saved_prediction_provenance_mismatch")
                if not np.isfinite(pred.estimate).all() or not pred.score.between(0, 1).all():
                    raise ValueError("invalid_saved_prediction")
                if name == "last_report" and not np.allclose(merged.estimate, merged.fb_last):
                    raise ValueError("persistence_uses_unavailable_rating")
                for scenario, part in pred.groupby("condition", sort=True):
                    row = current[current.model.eq(name) & current.condition.eq(scenario)].iloc[0]
                    error = part.estimate.to_numpy() - part.future_peak.to_numpy()
                    if not np.isclose(abs(error).mean(), row.mae, atol=1e-10) or not np.isclose(np.sqrt((error ** 2).mean()), row.rmse, atol=1e-10):
                        raise ValueError("saved_error_metrics_disagree_with_predictions")
                    flags = score_alerts(part.reset_index(drop=True), part.score, row.threshold,
                                         expected_action["cooldown_s"], expected_action["min_quality"])
                    if not np.array_equal(flags, part.alarm):
                        raise ValueError("saved_alarms_disagree_with_causal_rule")
            for name, rows in split["calibration_search"].items():
                feasible = [r for r in rows if r.get("usable_recall") is not None and r["usable_recall"] > 0
                            and r["false_alarms_per_min"] <= config["false_alarm_budget_per_min"] + 1e-9
                            and r["occupied_fraction"] <= config["occupancy_budget"] + 1e-9]
                threshold = min(feasible, key=lambda r: (-r["usable_recall"], r["false_alarms_per_min"], r["occupied_fraction"], -r["threshold"]))["threshold"] if feasible else 1.01
                if not np.isclose(threshold, split["thresholds"][name], atol=1e-12):
                    raise ValueError("threshold_does_not_follow_frozen_calibration_objective")
            expected_counts = expected.groupby("condition").size()
            if not np.array_equal(current.condition.map(expected_counts), current.windows):
                raise ValueError("metric_window_count_mismatch")
            primary = condition(config["primary_interval_s"], config["primary_delay_s"])
            if set(current.calibration_condition) != {primary}:
                raise ValueError("threshold_selected_on_nonprimary_condition")
            for name in MODELS:
                if current[current.model.eq(name)].threshold.nunique() != 1:
                    raise ValueError("threshold_changed_across_test_conditions")
            metrics.append(current)
            searches.extend({"seed": seed, "test_subject": subject, "model": name, **row}
                            for name, rows in split["calibration_search"].items() for row in rows)
            splits.append({k: v for k, v in split.items() if k != "calibration_search"})
            evidence[f"{seed}:{subject}"] = {"path": str(stem.relative_to(root)), "sha256": done}
    combined = pd.concat(metrics, ignore_index=True)
    output.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output / "subject_metrics.csv", index=False)
    pd.DataFrame(searches).to_csv(output / "calibration_search.csv", index=False)
    (output / "split_manifest.json").write_text(json.dumps(splits, indent=2, ensure_ascii=False), encoding="utf-8")
    numeric = combined.select_dtypes(include=[np.number]).columns.difference(["seed"])
    by_id = combined.groupby(["model", "condition", "subject"])[numeric].mean().reset_index()
    by_id.to_csv(output / "identifier_means.csv", index=False)
    summary = by_id.groupby(["model", "condition"])[numeric].mean().reset_index()
    summary.to_csv(output / "summary.csv", index=False)
    budget = combined.groupby(["model", "condition"])[["false_budget_exceeded", "occupancy_budget_exceeded"]].agg(["sum", "mean"])
    budget.to_csv(output / "budget_transfer.csv")
    rng, paired = np.random.default_rng(config["bootstrap_seed"]), []
    for scenario in scenarios:
        for a, b in (("last_report", "feedback_history_hgb"), ("feedback_history_hgb", "feedback_motion_hgb"), ("last_report", "feedback_motion_hgb")):
            aa = by_id[by_id.condition.eq(scenario) & by_id.model.eq(a)].set_index("subject")
            bb = by_id[by_id.condition.eq(scenario) & by_id.model.eq(b)].set_index("subject")
            for metric in METRICS:
                difference = (bb[metric] - aa[metric]).dropna().to_numpy()
                low = high = mean = np.nan
                if len(difference):
                    boot = rng.choice(difference, size=(config["bootstrap_repetitions"], len(difference)), replace=True).mean(axis=1)
                    low, high = np.quantile(boot, [.025, .975])
                    mean = difference.mean()
                paired.append({"condition": scenario, "baseline": a, "comparison": b, "metric": metric,
                               "difference": mean, "ci_low": low, "ci_high": high, "identifiers": len(difference)})
    paired = pd.DataFrame(paired)
    paired.to_csv(output / "paired_uncertainty.csv", index=False)
    manifest = {"dataset": dataset, "status": "complete", "identifiers": len(ids), "folds": len(ids) * len(config["seeds"]),
                "model_condition_seed_id_combinations": len(combined), "freeze_sha256": lock_sha,
                "all_heldout_windows_checked": True, "threshold_transfer_checked": True,
                "split_isolation_checked": True, "errors_and_alarm_rules_recomputed": True,
                "calibration_choice_checked": True, "source_fold_hashes": evidence}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    primary = condition(config["primary_interval_s"], config["primary_delay_s"])
    shown = summary[summary.condition.eq(primary)].set_index("model")
    comparison = paired[paired.condition.eq(primary) & paired.baseline.eq("feedback_history_hgb") & paired.comparison.eq("feedback_motion_hgb")].set_index("metric")
    lines = [f"# {dataset} 低频反馈可行性结果", "", "日期：2026-10-19。探索性分析，主条件为每 30 秒请求、3 秒设定传输延迟。", "",
             f"完整完成 {manifest['folds']} 个编号/种子折、{len(combined)} 个模型/条件/编号/种子组合。", "",
             "| 方法 | 原生峰值 MAE | 可用动作召回 | 误警/分钟 | 动作占用 |", "|---|---:|---:|---:|---:|"]
    for name in MODELS:
        row = shown.loc[name]
        lines.append(f"| {name} | {row.mae:.4f} | {row.usable_recall:.2%} | {row.false_alarms_per_min:.4f} | {row.occupied_fraction:.2%} |")
    lines += ["", "## 运动相对评分历史的配对差值", ""]
    for metric in ("mae", "usable_recall", "false_alarms_per_min", "occupied_fraction"):
        row = comparison.loc[metric]
        lines.append(f"- {metric}: {row.difference:.6f}，描述性 95% 区间 [{row.ci_low:.6f}, {row.ci_high:.6f}]，配对编号 n={int(row.identifiers)}。")
    lines += ["", "差值为运动增强减评分历史；MAE/误警/占用越低越好，召回越高越好。",
              "先在编号内平均种子，再在编号间宏平均。无事件编号召回为 NA；区间以编号为重采样单位。",
              "其他 8 条件的阈值沿用主条件校准结果，逐条件结果见 summary.csv，逐折预算超限见 budget_transfer.csv。",
              "评分保持基线只使用最近已到达报告；恒定预测不提前预测加重，固定不报警。",
              "原始评分轨迹不随模拟动作改变，结果不构成负担降低、真实头显时延或症状减缓证据。"]
    (output / "report_zh.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    figure(summary, output, dataset)
    return manifest


def figure(summary, output, dataset):
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.5), sharex=True, sharey="row")
    colors = ["#666666", "#2671ac", "#c35b21"]
    for j, delay in enumerate((0, 3, 6)):
        for name, color in zip(MODELS, colors):
            points = summary[summary.model.eq(name)].copy()
            points = points[points.condition.str.endswith(f"_d{delay}")]
            points["interval"] = points.condition.str.extract(r"i(\d+)").astype(int).to_numpy()
            points = points.sort_values("interval")
            axes[0, j].plot(points.interval, points.mae, "o-", color=color, label=name)
            axes[1, j].plot(points.interval, points.usable_recall * 100., "o-", color=color)
        axes[0, j].set_title(f"Report transmission delay: {delay} s")
        axes[1, j].set_xlabel("Simulated report interval (s)")
        axes[1, j].set_xticks([15, 30, 60])
        for ax in axes[:, j]:
            ax.grid(alpha=.25)
            ax.spines[["right", "top"]].set_visible(False)
    axes[0, 0].set_ylabel("Future peak MAE (native scale)")
    axes[1, 0].set_ylabel("Usable action recall (%)")
    axes[1, 0].set_ylim(0, max(1., float(summary.usable_recall.max()) * 100. * 1.15))
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=9)
    fig.suptitle(f"{dataset}: simulated feedback; ID macro means after seed averaging", fontsize=12)
    fig.text(.5, .055, "Action thresholds calibrated at 30 s / 3 s and transferred unchanged. No symptom-mitigation estimate.", ha="center", fontsize=8)
    fig.tight_layout(rect=[0, .1, 1, .95])
    fig.savefig(output / "feedback_conditions.png", dpi=180)
    fig.savefig(output / "feedback_conditions.pdf")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, default=Path("analysis/runs/feedback_v4_original_complete"))
    parser.add_argument("--secondary-parts", nargs="+", default=["7=analysis/runs/feedback_v4_secondary_complete", "19=analysis/runs/feedback_v4_secondary_s19", "42=analysis/runs/feedback_v4_secondary_s42"])
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    config = json.loads((root / "analysis/configs/feedback_v4.json").read_text(encoding="utf-8"))
    lock_path = root / "research/results/feedback_v4_lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    for path, digest in lock["source_sha256"].items():
        if sha256(root / path) != digest:
            raise ValueError("Frozen source changed before reporting: " + path)
    for dataset, frozen in lock["data"].items():
        if sha256(root / frozen["path"]) != frozen["sha256"]:
            raise ValueError("Frozen prepared input changed before reporting")
        if sha256(root / f"research/results/feedback_v4_audit/{dataset}/summary.json") != frozen["audit_summary_sha256"]:
            raise ValueError("Frozen audit summary changed before reporting")
    mappings = {int(pair.split("=", 1)[0]): root / pair.split("=", 1)[1] for pair in args.secondary_parts}
    manifests = []
    for dataset, folders in (("original", {seed: root / args.original for seed in config["seeds"]}), ("secondary", mappings)):
        audit_report(root, dataset)
        manifests.append(collect(root, dataset, folders, root / f"research/results/feedback_v4_{dataset}", config, sha256(lock_path)))
    final = {"status": "complete", "date": "2026-10-19", "folds": sum(m["folds"] for m in manifests),
             "model_condition_seed_id_combinations": sum(m["model_condition_seed_id_combinations"] for m in manifests),
             "reporting_source_sha256": sha256(Path(__file__)), "freeze_sha256": sha256(lock_path),
             "scope": "simulated report availability; public data secondary analysis; no new human study"}
    (root / "research/results/feedback_v4_completion.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
    print(json.dumps(final), flush=True)
