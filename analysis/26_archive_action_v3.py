"""Strictly merge independently scheduled seeds, then archive research outputs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import pandas as pd

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("features",type=Path)
    parser.add_argument("--parts",nargs="+",required=True,help="7=directory 19=directory 42=directory")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--archive",type=Path,required=True)
    args=parser.parse_args()
    frame=pd.read_csv(args.features,dtype={"subject":str,"session":str})
    subjects=set(frame.subject.unique())
    parts={int(item.split("=",1)[0]):Path(item.split("=",1)[1]) for item in args.parts}
    if set(parts)!={7,19,42}:raise ValueError("All three predeclared seeds are required")
    metrics=[];predictions=[];regressions=[];splits=[];identities={};sources=[];canonical=None
    for seed,directory in sorted(parts.items()):
        identity=json.loads((directory/"run.json").read_text(encoding="utf-8"))
        if identity["input_sha256"]!=digest(args.features) or seed not in identity["seeds"]:
            raise ValueError("Input/seed mismatch")
        identity_without_seeds={k:v for k,v in identity.items() if k!="seeds"}
        if canonical is not None and identity_without_seeds!=canonical:raise ValueError("Incompatible protocol or source hashes")
        canonical=identity_without_seeds;identities[str(seed)]=identity
        for subject in sorted(subjects):
            prefix=directory/f"fold_{seed}_{subject}"
            paths={k:prefix.with_suffix("."+suffix) for k,suffix in [
                ("metrics","metrics.csv"),("predictions","predictions.csv"),("regression","regression.csv"),("split","split.json"),("calibration","calibration.csv")]}
            if not all(p.exists() for p in paths.values()):raise ValueError(f"Incomplete fold {seed}/{subject}")
            m=pd.read_csv(paths["metrics"],dtype={"subject":str})
            p=pd.read_csv(paths["predictions"],dtype={"subject":str,"session":str})
            r=pd.read_csv(paths["regression"],dtype={"subject":str})
            split=json.loads(paths["split"].read_text(encoding="utf-8"))
            fitting,calibration=set(split["fit_subjects"]),set(split["calibration_subjects"])
            if fitting & calibration or subject in fitting|calibration or fitting|calibration|{subject}!=subjects:
                raise ValueError("Subject separation failure")
            if set(m.seed)!={seed} or set(m.subject)!={subject} or m.policy.nunique()!=6:
                raise ValueError("Metric grid mismatch")
            if set(p.model)!=set(m.policy) or set(p.seed)!={seed} or set(p.subject)!={subject}:
                raise ValueError("Prediction policy grid mismatch")
            if len(r)!=4 or set(r.seed)!={seed} or set(r.subject)!={subject}:
                raise ValueError("Regression baseline grid mismatch")
            cal_file=pd.read_csv(paths["calibration"],dtype={"subject":str})
            if set(cal_file.subject)!=calibration:
                raise ValueError("Calibration output does not match declared subjects")
            expected=set(map(tuple,frame.loc[frame.subject==subject,["session","timestamp_s"]].to_numpy()))
            for _,part in p.groupby("model"):
                if part.duplicated(["session","timestamp_s"]).any() or set(map(tuple,part[["session","timestamp_s"]].to_numpy()))!=expected:
                    raise ValueError("Prediction windows do not match the complete prepared cohort")
            metrics.append(m);predictions.append(p);regressions.append(r)
            splits.append({"seed":seed,**split})
            sources.append({"seed":seed,"subject":subject,"files":{k:{"path":str(v),"sha256":digest(v)} for k,v in paths.items()}})
    args.output.mkdir(parents=True,exist_ok=True);args.archive.mkdir(parents=True,exist_ok=True)
    pd.concat(metrics,ignore_index=True).to_csv(args.output/"subject_metrics.csv",index=False)
    pd.concat(predictions,ignore_index=True).to_csv(args.output/"predictions.csv",index=False)
    pd.concat(regressions,ignore_index=True).to_csv(args.output/"regression_metrics.csv",index=False)
    (args.output/"split_manifest.json").write_text(json.dumps(splits,indent=2),encoding="utf-8")
    spec=importlib.util.spec_from_file_location("v3",Path(__file__).with_name("23_run_action_v3.py"))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.summarize(args.output,canonical["settings"])
    for name in ["subject_metrics.csv","regression_metrics.csv","subject_seed_averages.csv","summary.csv",
                 "regression_summary.csv","paired_bootstrap.csv","budget_transfer.csv","report_zh.md","split_manifest.json"]:
        shutil.copyfile(args.output/name,args.archive/name)
    manifest={"status":"complete","dataset":canonical["dataset"],"subjects":len(subjects),
        "windows":len(frame),"seeds":[7,19,42],"completed_model_folds":3*len(subjects),
        "policy_subject_seed_combinations":6*3*len(subjects),"identities":identities,"sources":sources,
        "merged_predictions_sha256":digest(args.output/"predictions.csv"),
        "archive_files":{p.name:digest(p) for p in args.archive.iterdir() if p.is_file() and p.name!="manifest.json"}}
    (args.archive/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in manifest.items() if k not in ("sources","identities","archive_files")},indent=2))

if __name__=="__main__":main()
