import argparse
from dataclasses import replace
from forecasting.config import Protocol
from forecasting.evaluation import run_experiment
from threadpoolctl import threadpool_limits

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nested subject-disjoint forecast evaluation")
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="configs/forecast_v1.json")
    parser.add_argument("--horizon", type=float)
    parser.add_argument("--seeds", nargs="+", type=int)
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    cfg = Protocol.load(args.config)
    if args.horizon is not None:
        cfg = replace(cfg, horizon_s=args.horizon)
    with threadpool_limits(limits=2):
        run_experiment(args.input, args.output, cfg, seeds=args.seeds, models=args.models, resume=args.resume)
