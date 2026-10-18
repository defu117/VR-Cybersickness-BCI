# Offline EEG and risk replay

## Independent dataset and execution-aware evaluation (21-27)

Scripts `21` and `22` acquire the pinned Ryu/Kim author snapshot and audit
headerless rows, timestamps, static identity conflicts and native FMS labels.
`23` compares two calibration objectives under the same false-alarm and
actuator-occupancy budgets. `24` recomputes Unity frame/event telemetry; `25`
generates explicitly synthetic software fixtures; `26` merges and audits the
complete grouped seed grid; `27` benchmarks a fixed held-out model's scoring
cost. See `../research/action_v3_protocol.md` and `../research/README.md`.

The replay CSV retains the four legacy columns and optionally adds
`prediction_id`, `alarm_id`, `source_timestamp_s`, `monitor_until_s` and
`raw_record_timestamp_s`. Heartbeats repeat IDs; source time is never replaced
by normalized playback time. Unity logs action timing and per-frame multipliers
and completes a separate recovery tail. This is software execution evidence.

## Research forecasting pipeline

The publication-oriented causal forecasting workflow starts at
`08_prepare_forecast.py`, not at the teaching scripts below. See
`../research/README.md` for data acquisition, frozen protocol, grouped
forecast evaluation, warning metrics, and Unity export commands. The research
pipeline keeps subjective ratings continuous and audits time availability.

## Earlier educational pipeline (00-07)

The commands below describe the earlier teaching workflow. They do not reproduce
the research forecast experiment or provide symptom-mitigation evidence.
This teaching pipeline starts without a BCI vendor SDK. It accepts a raw
CSV with `timestamp_s`, optional `subject`/`session`/`label`, and channel
columns beginning with `ch` or `eeg_`. The output risk replay format is:

```csv
timestamp_s,risk,quality,source
0.0,0.2,1.0,replay
1.0,0.7,0.95,replay
```

## Smoke test

From this `analysis` directory:

```powershell
python 00_generate_synthetic.py --output data/synthetic_eeg.csv
python 01_inspect_data.py data/synthetic_eeg.csv
python 02_preprocess_eeg.py data/synthetic_eeg.csv --output data/preprocessed_eeg.npz
python 03_extract_features.py data/preprocessed_eeg.npz --output data/eeg_features.csv
```

The synthetic file contains one subject, so it is suitable for checking the
reader and feature stages but not for grouped model validation. Add at least
two subjects/sessions before running `05_train_baselines.py`.

## HMD alignment and models

```powershell
python 04_align_hmd_eeg.py --hmd path/to/unity.csv --eeg data/eeg_features.csv --output data/aligned_features.csv
python 05_train_baselines.py data/aligned_features.csv --output data/model_results.csv --predictions data/predictions.csv
python 06_evaluate_subjectwise.py data/predictions.csv --output data/subjectwise_results.csv
python 07_export_risk_replay.py data/predictions.csv --output data/risk_replay.csv
```

The model script reports HMD-only, EEG-only, fusion and quality-gated fusion
when the corresponding columns exist. It uses grouped folds by subject/session
to avoid leaking adjacent EEG windows between train and test.

This is an educational baseline. It does not produce a clinical diagnosis and
does not replace device-specific validation, artifact inspection, or ethics and
safety review.
