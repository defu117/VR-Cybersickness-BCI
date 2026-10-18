# Forecast experiment report

Data kind: **PUBLIC**.

Synthetic runs verify software only. Public runs are retrospective prediction experiments, not evidence of symptom mitigation.

Scores are macro-averaged across held-out subjects after averaging seeds within each subject.

| Model | Policy | MAE | AP | Event recall | False alarms/min | Lead (s) | Interval coverage |
|---|---|---:|---:|---:|---:|---:|---:|
| eeg_ridge | gated | 0.2105 | 0.1865 | 0.0370 | 0.0804 | 3.5735 | 0.7892 |
| eeg_ridge | raw | 0.2105 | 0.1865 | 0.1749 | 0.8568 | 3.2148 | 0.7892 |
| fusion_cnn_lstm | gated | 0.2362 | 0.2012 | 0.0000 | 0.0000 | NA | 0.7511 |
| fusion_cnn_lstm | raw | 0.2362 | 0.2012 | 0.3425 | 2.7388 | 3.1100 | 0.7511 |
| fusion_cqr | gated | 0.1997 | 0.1257 | 0.0000 | 0.0000 | NA | 0.8064 |
| fusion_cqr | raw | 0.1997 | 0.1257 | 0.0000 | 0.0000 | NA | 0.8064 |
| fusion_hgb | gated | 0.1997 | 0.1603 | 0.0000 | 0.0000 | NA | 0.7044 |
| fusion_hgb | raw | 0.1997 | 0.1603 | 0.0000 | 0.0319 | NA | 0.7044 |
| fusion_ridge | gated | 0.2133 | 0.1914 | 0.0370 | 0.0903 | 2.0735 | 0.7808 |
| fusion_ridge | raw | 0.2133 | 0.1914 | 0.1687 | 0.9318 | 2.9060 | 0.7808 |
| fusion_state | gated | 0.1929 | 0.1257 | 0.0000 | 0.0000 | NA | NA |
| fusion_state | raw | 0.1929 | 0.1257 | 0.0000 | 0.0000 | NA | NA |
| hmd_ridge | gated | 0.1728 | 0.1553 | 0.0000 | 0.0078 | NA | 0.6785 |
| hmd_ridge | raw | 0.1728 | 0.1553 | 0.0000 | 0.0357 | NA | 0.6785 |
| oracle_rating_persistence | gated | 0.0758 | 0.1257 | 0.0000 | 0.0000 | NA | NA |
| oracle_rating_persistence | raw | 0.0758 | 0.1257 | 0.0000 | 0.0000 | NA | NA |
| time_hgb | gated | 0.1752 | 0.1925 | 0.0000 | 0.0000 | NA | 0.7297 |
| time_hgb | raw | 0.1752 | 0.1925 | 0.0000 | 0.0000 | NA | 0.7297 |

`oracle_rating_persistence` observes the current self-rating; it is a rating-available comparator, not a passive sensor-only model.
`paired_mae_bootstrap.json` additionally compares sensor forecasts with estimated-state persistence, HMD alone, and time alone. These descriptive intervals are not adjusted for multiple comparisons.
Intervals use pooled residuals from calibration subjects disjoint from training and test. Temporal dependence and distribution shift preclude a claimed distribution-free coverage guarantee.
Event recall merges consecutive positive target windows into one episode. Lead time is measured on matched emitted alerts; all-event recall and false alarms must be read alongside it.
Quality measures data completeness, not validated EEG artifact rejection. No effect size for reducing discomfort can be inferred from replay.
