"""Causal motion-only adapter for the author-published Ryu/Kim CSV snapshot.

FMS is a target on its native scale, never an input. No identity is inferred
from row order, demographics, or a timestamp reset.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import numpy as np
import pandas as pd

COLUMNS = ["time_s", "rating", "ax", "ay", "az", "wx", "wy", "wz", "gender", "mssq", "age"]
MOTION = COLUMNS[2:8]

def read_recording(path):
    frame = pd.read_csv(path, header=None)
    if frame.shape[1] != 11:
        raise ValueError("expected_11_headerless_columns")
    frame.columns = COLUMNS
    frame["gender"] = frame.gender.astype(str).str.strip().str.lower()
    for name in COLUMNS:
        if name != "gender":
            frame[name] = pd.to_numeric(frame[name], errors="coerce")
    return frame

def identity(frame):
    genders = set(frame.gender.dropna()) - {"nan", "", "none"}
    ages = {round(float(x), 6) for x in frame.age.dropna()}
    scores = {round(float(x), 6) for x in frame.mssq.dropna()}
    if not genders or not ages or not scores or not genders <= {"m", "f"}:
        raise ValueError("invalid_identity_attributes")
    if len(genders) != 1 or len(ages) != 1 or len(scores) != 1:
        raise ValueError("identity_changes_within_recording")
    age, score = next(iter(ages)), next(iter(scores))
    if not np.isfinite(age) or not np.isfinite(score):
        raise ValueError("invalid_identity_attributes")
    return next(iter(genders)), age, score

def causal_samples(frame, subject, session, settings, data_kind="public_secondary"):
    frame = frame.iloc[:settings["secondary_max_rows"]].copy()
    t = frame.time_s.to_numpy(dtype=float)
    if not np.isfinite(t).all() or (np.diff(t) <= 0).any():
        raise ValueError("nonfinite_or_nonincreasing_timestamps")
    if not np.isfinite(frame.rating).all() or not frame.rating.between(0, 20).all():
        raise ValueError("invalid_native_fms")
    origin = float(t[0])
    t = t - origin
    step, horizon, history = settings["window_s"], settings["horizon_s"], settings["history_s"]
    gap = settings["secondary_max_gap_s"]
    windows = {}
    for end in np.arange(step, t[-1] + 1e-8, step):
        idx = np.flatnonzero((t > end - step) & (t <= end))
        selected = frame.iloc[idx]
        coverage = min(1., len(idx) / (step / .5))
        if coverage < settings["secondary_min_coverage"] or not np.isfinite(selected[MOTION]).all().all():
            continue
        if np.diff(np.r_[end - step, t[idx], end]).max() > gap:
            continue
        features = {}
        for name in MOTION:
            a = selected[name].to_numpy(dtype=float)
            for statistic, value in (("mean", a.mean()), ("std", a.std()), ("min", a.min()), ("max", a.max())):
                features[f"motion_{name}_{statistic}"] = float(value)
        windows[round(float(end), 6)] = (features, coverage)
    rows = []
    for end in sorted(windows):
        lag_times = [round(end - i * step, 6) for i in range(int(history / step))]
        if any(x not in windows for x in lag_times) or end + horizon > t[-1] + 1e-8:
            continue
        left = np.searchsorted(t, end, side="right") - 1
        right = np.searchsorted(t, end + horizon, side="right") - 1
        if left < 0 or end - t[left] > gap or end + horizon - t[right] > gap:
            continue
        if np.diff(np.r_[end, t[left + 1:right + 1], end + horizon]).max() > gap:
            continue
        current = float(frame.rating.iloc[left])
        future = frame.rating.iloc[left + 1:right + 1].to_numpy(dtype=float)
        peak = max(current, float(future.max()))
        crossings = np.flatnonzero(future >= current + settings["secondary_event_delta"] - 1e-8)
        row = {"subject": subject, "session": session, "timestamp_s": end,
               "source_origin_s": origin, "feature_start_s": end - history,
               "feature_end_s": end, "forecast_end_s": end + horizon,
               "current_rating": current, "future_peak": peak, "delta_target": peak-current,
               "event": int(bool(len(crossings))),
               "event_time_s": float(t[left + 1 + crossings[0]]) if len(crossings) else np.nan,
               "quality": min(windows[x][1] for x in lag_times), "data_kind": data_kind}
        for lag, time in enumerate(lag_times):
            row.update({f"{k}__lag{lag}": v for k, v in windows[time][0].items()})
        rows.append(row)
    return pd.DataFrame(rows)

def prepare(raw: Path, output: Path, report: Path, settings):
    report.mkdir(parents=True, exist_ok=True)
    audits, loaded, attributes = [], {}, {}
    for path in sorted((raw / "Dataset").glob("*.csv")):
        match = re.match(r"^(PA\d+)_", path.name)
        item = {"file": path.name, "subject": match[1] if match else "", "status": "candidate",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        try:
            if not match:
                raise ValueError("unrecognized_subject_identifier")
            frame = read_recording(path)
            attr = identity(frame.iloc[:settings["secondary_max_rows"]])
            attributes.setdefault(match[1], set()).add(attr)
            loaded[path.name] = frame
            prefix = frame.iloc[:settings["secondary_max_rows"]]
            t = prefix.time_s.to_numpy(dtype=float)
            diffs = np.diff(t)
            r = prefix.rating.to_numpy(dtype=float)
            item.update(rows_total=len(frame), rows_prefix=len(prefix),
                        first_timestamp_s=float(t[0]), first_rating=float(r[0]),
                        duration_prefix_s=float(t[-1] - t[0]), median_interval_s=float(np.median(diffs)),
                        max_interval_s=float(diffs.max()), nonincreasing_steps=int((diffs <= 0).sum()),
                        rating_changes=int((np.diff(r) != 0).sum()),
                        unchanged_fraction=float((np.diff(r) == 0).mean()),
                        rating_min=float(np.nanmin(r)), rating_max=float(np.nanmax(r)),
                        invalid_motion_rows=int((~np.isfinite(prefix[MOTION]).all(axis=1)).sum()))
        except (ValueError, pd.errors.ParserError, IndexError) as error:
            item["status"], item["reason"] = "excluded", str(error)
        audits.append(item)
    ambiguous = {subject for subject, values in attributes.items() if len(values) > 1}
    seen = {}
    samples = []
    for item in audits:
        if item["status"] != "candidate":
            continue
        if item["subject"] in ambiguous:
            item.update(status="excluded", reason="conflicting_identity_attributes_for_PA_identifier")
            continue
        if item["sha256"] in seen:
            item.update(status="excluded", reason="byte_identical_duplicate", duplicate_of=seen[item["sha256"]])
            continue
        seen[item["sha256"]] = item["file"]
        try:
            rows = causal_samples(loaded[item["file"]], item["subject"], Path(item["file"]).stem, settings)
            item["windows"] = len(rows)
            item["positive_windows"] = int(rows.event.sum()) if len(rows) else 0
            if rows.empty:
                raise ValueError("no_complete_causal_forecast_windows")
            item["status"] = "included"
            samples.append(rows)
        except ValueError as error:
            item.update(status="excluded", reason=str(error))
    table = pd.concat(samples, ignore_index=True) if samples else pd.DataFrame()
    audit = pd.DataFrame(audits)
    audit.to_csv(report / "recording_audit.csv", index=False)
    (report / "identity_conflicts.json").write_text(json.dumps({s: sorted(attributes[s]) for s in sorted(ambiguous)}, indent=2), encoding="utf-8")
    included = audit[audit.status == "included"]
    summary = {"files": len(audit), "PA_identifiers": int(audit.subject.nunique()),
               "ambiguous_PA_identifiers": len(ambiguous), "included_recordings": len(included),
               "included_subjects": int(table.subject.nunique()) if len(table) else 0,
               "windows": len(table), "positive_windows": int(table.event.sum()) if len(table) else 0,
               "rating_scale": "native author FMS 0-20; recorded values, on-demand updates",
               "identity_assumption": "PA identifier with consistent gender/age/MSSQ; real identity not independently verified",
               "exclusion_reasons": audit.loc[audit.status == "excluded", "reason"].value_counts().to_dict(),
               "settings": settings, "acquisition": json.loads((raw / "acquisition_manifest.json").read_text(encoding="utf-8"))}
    output.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output, index=False)
    summary["prepared_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    (report / "audit_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    text = ["# 第二公开数据集审计", "", f"固定提交：`{summary['acquisition']['commit']}`。保留无表头 CSV 的第一行，使用前 420 个数据行。", "",
            f"428 份源 CSV 中，纳入 {len(included)} 段记录、{summary['included_subjects']} 个身份属性一致的 PA 编号，形成 {len(table)} 个窗口、{summary['positive_windows']} 个恶化正窗口。", "",
            f"发现 {len(ambiguous)} 个 PA 编号存在性别/年龄/MSSQ 冲突，整组排除；详见 recording_audit.csv 与 identity_conflicts.json。", "",
            "PA 编号是原作者标识，无法核实真实身份或不同编号是否有同一人的别名。属性一致是本研究的纳入规则，不构成身份认证。", "",
            "评分保留原生 FMS 单位；每约 0.5 秒的记录不代表独立自报。相邻相同评分可能是保持，也可能是重复报告，数据没有报告按钮事件，不能区分。", "",
            "过去 9 秒运动统计为输入，每 3 秒预测未来 6 秒内相对当前评分增加至少 1 分。当前评分只用于训练/评估标签，不作为被动模型输入。", "",
            "样本完整度使用名义 2 Hz 计算，历史各段覆盖至少 80%，采样/评分记录间隙最大 1.5 秒。时间重置记录整段排除，不排序拼接。", "",
            "这是另一数据源上的独立训练评估；场景运动不等于第一数据源的头动，不是冻结模型跨数据集迁移，也不验证 EEG 的增益或减缓效果。", "",
            "## 排除原因", ""]
    text += [f"- {reason}: {count}" for reason, count in summary["exclusion_reasons"].items()]
    (report / "audit_zh.md").write_text("\n".join(text)+"\n", encoding="utf-8")
    return summary
