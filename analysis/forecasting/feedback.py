"""Audited, simulated report availability; never reconstruct actual button events."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .dataset import POSE_COLUMNS, hmd_features, read_table, sha256
from .secondary import MOTION, identity, read_recording


META = ["subject", "session", "timestamp_s", "feature_start_s", "feature_end_s",
        "forecast_end_s", "current_rating", "future_peak", "event", "event_time_s",
        "quality", "data_kind"]
FEEDBACK_COLUMNS = ["fb_last", "fb_previous", "fb_previous2", "fb_age_s",
                    "fb_previous_age_s", "fb_previous2_age_s", "fb_slope_per_s",
                    "fb_previous_slope_per_s", "fb_delta", "fb_reports_received",
                    "fb_since_arrival_s", "feedback_interval_s", "feedback_delay_s", "timestamp_s"]


def condition(interval, delay):
    return f"i{int(interval)}_d{int(delay)}"


def sequence_digest(times, values):
    array = np.column_stack((np.asarray(times) - times[0], values)).astype("<f8")
    return hashlib.sha256(array.tobytes()).hexdigest()


def rating_statistics(times, ratings):
    times, ratings = np.asarray(times, float), np.asarray(ratings, float)
    dt = np.diff(times)
    changed = np.r_[True, np.diff(ratings) != 0]
    change_times = times[changed]
    holds = np.diff(np.r_[change_times, times[-1]])
    return {
        "rating_rows": len(times), "rating_first_s": float(times[0]),
        "rating_last_s": float(times[-1]), "rating_median_interval_s": float(np.median(dt)),
        "rating_p95_interval_s": float(np.quantile(dt, .95)), "rating_max_gap_s": float(dt.max()),
        "stored_value_changes": int(changed.sum() - 1),
        "stored_unchanged_fraction": float((~changed[1:]).mean()),
        "hold_median_s": float(np.median(holds)), "hold_max_s": float(holds.max()),
        "observed_change_median_interval_s": float(np.median(np.diff(change_times))) if len(change_times) > 1 else None,
        "rating_min": float(np.min(ratings)), "rating_max": float(np.max(ratings)),
    }


def source_records(root, dataset, config):
    """Read rating/motion provenance only; no new EEG preprocessing."""
    records, streams, attrs = [], {}, {}
    if dataset == "secondary":
        paths = sorted((root / "data/raw/ryu2026/Dataset").glob("*.csv"))
    else:
        paths = sorted((root / "data/raw/juliete").rglob("*_SubjectiveCs.csv"))
    prior_audit = json.loads((root / "data/processed/public_h6.audit.json").read_text(encoding="utf-8"))
    original_prior = {r["recording"]: r for r in prior_audit["recordings"]}
    secondary_prior = pd.read_csv(root.parent / "research/results/secondary_audit/recording_audit.csv")
    secondary_status = secondary_prior.set_index("file").to_dict("index")
    native = config["datasets"][dataset]
    for path in paths:
        session = path.stem if dataset == "secondary" else path.stem.removesuffix("_SubjectiveCs")
        subject = session.split("_", 1)[0]
        item = {"dataset": dataset, "subject": subject, "session": session, "file": path.name,
                "file_sha256": sha256(path), "status": "candidate", "reason": ""}
        try:
            if not re.fullmatch(r"PA\d+" if dataset == "secondary" else r"\d{4}", subject):
                raise ValueError("unconfirmed_author_identifier")
            if dataset == "secondary":
                full = read_recording(path)
                item["rows_full"] = len(full)
                # Identity auditing covers all observed static attributes, not just motion exposure.
                try:
                    observed = identity(full)
                    attrs.setdefault(subject, set()).add(observed)
                except ValueError:
                    attrs.setdefault(subject, set()).add(("INVALID", -1., -1.))
                    raise ValueError("identity_attributes_unconfirmed_or_changed")
                frame = full.iloc[:native["max_rows"]]
                raw_t = frame.time_s.to_numpy(float)
                values = frame.rating.to_numpy(float)
                motion = frame[MOTION].to_numpy(float)
                item["numeric_missing_rows"] = int((~np.isfinite(frame.iloc[:, :8].to_numpy(float))).any(axis=1).sum())
                item["static_missing_cells_full"] = int(full[["age", "mssq"]].isna().sum().sum() + full.gender.isin(["nan", "", "none"]).sum())
                item["time_origin_s"] = float(raw_t[0])
                item["raw_nonincreasing_steps"] = int((np.diff(raw_t) <= 0).sum())
                t = raw_t - raw_t[0]
                item["content_sha256"] = sequence_digest(raw_t, np.column_stack((values, motion)))
                prior = secondary_status.get(path.name, {})
                item["prior_status"] = prior.get("status", "not_in_prior_audit")
                item["prior_reason"] = prior.get("reason", "")
                if prior.get("sha256") != item["file_sha256"]:
                    raise ValueError("raw_record_changed_since_pinned_audit")
            else:
                raw = pd.read_csv(path)
                item["rows_full"] = len(raw)
                item["raw_nonincreasing_steps"] = int((pd.to_numeric(raw.Millis).diff() <= 0).sum())
                frame = read_table(path, duplicate_last=True, startup_eeg_rate=300., startup_limit_s=5.)
                hmd_path = path.with_name(session + "_Transforms.csv")
                hmd = read_table(hmd_path, duplicate_last=True, startup_eeg_rate=300., startup_limit_s=5.)
                t, values = frame.time_s.to_numpy(float), frame.Rating.to_numpy(float)
                item["numeric_missing_rows"] = int((~np.isfinite(values)).sum())
                item["discarded_startup_rating_rows"] = int(frame.attrs.get("discarded_startup_rows", 0))
                item["rating_duplicate_rows_removed"] = len(raw) - len(frame) - item["discarded_startup_rating_rows"]
                item["motion_file_sha256"] = sha256(hmd_path)
                rating_sig = sequence_digest(t, values[:, None])
                motion_sig = sequence_digest(hmd.time_s.to_numpy(float), hmd[POSE_COLUMNS].to_numpy(float))
                item["content_sha256"] = hashlib.sha256((rating_sig + motion_sig).encode()).hexdigest()
                prior = original_prior.get(session, {})
                item["prior_status"] = prior.get("status", "not_in_prior_audit")
                item["prior_reason"] = prior.get("reason", "")
                if not prior.get("forecast_windows", 0):
                    item["prior_status"] = "no_retained_forecast_windows"
                expected = prior.get("files", {}).get(path.name)
                if expected is not None and expected != item["file_sha256"]:
                    raise ValueError("raw_rating_changed_since_prior_preparation")
                expected_motion = prior.get("files", {}).get(hmd_path.name)
                if expected_motion is not None and expected_motion != item["motion_file_sha256"]:
                    raise ValueError("raw_motion_changed_since_prior_preparation")
            if len(t) < 2 or not np.isfinite(t).all() or (np.diff(t) <= 0).any():
                raise ValueError("invalid_analysis_clock")
            if not np.isfinite(values).all() or (values < 0).any() or (values > native["scale_max"]).any():
                raise ValueError("invalid_native_rating_or_missing_rating")
            item.update(rating_statistics(t, values))
            streams[session] = (t, values, motion if dataset == "secondary" else hmd)
        except (ValueError, KeyError, OSError, pd.errors.ParserError) as error:
            item.update(status="excluded", reason=str(error))
        records.append(item)
    ambiguous = {s for s, values in attrs.items() if len(values) != 1 or any(v[0] == "INVALID" for v in values)}
    signatures = {}
    for item in records:
        if item["status"] == "candidate":
            signatures.setdefault(item["content_sha256"], []).append(item)
    alias_ids = set()
    for items in signatures.values():
        if len({r["subject"] for r in items}) > 1:
            alias_ids.update(r["subject"] for r in items)
    seen = {}
    for item in records:
        if item["subject"] in ambiguous:
            item.update(status="excluded", reason="conflicting_or_unconfirmed_identity_for_PA_identifier")
        elif item["subject"] in alias_ids:
            item.update(status="excluded", reason="cross_identifier_exact_content_duplicate")
        elif item["status"] == "candidate":
            if item["content_sha256"] in seen:
                item.update(status="excluded", reason="within_identifier_exact_content_duplicate", duplicate_of=seen[item["content_sha256"]])
            elif item["prior_status"] not in ("included", "ok"):
                item.update(status="excluded", reason="outside_frozen_v3_candidate_cohort")
            else:
                seen[item["content_sha256"]] = item["session"]
                item["status"] = "included"
    return records, streams, {"conflicting_identifiers": sorted(ambiguous), "cross_identifier_exact_duplicate_groups": sorted(alias_ids)}


def simulated_reports(times, values, interval, delay, max_sample_age):
    requested = np.arange(times[0], times[-1] + 1e-8, interval)
    positions = np.searchsorted(times, requested + 1e-9, side="right") - 1
    valid = (positions >= 0) & (requested - times[np.maximum(positions, 0)] <= max_sample_age + 1e-8)
    return pd.DataFrame({"request_s": requested[valid], "sample_s": times[positions[valid]],
                         "arrival_s": requested[valid] + delay, "value": values[positions[valid]]}), int((~valid).sum())


def add_feedback(base, reports, interval, delay):
    t = base.timestamp_s.to_numpy(float)
    arrivals = reports.arrival_s.to_numpy(float)
    idx = np.searchsorted(arrivals, t + 1e-9, side="right") - 1
    out = base.copy()
    out["feedback_interval_s"], out["feedback_delay_s"] = interval, delay
    out["condition"] = condition(interval, delay)
    out["feedback_available"] = idx >= 0
    sample = reports.sample_s.to_numpy(float)
    values = reports.value.to_numpy(float)
    for lag, suffix in ((0, "last"), (1, "previous"), (2, "previous2")):
        k = np.maximum(idx - lag, 0)
        out["fb_" + suffix] = np.where(idx >= lag, values[k], np.nan)
        age_name = "fb_age_s" if lag == 0 else f"fb_{suffix}_age_s"
        out[age_name] = np.where(idx >= lag, t - sample[k], np.nan)
    latest = np.maximum(idx, 0)
    out["fb_request_s"] = np.where(idx >= 0, reports.request_s.to_numpy(float)[latest], np.nan)
    out["fb_sample_s"] = np.where(idx >= 0, sample[latest], np.nan)
    out["fb_arrival_s"] = np.where(idx >= 0, arrivals[latest], np.nan)
    out["fb_since_arrival_s"] = t - out.fb_arrival_s
    out["fb_reports_received"] = np.maximum(idx + 1, 0)
    out["fb_delta"] = out.fb_last - out.fb_previous
    denominator = out.fb_previous_age_s - out.fb_age_s
    out["fb_slope_per_s"] = np.divide(out.fb_delta, denominator, out=np.zeros(len(out)), where=denominator.to_numpy() > 0)
    denominator = out.fb_previous2_age_s - out.fb_previous_age_s
    out["fb_previous_slope_per_s"] = np.divide(out.fb_previous - out.fb_previous2, denominator,
                                               out=np.zeros(len(out)), where=denominator.to_numpy() > 0)
    return out


def confirm_targets(base, times, values, native):
    left = np.searchsorted(times, base.timestamp_s.to_numpy(), side="right") - 1
    right = np.searchsorted(times, base.forecast_end_s.to_numpy(), side="right") - 1
    if (left < 0).any() or (right < left).any():
        raise ValueError("prepared_windows_outside_rating_support")
    for n, row in enumerate(base.itertuples()):
        current = values[left[n]]
        future = values[left[n] + 1:right[n] + 1]
        peak = max(current, float(future.max()))
        crossings = np.flatnonzero(future >= current + native["event_delta"] - 1e-8)
        gaps = np.diff(np.r_[row.timestamp_s, times[left[n] + 1:right[n] + 1], row.forecast_end_s])
        if (row.timestamp_s - times[left[n]] > native["rating_max_gap_s"] + 1e-8 or
                row.forecast_end_s - times[right[n]] > native["rating_max_gap_s"] + 1e-8 or
                gaps.max() > native["rating_max_gap_s"] + 1e-8):
            raise ValueError("prepared_target_spans_rating_gap")
        actual_event = bool(len(crossings))
        if not np.isclose(current, row.current_rating, atol=1e-8) or not np.isclose(peak, row.future_peak, atol=1e-8):
            raise ValueError("prepared_target_disagrees_with_raw_ratings")
        if actual_event != bool(row.event):
            raise ValueError("prepared_event_disagrees_with_raw_ratings")
        if actual_event and not np.isclose(times[left[n] + 1 + crossings[0]], row.event_time_s, atol=1e-8):
            raise ValueError("prepared_event_clock_disagrees_with_raw_ratings")


def confirm_motion(base, times, motion, dataset):
    """Recompute every selected historical motion feature from raw samples."""
    for row in base.to_dict("records"):
        for lag in range(3):
            end = row["timestamp_s"] - lag * 3.
            if dataset == "secondary":
                selected = motion[(times > end - 3.) & (times <= end)]
                if not len(selected) or not np.isfinite(selected).all():
                    raise ValueError("retained_history_contains_missing_raw_motion")
                features = {}
                for i, name in enumerate(MOTION):
                    a = selected[:, i]
                    for statistic, value in (("mean", a.mean()), ("std", a.std()), ("min", a.min()), ("max", a.max())):
                        features[f"motion_{name}_{statistic}"] = value
            else:
                selected = motion[(motion.time_s > end - 3.) & (motion.time_s <= end)]
                features = hmd_features(selected)
            for name, value in features.items():
                if not np.isclose(row[f"{name}__lag{lag}"], value, rtol=1e-6, atol=1e-8):
                    raise ValueError("historical_motion_feature_disagrees_with_raw_samples")


def prepare_feedback(root, dataset, config, report):
    report.mkdir(parents=True, exist_ok=True)
    original_path = root / ("data/processed/secondary_h6.csv" if dataset == "secondary" else "data/processed/public_h6.csv")
    prior = pd.read_csv(original_path, dtype={"subject": str, "session": str})
    if dataset == "original":
        # The old feature table stores a short condition, while raw filenames
        # include the ID. Use a unique recording key rather than merging IDs.
        prior["session"] = prior.subject + "_" + prior.session
    prefix = "motion_" if dataset == "secondary" else "hmd_"
    motion_cols = [c for c in prior if c.startswith(prefix) and "__lag" in c]
    prior = prior[[*META, *motion_cols]].copy()
    if prior.duplicated(["subject", "session", "timestamp_s"]).any():
        raise ValueError("duplicate_prepared_window")
    if not np.allclose(prior.feature_end_s, prior.timestamp_s) or not np.allclose(prior.forecast_end_s - prior.timestamp_s, config["horizon_s"]):
        raise ValueError("invalid_feature_or_outcome_clock")
    records, streams, identity_audit = source_records(root, dataset, config)
    included = {r["session"] for r in records if r["status"] == "included"}
    missing_sessions = set(prior.session) - included
    base = prior[prior.session.isin(included)].copy()
    pieces, availability, reports_all = [], [], []
    native = config["datasets"][dataset]
    for session, part in base.groupby("session", sort=True):
        part = part.sort_values("timestamp_s").reset_index(drop=True)
        t, rating, motion = streams[session]
        confirm_targets(part, t, rating, native)
        confirm_motion(part, t, motion, dataset)
        scenarios, shared = [], np.ones(len(part), dtype=bool)
        for interval in config["intervals_s"]:
            for delay in config["delays_s"]:
                reports, missing_requests = simulated_reports(t, rating, interval, delay, native["rating_max_gap_s"])
                if reports.empty:
                    raise ValueError("recording_has_no_simulatable_report")
                table = add_feedback(part, reports, interval, delay)
                shared &= table.feedback_available.to_numpy()
                scenarios.append(table)
                reports_all.append(reports.assign(dataset=dataset, subject=part.subject.iloc[0], session=session,
                                                  condition=condition(interval, delay)))
                availability.append({"dataset": dataset, "subject": part.subject.iloc[0], "session": session,
                                     "condition": condition(interval, delay), "interval_s": interval, "delay_s": delay,
                                     "simulated_requests": len(reports) + missing_requests, "missing_requests": missing_requests,
                                     "reports_arrived_before_last_decision": int((reports.arrival_s <= part.timestamp_s.max()).sum()),
                                     "windows_without_initial_report": int((~table.feedback_available).sum())})
        pieces.extend(s.loc[shared].copy() for s in scenarios)
    frame = pd.concat(pieces, ignore_index=True)
    if frame.empty or frame.subject.nunique() < 5:
        raise ValueError("insufficient_verified_identifiers")
    if ((frame.fb_sample_s > frame.fb_request_s + 1e-8) |
            (frame.fb_request_s > frame.fb_arrival_s + 1e-8) |
            (frame.fb_arrival_s > frame.timestamp_s + 1e-8)).any():
        raise ValueError("feedback_availability_violation")
    if not np.isfinite(frame[motion_cols]).all().all():
        raise ValueError("missing_motion_in_retained_causal_windows")
    expected_conditions = len(config["intervals_s"]) * len(config["delays_s"])
    keys = ["subject", "session", "timestamp_s"]
    if not (frame.groupby(keys).size() == expected_conditions).all():
        raise ValueError("unequal_comparison_windows")
    # No rating/imputed future values are added to the motion allowlist.
    if set(FEEDBACK_COLUMNS + motion_cols) & {"current_rating", "future_peak", "event", "event_time_s"}:
        raise ValueError("outcome_in_feature_allowlist")
    local = root / "data/processed/feedback_v4"
    local.mkdir(parents=True, exist_ok=True)
    output = local / f"{dataset}.csv"
    frame.to_csv(output, index=False)
    pd.concat(reports_all, ignore_index=True).to_csv(local / f"{dataset}_simulated_reports.csv", index=False)
    audit = pd.DataFrame(records)
    audit.to_csv(report / "recordings.csv", index=False)
    audit[audit.status != "included"].to_csv(report / "exclusions.csv", index=False)
    pd.DataFrame(availability).to_csv(report / "availability.csv", index=False)
    primary = frame[(frame.feedback_interval_s == config["primary_interval_s"]) & (frame.feedback_delay_s == config["primary_delay_s"])]
    counts = primary.groupby("subject").agg(recordings=("session", "nunique"), windows=("timestamp_s", "size"),
                                             positive_windows=("event", "sum"), feedback_age_median_s=("fb_age_s", "median"))
    counts.to_csv(report / "identifier_counts.csv")
    conditions = frame.groupby("condition").agg(windows=("timestamp_s", "size"), mean_feedback_age_s=("fb_age_s", "mean"),
                                                 max_feedback_age_s=("fb_age_s", "max"), mean_reports_received=("fb_reports_received", "mean"))
    conditions.to_csv(report / "condition_availability.csv")
    summary = {"dataset": dataset, "raw_records_audited": len(records), **identity_audit,
               "included_recordings": int(primary.session.nunique()), "included_identifiers": int(primary.subject.nunique()),
               "windows_per_condition": len(primary), "condition_rows": len(frame), "conditions": expected_conditions,
               "prior_windows": len(prior), "prior_sessions_removed_by_new_audit": sorted(missing_sessions),
               "prepared_source_sha256": sha256(original_path), "output_sha256": sha256(output),
               "motion_columns": motion_cols, "feedback_columns": FEEDBACK_COLUMNS,
               "exclusion_reasons": audit.loc[audit.status != "included", "reason"].value_counts().to_dict(),
               "target_recomputed_from_raw": True, "motion_recomputed_from_raw": True, "availability_violations": 0,
               "actual_report_events_available": False,
               "identity_limit": "author identifiers; cross-ID aliases not independently ruled out",
               "feedback_limit": "simulated availability of stored ratings; no measured burden or report response delay"}
    (report / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
