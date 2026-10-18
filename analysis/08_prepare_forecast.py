import argparse
from pathlib import Path
from dataclasses import replace
from forecasting.config import Protocol
from forecasting.dataset import prepare_directory

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Causal public EEG/HMD forecasting table")
    parser.add_argument("--raw", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="configs/forecast_v1.json")
    parser.add_argument("--sfreq", type=float, default=300)
    parser.add_argument("--horizon", type=float)
    parser.add_argument("--data-kind", choices=("public", "synthetic"), default="public")
    parser.add_argument("--tensors", help="Optional causal spectral/kinematic tensor NPZ for neural comparison")
    args = parser.parse_args()
    cfg = Protocol.load(args.config)
    if args.horizon is not None:
        cfg = replace(cfg, horizon_s=args.horizon)
    result = prepare_directory(Path(args.raw), Path(args.output), cfg, fs=args.sfreq, data_kind=args.data_kind, tensor_output=args.tensors)
    print(f"Prepared {len(result)} windows, {result.subject.nunique()} subjects, {result.event.sum()} positive windows; protocol={cfg.fingerprint}")
