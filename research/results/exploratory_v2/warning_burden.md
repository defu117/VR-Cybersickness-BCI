# Hypothetical warning occupancy

Hold: 10s; only 3s monitored decision cells count in the denominator. Missing periods are not interpolated.
This is a replay-state calculation before controller smoothing and actuation. It is not observed slowing, time lost, or symptom improvement.

| Model | Policy | Warning active fraction |
|---|---|---:|
| event_budget_0p1 | alarm | 0.0000 |
| event_budget_0p5 | alarm | 0.0150 |
| event_budget_1p0 | alarm | 0.0816 |
| event_fixed_0p5 | alarm | 0.0928 |
