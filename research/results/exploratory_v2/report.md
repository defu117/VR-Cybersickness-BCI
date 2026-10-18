# Exploratory direct-event classification

Specified after observing the negative v1 result. These results require independent validation.
Scores are class-weighted rankings, not calibrated probabilities. Budgets constrain calibration subjects empirically; they are not guarantees on unseen users.
Single-window confirmation and a 12-second cooldown are used. Seeds are averaged within participants before participant macro averaging.

| Policy | Event AP | Episode recall | False warnings/min | Mean of participant median lead (s) |
|---|---:|---:|---:|---:|
| event_budget_0p1 | 0.1906 | 0.0000 | 0.0000 | NA |
| event_budget_0p5 | 0.1906 | 0.0123 | 0.0765 | 4.2820 |
| event_budget_1p0 | 0.1906 | 0.0667 | 0.4668 | 3.6885 |
| event_fixed_0p5 | 0.1906 | 0.0991 | 0.4715 | 2.7621 |
