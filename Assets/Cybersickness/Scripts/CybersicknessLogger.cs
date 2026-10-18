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
    /// The logger is independent of a BCI vendor SDK: an EEG stream can be
    /// joined later with Unity time and marker columns.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("VR BCI/Cybersickness Logger")]
    public sealed class CybersicknessLogger : MonoBehaviour
    {
        [Header("Tracking")]
        [SerializeField] Transform m_HeadTransform;
        [SerializeField] Transform m_RigTransform;
        [SerializeField] Transform m_VirtualCameraTransform;
        [SerializeField, Min(0.02f)] float m_SampleInterval = 0.1f;
        [SerializeField] string m_SessionLabel = "vr_session";
        [SerializeField] bool m_AutoStart = true;
        [SerializeField] CybersicknessComfortController m_ComfortController;

        StreamWriter m_Writer;
        string m_CurrentFilePath;
        string m_CurrentCondition = "unspecified";
        float m_SampleAccumulator;
        float m_PreviousSampleTime;
        float m_SessionStartTime;
        float m_PreviousHeadAngularSpeed;
        float m_PreviousFrameTimeMs;
        Vector3 m_PreviousHeadPosition;
        Quaternion m_PreviousHeadRotation;
        Vector3 m_PreviousRigPosition;
        Vector3 m_PreviousVirtualPosition;
        Quaternion m_PreviousVirtualRotation;
        bool m_HasPreviousPose;
        bool m_HasPreviousVirtualPose;
        int m_CurrentRating = -1;
        float m_CurrentNormalizedRating = float.NaN;
        float m_RatingUpdateTime = float.NaN;
        string m_RatingSource = string.Empty;

        public bool IsRecording => m_Writer != null;
        public string CurrentFilePath => m_CurrentFilePath;
        public string CurrentCondition => m_CurrentCondition;
        public float CurrentNormalizedRating => m_CurrentNormalizedRating;
        public string CurrentRatingSource => m_RatingSource;
        public float RatingUpdateTime => m_RatingUpdateTime;

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
            m_Writer.WriteLine("row_type,unix_time_utc,unity_time_s,frame,scene,head_px,head_py,head_pz,head_qx,head_qy,head_qz,head_qw,head_linear_speed_mps,head_angular_speed_dps,head_angular_acceleration_dps2,rig_linear_speed_mps,virtual_camera_linear_speed_mps,virtual_camera_angular_speed_dps,visual_physical_mismatch,frame_time_ms,frame_jitter_ms,fps,exposure_duration_s,risk_raw,risk_smoothed,risk_level,intervention,external_risk,external_quality,risk_source,external_stale,condition,rating,marker,rating_normalized,rating_source,rating_update_unity_s,rating_age_s,target_speed_multiplier,applied_speed_multiplier,prediction_id,alarm_id,source_prediction_time_s,receipt_time_s");

            m_SampleAccumulator = 0f;
            m_PreviousSampleTime = Time.unscaledTime;
            m_SessionStartTime = Time.unscaledTime;
            m_PreviousHeadAngularSpeed = 0f;
            m_PreviousFrameTimeMs = 0f;
            m_HasPreviousPose = false;
            m_HasPreviousVirtualPose = false;
            // A new recording must not inherit a rating from the previous session.
            m_CurrentRating = -1;
            m_CurrentNormalizedRating = float.NaN;
            m_RatingUpdateTime = float.NaN;
            m_RatingSource = string.Empty;
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

        public void SetCondition(string condition)
        {
            m_CurrentCondition = string.IsNullOrWhiteSpace(condition) ? "unspecified" : condition;
            RecordMarker("condition_" + m_CurrentCondition);
        }

        public void SetSubjectiveRating(int rating)
        {
            m_CurrentRating = Mathf.Clamp(rating, 0, 10);
            m_CurrentNormalizedRating = m_CurrentRating / 10f;
            m_RatingUpdateTime = Time.unscaledTime;
            m_RatingSource = "manual_discrete_0_10";
            RecordMarker("rating_" + m_CurrentRating.ToString(CultureInfo.InvariantCulture));
        }

        /// <summary>Custom continuous self-report, not a standard clinical scale.</summary>
        public void SetContinuousSubjectiveRating(float normalizedRating)
        {
            if (float.IsNaN(normalizedRating) || float.IsInfinity(normalizedRating) ||
                normalizedRating < 0f || normalizedRating > 1f)
                return;
            m_CurrentRating = -1;
            m_CurrentNormalizedRating = normalizedRating;
            m_RatingUpdateTime = Time.unscaledTime;
            m_RatingSource = "custom_continuous_0_1";
            RecordMarker("rating_continuous_" + F(normalizedRating));
        }

        public void ClearSubjectiveRating()
        {
            m_CurrentRating = -1;
            m_CurrentNormalizedRating = float.NaN;
            m_RatingUpdateTime = float.NaN;
            m_RatingSource = string.Empty;
            RecordMarker("rating_cleared");
        }

        void ResolveTransforms()
        {
            if (m_HeadTransform == null && Camera.main != null)
                m_HeadTransform = Camera.main.transform;
            if (m_VirtualCameraTransform == null)
                m_VirtualCameraTransform = m_HeadTransform;
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
            float headAngularAcceleration = 0f;
            float rigLinearSpeed = 0f;
            float virtualLinearSpeed = 0f;
            float virtualAngularSpeed = 0f;

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
                    headAngularAcceleration = Mathf.Abs(headAngularSpeed - m_PreviousHeadAngularSpeed) / dt;
                }
                m_PreviousHeadPosition = headPosition;
                m_PreviousHeadRotation = headRotation;
                m_PreviousHeadAngularSpeed = headAngularSpeed;
            }

            if (m_RigTransform != null && m_HasPreviousPose)
                rigLinearSpeed = Vector3.Distance(m_RigTransform.position, m_PreviousRigPosition) / dt;
            if (m_RigTransform != null)
                m_PreviousRigPosition = m_RigTransform.position;

            if (m_VirtualCameraTransform != null)
            {
                if (m_HasPreviousVirtualPose)
                {
                    virtualLinearSpeed = Vector3.Distance(m_VirtualCameraTransform.position, m_PreviousVirtualPosition) / dt;
                    virtualAngularSpeed = Quaternion.Angle(m_VirtualCameraTransform.rotation, m_PreviousVirtualRotation) / dt;
                }
                m_PreviousVirtualPosition = m_VirtualCameraTransform.position;
                m_PreviousVirtualRotation = m_VirtualCameraTransform.rotation;
                m_HasPreviousVirtualPose = true;
            }

            m_HasPreviousPose = true;
            m_PreviousSampleTime = now;

            float frameTimeMs = Time.unscaledDeltaTime * 1000f;
            float frameJitterMs = m_PreviousFrameTimeMs <= 0f ? 0f : Mathf.Abs(frameTimeMs - m_PreviousFrameTimeMs);
            float fps = 1f / Mathf.Max(Time.unscaledDeltaTime, 0.0001f);
            float mismatch = Mathf.Clamp01(0.5f *
                (Mathf.Abs(virtualLinearSpeed - headLinearSpeed) / 2f +
                 Mathf.Abs(virtualAngularSpeed - headAngularSpeed) / 120f));
            m_PreviousFrameTimeMs = frameTimeMs;

            string riskRaw = m_ComfortController == null ? string.Empty : F(m_ComfortController.RawRisk);
            string riskSmoothed = m_ComfortController == null ? string.Empty : F(m_ComfortController.SmoothedRisk);
            string riskLevel = m_ComfortController == null ? string.Empty : m_ComfortController.CurrentRiskLevel.ToString();
            string intervention = m_ComfortController == null ? string.Empty : m_ComfortController.CurrentIntervention.ToString();
            string externalRisk = m_ComfortController == null ? string.Empty : F(m_ComfortController.ExternalRiskEnabled ? m_ComfortController.RawRisk : -1f);
            string externalQuality = m_ComfortController == null ? string.Empty : F(m_ComfortController.ExternalRiskQuality);
            string externalSource = m_ComfortController == null ? string.Empty : m_ComfortController.ExternalRiskSource;
            string externalStale = m_ComfortController == null ? string.Empty : m_ComfortController.ExternalRiskStale.ToString();
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
                F(headLinearSpeed), F(headAngularSpeed), F(headAngularAcceleration), F(rigLinearSpeed),
                F(virtualLinearSpeed), F(virtualAngularSpeed), F(mismatch),
                F(frameTimeMs), F(frameJitterMs), F(fps), F(now - m_SessionStartTime),
                riskRaw, riskSmoothed, riskLevel, intervention,
                externalRisk, externalQuality, externalSource, externalStale,
                m_CurrentCondition,
                m_CurrentRating < 0 ? string.Empty : m_CurrentRating.ToString(CultureInfo.InvariantCulture),
                marker,
                float.IsNaN(m_CurrentNormalizedRating) ? string.Empty : F(m_CurrentNormalizedRating),
                m_RatingSource,
                float.IsNaN(m_RatingUpdateTime) ? string.Empty : F(m_RatingUpdateTime),
                float.IsNaN(m_RatingUpdateTime) ? string.Empty : F(Mathf.Max(0f, now - m_RatingUpdateTime)),
                m_ComfortController == null ? string.Empty : F(m_ComfortController.TargetSpeedMultiplier),
                m_ComfortController == null ? string.Empty : F(m_ComfortController.AppliedSpeedMultiplier),
                m_ComfortController == null ? string.Empty : m_ComfortController.PredictionId,
                m_ComfortController == null ? string.Empty : m_ComfortController.AlarmId,
                m_ComfortController == null ? string.Empty : m_ComfortController.ExternalRiskTimestamp.ToString("R", CultureInfo.InvariantCulture),
                m_ComfortController == null ? string.Empty : m_ComfortController.LastRiskReceiptTime.ToString("R", CultureInfo.InvariantCulture)
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
