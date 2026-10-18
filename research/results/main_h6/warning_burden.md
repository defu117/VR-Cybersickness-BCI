# Hypothetical warning occupancy

Hold: 10s; only 3s monitored decision cells count in the denominator. Missing periods are not interpolated.
This is a replay-state calculation before controller smoothing and actuation. It is not observed slowing, time lost, or symptom improvement.

| Model | Policy | Warning active fraction |
|---|---|---:|
| eeg_ridge | gated | 0.0142 |
| eeg_ridge | raw | 0.1607 |
| fusion_cnn_lstm | gated | 0.0000 |
| fusion_cnn_lstm | raw | 0.4819 |
| fusion_cqr | gated | 0.0000 |
| fusion_cqr | raw | 0.0000 |
| fusion_hgb | gated | 0.0000 |
| fusion_hgb | raw | 0.0052 |
| fusion_ridge | gated | 0.0153 |
| fusion_ridge | raw | 0.1706 |
| fusion_state | gated | 0.0000 |
| fusion_state | raw | 0.0000 |
| hmd_ridge | gated | 0.0008 |
| hmd_ridge | raw | 0.0056 |
| oracle_rating_persistence | gated | 0.0000 |
| oracle_rating_persistence | raw | 0.0000 |
| time_hgb | gated | 0.0000 |
| time_hgb | raw | 0.0000 |
