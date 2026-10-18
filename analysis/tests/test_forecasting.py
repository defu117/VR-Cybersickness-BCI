from dataclasses import replace
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forecasting.config import Protocol
from forecasting.dataset import process_recording, add_history_and_targets, CHANNELS
from forecasting.evaluation import apply_warning_policy, feature_columns, split_subjects, calibration_radius
from forecasting.replay import export_replay
from forecasting.alerts import score_alerts


def raw_recording(directory, *, changed_future=False):
    fs, duration = 100, 60
    t = np.arange(fs * duration) / fs
    values = np.stack([np.sin(2 * np.pi * (6 + i / 10) * t) for i in range(24)], axis=1)
    if changed_future:
        values[t > 30] *= 10000
    eeg = pd.DataFrame(values, columns=[f"ch_{i + 1}" for i in range(24)])
    eeg.insert(0, "Millis", t * 1000)
    ht = np.arange(0, duration, .1)
    hmd = pd.DataFrame({"Millis": ht * 1000, "HeadPosition_X": ht / 10,
                        "HeadPosition_Y": 0, "HeadPosition_Z": 0,
                        "HeadRotation_Yaw": ht * 2, "HeadRotation_Pitch": 0, "HeadRotation_Roll": 0})
    if changed_future:
        hmd.loc[ht > 30, "HeadPosition_X"] += 10000
    ratings = pd.DataFrame({"Millis": ht * 1000, "Rating": np.clip((ht - 20) / 50, 0, 1)})
    paths = [directory / f"0001_FN_{name}.csv" for name in ("EEG", "Transforms", "SubjectiveCs")]
    for path, data in zip(paths, (eeg, hmd, ratings)):
        data.to_csv(path, index=False)
    return paths


def test_future_signal_changes_do_not_modify_earlier_features(tmp_path):
    cfg = replace(Protocol(), max_eeg_gap_s=.11)
    paths = raw_recording(tmp_path)
    before_tensors = []
    first, _ = process_recording(*paths, cfg, fs=100, data_kind="synthetic", tensor_sink=before_tensors)
    paths = raw_recording(tmp_path, changed_future=True)
    after_tensors = []
    second, _ = process_recording(*paths, cfg, fs=100, data_kind="synthetic", tensor_sink=after_tensors)
    names = feature_columns(first, "fusion")
    before = first.timestamp_s <= 30
    np.testing.assert_array_equal(first.loc[before, names], second.loc[second.timestamp_s <= 30, names])
    for i in np.flatnonzero(before.to_numpy()):
        np.testing.assert_array_equal(before_tensors[i][0], after_tensors[i][0])
        np.testing.assert_array_equal(before_tensors[i][1], after_tensors[i][1])
    assert (first.feature_end_s == first.timestamp_s).all()
    assert (first.forecast_end_s - first.timestamp_s == 6).all()
    assert len(first) > 0


def test_labels_respect_horizon_and_do_not_bridge_rating_gaps():
    base = pd.DataFrame({"subject": "0001", "session": "FN", "window_start_s": np.arange(0, 30, 3),
                         "timestamp_s": np.arange(3, 33, 3), "quality": 1, "data_kind": "synthetic",
                         "eeg_test": np.arange(10), "hmd_test": np.arange(10)})
    rt = np.r_[np.arange(0, 13, .5), np.arange(22, 40, .5)]
    ratings = pd.DataFrame({"time_s": rt, "Rating": np.where(rt >= 11, .4, 0)})
    rows = add_history_and_targets(base, ratings, Protocol())
    row = rows[rows.timestamp_s == 24].iloc[0]
    assert row.current_rating == .4 and row.future_peak == .4 and row.event == 0
    assert not rows.timestamp_s.isin([9, 12, 15, 18, 21]).any()


def test_named_channels_and_startup_preroll_are_handled_without_sorting(tmp_path):
    paths = raw_recording(tmp_path)
    expected, _ = process_recording(*paths, Protocol(), fs=100, data_kind="synthetic")
    for path in paths:
        data = pd.read_csv(path)
        if path.name.endswith("_EEG.csv"):
            data = data.rename(columns={f"ch_{i + 1}": label for i, label in enumerate(CHANNELS)})
            prefix = data.iloc[:100].copy()
        else:
            prefix = data.iloc[:10].copy()
        pd.concat([prefix, data], ignore_index=True).to_csv(path, index=False)
    actual, audit = process_recording(*paths, Protocol(), fs=100, data_kind="synthetic")
    np.testing.assert_array_equal(expected[feature_columns(expected, "fusion")], actual[feature_columns(actual, "fusion")])
    assert audit["discarded_startup_eeg_rows"] == 100
    assert audit["discarded_startup_hmd_rows"] == 10


def test_group_partition_and_feature_allowlist():
    fit, cal = split_subjects([f"{i:04}" for i in range(8)], "0001", 7, .25)
    assert not set(fit) & set(cal)
    assert "0001" not in fit + cal
    frame = pd.DataFrame(columns=["current_rating", "future_peak", "timestamp_s", "eeg_rating", "eeg_P3_alpha__lag0", "hmd_speed__lag1"])
    assert feature_columns(frame, "fusion") == ["eeg_P3_alpha__lag0", "hmd_speed__lag1"]
    assert calibration_radius([.1, .2, .3, .4], .2) == .4


def test_warning_counts_distinct_windows_and_resets_at_gaps():
    frame = pd.DataFrame({"subject": "s", "session": "a", "timestamp_s": [3, 6, 9, 30, 33],
                         "delta_lower": .2, "delta_pred": .2, "quality": 1})
    assert apply_warning_policy(frame, Protocol()).tolist() == [0, 1, 0, 0, 1]
    frame.loc[1, "quality"] = 0
    assert apply_warning_policy(frame, Protocol()).tolist() == [0, 0, 0, 0, 1]


def test_budget_rule_reads_only_scores_and_available_metadata():
    frame = pd.DataFrame({"subject": "s", "session": "a", "timestamp_s": [3, 6, 18, 21],
                         "quality": [1, 1, 1, 0], "event": [0, 0, 0, 0]})
    expected = score_alerts(frame, [.9, .9, .9, .9], .5)
    frame["event"] = 1
    frame["future_label"] = 99
    np.testing.assert_array_equal(expected, score_alerts(frame, [.9, .9, .9, .9], .5))
    assert expected.tolist() == [1, 0, 1, 0]


def test_replay_keeps_one_trajectory_and_preserves_stream_gaps(tmp_path):
    frame = pd.DataFrame({"subject": "0001", "session": "FN", "model": "fusion_cqr", "seed": 7,
                         "timestamp_s": [6., 9., 30.], "quality": 1, "alarm_gated": [0, 1, 0], "data_kind": "synthetic"})
    path = tmp_path / "replay.csv"
    export_replay(frame, path, subject="0001", session="FN", model="fusion_cqr", seed=7)
    rows = pd.read_csv(path)
    assert rows.timestamp_s.is_monotonic_increasing
    assert (rows.risk == .7).any()
    assert rows.timestamp_s.diff().max() > 2
    assert set(rows.source) == {"forecast_synthetic_gated"}
    with pytest.raises(ValueError):
        export_replay(frame, path, subject="0002", session="FN", model="fusion_cqr", seed=7)


def test_changing_heldout_targets_cannot_change_its_forecast(tmp_path):
    from forecasting.evaluation import run_experiment
    from threadpoolctl import threadpool_limits
    cfg = Protocol()
    rows = []
    for subject in range(5):
        for i in range(12):
            t = 15 + 3 * i
            current = .1 + .01 * i
            rows.append({"subject": f"{subject:04}", "session": "TEST", "timestamp_s": t,
                         "feature_start_s": t - 9, "feature_end_s": t, "forecast_end_s": t + 6,
                         "current_rating": current, "future_peak": current + .1, "delta_target": .1,
                         "event": 1, "event_time_s": t + 5, "quality": 1, "data_kind": "synthetic",
                         "protocol_hash": cfg.fingerprint, "eeg_a__lag0": i / 10, "hmd_a__lag0": i / 11})
    frame = pd.DataFrame(rows)
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    frame.to_csv(first, index=False)
    frame.loc[frame.subject == "0000", ["future_peak", "delta_target"]] = [.9, .8]
    frame.to_csv(second, index=False)
    with threadpool_limits(limits=1):
        a = run_experiment(first, tmp_path / "a", cfg, seeds=[7], models=["fusion_cqr"])
        b = run_experiment(second, tmp_path / "b", cfg, seeds=[7], models=["fusion_cqr"])
    names = ["future_pred", "delta_pred", "delta_lower", "delta_upper"]
    np.testing.assert_array_equal(a.loc[a.subject == "0000", names], b.loc[b.subject == "0000", names])
