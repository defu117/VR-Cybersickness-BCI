using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;

namespace VRBCI.Cybersickness
{
    /// <summary>Per-frame actuator trace and event stream, independent of pose sampling.</summary>
    [DisallowMultipleComponent]
    public sealed class CybersicknessActionRecorder : MonoBehaviour
    {
        StreamWriter m_Frames, m_Events;
        CybersicknessComfortController m_Controller;
        double m_Start, m_Origin, m_PreviousTime;
        float m_PlaybackSpeed, m_PreviousMultiplier;
        bool m_Tail, m_MonitorValid = true;
        readonly List<double[]> m_Intervals = new List<double[]>();
        public bool IsRecording => m_Frames != null;
        public double MonitoredSeconds { get; private set; }
        public double OccupiedSeconds { get; private set; }
        public double IntensitySeconds { get; private set; }
        public double TailSeconds { get; private set; }
        public double TailOccupiedSeconds { get; private set; }
        public double TailIntensitySeconds { get; private set; }
        public string OutputPrefix { get; private set; }

        public void Begin(CybersicknessComfortController controller, string prefix,
            double localStart, double sourceOrigin, float playbackSpeed)
        {
            Finish("replaced", true);
            m_Controller = controller;
            m_Start = m_PreviousTime = localStart;
            m_Origin = sourceOrigin;
            m_PlaybackSpeed = playbackSpeed;
            m_PreviousMultiplier = controller.AppliedSpeedMultiplier;
            m_Tail = false;
            m_MonitorValid = true;
            m_Intervals.Clear();
            MonitoredSeconds = OccupiedSeconds = IntensitySeconds = 0d;
            TailSeconds = TailOccupiedSeconds = TailIntensitySeconds = 0d;
            OutputPrefix = prefix;
            Directory.CreateDirectory(Path.GetDirectoryName(prefix));
            m_Frames = new StreamWriter(prefix + "_frames.csv");
            m_Events = new StreamWriter(prefix + "_events.csv");
            m_Frames.WriteLine("local_time_s,replay_elapsed_s,mapped_data_time_s,source_prediction_time_s,prediction_id,alarm_id,playback_speed,tail,external_enabled,external_stale,risk_raw,risk_smoothed,target_multiplier,applied_multiplier,dt_s,occupied_dt_s,intensity_dt_s,monitor_valid,valid_dt_s,valid_occupied_dt_s,valid_intensity_dt_s");
            m_Events.WriteLine("event,local_time_s,replay_elapsed_s,mapped_data_time_s,source_prediction_time_s,prediction_id,alarm_id,target_multiplier,applied_multiplier,source");
            controller.FrameAdvanced += RecordFrame;
            controller.TimingEventRecorded += RecordEvent;
            RecordFrame(controller);
        }

        public void BeginTail(double localTime)
        {
            // Close the last monitored interval at the actual phase boundary.
            if (m_Controller != null) RecordFrame(m_Controller);
            m_Tail = true;
            m_PreviousTime = localTime;
        }

        public void SetMonitoringValid(bool valid) { m_MonitorValid = valid; }
        public void AddMonitoringInterval(double sourceStart, double sourceEnd)
        {
            double start = m_Start + (sourceStart-m_Origin)/m_PlaybackSpeed;
            double end = m_Start + (sourceEnd-m_Origin)/m_PlaybackSpeed;
            if (m_Intervals.Count > 0 && start <= m_Intervals[m_Intervals.Count-1][1] + .000001)
                m_Intervals[m_Intervals.Count-1][1] = Math.Max(end,m_Intervals[m_Intervals.Count-1][1]);
            else m_Intervals.Add(new[]{start,end});
        }

        static double OccupiedFraction(double a, double b)
        {
            if (a < .99 && b < .99) return 1d;
            if (a >= .99 && b >= .99) return 0d;
            double crossing = (.99 - a) / (b - a);
            return a < .99 ? crossing : 1d - crossing;
        }

        void RecordFrame(CybersicknessComfortController controller)
        {
            if (!IsRecording) return;
            double now = controller.LocalTime;
            double dt = Math.Max(0d, now - m_PreviousTime);
            double multiplier = controller.AppliedSpeedMultiplier;
            double occupied = dt * OccupiedFraction(m_PreviousMultiplier, multiplier);
            double intensity = dt * (2d - m_PreviousMultiplier - multiplier) / 2d;
            double validDt=0d, validOccupied=0d, validIntensity=0d;
            if (!m_Tail && dt>0d)
                foreach(double[] interval in m_Intervals)
                {
                    double left=Math.Max(m_PreviousTime,interval[0]), right=Math.Min(now,interval[1]);
                    if(right<=left) continue;
                    double a=m_PreviousMultiplier+(multiplier-m_PreviousMultiplier)*(left-m_PreviousTime)/dt;
                    double b=m_PreviousMultiplier+(multiplier-m_PreviousMultiplier)*(right-m_PreviousTime)/dt;
                    validDt+=right-left;
                    validOccupied+=(right-left)*OccupiedFraction(a,b);
                    validIntensity+=(right-left)*(2d-a-b)/2d;
                }
            if (m_Tail) { TailSeconds += dt; TailOccupiedSeconds += occupied; TailIntensitySeconds += intensity; }
            else { MonitoredSeconds += validDt; OccupiedSeconds += validOccupied; IntensitySeconds += validIntensity; }
            m_Frames.WriteLine(string.Join(",", F(now), F(now-m_Start), F(m_Origin+(now-m_Start)*m_PlaybackSpeed),
                F(controller.ExternalRiskTimestamp), Q(controller.PredictionId), Q(controller.AlarmId), F(m_PlaybackSpeed),
                m_Tail ? "1" : "0", controller.ExternalRiskEnabled ? "1" : "0", controller.ExternalRiskStale ? "1" : "0",
                F(controller.RawRisk), F(controller.SmoothedRisk), F(controller.TargetSpeedMultiplier), F(multiplier),
                F(dt), F(occupied), F(intensity), m_MonitorValid && !m_Tail ? "1" : "0", F(validDt), F(validOccupied), F(validIntensity)));
            m_PreviousTime = now;
            m_PreviousMultiplier = (float)multiplier;
        }

        void RecordEvent(CybersicknessComfortController.TimingEvent item)
        {
            if (!IsRecording) return;
            m_Events.WriteLine(string.Join(",", item.type, F(item.localTime), F(item.localTime-m_Start),
                F(m_Origin+(item.localTime-m_Start)*m_PlaybackSpeed), F(item.sourceTimestamp),
                Q(item.predictionId), Q(item.alarmId), F(item.targetMultiplier), F(item.appliedMultiplier), Q(item.source)));
        }

        public void Finish(string reason, bool truncated)
        {
            if (!IsRecording) return;
            RecordFrame(m_Controller);
            m_Controller.FrameAdvanced -= RecordFrame;
            m_Controller.TimingEventRecorded -= RecordEvent;
            m_Frames.Dispose(); m_Events.Dispose();
            m_Frames = m_Events = null;
            string json = "{\"reason\":" + J(reason) + ",\"truncated\":" + (truncated ? "true" : "false") +
                ",\"playback_speed\":" + F(m_PlaybackSpeed) + ",\"source_origin_s\":" + F(m_Origin) +
                ",\"monitored_s\":" + F(MonitoredSeconds) + ",\"occupied_s\":" + F(OccupiedSeconds) +
                ",\"intensity_s\":" + F(IntensitySeconds) + ",\"tail_s\":" + F(TailSeconds) +
                ",\"tail_occupied_s\":" + F(TailOccupiedSeconds) + ",\"tail_intensity_s\":" + F(TailIntensitySeconds) +
                ",\"scope\":\"desktop software actuator trace; no symptom or XR display measurement\"}";
            File.WriteAllText(OutputPrefix + "_summary.json", json);
        }

        void OnDestroy() { Finish("destroyed", true); }
        static string F(double value) => value.ToString("R", CultureInfo.InvariantCulture);
        static string Q(string value) => "\"" + (value ?? "").Replace("\"", "\"\"") + "\"";
        static string J(string value) => "\"" + (value ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }
}
