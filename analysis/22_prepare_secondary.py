import argparse
import json
from pathlib import Path
from forecasting.secondary import prepare

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", default="data/raw/ryu2026")
    parser.add_argument("--output", default="data/processed/secondary_h6.csv")
    parser.add_argument("--report", default="../research/results/secondary_audit")
    parser.add_argument("--config", default="configs/action_v3.json")
    args = parser.parse_args()
    result = prepare(Path(args.raw), Path(args.output), Path(args.report), json.loads(Path(args.config).read_text(encoding="utf-8")))
    print(json.dumps({k: v for k,v in result.items() if k not in ("acquisition", "settings")}, indent=2))
