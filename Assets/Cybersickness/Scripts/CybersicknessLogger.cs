using System;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace VRBCI.Cybersickness
{
    /// <summary>
    /// Writes a synchronized, analysis-friendly CSV stream for each VR session.
    /// The logger is intentionally independent of the BCI vendor SDK: an EEG
    /// stream can be joined later with the Unity timestamp and marker columns.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("VR BCI/Cybersickness Logger")]
    public sealed class CybersicknessLogger : MonoBehaviour
    {
        [Header("Tracking")]
        [SerializeField]
        Transform m_HeadTransform;

        [SerializeField]
        Transform m_RigTransform;

        [SerializeField, Min(0.02f)]
        float m_SampleInterval = 0.1f;

        [SerializeField]
        string m_SessionLabel = "vr_session";

        [SerializeField]
        bool m_AutoStart = true;

        [SerializeField]
        CybersicknessComfortController m_ComfortController;

        StreamWriter m_Writer;
        string m_CurrentFilePath;
        float m_SampleAccumulator;
        float m_PreviousSampleTime;
        Vector3 m_PreviousHeadPosition;
        Quaternion m_PreviousHeadRotation;
        Vector3 m_PreviousRigPosition;
        bool m_HasPreviousPose;
        int m_CurrentRating = -1;

        public bool IsRecording => m_Writer != null;
        public string CurrentFilePath => m_CurrentFilePath;

        void Awake()
        {
            ResolveTransforms();
            if (m_AutoStart)
                StartRecording();
        }

        void Update()
        {
            if (!IsRecording)
                return;

            m_SampleAccumulator += Time.unscaledDeltaTime;
            if (m_SampleAccumulator < m_SampleInterval)
                return;

            m_SampleAccumulator = 0f;
            WriteSample("sample", string.Empty);
        }

        void OnDestroy()
        {
            StopRecording();
        }

        public void StartRecording()
        {
            if (IsRecording)
                return;

            ResolveTransforms();
            string directory = Path.Combine(Application.persistentDataPath, "CybersicknessLogs");
            Directory.CreateDirectory(directory);

            string safeLabel = SanitizeFileName(m_SessionLabel);
            string timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss_fff", CultureInfo.InvariantCulture);
            m_CurrentFilePath = Path.Combine(directory, safeLabel + "_" + timestamp + ".csv");
            m_Writer = new StreamWriter(m_CurrentFilePath, false, new UTF8Encoding(false));
            m_Writer.WriteLine("row_type,unix_time_utc,unity_time_s,frame,scene,head_px,head_py,head_pz,head_qx,head_qy,head_qz,head_qw,head_linear_speed_mps,head_angular_speed_dps,rig_linear_speed_mps,frame_time_ms,fps,risk_raw,risk_smoothed,risk_level,intervention,rating,marker");

            m_SampleAccumulator = 0f;
            m_PreviousSampleTime = Time.unscaledTime;
            m_HasPreviousPose = false;
            WriteSample("marker", "session_start");
            m_Writer.Flush();

            Debug.Log("Cybersickness log started: " + m_CurrentFilePath);
        }

        public void StopRecording()
        {
            if (!IsRecording)
                return;

            WriteSample("marker", "session_end");
            m_Writer.Flush();
            m_Writer.Dispose();
            m_Writer = null;
            Debug.Log("Cybersickness log saved: " + m_CurrentFilePath);
        }

        public void RecordMarker(string marker)
        {
            if (!IsRecording)
                return;

            WriteSample("marker", marker);
            m_Writer.Flush();
        }

        public void SetSubjectiveRating(int rating)
        {
            m_CurrentRating = Mathf.Clamp(rating, 0, 10);
            RecordMarker("rating_" + m_CurrentRating.ToString(CultureInfo.InvariantCulture));
        }

        public void ClearSubjectiveRating()
        {
            m_CurrentRating = -1;
            RecordMarker("rating_cleared");
        }

        void ResolveTransforms()
        {
            if (m_HeadTransform == null && Camera.main != null)
                m_HeadTransform = Camera.main.transform;
            if (m_RigTransform == null && m_HeadTransform != null && m_HeadTransform.parent != null)
                m_RigTransform = m_HeadTransform.parent;
            if (m_ComfortController == null)
                m_ComfortController = GetComponent<CybersicknessComfortController>();
        }

        void WriteSample(string rowType, string marker)
        {
            if (!IsRecording)
                return;

            ResolveTransforms();
            float now = Time.unscaledTime;
            float dt = Mathf.Max(now - m_PreviousSampleTime, 0.0001f);
            float headLinearSpeed = 0f;
            float headAngularSpeed = 0f;
            float rigLinearSpeed = 0f;

            Vector3 headPosition = Vector3.zero;
            Quaternion headRotation = Quaternion.identity;
            if (m_HeadTransform != null)
            {
                headPosition = m_HeadTransform.position;
                headRotation = m_HeadTransform.rotation;
                if (m_HasPreviousPose)
                {
                    headLinearSpeed = Vector3.Distance(headPosition, m_PreviousHeadPosition) / dt;
                    headAngularSpeed = Quaternion.Angle(headRotation, m_PreviousHeadRotation) / dt;
                }
                m_PreviousHeadPosition = headPosition;
                m_PreviousHeadRotation = headRotation;
            }

            if (m_RigTransform != null && m_HasPreviousPose)
                rigLinearSpeed = Vector3.Distance(m_RigTransform.position, m_PreviousRigPosition) / dt;

            if (m_RigTransform != null)
                m_PreviousRigPosition = m_RigTransform.position;

            m_HasPreviousPose = true;
            m_PreviousSampleTime = now;

            float frameTimeMs = Time.unscaledDeltaTime * 1000f;
            float fps = 1f / Mathf.Max(Time.unscaledDeltaTime, 0.0001f);
            string riskRaw = m_ComfortController == null ? string.Empty : F(m_ComfortController.RawRisk);
            string riskSmoothed = m_ComfortController == null ? string.Empty : F(m_ComfortController.SmoothedRisk);
            string riskLevel = m_ComfortController == null ? string.Empty : m_ComfortController.CurrentRiskLevel.ToString();
            string intervention = m_ComfortController == null ? string.Empty : m_ComfortController.CurrentIntervention.ToString();
            string utc = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture);
            string scene = SceneManager.GetActiveScene().name;

            string[] fields =
            {
                rowType,
                utc,
                F(now),
                Time.frameCount.ToString(CultureInfo.InvariantCulture),
                scene,
                F(headPosition.x), F(headPosition.y), F(headPosition.z),
                F(headRotation.x), F(headRotation.y), F(headRotation.z), F(headRotation.w),
                F(headLinearSpeed), F(headAngularSpeed), F(rigLinearSpeed),
                F(frameTimeMs), F(fps), riskRaw, riskSmoothed, riskLevel, intervention,
                m_CurrentRating < 0 ? string.Empty : m_CurrentRating.ToString(CultureInfo.InvariantCulture),
                marker
            };

            for (int i = 0; i < fields.Length; i++)
            {
                if (i > 0)
                    m_Writer.Write(',');
                m_Writer.Write(EscapeCsv(fields[i]));
            }
            m_Writer.WriteLine();
        }

        static string F(float value)
        {
            return value.ToString("R", CultureInfo.InvariantCulture);
        }

        static string EscapeCsv(string value)
        {
            if (string.IsNullOrEmpty(value))
                return string.Empty;
            if (value.IndexOfAny(new[] { ',', '"', '\r', '\n' }) < 0)
                return value;
            return "\"" + value.Replace("\"", "\"\"") + "\"";
        }

        static string SanitizeFileName(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
                return "vr_session";
            foreach (char invalid in Path.GetInvalidFileNameChars())
                value = value.Replace(invalid, '_');
            return value.Trim();
        }
    }
}
