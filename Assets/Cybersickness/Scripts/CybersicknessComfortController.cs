using System;
using System.Collections.Generic;
using UnityEngine;

namespace VRBCI.Cybersickness
{
    /// <summary>
    /// Explainable cybersickness-risk baseline and comfort policy.
    ///
    /// The controller can consume either local HMD motion features or an
    /// external risk stream (for example an offline EEG replay). External
    /// updates are quality-gated and automatically expire after a timeout.
    /// This is an engineering baseline, not a clinical classifier.
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
        [SerializeField] Transform m_HeadTransform;
        [SerializeField] Transform m_VirtualCameraTransform;
        [SerializeField] CybersicknessMoveProvider m_MoveProvider;

        [Header("Baseline feature limits")]
        [SerializeField, Min(0.1f)] float m_MaxHeadLinearSpeed = 2f;
        [SerializeField, Min(1f)] float m_MaxHeadAngularSpeed = 120f;
        [SerializeField, Range(30f, 144f)] float m_TargetFrameRate = 72f;
        [SerializeField, Min(1f)] float m_FrameTimeHardLimitMs = 33f;

        [Header("Risk thresholds")]
        [SerializeField, Range(0f, 1f)] float m_ModerateThreshold = 0.35f;
        [SerializeField, Range(0f, 1f)] float m_HighThreshold = 0.60f;
        [SerializeField, Range(0f, 1f)] float m_CriticalThreshold = 0.80f;
        [SerializeField, Min(0.05f)] float m_SmoothingTime = 1f;

        [Header("Decision state")]
        [SerializeField, Min(1)] int m_RequiredConsecutiveWindows = 3;
        [SerializeField, Min(0.02f)] float m_DecisionWindowSeconds = 0.1f;
        [SerializeField, Min(0f)] float m_MinInterventionDuration = 10f;
        [SerializeField, Min(0f)] float m_RecoveryHoldTime = 3f;
        [SerializeField, Min(0.05f)] float m_SpeedRecoveryDuration = 2f;

        [Header("Comfort policy")]
        [SerializeField] bool m_AutomaticIntervention = true;
        [SerializeField, Range(0f, 1f)] float m_ModerateSpeedMultiplier = 0.75f;
        [SerializeField, Range(0f, 1f)] float m_HighSpeedMultiplier = 0.50f;
        [SerializeField, Range(0f, 1f)] float m_CriticalSpeedMultiplier = 0.25f;
        [SerializeField, Min(0f)] float m_InterventionCooldown = 1f;
        [SerializeField, Min(0.1f)] float m_ExternalRiskTimeout = 2f;
        [SerializeField, Range(0f, 1f)] float m_MinExternalQuality = 0.5f;

        Vector3 m_PreviousHeadPosition;
        Quaternion m_PreviousHeadRotation;
        Vector3 m_PreviousVirtualPosition;
        Quaternion m_PreviousVirtualRotation;
        float m_PreviousTime;
        float m_PreviousHeadAngularSpeed;
        float m_PreviousFrameTimeMs;
        float m_ExposureDuration;
        float m_LastInterventionTime = float.NegativeInfinity;
        float m_InterventionStartTime = float.NegativeInfinity;
        float m_LastExternalRiskTime = float.NegativeInfinity;
        float m_DecisionAccumulator;
        float m_AppliedSpeedMultiplier = 1f;
        float m_TargetSpeedMultiplier = 1f;
        int m_ConsecutiveRiskWindows;
        int m_ConsecutiveLowWindows;
        bool m_HasPreviousPose;
        bool m_HasPreviousVirtualPose;
        bool m_ExternalRiskEnabled;
        bool m_ExternalRiskStale = true;
        bool m_EmergencyStopped;
        float m_ExternalRiskQuality;
        double m_ExternalRiskTimestamp;
        string m_ExternalRiskSource = "hmd";
        bool m_SimulationClock;
        bool m_AdvancingSimulation;
        float m_SimulationTime;
        float m_SimulationDelta;
        bool m_ActionActive;
        bool m_ActionEffective;
        bool m_ForceNoHeadFallback;
        readonly HashSet<string> m_ReceivedAlarmIds = new HashSet<string>();

        public struct TimingEvent
        {
            public string type, predictionId, alarmId, source;
            public double localTime, sourceTimestamp;
            public float targetMultiplier, appliedMultiplier;
        }

        public event Action<TimingEvent> TimingEventRecorded;
        public event Action<CybersicknessComfortController> FrameAdvanced;
        float Now => m_SimulationClock ? m_SimulationTime : Time.unscaledTime;
        float Delta => m_SimulationClock ? m_SimulationDelta : Time.unscaledDeltaTime;

        public event Action<RiskLevel> RiskLevelChanged;
        public event Action<Intervention> InterventionChanged;

        public float RawRisk { get; private set; }
        public float SmoothedRisk { get; private set; }
        public float HeadLinearSpeed { get; private set; }
        public float HeadAngularSpeed { get; private set; }
        public float HeadAngularAcceleration { get; private set; }
        public float VirtualCameraLinearSpeed { get; private set; }
        public float VirtualCameraAngularSpeed { get; private set; }
        public float VisualPhysicalMismatch { get; private set; }
        public float FrameTimeMs { get; private set; }
        public float FrameJitterMs { get; private set; }
        public float ExposureDuration => m_ExposureDuration;
        public RiskLevel CurrentRiskLevel { get; private set; } = RiskLevel.Low;
        public Intervention CurrentIntervention { get; private set; } = Intervention.None;
        public bool EmergencyStopped => m_EmergencyStopped;
        public bool ExternalRiskEnabled => m_ExternalRiskEnabled;
        public bool ExternalRiskStale => m_ExternalRiskStale;
        public float ExternalRiskQuality => m_ExternalRiskQuality;
        public double ExternalRiskTimestamp => m_ExternalRiskTimestamp;
        public string ExternalRiskSource => m_ExternalRiskSource;
        public float AppliedSpeedMultiplier => m_AppliedSpeedMultiplier;
        public float TargetSpeedMultiplier => m_TargetSpeedMultiplier;
        public double LocalTime => Now;
        public float FrameDelta => Delta;
        public string PredictionId { get; private set; } = "";
        public string AlarmId { get; private set; } = "";
        public double LastRiskReceiptTime { get; private set; }
        public float InterventionStartTime => m_InterventionStartTime;

        void Awake()
        {
            ResolveHeadTransform();
            ResetPoseBaseline();
            ApplyMoveMultiplier();
        }

        void Update()
        {
            if (m_SimulationClock && !m_AdvancingSimulation)
                return;
            ResolveHeadTransform();
            m_ExposureDuration += Delta;

            if (m_ExternalRiskEnabled && Now - m_LastExternalRiskTime > m_ExternalRiskTimeout + .0001f)
            {
                m_ExternalRiskEnabled = false;
                m_ExternalRiskStale = true;
                m_ExternalRiskSource = "hmd_fallback";
                EmitTiming("risk_timeout");
                ResetPoseBaseline();
            }

            if (!m_ExternalRiskEnabled)
                UpdateFromHeadMotion();
            else
            {
                // Smoothing follows elapsed frame time, independent of the
                // external message/heartbeat cadence.
                FrameTimeMs = Delta * 1000f;
                UpdateRiskState(RawRisk);
            }

            UpdatePolicyState();
            SmoothAppliedMultiplier();
            FrameAdvanced?.Invoke(this);
        }

        /// <summary>Explicit clock for deterministic desktop checks, not a hardware latency measurement.</summary>
        public void AdvanceSimulationFrame(float dt, float now)
        {
            if (dt <= 0f || float.IsNaN(dt) || float.IsInfinity(dt) ||
                float.IsNaN(now) || float.IsInfinity(now))
                throw new ArgumentOutOfRangeException(nameof(dt));
            m_SimulationClock = true;
            m_SimulationTime = now;
            m_SimulationDelta = dt;
            m_AdvancingSimulation = true;
            try { Update(); }
            finally { m_AdvancingSimulation = false; }
        }

        public void SetSimulationReceiptTime(float now)
        {
            if (!m_SimulationClock)
                throw new InvalidOperationException("ResetForReplay(simulation:true) is required.");
            m_SimulationTime = now;
        }

        public void ConfigureResearchReplay(bool forceNoHeadFallback = false)
        {
            m_ForceNoHeadFallback = forceNoHeadFallback;
            m_RequiredConsecutiveWindows = 1;
            m_DecisionWindowSeconds = 0.1f;
            m_SmoothingTime = 1f;
            m_MinInterventionDuration = 10f;
            m_RecoveryHoldTime = 3f;
            m_SpeedRecoveryDuration = 2f;
            m_InterventionCooldown = 1f;
            m_ExternalRiskTimeout = 2f;
            m_ModerateThreshold = .35f; m_HighThreshold = .60f; m_CriticalThreshold = .80f;
            m_ModerateSpeedMultiplier = .75f; m_HighSpeedMultiplier = .5f; m_CriticalSpeedMultiplier = .25f;
            m_MinExternalQuality = .5f;
            m_AutomaticIntervention = true;
        }

        public void ResetForReplay(bool simulation = false, float now = 0f)
        {
            m_SimulationClock = simulation;
            m_SimulationTime = now;
            m_ForceNoHeadFallback = false;
            m_ReceivedAlarmIds.Clear();
            PredictionId = AlarmId = "";
            m_ExternalRiskTimestamp = LastRiskReceiptTime = 0d;
            m_ExternalRiskQuality = 0f;
            m_LastExternalRiskTime = float.NegativeInfinity;
            RawRisk = SmoothedRisk = m_ExposureDuration = 0f;
            CurrentRiskLevel = RiskLevel.Low;
            m_ConsecutiveRiskWindows = m_ConsecutiveLowWindows = 0;
            m_DecisionAccumulator = 0f;
            m_LastInterventionTime = m_InterventionStartTime = float.NegativeInfinity;
            m_ActionActive = m_ActionEffective = false;
            CurrentIntervention = m_EmergencyStopped ? Intervention.EmergencyStop : Intervention.None;
            m_AppliedSpeedMultiplier = m_TargetSpeedMultiplier = m_EmergencyStopped ? 0f : 1f;
            ClearExternalRisk();
            ApplyMoveMultiplier();
        }

        public void SetExternalRisk(float normalizedRisk)
        {
            SetExternalRisk(normalizedRisk, 1f, "external", Now);
        }

        public void SetExternalRisk(float normalizedRisk, float quality, string source)
        {
            SetExternalRisk(normalizedRisk, quality, source, Now);
        }

        /// <summary>Accepts an external risk. Timeout uses local receipt time.</summary>
        public void SetExternalRisk(float normalizedRisk, float quality, string source, double sourceTimestamp)
        {
            SetExternalRiskSample(normalizedRisk, quality, source, sourceTimestamp, "", "");
        }

        public void SetExternalRiskSample(float normalizedRisk, float quality, string source, double sourceTimestamp,
            string predictionId, string alarmId)
        {
            if (float.IsNaN(normalizedRisk) || float.IsInfinity(normalizedRisk) ||
                float.IsNaN(quality) || float.IsInfinity(quality) ||
                double.IsNaN(sourceTimestamp) || double.IsInfinity(sourceTimestamp))
                return;

            m_ExternalRiskQuality = Mathf.Clamp01(quality);
            m_ExternalRiskSource = string.IsNullOrWhiteSpace(source) ? "external" : source;
            m_ExternalRiskTimestamp = sourceTimestamp;
            PredictionId = predictionId ?? "";
            LastRiskReceiptTime = Now;

            if (m_ExternalRiskQuality < m_MinExternalQuality)
            {
                m_ExternalRiskEnabled = false;
                m_ExternalRiskStale = true;
                EmitTiming("risk_rejected_quality");
                ResetPoseBaseline();
                return;
            }

            m_ExternalRiskEnabled = true;
            m_ExternalRiskStale = false;
            m_LastExternalRiskTime = Now;
            RawRisk = Mathf.Clamp01(normalizedRisk);
            FrameTimeMs = Delta * 1000f;
            if (!string.IsNullOrEmpty(alarmId))
            {
                AlarmId = alarmId;
                if (m_ReceivedAlarmIds.Add(alarmId))
                    EmitTiming("alarm_received");
            }
        }

        void EmitTiming(string type)
        {
            TimingEventRecorded?.Invoke(new TimingEvent { type = type, localTime = Now,
                sourceTimestamp = m_ExternalRiskTimestamp, predictionId = PredictionId,
                alarmId = AlarmId, source = m_ExternalRiskSource,
                targetMultiplier = m_TargetSpeedMultiplier, appliedMultiplier = m_AppliedSpeedMultiplier });
        }

        public void ClearExternalRisk()
        {
            m_ExternalRiskEnabled = false;
            m_ExternalRiskStale = true;
            m_ExternalRiskSource = "hmd";
            ResetPoseBaseline();
        }

        public void EmergencyStop()
        {
            m_EmergencyStopped = true;
            SetIntervention(Intervention.EmergencyStop, 0f, true);
        }

        public void ResumeAfterEmergencyStop()
        {
            m_EmergencyStopped = false;
            m_ConsecutiveRiskWindows = 0;
            m_ConsecutiveLowWindows = 0;
            m_LastInterventionTime = float.NegativeInfinity;
            SetIntervention(Intervention.None, 1f, true);
        }

        public void SetAutomaticIntervention(bool enabled)
        {
            m_AutomaticIntervention = enabled;
            m_ConsecutiveRiskWindows = 0;
            m_ConsecutiveLowWindows = 0;
            if (!enabled && !m_EmergencyStopped)
                SetIntervention(Intervention.None, 1f, true);
        }

        public void SetManualComfortMultiplier(float multiplier)
        {
            m_AutomaticIntervention = false;
            m_EmergencyStopped = false;
            m_ConsecutiveRiskWindows = 0;
            m_ConsecutiveLowWindows = 0;
            SetIntervention(Intervention.None, Mathf.Clamp01(multiplier), true);
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
            if (m_VirtualCameraTransform != null)
            {
                m_PreviousVirtualPosition = m_VirtualCameraTransform.position;
                m_PreviousVirtualRotation = m_VirtualCameraTransform.rotation;
                m_HasPreviousVirtualPose = true;
            }
            m_PreviousTime = Now;
            m_HasPreviousPose = true;
        }

        void ResolveHeadTransform()
        {
            if (m_HeadTransform == null && Camera.main != null)
                m_HeadTransform = Camera.main.transform;
            if (m_VirtualCameraTransform == null)
                m_VirtualCameraTransform = m_HeadTransform;
        }

        void UpdateFromHeadMotion()
        {
            FrameTimeMs = Delta * 1000f;
            FrameJitterMs = m_PreviousFrameTimeMs <= 0f ? 0f : Mathf.Abs(FrameTimeMs - m_PreviousFrameTimeMs);
            m_PreviousFrameTimeMs = FrameTimeMs;

            if (m_HeadTransform == null || m_ForceNoHeadFallback)
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

            float dt = Mathf.Max(Now - m_PreviousTime, 0.0001f);
            HeadLinearSpeed = Vector3.Distance(m_HeadTransform.position, m_PreviousHeadPosition) / dt;
            HeadAngularSpeed = Quaternion.Angle(m_PreviousHeadRotation, m_HeadTransform.rotation) / dt;
            HeadAngularAcceleration = Mathf.Abs(HeadAngularSpeed - m_PreviousHeadAngularSpeed) / dt;

            if (m_VirtualCameraTransform != null)
            {
                if (m_HasPreviousVirtualPose)
                {
                    VirtualCameraLinearSpeed = Vector3.Distance(m_VirtualCameraTransform.position, m_PreviousVirtualPosition) / dt;
                    VirtualCameraAngularSpeed = Quaternion.Angle(m_PreviousVirtualRotation, m_VirtualCameraTransform.rotation) / dt;
                }
                m_PreviousVirtualPosition = m_VirtualCameraTransform.position;
                m_PreviousVirtualRotation = m_VirtualCameraTransform.rotation;
                m_HasPreviousVirtualPose = true;
            }

            VisualPhysicalMismatch = Mathf.Clamp01(0.5f *
                (Mathf.Abs(VirtualCameraLinearSpeed - HeadLinearSpeed) / 2f +
                 Mathf.Abs(VirtualCameraAngularSpeed - HeadAngularSpeed) / 120f));

            float linearRisk = Mathf.Clamp01(HeadLinearSpeed / m_MaxHeadLinearSpeed);
            float angularRisk = Mathf.Clamp01(HeadAngularSpeed / m_MaxHeadAngularSpeed);
            float angularAccelerationRisk = Mathf.Clamp01(HeadAngularAcceleration / 240f);
            float frameRisk = Mathf.Clamp01(0.7f * FrameRisk(FrameTimeMs) + 0.3f * (FrameJitterMs / 8f));
            float exposureRisk = Mathf.Clamp01(m_ExposureDuration / 300f);
            RawRisk = Mathf.Clamp01(
                0.25f * linearRisk +
                0.20f * angularRisk +
                0.15f * angularAccelerationRisk +
                0.15f * VisualPhysicalMismatch +
                0.15f * frameRisk +
                0.10f * exposureRisk);
            UpdateRiskState(RawRisk);

            m_PreviousHeadPosition = m_HeadTransform.position;
            m_PreviousHeadRotation = m_HeadTransform.rotation;
            m_PreviousHeadAngularSpeed = HeadAngularSpeed;
            m_PreviousTime = Now;
        }

        float FrameRisk(float frameTimeMs)
        {
            float targetBudget = 1000f / Mathf.Max(m_TargetFrameRate, 1f);
            return Mathf.InverseLerp(targetBudget, m_FrameTimeHardLimitMs, frameTimeMs);
        }

        void UpdateRiskState(float rawRisk)
        {
            float dt = Mathf.Max(Delta, 0.0001f);
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

        void UpdatePolicyState()
        {
            if (!m_AutomaticIntervention || m_EmergencyStopped)
                return;

            m_DecisionAccumulator += Delta;
            if (m_DecisionAccumulator + 0.000001f < m_DecisionWindowSeconds)
                return;

            m_DecisionAccumulator = 0f;
            if (CurrentRiskLevel == RiskLevel.Low)
            {
                m_ConsecutiveRiskWindows = 0;
                m_ConsecutiveLowWindows++;
                bool canRecover = Now - m_InterventionStartTime + .0001f >= m_MinInterventionDuration &&
                                   m_ConsecutiveLowWindows >= m_RequiredConsecutiveWindows &&
                                   Now - m_LastInterventionTime + .0001f >= m_RecoveryHoldTime;
                if (canRecover)
                    SetIntervention(Intervention.None, 1f, false);
                return;
            }

            m_ConsecutiveLowWindows = 0;
            m_ConsecutiveRiskWindows++;
            if (m_ConsecutiveRiskWindows < m_RequiredConsecutiveWindows)
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
                default:
                    intervention = Intervention.ReduceSpeed;
                    multiplier = m_ModerateSpeedMultiplier;
                    break;
            }

            bool canChange = Now - m_LastInterventionTime + .0001f >= m_InterventionCooldown ||
                             intervention != CurrentIntervention;
            if (canChange)
                SetIntervention(intervention, multiplier, false);
        }

        void SmoothAppliedMultiplier()
        {
            if (m_EmergencyStopped)
                m_AppliedSpeedMultiplier = 0f;
            else
                m_AppliedSpeedMultiplier = Mathf.MoveTowards(
                    m_AppliedSpeedMultiplier,
                    m_TargetSpeedMultiplier,
                    Delta / Mathf.Max(m_SpeedRecoveryDuration, 0.05f));

            if (!m_ActionActive && m_AppliedSpeedMultiplier < .99f)
            {
                m_ActionActive = true;
                m_ActionEffective = false;
                EmitTiming("action_started");
            }
            if (m_ActionActive && !m_ActionEffective && m_AppliedSpeedMultiplier <= .800001f)
            {
                m_ActionEffective = true;
                EmitTiming("action_effective");
            }
            if (m_ActionActive && m_AppliedSpeedMultiplier >= .99f)
            {
                EmitTiming("recovery_completed");
                m_ActionActive = m_ActionEffective = false;
            }

            ApplyMoveMultiplier();
        }

        void SetIntervention(Intervention intervention, float multiplier, bool force)
        {
            multiplier = Mathf.Clamp01(multiplier);
            // Repeated high-risk heartbeats must not restart the episode or recovery clock.
            if (!force && intervention == CurrentIntervention && Mathf.Approximately(multiplier, m_TargetSpeedMultiplier))
                return;

            bool entering = CurrentIntervention == Intervention.None && intervention != Intervention.None;
            bool recovering = m_TargetSpeedMultiplier < 1f && multiplier >= 1f;
            m_TargetSpeedMultiplier = multiplier;
            if (force)
                m_AppliedSpeedMultiplier = m_TargetSpeedMultiplier;

            bool changed = CurrentIntervention != intervention;
            CurrentIntervention = intervention;
            m_LastInterventionTime = Now;
            if (entering)
                m_InterventionStartTime = Now;

            EmitTiming("target_changed");
            if (recovering)
                EmitTiming("recovery_started");

            ApplyMoveMultiplier();
            if (changed)
                InterventionChanged?.Invoke(CurrentIntervention);
        }

        void ApplyMoveMultiplier()
        {
            if (m_MoveProvider != null)
                m_MoveProvider.ComfortMultiplier = Mathf.Clamp01(m_AppliedSpeedMultiplier);
        }
    }
}
