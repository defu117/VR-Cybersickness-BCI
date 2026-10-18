# Forecast experiment report

Data kind: **PUBLIC**.

Synthetic runs verify software only. Public runs are retrospective prediction experiments, not evidence of symptom mitigation.

Scores are macro-averaged across held-out subjects after averaging seeds within each subject.

| Model | Policy | MAE | AP | Event recall | False alarms/min | Lead (s) | Interval coverage |
|---|---|---:|---:|---:|---:|---:|---:|
| fusion_cqr | gated | 0.1850 | 0.1493 | 0.0000 | 0.0000 | NA | 0.8579 |
| fusion_cqr | raw | 0.1850 | 0.1493 | 0.0000 | 0.0000 | NA | 0.8579 |
| fusion_hgb | gated | 0.1850 | 0.1698 | 0.0000 | 0.0000 | NA | 0.7375 |
| fusion_hgb | raw | 0.1850 | 0.1698 | 0.0000 | 0.0097 | NA | 0.7375 |
| oracle_rating_persistence | gated | 0.0298 | 0.1493 | 0.0000 | 0.0000 | NA | NA |
| oracle_rating_persistence | raw | 0.0298 | 0.1493 | 0.0000 | 0.0000 | NA | NA |

`oracle_rating_persistence` observes the current self-rating; it is a rating-available comparator, not a passive sensor-only model.
`paired_mae_bootstrap.json` additionally compares sensor forecasts with estimated-state persistence, HMD alone, and time alone. These descriptive intervals are not adjusted for multiple comparisons.
Intervals use pooled residuals from calibration subjects disjoint from training and test. Temporal dependence and distribution shift preclude a claimed distribution-free coverage guarantee.
Event recall merges consecutive positive target windows into one episode. Lead time is measured on matched emitted alerts; all-event recall and false alarms must be read alongside it.
Quality measures data completeness, not validated EEG artifact rejection. No effect size for reducing discomfort can be inferred from replay.
