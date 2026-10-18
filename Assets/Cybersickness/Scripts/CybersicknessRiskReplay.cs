using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;

namespace VRBCI.Cybersickness
{
    /// <summary>CSV replay with separate source/receipt clocks and a recorded recovery tail.</summary>
    [DefaultExecutionOrder(-100)]
    [DisallowMultipleComponent]
    [AddComponentMenu("VR BCI/Cybersickness Risk Replay")]
    public sealed class CybersicknessRiskReplay : MonoBehaviour
    {
        struct RiskSample
        {
            public double timestamp, sourceTimestamp, validUntil;
            public float risk, quality;
            public string source, predictionId, alarmId;
        }
        [Header("References")]
        [SerializeField] CybersicknessComfortController m_ComfortController;
        [Header("Input")]
        [SerializeField] TextAsset m_ReplayAsset;
        [SerializeField] string m_FilePath;
        [SerializeField] bool m_AutoPlay;
        [SerializeField] bool m_Loop;
        [SerializeField, Min(0.01f)] float m_PlaybackSpeed = 1f;
        [SerializeField] bool m_ResearchProfile = true;
        [SerializeField] bool m_RecordTiming = true;
        [SerializeField] string m_OutputDirectory;
        readonly List<RiskSample> m_Samples = new List<RiskSample>();
        float m_PlayStartTime, m_TailStartTime, m_LastAlarmTime = float.NegativeInfinity;
        float m_EndpointRisk, m_EndpointQuality;
        double m_SourceOrigin, m_LastValidUntil;
        string m_LastAlarmId = "";
        int m_NextSampleIndex;
        bool m_IsPlaying, m_InTail, m_Simulated;
        CybersicknessActionRecorder m_Recorder;
        public bool IsPlaying => m_IsPlaying;
        public bool IsRecoveringTail => m_InTail;
        public int CurrentSampleIndex => m_NextSampleIndex;
        public int SampleCount => m_Samples.Count;
        public string LastReplayStatus { get; private set; } = "not_started";
        public string LastOutputPrefix => m_Recorder == null ? "" : m_Recorder.OutputPrefix;

        void Awake() { ResolveReferences(); LoadSamples(); }
        void Start() { if (m_AutoPlay) StartReplay(); }
        void Update() { if (!m_Simulated) AdvanceReplayAt(Time.unscaledTime); }

        public void AdvanceReplayAt(float now)
        {
            if (!m_IsPlaying || m_ComfortController == null) return;
            if (m_Simulated) m_ComfortController.SetSimulationReceiptTime(now);
            double elapsed = (now - m_PlayStartTime) * m_PlaybackSpeed;
            if (!m_InTail)
            {
                while (m_NextSampleIndex < m_Samples.Count && m_Samples[m_NextSampleIndex].timestamp <= elapsed + .0001)
                {
                    RiskSample sample = m_Samples[m_NextSampleIndex++];
                    m_ComfortController.SetExternalRiskSample(sample.risk, sample.quality, sample.source,
                        sample.sourceTimestamp, sample.predictionId, sample.alarmId);
                    m_EndpointRisk = sample.risk; m_EndpointQuality = sample.quality;
                    m_LastValidUntil = sample.validUntil;
                    m_Recorder?.AddMonitoringInterval(sample.sourceTimestamp, sample.validUntil);
                    if (!string.IsNullOrEmpty(sample.alarmId) && sample.alarmId != m_LastAlarmId)
                    {
                        m_LastAlarmId = sample.alarmId;
                        m_LastAlarmTime = m_PlayStartTime + (float)sample.timestamp / m_PlaybackSpeed;
                    }
                }
                m_Recorder?.SetMonitoringValid(m_SourceOrigin + elapsed <= m_LastValidUntil + .0001);
                if (m_NextSampleIndex < m_Samples.Count) return;
                m_InTail = true;
                m_TailStartTime = now;
                m_Recorder?.BeginTail(now);
                LastReplayStatus = "recovering_tail";
                return;
            }
            bool remainingHold = m_EndpointRisk >= .35f && now < m_LastAlarmTime + 10f / m_PlaybackSpeed;
            m_ComfortController.SetExternalRiskSample(remainingHold ? m_EndpointRisk : 0f,
                remainingHold ? m_EndpointQuality : 1f, "replay_tail", m_SourceOrigin + elapsed,
                "tail", remainingHold ? m_LastAlarmId : "");
            bool recovered = !remainingHold && !m_ComfortController.EmergencyStopped &&
                m_ComfortController.CurrentIntervention == CybersicknessComfortController.Intervention.None &&
                m_ComfortController.AppliedSpeedMultiplier >= .99f && m_ComfortController.SmoothedRisk < .35f;
            if (recovered || now - m_TailStartTime >= 30f)
            {
                FinishReplay(recovered ? "recovered" : "tail_timeout", !recovered);
                if (m_Loop) StartReplayAt(now, m_Simulated);
            }
        }

        public bool StartReplay() => StartReplayAt(Time.unscaledTime, false);
        public bool StartReplayAt(float now, bool simulated, string outputPrefix = null)
        {
            ResolveReferences();
            if (m_IsPlaying) FinishReplay("replaced", true);
            if (m_Samples.Count == 0 && !LoadSamples()) return false;
            if (m_ComfortController == null) return false;
            m_Simulated = simulated;
            m_ComfortController.ResetForReplay(simulated, now);
            if (m_ResearchProfile) m_ComfortController.ConfigureResearchReplay(simulated);
            m_NextSampleIndex = 0; m_PlayStartTime = now;
            m_InTail = false; m_IsPlaying = true;
            m_LastAlarmId = ""; m_LastAlarmTime = float.NegativeInfinity;
            m_EndpointRisk = 0f; m_EndpointQuality = 1f;
            m_LastValidUntil = m_SourceOrigin;
            LastReplayStatus = "playing";
            if (m_RecordTiming)
            {
                m_Recorder = GetComponent<CybersicknessActionRecorder>();
                if (m_Recorder == null) m_Recorder = gameObject.AddComponent<CybersicknessActionRecorder>();
                string directory = string.IsNullOrWhiteSpace(m_OutputDirectory)
                    ? Path.Combine(Application.persistentDataPath, "CybersicknessLogs") : m_OutputDirectory;
                string prefix = outputPrefix ?? Path.Combine(directory,
                    "replay_" + DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff") + "_" + Guid.NewGuid().ToString("N").Substring(0, 8));
                m_Recorder.Begin(m_ComfortController, prefix, now, m_SourceOrigin, m_PlaybackSpeed);
            }
            return true;
        }

        public void StopReplay() { FinishReplay("manual_stop", true); }
        void OnDestroy() { FinishReplay("destroyed", true); }
        void FinishReplay(string reason, bool truncated)
        {
            m_IsPlaying = false; m_InTail = false;
            LastReplayStatus = reason;
            m_Recorder?.Finish(reason, truncated);
            m_ComfortController?.ClearExternalRisk();
        }
        public void SetReplayAsset(TextAsset asset)
        {
            if (m_IsPlaying) FinishReplay("input_changed", true);
            m_ReplayAsset = asset; m_Samples.Clear(); LoadSamples();
        }

        bool LoadSamples()
        {
            m_Samples.Clear();
            string text = m_ReplayAsset != null ? m_ReplayAsset.text :
                !string.IsNullOrWhiteSpace(m_FilePath) && File.Exists(m_FilePath) ? File.ReadAllText(m_FilePath) : null;
            if (string.IsNullOrWhiteSpace(text)) return false;
            string[] lines = text.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
            if (lines.Length < 2) return false;
            string[] header = lines[0].Split(',');
            int tc = FindColumn(header, "timestamp_s", "timestamp", "time_s", "unity_time_s");
            int rc = FindColumn(header, "risk", "risk_smoothed", "risk_raw");
            int qc = FindColumn(header, "quality", "external_quality");
            int sc = FindColumn(header, "source", "risk_source");
            int pc = FindColumn(header, "prediction_id");
            int ac = FindColumn(header, "alarm_id");
            int oc = FindColumn(header, "source_timestamp_s");
            int vc = FindColumn(header, "monitor_until_s");
            if (tc < 0 || rc < 0) return false;
            bool first = true;
            double firstTime = 0d, previous = double.NegativeInfinity;
            string legacyAlarm = "";
            for (int i = 1; i < lines.Length; i++)
            {
                string[] fields = lines[i].Split(',');
                if (!TryNumber(fields, tc, out double timestamp) || !TryNumber(fields, rc, out double risk)) continue;
                double quality = 1d;
                if (qc >= 0 && !TryNumber(fields, qc, out quality)) continue;
                double sourceTime = timestamp;
                if (oc >= 0 && !TryNumber(fields, oc, out sourceTime)) continue;
                double validUntil = sourceTime + 3d;
                if (vc >= 0 && !TryNumber(fields, vc, out validUntil)) continue;
                if (timestamp <= previous) { m_Samples.Clear(); return false; }
                if (first) { first = false; firstTime = timestamp; m_SourceOrigin = sourceTime; }
                previous = timestamp;
                string prediction = Get(fields, pc, "legacy_prediction_" + i);
                if (risk >= .35d && legacyAlarm == "") legacyAlarm = "legacy_alarm_" + i;
                if (risk < .35d) legacyAlarm = "";
                m_Samples.Add(new RiskSample { timestamp = timestamp-firstTime, sourceTimestamp = sourceTime, validUntil = validUntil,
                    risk = Mathf.Clamp01((float)risk), quality = Mathf.Clamp01((float)quality),
                    source = Get(fields, sc, "replay"), predictionId = prediction,
                    alarmId = ac >= 0 ? Get(fields, ac, "") : legacyAlarm });
            }
            return m_Samples.Count > 0;
        }
        void ResolveReferences()
        {
            if (m_ComfortController == null) m_ComfortController = GetComponent<CybersicknessComfortController>();
        }
        static string Get(string[] fields, int index, string fallback)
            => index >= 0 && index < fields.Length && !string.IsNullOrWhiteSpace(fields[index]) ? fields[index].Trim() : fallback;
        static bool TryNumber(string[] fields, int column, out double value)
        {
            value = 0d;
            return column >= 0 && column < fields.Length && double.TryParse(fields[column], NumberStyles.Float,
                CultureInfo.InvariantCulture, out value) && !double.IsNaN(value) && !double.IsInfinity(value);
        }
        static int FindColumn(string[] header, params string[] names)
        {
            for (int i = 0; i < header.Length; i++)
                foreach (string name in names)
                    if (string.Equals(header[i].Trim(), name, StringComparison.OrdinalIgnoreCase)) return i;
            return -1;
        }
    }
}
