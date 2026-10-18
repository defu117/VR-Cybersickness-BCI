from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path


@dataclass(frozen=True)
class Protocol:
    window_s: float = 3.0
    history_windows: int = 3
    horizon_s: float = 6.0
    event_delta: float = 0.1
    interval_alpha: float = 0.2
    min_quality: float = 0.8
    max_rating_age_s: float = 1.0
    max_eeg_gap_s: float = 0.25
    max_startup_eeg_s: float = 5.0
    max_hmd_gap_s: float = 0.25
    low_hz: float = 1.0
    high_hz: float = 40.0
    notch_hz: float = 50.0
    baseline_windows: int = 3
    consecutive_windows: int = 2
    cooldown_s: float = 12.0
    calibration_fraction: float = 0.25
    seeds: tuple[int, ...] = (7, 19, 42)

    def __post_init__(self):
        if self.window_s <= 0 or self.horizon_s <= 0 or self.history_windows < 1:
            raise ValueError("window, horizon and history must be positive")
        if self.baseline_windows < 1 or self.consecutive_windows < 1:
            raise ValueError("baseline and consecutive window counts must be positive")
        if not 0 < self.interval_alpha < 1 or not 0 < self.calibration_fraction < 0.5:
            raise ValueError("invalid interval alpha or calibration fraction")
        if not 0 < self.event_delta <= 1 or not 0 <= self.min_quality <= 1:
            raise ValueError("invalid event delta or quality threshold")
        if self.max_rating_age_s <= 0 or self.max_eeg_gap_s <= 0 or self.max_hmd_gap_s <= 0:
            raise ValueError("maximum data gaps must be positive")
        if not 0 < self.low_hz < self.high_hz or self.notch_hz <= 0:
            raise ValueError("invalid EEG filter frequencies")

    @classmethod
    def load(cls, path: str | Path | None = None):
        values = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
        if "seeds" in values:
            values["seeds"] = tuple(values["seeds"])
        return cls(**values)

    def to_dict(self):
        return asdict(self)

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:16]
