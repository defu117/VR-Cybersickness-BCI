using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;

namespace VRBCI.Cybersickness
{
    /// <summary>
    /// Replays a CSV risk stream into CybersicknessComfortController.
    /// Expected columns are timestamp_s (or timestamp), risk, quality and source.
    /// It deliberately uses the same public API as a future EEG/LSL adapter.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("VR BCI/Cybersickness Risk Replay")]
    public sealed class CybersicknessRiskReplay : MonoBehaviour
    {
        [Serializable]
        struct RiskSample
        {
            public double timestamp;
            public float risk;
            public float quality;
            public string source;
        }

        [Header("References")]
        [SerializeField] CybersicknessComfortController m_ComfortController;

        [Header("Input")]
        [SerializeField] TextAsset m_ReplayAsset;
        [SerializeField] string m_FilePath;
        [SerializeField] bool m_AutoPlay;
        [SerializeField] bool m_Loop;
        [SerializeField, Min(0.01f)] float m_PlaybackSpeed = 1f;

        readonly List<RiskSample> m_Samples = new List<RiskSample>();
        float m_PlayStartTime;
        int m_NextSampleIndex;
        bool m_IsPlaying;

        public bool IsPlaying => m_IsPlaying;
        public int CurrentSampleIndex => m_NextSampleIndex;
        public int SampleCount => m_Samples.Count;

        void Awake()
        {
            ResolveReferences();
            LoadSamples();
        }

        void Start()
        {
            if (m_AutoPlay)
                StartReplay();
        }

        void Update()
        {
            if (!m_IsPlaying || m_Samples.Count == 0 || m_ComfortController == null)
                return;

            double elapsed = (Time.unscaledTime - m_PlayStartTime) * m_PlaybackSpeed;
            while (m_NextSampleIndex < m_Samples.Count && m_Samples[m_NextSampleIndex].timestamp <= elapsed)
            {
                RiskSample sample = m_Samples[m_NextSampleIndex++];
                m_ComfortController.SetExternalRisk(sample.risk, sample.quality, sample.source, sample.timestamp);
            }

            if (m_NextSampleIndex >= m_Samples.Count)
            {
                if (m_Loop)
                    StartReplay();
                else
                    StopReplay();
            }
        }

        public bool StartReplay()
        {
            ResolveReferences();
            if (m_Samples.Count == 0 && !LoadSamples())
                return false;

            m_NextSampleIndex = 0;
            m_PlayStartTime = Time.unscaledTime;
            m_IsPlaying = true;
            if (m_ComfortController != null)
                m_ComfortController.ClearExternalRisk();
            return true;
        }

        public void StopReplay()
        {
            m_IsPlaying = false;
            if (m_ComfortController != null)
                m_ComfortController.ClearExternalRisk();
        }

        public void SetReplayAsset(TextAsset asset)
        {
            m_ReplayAsset = asset;
            m_Samples.Clear();
            LoadSamples();
        }

        bool LoadSamples()
        {
            m_Samples.Clear();
            string text = null;
            if (m_ReplayAsset != null)
                text = m_ReplayAsset.text;
            else if (!string.IsNullOrWhiteSpace(m_FilePath) && File.Exists(m_FilePath))
                text = File.ReadAllText(m_FilePath);

            if (string.IsNullOrWhiteSpace(text))
                return false;

            string[] lines = text.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
            if (lines.Length < 2)
                return false;

            string[] header = SplitCsvLine(lines[0]);
            int timeColumn = FindColumn(header, "timestamp_s", "timestamp", "time_s", "unity_time_s");
            int riskColumn = FindColumn(header, "risk", "risk_smoothed", "risk_raw");
            int qualityColumn = FindColumn(header, "quality", "external_quality");
            int sourceColumn = FindColumn(header, "source", "risk_source");
            if (timeColumn < 0 || riskColumn < 0)
            {
                Debug.LogError("Cybersickness risk replay requires timestamp_s/timestamp and risk columns.");
                return false;
            }

            double firstTimestamp = 0d;
            bool hasFirstTimestamp = false;
            for (int i = 1; i < lines.Length; i++)
            {
                string[] fields = SplitCsvLine(lines[i]);
                if (fields.Length <= Mathf.Max(timeColumn, riskColumn))
                    continue;
                if (!double.TryParse(fields[timeColumn], NumberStyles.Float, CultureInfo.InvariantCulture, out double timestamp) ||
                    !float.TryParse(fields[riskColumn], NumberStyles.Float, CultureInfo.InvariantCulture, out float risk))
                    continue;

                if (!hasFirstTimestamp)
                {
                    firstTimestamp = timestamp;
                    hasFirstTimestamp = true;
                }

                float quality = 1f;
                if (qualityColumn >= 0 && qualityColumn < fields.Length)
                    float.TryParse(fields[qualityColumn], NumberStyles.Float, CultureInfo.InvariantCulture, out quality);
                string source = sourceColumn >= 0 && sourceColumn < fields.Length && !string.IsNullOrWhiteSpace(fields[sourceColumn])
                    ? fields[sourceColumn]
                    : "replay";

                m_Samples.Add(new RiskSample
                {
                    timestamp = Math.Max(0d, timestamp - firstTimestamp),
                    risk = Mathf.Clamp01(risk),
                    quality = Mathf.Clamp01(quality),
                    source = source
                });
            }

            m_Samples.Sort((a, b) => a.timestamp.CompareTo(b.timestamp));
            return m_Samples.Count > 0;
        }

        void ResolveReferences()
        {
            if (m_ComfortController == null)
                m_ComfortController = GetComponent<CybersicknessComfortController>();
        }

        static int FindColumn(string[] header, params string[] names)
        {
            for (int i = 0; i < header.Length; i++)
                for (int j = 0; j < names.Length; j++)
                    if (string.Equals(header[i].Trim(), names[j], StringComparison.OrdinalIgnoreCase))
                        return i;
            return -1;
        }

        static string[] SplitCsvLine(string line)
        {
            // Replay exports are intentionally simple and contain no quoted commas.
            return line.Split(',');
        }
    }
}
