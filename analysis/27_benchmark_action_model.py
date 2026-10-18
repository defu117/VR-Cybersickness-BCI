"""Post-fit software-only scoring benchmark; does not choose a model or threshold."""
import argparse
import json
from pathlib import Path
import platform
import time
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from threadpoolctl import threadpool_limits

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("features",type=Path);parser.add_argument("fold_prefix",type=Path)
    parser.add_argument("--dataset",choices=("original","secondary"),required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    settings=json.loads(Path('configs/action_v3.json').read_text())
    split=json.loads(args.fold_prefix.with_suffix('.split.json').read_text())
    original=pd.read_csv(args.fold_prefix.with_suffix('.predictions.csv'),dtype={'subject':str,'session':str})
    seed=int(original.seed.iloc[0])
    f=pd.read_csv(args.features,dtype={'subject':str,'session':str})
    fit=f[f.subject.isin(split['fit_subjects'])];test=f[f.subject==split['test_subject']]
    prefixes=('motion_',) if args.dataset=='secondary' else ('eeg_','hmd_')
    columns=[c for c in f if c.startswith(prefixes) and '__lag' in c]
    if fit.event.nunique()!=2:raise ValueError('Benchmark requires a nonconstant trained classifier')
    with threadpool_limits(limits=2):
        model=HistGradientBoostingClassifier(**settings['hgb'],class_weight='balanced',early_stopping=False,random_state=seed)
        model.fit(fit[columns],fit.event)
        expected=original.drop_duplicates(['session','timestamp_s'])[['session','timestamp_s','score']]
        check=test[['session','timestamp_s']].merge(expected,on=['session','timestamp_s'],validate='one_to_one')
        predicted=model.predict_proba(test[columns])[:,1]
        error=float(np.max(abs(predicted-check.score.to_numpy())))
        if error>1e-10:raise ValueError('Refit benchmark does not reproduce held-out scores')
        row=test[columns].iloc[:1]
        for _ in range(20):model.predict_proba(row)
        timings=[]
        for _ in range(200):
            started=time.perf_counter_ns();model.predict_proba(row)
            timings.append((time.perf_counter_ns()-started)/1e6)
    output={'scope':'one-row HGB scoring only, excludes acquisition, feature processing, networking and XR rendering',
        'selection':'lexicographically first subject, seed 7; fixed experimental model; no timing-based selection',
        'concurrency_context':'other study training workers may be running; not an isolated latency benchmark',
        'python':platform.python_version(),'features':len(columns),'subject':split['test_subject'],'seed':seed,
        'score_reproduction_max_error':error,'warmup_calls':20,'measured_calls':200,
        'median_score_ms':float(np.median(timings)),'p95_score_ms':float(np.quantile(timings,.95))}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(output,indent=2))
