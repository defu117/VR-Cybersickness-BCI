import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from forecasting.secondary import read_recording, identity, causal_samples
from forecasting.action import simulate_session, occupied_fraction, evaluate_actions
from forecasting.replay import export_replay

SETTINGS=json.loads((Path(__file__).resolve().parents[1]/"configs/action_v3.json").read_text())

def recording():
    t=np.arange(.5,65,.5)
    f=pd.DataFrame({"time_s":t,"rating":np.where(t>30,3.,0.),"gender":"m","age":25.,"mssq":5.})
    for i,c in enumerate(["ax","ay","az","wx","wy","wz"]):f[c]=np.sin(t+i)
    return f

def test_headerless_first_row_and_identity_missing_tail(tmp_path):
    f=recording()[["time_s","rating","ax","ay","az","wx","wy","wz","gender","mssq","age"]]
    f.loc[len(f)-1,["gender","mssq","age"]]=np.nan
    p=tmp_path/"PA1_Base.csv";f.to_csv(p,index=False,header=False)
    actual=read_recording(p)
    assert len(actual)==len(f) and actual.time_s.iloc[0]==.5
    assert identity(actual)==("m",25.,5.)
    actual.loc[0,"age"]=26
    with pytest.raises(ValueError,match="identity_changes"):identity(actual)

def test_secondary_future_features_do_not_leak():
    f=recording();a=causal_samples(f,"PA1","a",SETTINGS)
    f.loc[f.time_s>30,["ax","ay","az","wx","wy","wz"]]=1e8
    f.loc[f.time_s>30,"rating"]=20
    b=causal_samples(f,"PA1","a",SETTINGS)
    names=[c for c in a if c.startswith("motion_")]
    np.testing.assert_array_equal(a.loc[a.timestamp_s<=27,names],b.loc[b.timestamp_s<=27,names])
    assert len(names)==72 and not any("rating" in c for c in names)

def test_secondary_reset_and_row_cap():
    f=recording();f.loc[10,"time_s"]=0
    with pytest.raises(ValueError,match="nonincreasing"):causal_samples(f,"PA1","a",SETTINGS)
    config={**SETTINGS,"secondary_max_rows":40}
    a=causal_samples(recording(),"PA1","a",config)
    assert (a.forecast_end_s<=19.5).all()

def test_secondary_rating_events_native_units_and_quality():
    a=causal_samples(recording(),"PA1","a",SETTINGS)
    assert a.event.sum()>0 and a.future_peak.max()==3
    assert (a.loc[a.event==1,"delta_target"]>=1).all()
    assert a.feature_start_s.min()==0

def test_linear_occupancy_crossing():
    np.testing.assert_allclose(occupied_fraction(np.array([1.,.98,.97]),np.array([.98,1.,.96])),[.5,.5,1])

def test_no_alarm_and_last_alarm_tail():
    f=pd.DataFrame({"timestamp_s":[0.],"quality":[1.]})
    assert simulate_session(f,[0],SETTINGS)["occupied_s"]==0
    result=simulate_session(f,[1],SETTINGS,True)
    assert result["occupied_s"]==pytest.approx(2.2966666667,abs=.02)
    assert 1<result["alarm_ready_times"][0]<1.2
    assert result["tail_occupied_s"]>10 and not result["truncated"]

def test_gap_time_not_counted_as_monitored_exposure():
    f=pd.DataFrame({"timestamp_s":[9.,12.,30.,33.],"quality":1.})
    r=simulate_session(f,[1,0,0,1],SETTINGS,True)
    assert r["monitor_s"]==12.
    assert r["trace"].monitor_valid.sum()*SETTINGS["controller"]["step_s"]==pytest.approx(12.)

def test_action_metrics_cannot_invent_usable_lead():
    f=pd.DataFrame({"subject":"s","session":"a","timestamp_s":[0.,3.,6.],"quality":1.,
                    "event":[1,0,0],"event_time_s":[2.,np.nan,np.nan]})
    metrics=evaluate_actions(f,[.9,.1,.1],.5,SETTINGS)
    assert metrics["event_recall"]==1 and metrics["usable_recall"]==0
    f.loc[0,"event_time_s"]=5.
    assert evaluate_actions(f,[.9,.1,.1],.5,SETTINGS)["usable_recall"]==1

def test_policy_uses_same_budgets_and_no_action_fallback():
    spec=importlib.util.spec_from_file_location("action_runner",Path(__file__).resolve().parents[1]/"23_run_action_v3.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    search=[dict(threshold=.2,event_recall=.8,usable_recall=.2,false_alarms_per_min=.4,occupied_fraction=.19),
            dict(threshold=.4,event_recall=.6,usable_recall=.5,false_alarms_per_min=.3,occupied_fraction=.1),
            dict(threshold=1.01,event_recall=0.,usable_recall=0.,false_alarms_per_min=0.,occupied_fraction=0.)]
    assert module.choose_policy(search,.5,"event_recall",.2)["threshold"]==.2
    assert module.choose_policy(search,.5,"usable_recall",.2)["threshold"]==.4
    assert module.choose_policy(search,.1,"usable_recall",.2)["threshold"]==1.01

def test_replay_identity_and_source_clock(tmp_path):
    f=pd.DataFrame({"subject":"s","session":"a","model":"m","seed":7,"timestamp_s":[12.,15.,30.],
        "quality":1,"alarm":[1,0,1],"data_kind":"synthetic"})
    p=tmp_path/"r.csv";export_replay(f,p,subject="s",session="a",model="m",seed=7)
    r=pd.read_csv(p)
    assert r.timestamp_s.iloc[0]==0 and r.source_timestamp_s.iloc[0]==12
    assert r.loc[r.risk>.5,"alarm_id"].nunique()==2
    assert r.timestamp_s.diff().max()>2
    assert json.loads(p.with_suffix(".json").read_text())["data_kind"]=="synthetic"

def test_v3_heldout_labels_cannot_change_its_score_or_threshold(tmp_path):
    spec=importlib.util.spec_from_file_location("v3_runner",Path(__file__).resolve().parents[1]/"23_run_action_v3.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    rows=[]
    for subject in range(5):
        for i in range(8):
            t=9.+3*i
            rows.append(dict(subject=f"{subject:04}",session="a",timestamp_s=t,feature_start_s=t-9,
                feature_end_s=t,forecast_end_s=t+6,event=i%2,event_time_s=t+5 if i%2 else np.nan,
                current_rating=.1,future_peak=.1+.1*(i%2),delta_target=.1*(i%2),
                quality=1.,data_kind="synthetic",hmd_a__lag0=float(i)))
    f=pd.DataFrame(rows);a=tmp_path/"a.csv";b=tmp_path/"b.csv";f.to_csv(a,index=False)
    f.loc[f.subject=="0000",["current_rating","future_peak","delta_target","event"]]=[.8,.9,.1,0]
    f.to_csv(b,index=False)
    config={**SETTINGS,"threshold_grid_quantiles":3,"bootstrap_repetitions":20,"false_alarm_budgets_per_min":[.5]}
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        module.run(a,tmp_path/"run_a",config,"original",[7])
        module.run(b,tmp_path/"run_b",config,"original",[7])
    x=pd.read_csv(tmp_path/"run_a/fold_7_0000.predictions.csv")
    y=pd.read_csv(tmp_path/"run_b/fold_7_0000.predictions.csv")
    np.testing.assert_array_equal(x[["score","threshold","alarm"]],y[["score","threshold","alarm"]])
