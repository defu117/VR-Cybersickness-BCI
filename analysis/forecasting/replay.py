from __future__ import annotations

from pathlib import Path
import json
import hashlib
import numpy as np
import pandas as pd


def export_replay(predictions: pd.DataFrame, output: Path, *, subject: str, session: str,
                  model: str, seed: int, policy="gated", heartbeat_s=0.1, hold_s=10.0):
    if heartbeat_s <= 0 or heartbeat_s >= 2 or hold_s <= 0:
        raise ValueError("heartbeat must be positive and below the Unity 2s timeout; hold must be positive")
    selected = predictions[(predictions.subject.astype(str) == str(subject)) &
                           (predictions.session.astype(str) == str(session)) &
                           (predictions.model == model) & (predictions.seed == seed)].sort_values("timestamp_s")
    if selected.empty or selected.timestamp_s.duplicated().any():
        raise ValueError("select exactly one nonempty subject/session/model/seed trajectory")
    source = "forecast_" + str(selected.data_kind.iloc[0]) + "_" + policy
    t = selected.timestamp_s.to_numpy(dtype=float)
    start, stop = float(t[0]), float(t[-1]) + 3.0
    rows, active_until = [], -np.inf
    active_id = ""
    alarm_column = "alarm_" + policy if "alarm_" + policy in selected else "alarm"
    if alarm_column not in selected:
        raise ValueError("prediction table has no selected alarm policy")
    cursor = 0
    # Gaps in prediction data emit no heartbeat; Unity then expires the stream.
    for timestamp in np.arange(start, stop + heartbeat_s / 2, heartbeat_s):
        while cursor + 1 < len(t) and t[cursor + 1] <= timestamp + 1e-8:
            cursor += 1
        row = selected.iloc[cursor]
        if timestamp - t[cursor] > 3 + 1e-6:
            active_until = -np.inf
            active_id = ""
            continue
        prediction_id = f"{subject}.{session}.{model}.{seed}.{t[cursor]:.6f}"
        if row[alarm_column] and timestamp < t[cursor] + heartbeat_s / 2:
            active_until = max(active_until, t[cursor] + hold_s)
            active_id = prediction_id
        rows.append({"timestamp_s": round(timestamp - start, 6),
                     "risk": 0.7 if timestamp < active_until - 1e-8 else 0.0,
                     "quality": float(row.quality), "source": source,
                     "prediction_id": prediction_id, "alarm_id": active_id if timestamp < active_until - 1e-8 else "",
                     "source_timestamp_s": float(t[cursor]), "monitor_until_s": float(t[cursor]+3),
                     "raw_record_timestamp_s": float(t[cursor]+row.source_origin_s) if "source_origin_s" in row else ""})
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output, index=False)
    output.with_suffix(".json").write_text(json.dumps({"subject":subject,"session":session,"model":model,"seed":seed,
        "data_kind":str(selected.data_kind.iloc[0]),"source_origin_s":start,"heartbeat_s":heartbeat_s,"hold_s":hold_s,
        "monitor_intervals_source_s":[[float(x),float(x+3)] for x in t],
        "csv_sha256":hashlib.sha256(output.read_bytes()).hexdigest(),
        "scope":"input warning stream, not symptom outcomes under the simulated action"},indent=2),encoding="utf-8")
    return len(rows)
