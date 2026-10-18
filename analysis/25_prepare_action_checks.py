"""Explicit synthetic software fixtures, never used as participant evidence."""
from pathlib import Path
import numpy as np
import pandas as pd
from forecasting.replay import export_replay

if __name__=="__main__":
    root=Path("runs/action_parity");root.mkdir(parents=True,exist_ok=True)
    cases={"last":[[9.],[1]],"none":[[9.,12.,15.],[0,0,0]],
           "gap":[[9.,12.,30.,33.],[1,0,0,1]],
           "repeated":[list(np.arange(9.,72.,3.)),[int(i%4==0) for i in range(21)]]}
    jobs=[]
    for name,(times,alarms) in cases.items():
        f=pd.DataFrame({"subject":"synthetic","session":name,"model":"software_fixture","seed":7,
            "timestamp_s":times,"quality":1.,"alarm":alarms,"data_kind":"synthetic"})
        f.to_csv(root/(name+"_predictions.csv"),index=False)
        csv=root/(name+".csv")
        export_replay(f,csv,subject="synthetic",session=name,model="software_fixture",seed=7)
        jobs.append(str(csv.resolve())+"|"+str((root/name).resolve()))
    (root/"jobs.txt").write_text("\n".join(jobs),encoding="utf-8")
    print("4 synthetic software parity fixtures generated")
