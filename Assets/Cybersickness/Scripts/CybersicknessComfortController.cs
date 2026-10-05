using System;
using UnityEngine;

namespace VRBCI.Cybersickness
{
    /// <summary>
    /// Lightweight, explainable cybersickness-risk baseline.
    ///
    /// This is an engineering baseline, not a clinical classifier. It combines
    /// head linear speed, head angular speed, and frame-time degradation. A
    /// future EEG/BCI bridge can call SetExternalRisk without changing the
    /// Unity scene or the logger format.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("VR BCI/Cybersickness Comfort Controller")]
    public sealed class CybersicknessComfortController : MonoBehaviour
    {
        public enum RiskLevel
        {
            Low,
            Moderate,
            High,
            Critical
        }

        public enum Intervention
        {
            None,
            ReduceSpeed,
            StrongReduceSpeed,
            EmergencyStop
        }

        [Header("Tracking")]
        [SerializeField]
        Transform m_HeadTransform;

        [SerializeField]
        CybersicknessMoveProvider m_MoveProvider;

        [Header("Baseline feature limits")]
        [SerializeField, Min(0.1f)]
        float m_MaxHeadLinearSpeed = 2f;

        [SerializeField, Min(1f)]
        float m_MaxHeadAngularSpeed = 120f;

        [SerializeField, Range(30f, 144f)]
        float m_TargetFrameRate = 72f;

        [SerializeField, Min(1f)]
        float m_FrameTimeHardLimitMs = 33f;

        [Header("Risk thresholds")]
        [SerializeField, Range(0f, 1f)]
        float m_ModerateThreshold = 0.35f;

        [SerializeField, Range(0f, 1f)]
        float m_HighThreshold = 0.60f;

        [SerializeField, Range(0f, 1f)]
        float m_CriticalThreshold = 0.80f;

        [SerializeField, Min(0.05f)]
        float m_SmoothingTime = 1f;

        [Header("Comfort policy")]
        [SerializeField]
        bool m_AutomaticIntervention = true;

        [SerializeField, Range(0f, 1f)]
        float m_ModerateSpeedMultiplier = 0.75f;

        [SerializeField, Range(0f, 1f)]
        float m_HighSpeedMultiplier = 0.50f;

        [SerializeField, Range(0f, 1f)]
        float m_CriticalSpeedMultiplier = 0.25f;

        [SerializeField, Min(0f)]
        float m_InterventionCooldown = 1f;

        [SerializeField, Min(0.1f)]
        float m_ExternalRiskTimeout = 2f;

        Vector3 m_PreviousHeadPosition;
        Quaternion m_PreviousHeadRotation;
        float m_PreviousTime;
        float m_LastInterventionTime = float.NegativeInfinity;
        float m_LastExternalRiskTime = float.NegativeInfinity;
        bool m_HasPreviousPose;
        bool m_ExternalRiskEnabled;
        bool m_EmergencyStopped;
        /// <summary>Raised when the discrete risk level changes.</summary>
        public event Action<RiskLevel> RiskLevelChanged;

        /// <summary>Raised when the comfort intervention changes.</summary>
        public event Action<Intervention> InterventionChanged;

        public float RawRisk { get; private set; }
        public float SmoothedRisk { get; private set; }
        public float HeadLinearSpeed { get; private set; }
        public float HeadAngularSpeed { get; private set; }
        public float FrameTimeMs { get; private set; }
        public RiskLevel CurrentRiskLevel { get; private set; } = RiskLevel.Low;
        public Intervention CurrentIntervention { get; private set; } = Intervention.None;
        public bool EmergencyStopped => m_EmergencyStopped;

        /// <summary>Whether external EEG/BCI risk values are currently accepted.</summary>
        public bool ExternalRiskEnabled => m_ExternalRiskEnabled;

        void Awake()
        {
            ResolveHeadTransform();
            ResetPoseBaseline();
        }

        void Update()
        {
            ResolveHeadTransform();

            if (!m_ExternalRiskEnabled || Time.unscaledTime - m_LastExternalRiskTime > m_ExternalRiskTimeout)
            {
                m_ExternalRiskEnabled = false;
                UpdateFromHeadMotion();
            }

            if (m_AutomaticIntervention && !m_EmergencyStopped)
                ApplyPolicy();
        }

        /// <summary>
        /// Enables a future BCI bridge to provide risk values. Values must be
        /// normalized to [0, 1]. If updates stop, the controller falls back to
        /// the local head-motion baseline after the configured timeout.
        /// </summary>
        public void SetExternalRisk(float normalizedRisk)
        {
            m_ExternalRiskEnabled = true;
            m_LastExternalRiskTime = Time.unscaledTime;
            RawRisk = Mathf.Clamp01(normalizedRisk);
            UpdateRiskState(RawRisk);
        }

        public void ClearExternalRisk()
        {
            m_ExternalRiskEnabled = false;
            ResetPoseBaseline();
        }

        /// <summary>Stops adaptive movement without disabling the XR provider.</summary>
        public void EmergencyStop()
        {
            m_EmergencyStopped = true;
            SetIntervention(Intervention.EmergencyStop, 0f, true);
        }

        /// <summary>Clears the manual stop and restores the current policy.</summary>
        public void ResumeAfterEmergencyStop()
        {
            m_EmergencyStopped = false;
            m_LastInterventionTime = float.NegativeInfinity;
            if (m_AutomaticIntervention)
                ApplyPolicy();
            else
                SetIntervention(Intervention.None, 1f, true);
        }

        public void SetAutomaticIntervention(bool enabled)
        {
            m_AutomaticIntervention = enabled;
            if (!enabled)
                SetIntervention(Intervention.None, 1f, true);
        }

        public void ResetPoseBaseline()
        {
            ResolveHeadTransform();
            if (m_HeadTransform == null)
            {
                m_HasPreviousPose = false;
                return;
            }

            m_PreviousHeadPosition = m_HeadTransform.position;
            m_PreviousHeadRotation = m_HeadTransform.rotation;
            m_PreviousTime = Time.unscaledTime;
            m_HasPreviousPose = true;
        }

        void ResolveHeadTransform()
        {
            if (m_HeadTransform == null && Camera.main != null)
                m_HeadTransform = Camera.main.transform;
        }

        void UpdateFromHeadMotion()
        {
            FrameTimeMs = Time.unscaledDeltaTime * 1000f;

            if (m_HeadTransform == null)
            {
                RawRisk = Mathf.Clamp01(0.20f * FrameRisk(FrameTimeMs));
                UpdateRiskState(RawRisk);
                return;
            }

            if (!m_HasPreviousPose)
            {
                ResetPoseBaseline();
                RawRisk = 0f;
                UpdateRiskState(RawRisk);
                return;
            }

            float dt = Mathf.Max(Time.unscaledTime - m_PreviousTime, 0.0001f);
            HeadLinearSpeed = Vector3.Distance(m_HeadTransform.position, m_PreviousHeadPosition) / dt;
            HeadAngularSpeed = Quaternion.Angle(m_PreviousHeadRotation, m_HeadTransform.rotation) / dt;

            float linearRisk = Mathf.Clamp01(HeadLinearSpeed / m_MaxHeadLinearSpeed);
            float angularRisk = Mathf.Clamp01(HeadAngularSpeed / m_MaxHeadAngularSpeed);
            float frameRisk = FrameRisk(FrameTimeMs);

            // Weights are deliberately explicit so they can be reported and
            // replaced by a learned model later.
            RawRisk = Mathf.Clamp01(0.45f * linearRisk + 0.35f * angularRisk + 0.20f * frameRisk);
            UpdateRiskState(RawRisk);

            m_PreviousHeadPosition = m_HeadTransform.position;
            m_PreviousHeadRotation = m_HeadTransform.rotation;
            m_PreviousTime = Time.unscaledTime;
        }

        float FrameRisk(float frameTimeMs)
        {
            float targetBudget = 1000f / Mathf.Max(m_TargetFrameRate, 1f);
            return Mathf.InverseLerp(targetBudget, m_FrameTimeHardLimitMs, frameTimeMs);
        }

        void UpdateRiskState(float rawRisk)
        {
            float dt = Mathf.Max(Time.unscaledDeltaTime, 0.0001f);
            float alpha = 1f - Mathf.Exp(-dt / Mathf.Max(m_SmoothingTime, 0.05f));
            SmoothedRisk = Mathf.Lerp(SmoothedRisk, Mathf.Clamp01(rawRisk), alpha);

            RiskLevel nextLevel = ToRiskLevel(SmoothedRisk);
            if (nextLevel == CurrentRiskLevel)
                return;

            CurrentRiskLevel = nextLevel;
            RiskLevelChanged?.Invoke(CurrentRiskLevel);
        }

        RiskLevel ToRiskLevel(float risk)
        {
            if (risk >= m_CriticalThreshold)
                return RiskLevel.Critical;
            if (risk >= m_HighThreshold)
                return RiskLevel.High;
            if (risk >= m_ModerateThreshold)
                return RiskLevel.Moderate;
            return RiskLevel.Low;
        }

        void ApplyPolicy()
        {
            if (Time.unscaledTime - m_LastInterventionTime < m_InterventionCooldown &&
                CurrentRiskLevel != RiskLevel.Critical)
                return;

            Intervention intervention;
            float multiplier;
            switch (CurrentRiskLevel)
            {
                case RiskLevel.Critical:
                    intervention = Intervention.StrongReduceSpeed;
                    multiplier = m_CriticalSpeedMultiplier;
                    break;
                case RiskLevel.High:
                    intervention = Intervention.StrongReduceSpeed;
                    multiplier = m_HighSpeedMultiplier;
                    break;
                case RiskLevel.Moderate:
                    intervention = Intervention.ReduceSpeed;
                    multiplier = m_ModerateSpeedMultiplier;
                    break;
                default:
                    intervention = Intervention.None;
                    multiplier = 1f;
                    break;
            }

            SetIntervention(intervention, multiplier, false);
        }

        void SetIntervention(Intervention intervention, float multiplier, bool force)
        {
            if (!force && intervention == CurrentIntervention &&
                Time.unscaledTime - m_LastInterventionTime < m_InterventionCooldown)
                return;

            if (m_MoveProvider != null)
                m_MoveProvider.ComfortMultiplier = Mathf.Clamp01(multiplier);

            bool changed = CurrentIntervention != intervention;
            CurrentIntervention = intervention;
            m_LastInterventionTime = Time.unscaledTime;
            if (changed)
                InterventionChanged?.Invoke(CurrentIntervention);

        }
    }
}
