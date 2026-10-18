"""Frozen HGB + calibration objective comparison; never selects on test outcomes."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import platform
import time
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from forecasting.action import evaluate_actions
from forecasting.evaluation import split_subjects, _event_metrics
from forecasting.alerts import score_alerts
from forecasting.config import Protocol

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def json_safe(value):
    if isinstance(value,dict):return {k:json_safe(v) for k,v in value.items()}
    if isinstance(value,list):return [json_safe(v) for v in value]
    if isinstance(value,float) and not np.isfinite(value):return None
    return value

def choose_policy(search, budget, objective, occupancy_budget):
    feasible = [r for r in search if r["false_alarms_per_min"] <= budget+1e-9
                and r["occupied_fraction"] <= occupancy_budget+1e-9 and np.isfinite(r[objective]) and r[objective] > 0]
    if not feasible:
        return next(r for r in search if r["threshold"] > 1.)
    return min(feasible, key=lambda r:(-r[objective],r["false_alarms_per_min"],r["occupied_fraction"],-r["threshold"]))

def summarize(output, settings):
    metrics = pd.read_csv(output/"subject_metrics.csv", dtype={"subject":str})
    numeric = metrics.select_dtypes(include=[np.number]).columns.difference(["seed"])
    by_person = metrics.groupby(["policy","subject"])[numeric].mean().reset_index()
    summary = by_person.groupby("policy")[numeric].mean()
    summary.to_csv(output/"summary.csv")
    by_person.to_csv(output/"subject_seed_averages.csv",index=False)
    base = metrics.groupby("policy")[["false_budget_exceeded","occupancy_budget_exceeded"]].agg(["sum","mean","max"])
    base.to_csv(output/"budget_transfer.csv")
    differences=[]
    rng=np.random.default_rng(20261015)
    for budget in settings["false_alarm_budgets_per_min"]:
        suffix=str(budget).replace(".","p")
        a=by_person[by_person.policy=="recall_b"+suffix].set_index("subject")
        b=by_person[by_person.policy=="usable_b"+suffix].set_index("subject")
        for metric in ("usable_recall","event_recall","false_alarms_per_min","occupied_fraction"):
            delta=(b[metric]-a[metric]).dropna().to_numpy()
            bs=np.mean(rng.choice(delta,(settings["bootstrap_repetitions"],len(delta)),replace=True),axis=1) if len(delta) else np.array([np.nan])
            differences.append({"budget":budget,"metric":metric,"subjects":len(delta),"mean_usable_minus_recall":float(delta.mean()) if len(delta) else np.nan,
                "bootstrap_95_low":float(np.nanquantile(bs,.025)),"bootstrap_95_high":float(np.nanquantile(bs,.975))})
    pd.DataFrame(differences).to_csv(output/"paired_bootstrap.csv",index=False)
    reg = pd.read_csv(output/"regression_metrics.csv", dtype={"subject":str})
    reg.groupby(["model","subject"])[["mae","rmse","average_precision"]].mean().groupby("model").mean().to_csv(output/"regression_summary.csv")
    lines=["# 执行延迟感知阈值校准 v3", "", "固定模型、相同误警与占用约束，仅改变校准目标。先按被试内平均种子，再按被试宏平均；无事件被试的召回为 NA。", "",
        "| 策略 | 事件召回 | 可用动作召回 | 误警/分钟 | 动作占用 |", "|---|---:|---:|---:|---:|"]
    for name,row in summary.iterrows():
        lines.append(f"| {name} | {row.event_recall:.4f} | {row.usable_recall:.4f} | {row.false_alarms_per_min:.4f} | {row.occupied_fraction:.4f} |")
    lines += ["", "可用动作指倍率降至 0.80 且距公开评分事件至少 2 秒。占用指倍率低于 0.99，按逐帧线性插值积分；均是研究定义。", "",
        "阈值只由校准被试确定。约束为校准被试宏平均经验值，新被试可以超限，见 budget_transfer.csv。", "",
        "评分事件不是生理发作时刻。离线动作仿真使用无头动的桌面回退分支；原始症状轨迹不随模拟减速改变，不构成减缓效果证据。", "",
        "原数据已被用于 v1/v2 开发，该源上的 v3 为探索性；第二数据源为冻结设定下的方法独立评估，不是冻结权重迁移或外部预注册。"]
    (output/"report_zh.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(summary[["event_recall","usable_recall","false_alarms_per_min","occupied_fraction"]].to_string(),flush=True)

def run(features, output, settings, dataset, seeds):
    output.mkdir(parents=True,exist_ok=True)
    frame=pd.read_csv(features,dtype={"subject":str,"session":str})
    if frame.data_kind.nunique()!=1:
        raise ValueError("mixed public/synthetic data")
    if frame.duplicated(["subject","session","timestamp_s"]).any() or frame.subject.nunique()<5:
        raise ValueError("invalid subject/session/time identities")
    if not np.allclose(frame.feature_end_s,frame.timestamp_s) or not np.allclose(frame.forecast_end_s-frame.timestamp_s,settings["horizon_s"]):
        raise ValueError("invalid causal provenance")
    prefixes=("motion_",) if dataset=="secondary" else ("eeg_","hmd_")
    columns=[c for c in frame if c.startswith(prefixes) and "__lag" in c]
    if not columns:
        raise ValueError("empty feature allowlist")
    root=Path(__file__).resolve().parent
    files=[Path(__file__),root/"configs/action_v3.json",*sorted((root/"forecasting").glob("*.py")),
           *sorted((root.parent/"Assets/Cybersickness/Scripts").glob("Cybersickness*.cs"))]
    identity={"dataset":dataset,"input_sha256":digest(features),"settings":settings,"seeds":seeds,"feature_columns":columns,
        "source_sha256":{str(p.relative_to(root.parent)):digest(p) for p in files},"python":platform.python_version()}
    lock=output/"run.json"
    if lock.exists() and json.loads(lock.read_text(encoding="utf-8"))!=json.loads(json.dumps(identity)):
        raise ValueError("Run identity changed; use a new output directory")
    lock.write_text(json.dumps(identity,indent=2),encoding="utf-8")
    # This lock is written before fitting or scoring any v3 model.
    cfg=Protocol(event_delta=1. if dataset=="secondary" else .1,consecutive_windows=1)
    all_metrics, all_predictions, all_reg=[] , [], []
    for seed in seeds:
        for subject in sorted(frame.subject.unique()):
            started=time.perf_counter()
            prefix=output/f"fold_{seed}_{subject}"
            if prefix.with_suffix(".metrics.csv").exists():
                all_metrics.append(pd.read_csv(prefix.with_suffix(".metrics.csv"),dtype={"subject":str}))
                all_predictions.append(pd.read_csv(prefix.with_suffix(".predictions.csv"),dtype={"subject":str,"session":str}))
                all_reg.append(pd.read_csv(prefix.with_suffix(".regression.csv"),dtype={"subject":str}))
                continue
            fit_ids,cal_ids=split_subjects(frame.subject,subject,seed,.25)
            fit=frame[frame.subject.isin(fit_ids)]
            cal=frame[frame.subject.isin(cal_ids)].reset_index(drop=True)
            test=frame[frame.subject==subject].reset_index(drop=True)
            parameters={**settings["hgb"],"early_stopping":False,"random_state":seed}
            classifier=HistGradientBoostingClassifier(**parameters,class_weight="balanced")
            if fit.event.nunique()<2:
                cs,ts=np.zeros(len(cal)),np.zeros(len(test))
            else:
                classifier.fit(fit[columns],fit.event)
                cs,ts=classifier.predict_proba(cal[columns])[:,1],classifier.predict_proba(test[columns])[:,1]
            candidates=np.unique(np.r_[np.quantile(cs,np.linspace(0,1,settings["threshold_grid_quantiles"])),1.01])
            search=[]; cache={}
            for threshold in candidates:
                flags=score_alerts(cal,cs,threshold,settings["cooldown_s"],settings["min_quality"])
                key=flags.tobytes()
                if key not in cache:
                    raw=cal[["subject","session","timestamp_s","event","event_time_s"]].copy()
                    raw["alarm"]=flags
                    fa=float(np.mean([_event_metrics(p,"alarm",cfg)["false_alarms_per_min"] for _,p in raw.groupby("subject")]))
                    if fa>max(settings["false_alarm_budgets_per_min"])+1e-9:
                        cache[key]={"event_recall":None,"usable_recall":None,"false_alarms_per_min":fa,
                                    "occupied_fraction":None,"skipped_reason":"fails_all_false_alarm_budgets"}
                    else:
                        cache[key]=evaluate_actions(cal,cs,threshold,settings)
                search.append({"threshold":float(threshold),**cache[key]})
            metrics=[]; predictions=[]; chosen={}
            for budget in settings["false_alarm_budgets_per_min"]:
                for objective,name in (("event_recall","recall"),("usable_recall","usable")):
                    selected=choose_policy(search,budget,objective,settings["occupancy_budget"])
                    threshold=selected["threshold"]
                    policy=f"{name}_b{str(budget).replace('.', 'p')}"
                    chosen[policy]=selected
                    _,details,flags=evaluate_actions(test,ts,threshold,settings,True)
                    details["policy"],details["seed"],details["threshold"]=policy,seed,threshold
                    details["false_budget_exceeded"]=details.false_alarms_per_min>budget+1e-9
                    details["occupancy_budget_exceeded"]=details.occupied_fraction>settings["occupancy_budget"]+1e-9
                    metrics.append(details)
                    names=["subject","session","timestamp_s","event","event_time_s","quality","data_kind"]
                    if "source_origin_s" in test: names.append("source_origin_s")
                    pred=test[names].copy()
                    pred["score"],pred["alarm"],pred["threshold"],pred["model"],pred["seed"]=ts,flags,threshold,policy,seed
                    predictions.append(pred)
            native_max=20. if dataset=="secondary" else 1.
            regressions=[]
            sensor_name = "motion" if dataset=="secondary" else "fusion"
            for name in ("time_hgb",sensor_name+"_ridge",sensor_name+"_hgb","oracle_rating_persistence"):
                used=["timestamp_s"] if name=="time_hgb" else columns
                if name=="oracle_rating_persistence":
                    estimate=test.current_rating.to_numpy(); delta=np.zeros(len(test))
                else:
                    factory=(lambda:make_pipeline(SimpleImputer(strategy="median",keep_empty_features=True),StandardScaler(),Ridge(alpha=settings["ridge_alpha"]))) if name.endswith("_ridge") else (lambda:HistGradientBoostingRegressor(**parameters))
                    level=factory().fit(fit[used],fit.future_peak)
                    trend=factory().fit(fit[used],fit.delta_target)
                    estimate=np.clip(level.predict(test[used]),0,native_max)
                    delta=trend.predict(test[used])
                regressions.append({"model":name,"seed":seed,"subject":subject,"windows":len(test),
                    "mae":float(np.mean(abs(estimate-test.future_peak.to_numpy()))),
                    "rmse":float(np.sqrt(np.mean((estimate-test.future_peak.to_numpy())**2))),
                    "average_precision":float(average_precision_score(test.event,delta)) if test.event.nunique()>1 else np.nan})
            m=pd.concat(metrics,ignore_index=True); p=pd.concat(predictions,ignore_index=True); r=pd.DataFrame(regressions)
            # Store calibration scores separately, before reporting held-out outcomes.
            cal_out=cal[["subject","session","timestamp_s","event","event_time_s","quality","data_kind"]].copy()
            cal_out["score"]=cs; cal_out.to_csv(prefix.with_suffix(".calibration.csv"),index=False)
            prefix.with_suffix(".split.json").write_text(json.dumps(json_safe({"test_subject":subject,"fit_subjects":fit_ids,
                "calibration_subjects":cal_ids,"threshold_search":search,"chosen":chosen}),indent=2,allow_nan=False),encoding="utf-8")
            p.to_csv(prefix.with_suffix(".predictions.csv"),index=False)
            r.to_csv(prefix.with_suffix(".regression.csv"),index=False)
            m.to_csv(prefix.with_suffix(".metrics.csv"),index=False)
            all_metrics.append(m);all_predictions.append(p);all_reg.append(r)
            print(f"{dataset} seed={seed} test={subject} n={len(test)} unique_alarm_patterns={len(cache)} seconds={time.perf_counter()-started:.2f}",flush=True)
    pd.concat(all_metrics,ignore_index=True).to_csv(output/"subject_metrics.csv",index=False)
    pd.concat(all_predictions,ignore_index=True).to_csv(output/"predictions.csv",index=False)
    pd.concat(all_reg,ignore_index=True).to_csv(output/"regression_metrics.csv",index=False)
    summarize(output,settings)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("features",type=Path)
    parser.add_argument("--dataset",choices=("original","secondary"),required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--config",type=Path,default=Path("configs/action_v3.json"))
    parser.add_argument("--seeds",nargs="+",type=int,default=[7,19,42])
    args=parser.parse_args()
    with threadpool_limits(limits=2):
        run(args.features,args.output,json.loads(args.config.read_text(encoding="utf-8")),args.dataset,args.seeds)
