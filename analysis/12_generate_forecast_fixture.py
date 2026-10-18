"""Software fixture only; never use these results as research evidence."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/synthetic_raw")
    parser.add_argument("--subjects", type=int, default=6)
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    fs, duration = 100, 90
    for i in range(args.subjects):
        rng = np.random.default_rng(100 + i)
        t = np.arange(fs * duration) / fs
        score = np.clip(.25 + .25 * np.sin((t + i) / 7), 0, 1)
        eeg = pd.DataFrame({"Millis": t * 1000})
        for ch in range(24):
            eeg[f"ch_{ch + 1}"] = (1 + score) * np.sin(2 * np.pi * (5 + ch / 10) * t) + .1 * rng.standard_normal(len(t))
        ht = np.arange(0, duration, .1)
        hmd = pd.DataFrame({"Millis": ht * 1000, "HeadPosition_X": np.sin((ht + i) / 7),
                            "HeadPosition_Y": 0, "HeadPosition_Z": 0,
                            "HeadRotation_Yaw": 10 * np.sin(ht / 6), "HeadRotation_Pitch": 0,
                            "HeadRotation_Roll": 0})
        rating = pd.DataFrame({"Millis": ht * 1000, "Rating": np.clip(.25 + .25 * np.sin((ht + i) / 7), 0, 1)})
        for stream, data in (("EEG", eeg), ("Transforms", hmd), ("SubjectiveCs", rating)):
            data.to_csv(root / f"{i:04}_DEMO_{stream}.csv", index=False)
    print(f"Wrote SYNTHETIC software fixture for {args.subjects} subjects at {fs}Hz to {root}")
