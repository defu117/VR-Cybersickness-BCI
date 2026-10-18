"""Availability-time windows; no future interpolation or two-pass filtering."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd
from scipy import signal
from scipy.signal.windows import dpss

from .config import Protocol

# Published DSI-24 ordering; primary analysis excludes auxiliary/reference leads.
CHANNELS = "P3 C3 F3 Fz F4 C4 P4 Cz Pz A1 Fp1 Fp2 T3 T5 O1 O2 X3 X2 F7 F8 X1 A2 T6 T4".split()
SCALP_INDEX = [i for i, name in enumerate(CHANNELS) if name not in {"A1", "A2", "X1", "X2", "X3"}]
POSE_COLUMNS = ["HeadPosition_X", "HeadPosition_Y", "HeadPosition_Z", "HeadRotation_Yaw", "HeadRotation_Pitch", "HeadRotation_Roll"]
BANDS = (("delta", 1, 4), ("theta", 4, 8), ("alpha", 8, 13), ("beta", 13, 30), ("gamma", 30, 40))


def sha256(path: Path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read_table(path: Path, *, duplicate_last: bool = False, startup_eeg_rate=None, startup_limit_s=5.0):
    frame = pd.read_excel(path) if path.suffix.lower() == ".xlsx" else pd.read_csv(path)
    if "Millis" not in frame:
        raise ValueError(f"{path.name}: missing Millis clock")
    frame = frame.apply(pd.to_numeric, errors="coerce")
    if len(frame) < 2 or not np.isfinite(frame.Millis).all():
        raise ValueError(f"{path.name}: empty/invalid clock")
    resets = np.flatnonzero(frame.Millis.diff().to_numpy() < 0)
    discarded = 0
    if len(resets):
        last = int(resets[-1])
        if (startup_eeg_rate is not None and last <= startup_eeg_rate * startup_limit_s and
                frame.Millis.iloc[:last].max() <= startup_limit_s * 1000 and frame.Millis.iloc[last] <= 1000):
            # Discard the short buffered pre-roll preceding the trial clock.
            # Never sort samples across a reset or guess a clock offset.
            frame = frame.iloc[last:].reset_index(drop=True)
            discarded = last
        else:
            raise ValueError(f"{path.name}: non-startup clock reset; split into recordings before analysis")
    frame["time_s"] = frame.Millis.to_numpy(dtype=float) / 1000
    if duplicate_last:
        frame = frame.drop_duplicates("Millis", keep="last")
    frame = frame.reset_index(drop=True)
    frame.attrs["discarded_startup_rows"] = discarded
    return frame


def causal_filter(values: np.ndarray, times: np.ndarray, fs: float, cfg: Protocol):
    """Native-rate one-pass filtering. Receipt timestamps remain unchanged."""
    if fs <= 2 * cfg.high_hz:
        raise ValueError("EEG sampling rate cannot represent the configured band")
    clean = pd.DataFrame(values).ffill().fillna(0).to_numpy()
    sos = signal.butter(4, [cfg.low_hz, cfg.high_hz], btype="bandpass", fs=fs, output="sos")
    if cfg.notch_hz < fs / 2:
        b, a = signal.iirnotch(cfg.notch_hz, 30, fs=fs)
        sos = np.concatenate((signal.tf2sos(b, a), sos))
    output = np.empty_like(clean)
    splits = np.r_[0, np.flatnonzero(np.diff(times) > cfg.max_eeg_gap_s) + 1, len(times)]
    for lo, hi in zip(splits[:-1], splits[1:]):
        output[lo:hi] = signal.sosfilt(sos, clean[lo:hi], axis=0)
    return output


def eeg_features(segment: np.ndarray, fs: float, with_spectrum=False):
    n = len(segment)
    tapers = dpss(n, 3, Kmax=5, sym=False)
    centered = segment - segment.mean(axis=0, keepdims=True)
    spectrum = np.fft.rfft(tapers[:, :, None] * centered[None], axis=1)
    power = np.mean(np.abs(spectrum) ** 2, axis=0) / fs
    frequencies = np.fft.rfftfreq(n, 1 / fs)
    features = {}
    for index in SCALP_INDEX:
        label = CHANNELS[index]
        total = max(float(np.sum(power[(frequencies >= 1) & (frequencies < 40), index])), 1e-12)
        for band, low, high in BANDS:
            value = max(float(np.sum(power[(frequencies >= low) & (frequencies < high), index])), 1e-12)
            features[f"eeg_{label}_{band}_log"] = np.log10(value)
            features[f"eeg_{label}_{band}_rel"] = value / total
    if with_spectrum:
        grid = np.arange(151) / 3.0
        fixed = np.stack([np.interp(grid, frequencies, power[:, ch]) for ch in range(24)])
        return features, np.log10(np.maximum(fixed, 1e-12)).astype(np.float32)
    return features


def kinematic_tensor(frame):
    t = frame.time_s.to_numpy()
    pose = frame[POSE_COLUMNS].to_numpy(dtype=float)
    changes = np.vstack((np.zeros((1, 6)), np.diff(pose, axis=0)))
    norms = np.column_stack((np.linalg.norm(pose[:, :3], axis=1), np.linalg.norm(pose[:, 3:], axis=1)))
    norm_changes = np.vstack((np.zeros((1, 2)), np.diff(norms, axis=0)))
    values = np.column_stack((pose, changes, norms, norm_changes))
    grid = np.linspace(t[0], t[-1], 30)
    return np.stack([np.interp(grid, t, values[:, ch]) for ch in range(16)]).astype(np.float32)


def hmd_features(frame: pd.DataFrame):
    t = frame.time_s.to_numpy()
    pose = frame[POSE_COLUMNS].to_numpy()
    if len(t) < 3 or not np.isfinite(pose).all():
        raise ValueError("insufficient or missing head pose")
    dt = np.diff(t)
    rotation = np.unwrap(np.deg2rad(pose[:, 3:]), axis=0)
    linear = np.linalg.norm(np.diff(pose[:, :3], axis=0), axis=1) / dt
    angular = np.rad2deg(np.linalg.norm(np.diff(rotation, axis=0), axis=1)) / dt
    acceleration = np.diff(linear) / dt[1:]
    features = {}
    for name, values in (("linear_speed", linear), ("angular_speed", angular), ("acceleration", acceleration)):
        for stat, value in (("mean", np.mean(values)), ("std", np.std(values)), ("p95", np.percentile(np.abs(values), 95))):
            features[f"hmd_{name}_{stat}"] = float(value)
    return features


def add_history_and_targets(base: pd.DataFrame, ratings: pd.DataFrame, cfg: Protocol):
    """Rating columns are metadata/targets, never selected as model features."""
    rtime = ratings.time_s.to_numpy()
    rating = ratings.Rating.to_numpy(dtype=float)
    if not np.isfinite(rating).all() or np.any((rating < 0) | (rating > 1)):
        raise ValueError("Rating must be finite on the published 0-1 scale")
    feature_names = [c for c in base if c.startswith(("eeg_", "hmd_"))]
    rows = []
    for i in range(cfg.history_windows - 1, len(base)):
        history = base.iloc[i - cfg.history_windows + 1:i + 1]
        if not np.allclose(np.diff(history.timestamp_s), cfg.window_s, atol=1e-6):
            continue
        t = float(base.iloc[i].timestamp_s)
        left = np.searchsorted(rtime, t, side="right") - 1
        end = t + cfg.horizon_s
        right = np.searchsorted(rtime, end, side="right") - 1
        if left < 0 or right < left or end > rtime[-1] + 1e-8:
            continue
        if t - rtime[left] > cfg.max_rating_age_s or end - rtime[right] > cfg.max_rating_age_s:
            continue
        if np.any(np.diff(np.r_[t, rtime[left + 1:right + 1], end]) > cfg.max_rating_age_s):
            continue
        current = float(rating[left])
        peak = max(current, float(rating[left:right + 1].max()))
        crossings = np.flatnonzero(rating[left + 1:right + 1] >= current + cfg.event_delta - 1e-8)
        row = {
            "subject": str(base.iloc[i].subject), "session": str(base.iloc[i].session),
            "timestamp_s": t, "feature_start_s": float(history.iloc[0].window_start_s),
            "feature_end_s": t, "forecast_end_s": end,
            "current_rating": current, "future_peak": peak, "delta_target": peak - current,
            "event": int(peak - current >= cfg.event_delta - 1e-8),
            "event_time_s": float(rtime[left + 1 + crossings[0]]) if len(crossings) else np.nan,
            "quality": float(history.quality.min()), "data_kind": base.iloc[i].data_kind,
        }
        for lag in range(cfg.history_windows):
            source = history.iloc[-1 - lag]
            row.update({f"{name}__lag{lag}": float(source[name]) for name in feature_names})
        rows.append(row)
    return pd.DataFrame(rows)


def process_recording(eeg_path: Path, hmd_path: Path, rating_path: Path, cfg: Protocol, fs=300.0, data_kind="public", tensor_sink=None):
    eeg = read_table(eeg_path, startup_eeg_rate=fs, startup_limit_s=cfg.max_startup_eeg_s)
    hmd = read_table(hmd_path, duplicate_last=True, startup_eeg_rate=fs, startup_limit_s=cfg.max_startup_eeg_s)
    ratings = read_table(rating_path, duplicate_last=True, startup_eeg_rate=fs, startup_limit_s=cfg.max_startup_eeg_s)
    subject, session = eeg_path.stem.rsplit("_EEG", 1)[0].split("_", 1)
    expected = [f"ch_{i + 1}" for i in range(24)]
    eeg_columns = expected if set(expected).issubset(eeg) else CHANNELS
    if not set(eeg_columns).issubset(eeg):
        raise ValueError("EEG stream must contain ch_1..ch_24 or the named DSI-24 channels")
    values = eeg[eeg_columns].to_numpy(dtype=float)
    times = eeg.time_s.to_numpy()
    filtered = causal_filter(values, times, fs, cfg)
    first = np.ceil(max(times[0], hmd.time_s.iloc[0]) / cfg.window_s) * cfg.window_s
    stop = min(times[-1], hmd.time_s.iloc[-1])
    rows, skipped = [], 0
    spectra, kinematics = {}, {}
    for start in np.arange(first, stop - cfg.window_s + 1e-8, cfg.window_s):
        end = start + cfg.window_s
        lo, hi = np.searchsorted(times, [start, end], side="right")
        segment_times = times[lo:hi]
        hm = hmd[(hmd.time_s > start) & (hmd.time_s <= end)]
        coverage = min(1.0, (hi - lo) / (cfg.window_s * fs))
        finite_fraction = np.isfinite(values[lo:hi, SCALP_INDEX]).mean() if hi > lo else 0
        quality = coverage * finite_fraction
        eeg_gap = np.diff(np.r_[start, segment_times, end]).max(initial=cfg.window_s if hi == lo else 0)
        hmd_gap = np.diff(np.r_[start, hm.time_s, end]).max(initial=cfg.window_s if hm.empty else 0)
        if quality < cfg.min_quality or eeg_gap > cfg.max_eeg_gap_s or hmd_gap > cfg.max_hmd_gap_s:
            skipped += 1
            continue
        try:
            if tensor_sink is not None:
                eeg_values, spectrum = eeg_features(filtered[lo:hi], fs, with_spectrum=True)
            else:
                eeg_values = eeg_features(filtered[lo:hi], fs)
            features = {**eeg_values, **hmd_features(hm)}
        except ValueError:
            skipped += 1
            continue
        rows.append({"subject": subject, "session": session, "window_start_s": start,
                     "timestamp_s": end, "quality": quality, "data_kind": data_kind, **features})
        if tensor_sink is not None:
            spectra[round(end, 6)] = spectrum
            kinematics[round(end, 6)] = kinematic_tensor(hm)
    base = pd.DataFrame(rows)
    if len(base) < max(cfg.baseline_windows, cfg.history_windows):
        raise ValueError(f"only {len(base)} valid windows after gap/quality checks")
    baseline = base.iloc[:cfg.baseline_windows]
    if not np.allclose(np.diff(baseline.timestamp_s), cfg.window_s):
        raise ValueError("initial reference windows contain gaps")
    log_names = [c for c in base if c.startswith("eeg_") and c.endswith("_log")]
    for name in log_names:
        base[name + "_tr"] = base[name] - baseline[name].mean()
    # Reference is available only after its final window; no earlier decisions.
    base = base[base.timestamp_s >= baseline.timestamp_s.iloc[-1]].reset_index(drop=True)
    samples = add_history_and_targets(base, ratings, cfg)
    if tensor_sink is not None and len(samples):
        reference = np.mean([spectra[round(t, 6)] for t in baseline.timestamp_s], axis=0)
        for t in samples.timestamp_s:
            trailing = [spectra[round(t - lag * cfg.window_s, 6)] for lag in range(cfg.history_windows)]
            tensor_sink.append((np.mean(trailing, axis=0) - reference, kinematics[round(t, 6)]))
    audit = {
        "subject": subject, "session": session, "eeg_samples": len(eeg),
        "eeg_duplicate_receipt_times": int(eeg.Millis.duplicated().sum()),
        "discarded_startup_eeg_rows": int(eeg.attrs.get("discarded_startup_rows", 0)),
        "discarded_startup_hmd_rows": int(hmd.attrs.get("discarded_startup_rows", 0)),
        "discarded_startup_rating_rows": int(ratings.attrs.get("discarded_startup_rows", 0)),
        "hardware_clock_unique": int(eeg["HardwareSeconds" if "HardwareSeconds" in eeg else "Hardware"].nunique()) if "HardwareSeconds" in eeg or "Hardware" in eeg else None,
        "eeg_duration_s": float(times[-1] - times[0]), "sampling_rate_configured_hz": fs,
        "valid_feature_windows": len(base), "skipped_gap_quality_windows": skipped,
        "forecast_windows": len(samples), "positive_windows": int(samples.event.sum()) if len(samples) else 0,
        "rating_min": float(ratings.Rating.min()), "rating_max": float(ratings.Rating.max()),
        "files": {p.name: sha256(p) for p in (eeg_path, hmd_path, rating_path)},
    }
    return samples, audit


def prepare_directory(raw: Path, output: Path, cfg: Protocol, *, fs=300.0, data_kind="public", tensor_output=None):
    if data_kind not in {"public", "synthetic"}:
        raise ValueError("unknown data kind")
    tables, audits = [], []
    tensors = [] if tensor_output is not None else None
    candidates = sorted([*raw.rglob("*_EEG.csv"), *raw.rglob("*_EEG.xlsx")])
    if not candidates:
        raise ValueError(f"no *_EEG.csv/xlsx files in {raw}")
    seen = set()
    for eeg in candidates:
        stem = eeg.stem[:-4]
        if stem in seen:
            raise ValueError(f"duplicate recording {stem}: keep one export format")
        seen.add(stem)
        def find(stream):
            choices = [p for suffix in (".csv", ".xlsx") if (p := eeg.with_name(stem + "_" + stream + suffix)).exists()]
            if len(choices) != 1:
                raise ValueError(f"{stem}: expected one {stream} file, found {len(choices)}")
            return choices[0]
        try:
            samples, audit = process_recording(eeg, find("Transforms"), find("SubjectiveCs"), cfg, fs, data_kind, tensor_sink=tensors)
            tables.append(samples)
            audits.append({"recording": stem, "status": "ok", **audit})
            print(f"{stem}: {len(samples)} forecast windows, {audit['positive_windows']} positive", flush=True)
        except (ValueError, KeyError, pd.errors.EmptyDataError) as error:
            audits.append({"recording": stem, "status": "excluded", "reason": str(error)})
            print(f"{stem}: EXCLUDED ({error})", flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    audit_path = output.with_suffix(".audit.json")
    metadata = {"protocol": cfg.to_dict(), "protocol_hash": cfg.fingerprint, "data_kind": data_kind,
                "preprocessing_sha256": sha256(Path(__file__)),
                "raw_directory": str(raw.resolve()), "recordings": audits}
    audit_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    if not tables or not any(len(t) for t in tables):
        raise ValueError(f"no valid forecast windows; see {audit_path}")
    combined = pd.concat(tables, ignore_index=True)
    combined["protocol_hash"] = cfg.fingerprint
    combined.to_csv(output, index=False)
    if tensor_output is not None:
        if len(tensors) != len(combined):
            raise RuntimeError("tensor/table alignment mismatch")
        tensor_output = Path(tensor_output)
        tensor_output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(tensor_output, psd=np.stack([pair[0] for pair in tensors]),
                            kinematic=np.stack([pair[1] for pair in tensors]),
                            features_sha256=np.asarray(sha256(output)), protocol_hash=np.asarray(cfg.fingerprint),
                            data_kind=np.asarray(data_kind))
    return combined
