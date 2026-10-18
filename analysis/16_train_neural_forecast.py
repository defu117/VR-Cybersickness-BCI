"""Causal CNN-LSTM architecture comparison, not the published label protocol.

Architecture follows the dual spectral/kinematic encoders in the public
Beyond Subjectivity implementation. Inputs, preprocessing, supervision and
participant validation are deliberately retargeted and documented here.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

from forecasting.config import Protocol
from forecasting.dataset import sha256
from forecasting.evaluation import split_subjects, validate_dataset, calibration_radius, apply_warning_policy, subject_metrics


class Encoder(nn.Module):
    def __init__(self, channels, kernel):
        super().__init__()
        blocks = []
        for ins, outs in ((channels, 32), (32, 64), (64, 10)):
            blocks += [nn.Conv1d(ins, outs, kernel * 2, padding=1, bias=False), nn.BatchNorm1d(outs),
                       nn.ReLU(), nn.MaxPool1d(kernel, stride=kernel, padding=1)]
        self.cnn = nn.Sequential(*blocks)
        self.lstm = nn.LSTM(10, 10, num_layers=2, batch_first=True)

    def forward(self, values):
        output, _ = self.lstm(self.cnn(values).transpose(1, 2))
        return output[:, -1]


class ForecastNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.psd = Encoder(24, 4)
        self.kin = Encoder(16, 2)
        self.head = nn.Sequential(nn.Linear(20, 40), nn.ReLU(), nn.Linear(40, 10), nn.ReLU(), nn.Linear(10, 2), nn.Sigmoid())

    def forward(self, psd, kinematic):
        return self.head(torch.cat((self.psd(psd), self.kin(kinematic)), dim=1))


def normalization(data, fit):
    mean = data[fit].mean(axis=(0, 2), keepdims=True)
    std = np.maximum(data[fit].std(axis=(0, 2), keepdims=True), 1e-5)
    return torch.tensor((data - mean) / std, dtype=torch.float32)


def train_model(psd, kin, targets, fit, seed, epochs, validation=None):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = ForecastNet()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-3)
    loss_fn = nn.MSELoss()
    best_score, best_epoch, stale = np.inf, 1, 0
    for epoch in range(epochs):
        model.train()
        for batch in np.array_split(rng.permutation(fit), max(1, int(np.ceil(len(fit) / 64)))):
            if len(batch) == 0:
                continue
            optimizer.zero_grad()
            loss = loss_fn(model(psd[batch], kin[batch]), targets[batch])
            loss.backward()
            optimizer.step()
        if validation is not None:
            model.eval()
            with torch.no_grad():
                score = torch.mean(torch.abs(model(psd[validation], kin[validation])[:, 0] - targets[validation, 0])).item()
            if score < best_score - 1e-5:
                best_score, best_epoch, stale = score, epoch + 1, 0
            else:
                stale += 1
            if stale >= 10:
                break
    return model, best_epoch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("features")
    parser.add_argument("tensors")
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="configs/forecast_v1.json")
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 19, 42])
    parser.add_argument("--max-epochs", type=int, default=60)
    args = parser.parse_args()
    cfg = Protocol.load(args.config)
    frame = pd.read_csv(args.features, dtype={"subject": str, "session": str})
    validate_dataset(frame, cfg)
    bundle = np.load(args.tensors, allow_pickle=False)
    if str(bundle["features_sha256"]) != sha256(Path(args.features)) or str(bundle["protocol_hash"]) != cfg.fingerprint:
        raise ValueError("Neural tensors do not match the canonical feature table/protocol")
    psd_raw, kin_raw = bundle["psd"], bundle["kinematic"]
    if len(psd_raw) != len(frame):
        raise ValueError("Tensor row mismatch")
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    targets = torch.tensor(frame[["future_peak", "delta_target"]].to_numpy(), dtype=torch.float32)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    meta_path = output / "run.json"
    identity = {"input_sha256": sha256(Path(args.features)), "tensor_sha256": sha256(Path(args.tensors)),
                "protocol": cfg.to_dict(), "data_kind": frame.data_kind.iloc[0], "models": ["fusion_cnn_lstm"],
                "seeds": args.seeds, "evaluation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "max_epochs": args.max_epochs}
    # Exactly matched reruns resume per-fold files; changed source/config cannot.
    if meta_path.exists() and json.loads(meta_path.read_text(encoding="utf-8"))["identity"] != json.loads(json.dumps(identity)):
        raise ValueError("Output run identity differs")
    meta_path.write_text(json.dumps({"identity": identity, "torch": torch.__version__}, indent=2), encoding="utf-8")
    outputs, splits = [], []
    for seed in args.seeds:
        for subject in sorted(frame.subject.unique()):
            path = output / f"pred_{seed}_{subject}_fusion_cnn_lstm.csv"
            split_path = output / f"split_{seed}_{subject}.json"
            if path.exists() and split_path.exists():
                outputs.append(pd.read_csv(path, dtype={"subject": str, "session": str}))
                splits.append(json.loads(split_path.read_text(encoding="utf-8")))
                continue
            fit_subjects, cal_subjects = split_subjects(frame.subject, subject, seed, cfg.calibration_fraction)
            fit = np.flatnonzero(frame.subject.isin(fit_subjects))
            cal = np.flatnonzero(frame.subject.isin(cal_subjects))
            test = np.flatnonzero(frame.subject == subject)
            validation_subject = fit_subjects[-1]
            inner_validation = np.flatnonzero(frame.subject == validation_subject)
            inner_fit = np.flatnonzero(frame.subject.isin(fit_subjects[:-1]))
            psd, kin = normalization(psd_raw, inner_fit), normalization(kin_raw, inner_fit)
            _, best_epoch = train_model(psd, kin, targets, inner_fit, seed, args.max_epochs, inner_validation)
            psd, kin = normalization(psd_raw, fit), normalization(kin_raw, fit)
            model, _ = train_model(psd, kin, targets, fit, seed, best_epoch)
            model.eval()
            with torch.no_grad():
                predicted = model(psd[test], kin[test]).numpy()
                calibrated = model(psd[cal], kin[cal]).numpy()
            radius = calibration_radius(np.abs(calibrated[:, 1] - frame.iloc[cal].delta_target.to_numpy()), cfg.interval_alpha)
            names = ["subject", "session", "timestamp_s", "forecast_end_s", "current_rating", "future_peak", "delta_target", "event", "event_time_s", "quality", "data_kind"]
            result = frame.iloc[test][names].copy().reset_index(drop=True)
            result["future_pred"], result["delta_pred"] = predicted.T
            result["delta_lower"] = np.clip(predicted[:, 1] - radius, 0, 1)
            result["delta_upper"] = np.clip(predicted[:, 1] + radius, 0, 1)
            result["uses_live_rating"], result["model"], result["seed"] = False, "fusion_cnn_lstm", seed
            result["alarm_raw"] = apply_warning_policy(result, cfg, gated=False)
            result["alarm_gated"] = apply_warning_policy(result, cfg, gated=True)
            result.to_csv(path, index=False)
            record = {"seed": seed, "test_subject": subject, "fit_subjects": fit_subjects, "calibration_subjects": cal_subjects,
                      "epoch_selection_subject": validation_subject, "selected_epochs": best_epoch,
                      "calibration_radius": radius, "architecture": "rebuilt dual spectral/kinematic CNN-LSTM; two forecast heads"}
            split_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
            outputs.append(result)
            splits.append(record)
            print(f"CNN-LSTM seed={seed} subject={subject}, epochs={best_epoch}, n={len(test)}", flush=True)
    predictions = pd.concat(outputs, ignore_index=True)
    predictions.to_csv(output / "predictions.csv", index=False)
    subject_metrics(predictions, cfg).to_csv(output / "subject_metrics.csv", index=False)
    (output / "split_manifest.json").write_text(json.dumps(splits, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
