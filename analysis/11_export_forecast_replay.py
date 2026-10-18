import argparse
from pathlib import Path
import pandas as pd
from forecasting.replay import export_replay

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="One held-out trajectory to Unity risk heartbeat")
    parser.add_argument("predictions")
    parser.add_argument("--output", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--model", default="fusion_cqr")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--policy", choices=("gated", "raw"), default="gated")
    args = parser.parse_args()
    frame = pd.read_csv(args.predictions, dtype={"subject": str, "session": str})
    print("Heartbeat rows:", export_replay(frame, Path(args.output), subject=args.subject,
                                         session=args.session, model=args.model, seed=args.seed, policy=args.policy))
