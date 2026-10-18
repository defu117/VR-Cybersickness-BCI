from __future__ import annotations
import numpy as np


def score_alerts(frame, scores, threshold, cooldown_s=12.0, min_quality=.8):
    """An inference-only rule: never reads current or future symptom labels."""
    scores = np.asarray(scores, dtype=float)
    if len(scores) != len(frame):
        raise ValueError("score length mismatch")
    alarms = np.zeros(len(frame), dtype=int)
    times = frame.timestamp_s.to_numpy(dtype=float)
    quality = frame.quality.to_numpy(dtype=float)
    for _, indices in frame.groupby(["subject", "session"], sort=False).indices.items():
        indices = np.asarray(indices)
        indices = indices[np.argsort(times[indices])]
        last = -np.inf
        for index in indices:
            if (np.isfinite(scores[index]) and scores[index] >= threshold and quality[index] >= min_quality
                    and times[index] - last >= cooldown_s):
                alarms[index] = 1
                last = times[index]
    return alarms
