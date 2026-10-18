"""Deterministic desktop controller model. Validate against Unity before use.

Source symptom trajectories are never changed by simulated actuator output.
The model measures action opportunity, not a counterfactual treatment effect.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import json
from collections import OrderedDict
from scipy.signal import lfilter
from .alerts import score_alerts

def episode_times(frame, window_s=3.):
    frame = frame.sort_values("timestamp_s")
    times = frame.timestamp_s.to_numpy(dtype=float)
    positive = frame.event.to_numpy(dtype=bool)
    crossings = frame.event_time_s.to_numpy(dtype=float)
    events, i = [], 0
    while i < len(times):
        if positive[i]:
            j = i
            while j+1 < len(times) and positive[j+1] and np.isclose(times[j+1]-times[j], window_s):
                j += 1
            events.append(float(np.nanmin(crossings[i:j+1])))
            i = j
        i += 1
    return np.asarray(events)

def occupied_fraction(a, b, threshold=.99):
    a, b = np.asarray(a), np.asarray(b)
    result = ((a < threshold) & (b < threshold)).astype(float)
    crossing = (a < threshold) != (b < threshold)
    fraction = np.divide(threshold-a, b-a, out=np.zeros_like(a, dtype=float), where=crossing)
    return np.where(crossing, np.where(a < threshold, fraction, 1-fraction), result)

_SIMULATION_CACHE = OrderedDict()

def simulate_session(frame, alarms, settings, return_trace=False):
    if return_trace:
        return _simulate_session(frame, alarms, settings, True)
    key = (tuple(frame.timestamp_s),tuple(frame.quality),tuple(np.asarray(alarms,dtype=bool)),
           json.dumps({k:settings[k] for k in ("controller","window_s","hold_s")},sort_keys=True))
    if key in _SIMULATION_CACHE:
        _SIMULATION_CACHE.move_to_end(key)
        return _SIMULATION_CACHE[key]
    result = _simulate_session(frame, alarms, settings, False)
    _SIMULATION_CACHE[key] = result
    if len(_SIMULATION_CACHE)>4096:
        _SIMULATION_CACHE.popitem(last=False)
    return result

def _simulate_session(frame, alarms, settings, return_trace=False):
    """60-Hz research profile; heartbeat=0.1s, missing streams expire after 2s.

    No-head fallback is the same frame-risk-only branch used in desktop Unity.
    Real HMD-motion fallback is outside the scope of this offline model.
    """
    cfg = settings["controller"]
    frame = frame.sort_values("timestamp_s").reset_index(drop=True)
    original = frame.timestamp_s.to_numpy(dtype=float)
    origin = original[0]
    decisions = original-origin
    alarms = np.asarray(alarms, dtype=bool)
    alarm_times = decisions[alarms]
    if not len(alarm_times) and not return_trace:
        return {"monitor_s":len(decisions)*settings["window_s"],"occupied_s":0.,"intensity_s":0.,
                "tail_s":0.,"tail_occupied_s":0.,"tail_intensity_s":0.,"alarm_ready_times":np.array([]),"truncated":False}
    stop = decisions[-1] + settings["window_s"]
    dt = cfg["step_s"]
    clock = np.arange(1, int(np.ceil((stop+cfg["tail_s"])/dt))+1) * dt
    # Feed the same heartbeat protocol as the exporter. Silence is not a zero-risk sample.
    hb = np.arange(0, stop+.050001, .1)
    pi = np.searchsorted(decisions, hb+1e-8, side="right")-1
    pi = np.maximum(pi, 0)
    valid = hb-decisions[pi] <= settings["window_s"]+1e-8
    segments = np.cumsum(np.r_[0, np.diff(decisions) > settings["window_s"]+1e-8])
    ai = np.searchsorted(alarm_times, hb+1e-8, side="right")-1
    if len(alarm_times):
        alarm_rows = np.flatnonzero(alarms)
        active = (ai >= 0) & (hb < alarm_times[np.maximum(ai,0)]+settings["hold_s"]-1e-8)
        active &= segments[pi] == segments[alarm_rows[np.maximum(ai,0)]]
    else:
        active = np.zeros(len(hb), dtype=bool)
    last_valid = np.maximum.accumulate(np.where(valid, np.arange(len(hb)), -1))
    hi = np.clip(np.searchsorted(hb, clock+1e-6, side="right")-1, 0, len(hb)-1)
    hi = last_valid[hi]
    quality = frame.quality.to_numpy(dtype=float)[pi[np.maximum(hi,0)]]
    external = (hi >= 0) & (clock-hb[np.maximum(hi,0)] <= cfg["timeout_s"]+1e-6) & (quality >= cfg["min_external_quality"])
    fallback = .2 * np.clip((dt*1000.-1000./72.)/(33.-1000./72.), 0, 1)
    raw = np.where(external, np.where(active[np.maximum(hi,0)], .7, 0.), fallback)
    tail = clock >= stop-1e-6
    remaining = np.zeros(len(clock), dtype=bool)
    if len(alarm_times) and active[-1]:
        remaining = clock < alarm_times[-1]+settings["hold_s"]-1e-6
    raw[tail] = np.where(remaining[tail], .7, 0.)
    alpha = 1.-np.exp(-dt/cfg["smoothing_s"])
    smoothed = lfilter([alpha], [1., -(1.-alpha)], raw)
    target = np.ones(len(clock))
    current_mode, value, started, last_change = 0, 1., -np.inf, -np.inf
    consecutive_low = consecutive_high = 0
    cadence = max(1, int(np.ceil(cfg["decision_s"]/dt-1e-6)))
    previous = 0
    changes = []
    for i in range(cadence-1, len(clock), cadence):
        target[previous:i] = value
        now, risk = clock[i], smoothed[i]
        if risk < .35:
            consecutive_high = 0
            consecutive_low += 1
            if (now-started >= cfg["min_duration_s"]-1e-6 and consecutive_low >= cfg["confirmation_windows"]
                    and now-last_change >= cfg["recovery_hold_s"]-1e-6 and current_mode != 0):
                value, current_mode, last_change = 1., 0, now
                changes.append((i, value))
        else:
            consecutive_low = 0
            consecutive_high += 1
            mode = 2 if risk >= .6 else 1
            new_value = .25 if risk >= .8 else .5 if risk >= .6 else .75
            if (consecutive_high >= cfg["confirmation_windows"] and
                (now-last_change >= cfg["change_cooldown_s"]-1e-6 or mode != current_mode) and
                (mode != current_mode or value != new_value)):
                if current_mode == 0:
                    started = now
                value, current_mode, last_change = new_value, mode, now
                changes.append((i, value))
        target[i] = value
        previous = i+1
    target[previous:] = value
    applied = np.ones(len(clock))
    boundaries = np.r_[0, np.flatnonzero(np.diff(target) != 0)+1, len(clock)]
    prior = 1.
    for left, right in zip(boundaries[:-1], boundaries[1:]):
        desired = target[left]
        distance = np.arange(1, right-left+1)*dt/cfg["speed_duration_s"]
        applied[left:right] = prior+np.sign(desired-prior)*np.minimum(distance, abs(desired-prior))
        prior = applied[right-1]
    # Recovery is checked by Replay before this frame advances the controller.
    previous_applied = np.r_[1., applied[:-1]]
    previous_target = np.r_[1., target[:-1]]
    previous_risk = np.r_[0., smoothed[:-1]]
    finished = np.flatnonzero(tail & ~remaining & (previous_applied >= .99) & (previous_target == 1.) & (previous_risk < .35))
    end_index = int(finished[0]) if len(finished) else len(clock)
    clock, raw, smoothed, target, applied, tail = [x[:end_index] for x in (clock,raw,smoothed,target,applied,tail)]
    previous_applied = np.r_[1., applied[:-1]]
    fractions = occupied_fraction(previous_applied, applied, cfg["occupancy_threshold"])
    intensity = dt*(2.-previous_applied-applied)/2.
    pred_index = np.maximum(0, np.searchsorted(decisions, clock-1e-6, side="right")-1)
    monitored = (clock-decisions[pred_index] <= settings["window_s"]+1e-6) & ~tail
    # The source monitoring interval includes its right endpoint and excludes the initial zero-duration row.
    monitored |= np.isclose(clock, stop, atol=1e-6)
    monitoring_s = float(monitored.sum()*dt)
    # Nominal windows are disjoint; use exact interval duration for the denominator.
    expected_monitoring = len(decisions)*settings["window_s"]
    ready = []
    for alarm in alarm_times:
        match = np.flatnonzero((clock >= alarm-1e-6) & (applied <= cfg["effective_threshold"]+1e-7))
        ready.append(float(clock[match[0]]+origin) if len(match) else np.inf)
    stats = {"monitor_s": float(expected_monitoring),
             "occupied_s": float((fractions*dt)[monitored].sum()),
             "intensity_s": float(intensity[monitored].sum()),
             "tail_s": float(tail.sum()*dt),
             "tail_occupied_s": float((fractions*dt)[tail & ~monitored].sum()),
             "tail_intensity_s": float(intensity[tail & ~monitored].sum()),
             "alarm_ready_times": np.asarray(ready), "truncated": not bool(len(finished))}
    if return_trace:
        stats["trace"] = pd.DataFrame({"time_s": clock, "risk_raw":raw,"risk_smoothed":smoothed,
            "target_multiplier":target,"applied_multiplier":applied,"monitor_valid":monitored,"tail":tail})
    return stats

def evaluate_actions(frame, scores, threshold, settings, return_details=False):
    alarm_flags = score_alerts(frame, scores, threshold, settings["cooldown_s"], settings["min_quality"])
    records = []
    for subject, positions in frame.groupby("subject", sort=False).indices.items():
        part = frame.iloc[positions]
        all_events = matched = useful = false = redundant = count = 0
        monitored = occupied = intensity = tail_occupied = tail_intensity = 0.
        leads, usable_leads = [], []
        for _, indices in part.groupby("session", sort=False).indices.items():
            absolute = np.asarray(positions)[indices]
            order = np.argsort(frame.iloc[absolute].timestamp_s.to_numpy())
            absolute = absolute[order]
            session = frame.iloc[absolute]
            alarms = alarm_flags[absolute]
            sim = simulate_session(session, alarms, settings)
            events = episode_times(session, settings["window_s"])
            all_events += len(events)
            used, used_usable = set(), set()
            for k, index in enumerate(np.flatnonzero(alarms)):
                now = float(session.timestamp_s.iloc[index])
                count += 1
                candidates = [i for i,e in enumerate(events) if i not in used and 0 < e-now <= settings["horizon_s"]+1e-8]
                if candidates:
                    i = min(candidates, key=lambda x: events[x]); used.add(i)
                    matched += 1; leads.append(events[i]-now)
                elif not session.event.iloc[index]:
                    false += 1
                else:
                    redundant += 1
                candidates = [i for i,e in enumerate(events) if i not in used_usable and
                    0 < e-now <= settings["horizon_s"]+1e-8 and e-sim["alarm_ready_times"][k] >= settings["minimum_usable_lead_s"]-1e-8]
                if candidates:
                    i=min(candidates,key=lambda x:events[x]); used_usable.add(i)
                    useful += 1; usable_leads.append(events[i]-sim["alarm_ready_times"][k])
            monitored += sim["monitor_s"]; occupied += sim["occupied_s"]; intensity += sim["intensity_s"]
            tail_occupied += sim["tail_occupied_s"]; tail_intensity += sim["tail_intensity_s"]
        records.append({"subject":subject,"events":all_events,"alarms":count,"matched":matched,"usable_matched":useful,
            "event_recall":matched/all_events if all_events else np.nan,
            "usable_recall":useful/all_events if all_events else np.nan,
            "false_alarms":false,"redundant_alarms":redundant,"false_alarms_per_min":false*60./monitored,
            "occupied_fraction":occupied/monitored,"occupied_s":occupied,"intensity_s":intensity,"monitor_s":monitored,
            "tail_occupied_s":tail_occupied,"tail_intensity_s":tail_intensity,
            "median_lead_s":float(np.median(leads)) if leads else np.nan,
            "median_usable_lead_s":float(np.median(usable_leads)) if usable_leads else np.nan})
    result = pd.DataFrame(records)
    summary = {key:float(result[key].mean()) for key in ("event_recall","usable_recall","false_alarms_per_min","occupied_fraction")}
    if return_details:
        return summary, result, alarm_flags
    return summary
