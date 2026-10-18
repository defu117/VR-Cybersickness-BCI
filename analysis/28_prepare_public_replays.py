"""Choose deterministic held-out examples for software checks, not efficacy figures."""
import json
from pathlib import Path
import pandas as pd
from forecasting.replay import export_replay

if __name__=="__main__":
    root=Path('runs/public_action_replays');root.mkdir(parents=True,exist_ok=True)
    choices=[];jobs=[]
    for dataset,policy,nonzero in [('original','recall_b0p5',False),('secondary','recall_b0p5',False),('secondary','usable_b0p5',True)]:
        source=Path('runs/action_v3_'+dataset)
        parts=[pd.read_csv(p,dtype={'subject':str,'session':str}) for p in sorted(source.glob('fold_7_*.predictions.csv'))]
        if not parts:raise ValueError('No completed held-out folds')
        f=pd.concat(parts,ignore_index=True)
        f=f[f.model==policy].sort_values(['subject','session','timestamp_s'])
        eligible=f[f.alarm==1] if nonzero else f
        if eligible.empty:eligible=f
        selected=eligible.iloc[0]
        case=dataset+'_'+policy
        trajectory=f[(f.subject==selected.subject)&(f.session==selected.session)].copy()
        trajectory.to_csv(root/(case+'_predictions.csv'),index=False)
        csv=root/(case+'.csv')
        export_replay(trajectory,csv,subject=selected.subject,session=selected.session,model=policy,seed=7,policy='action')
        choices.append({'case':case,'subject':selected.subject,'session':selected.session,'policy':policy,'seed':7,
            'alarms':int(trajectory.alarm.sum()),'selection':'lexicographically first trajectory; third case prefers a nonzero alarm if available',
            'scope':'held-out software integration example, not representative efficacy or best-case performance'})
        jobs.append(str(csv.resolve())+'|'+str((root/case).resolve()))
    (root/'jobs.txt').write_text('\n'.join(jobs),encoding='utf-8')
    (root/'selection.json').write_text(json.dumps(choices,indent=2),encoding='utf-8')
    print(json.dumps(choices,indent=2))
