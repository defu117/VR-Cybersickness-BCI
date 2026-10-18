"""Recompute telemetry burden and, optionally, compare the frozen model to Unity."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from forecasting.action import occupied_fraction, simulate_session

def analyze(prefix: Path, output: Path, predictions=None, settings=None):
    frames=pd.read_csv(str(prefix)+"_frames.csv")
    events=pd.read_csv(str(prefix)+"_events.csv",keep_default_na=False)
    dt=frames.dt_s.to_numpy(dtype=float)
    applied=frames.applied_multiplier.to_numpy(dtype=float)
    previous=np.r_[applied[0],applied[:-1]]
    occupied=dt*occupied_fraction(previous,applied)
    intensity=dt*(2.-previous-applied)/2.
    tail=frames["tail"].astype(bool).to_numpy()
    valid=frames.monitor_valid.astype(bool).to_numpy() if "monitor_valid" in frames else ~tail
    result={"scope":"desktop software actuator measurements, not symptom reduction or XR display latency",
            "monitor_s":float(dt[valid].sum()),"occupied_s":float(occupied[valid].sum()),
            "intensity_s":float(intensity[valid].sum()),"tail_s":float(dt[tail].sum()),
            "tail_occupied_s":float(occupied[tail].sum()),"tail_intensity_s":float(intensity[tail].sum()),
            "unique_received_alarms":int(events.loc[events.event=="alarm_received","alarm_id"].nunique()),
            "occupied_column_max_error":float(np.max(abs(occupied-frames.occupied_dt_s.to_numpy()))),
            "intensity_column_max_error":float(np.max(abs(intensity-frames.intensity_dt_s.to_numpy())))}
    if "valid_dt_s" in frames:
        result.update(monitor_s=float(frames.valid_dt_s.sum()),occupied_s=float(frames.valid_occupied_dt_s.sum()),
                      intensity_s=float(frames.valid_intensity_dt_s.sum()))
    received=events[events.event=="alarm_received"]
    timings=[]
    for row in received.itertuples(index=False):
        future=frames[frames.local_time_s >= row.local_time_s-1e-6]
        ready=future[future.applied_multiplier <= .800001]
        started=future[future.applied_multiplier < .99]
        timings.append({"alarm_id":row.alarm_id,"receipt_local_s":row.local_time_s,
            "action_start_delay_s":float(started.local_time_s.iloc[0]-row.local_time_s) if len(started) else np.nan,
            "action_effective_delay_s":float(ready.local_time_s.iloc[0]-row.local_time_s) if len(ready) else np.nan})
    output.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(timings).to_csv(output/(prefix.name+"_alarm_timing.csv"),index=False)
    if predictions is not None:
        if not np.allclose(frames.playback_speed,1.):
            raise ValueError("Formal timing comparison requires 1x playback")
        selected=predictions.sort_values("timestamp_s")
        simulated=simulate_session(selected,selected.alarm.to_numpy(),settings,True)
        reference=simulated.pop("trace")
        measured=frames.drop_duplicates("replay_elapsed_s",keep="last")
        measured=measured[(measured.replay_elapsed_s>0)&(measured.replay_elapsed_s<=reference.time_s.iloc[-1]+1e-6)]
        indices=np.clip(np.rint(measured.replay_elapsed_s.to_numpy()/settings["controller"]["step_s"]).astype(int)-1,0,len(reference)-1)
        for name in ("risk_smoothed","target_multiplier","applied_multiplier"):
            result["parity_max_error_"+name]=float(np.max(abs(measured[name].to_numpy()-reference.iloc[indices][name].to_numpy())))
        result["parity_occupied_error_s"]=abs(result["occupied_s"]-simulated["occupied_s"])
        result["parity_intensity_error_s"]=abs(result["intensity_s"]-simulated["intensity_s"])
        result["parity_passed"]=bool(result["parity_max_error_applied_multiplier"]<=.009
            and result["parity_max_error_risk_smoothed"]<=.012
            and result["parity_occupied_error_s"]<=.05 and result["parity_intensity_error_s"]<=.02)
    (output/(prefix.name+"_analysis.json")).write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("prefix",type=Path);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--predictions",type=Path);p.add_argument("--config",type=Path,default=Path("configs/action_v3.json"))
    a=p.parse_args()
    print(json.dumps(analyze(a.prefix,a.output,pd.read_csv(a.predictions) if a.predictions else None,
        json.loads(a.config.read_text()) if a.predictions else None),indent=2))
