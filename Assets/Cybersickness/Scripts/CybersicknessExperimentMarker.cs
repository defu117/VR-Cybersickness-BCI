using UnityEngine;

namespace VRBCI.Cybersickness
{
    /// <summary>
    /// Small UI/keyboard-independent façade for experiment buttons and markers.
    /// Hook these public methods to Unity UI buttons or call them from a future
    /// LSL/BCI adapter; no vendor SDK is required.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("VR BCI/Cybersickness Experiment Marker")]
    public sealed class CybersicknessExperimentMarker : MonoBehaviour
    {
        [SerializeField]
        CybersicknessLogger m_Logger;

        [SerializeField]
        CybersicknessComfortController m_ComfortController;

        void Awake()
        {
            if (m_Logger == null)
                m_Logger = GetComponent<CybersicknessLogger>();
            if (m_ComfortController == null)
                m_ComfortController = GetComponent<CybersicknessComfortController>();
        }

        public void StartSession()
        {
            if (m_Logger == null)
                return;
            m_Logger.StartRecording();
            m_Logger.RecordMarker("experiment_start");
        }

        public void EndSession()
        {
            if (m_Logger == null)
                return;
            m_Logger.RecordMarker("experiment_end");
            m_Logger.StopRecording();
        }

        public void MarkStimulus(string label)
        {
            if (m_Logger != null)
                m_Logger.RecordMarker("stimulus_" + label);
        }

        public void MarkCondition(string condition)
        {
            if (m_Logger != null)
                m_Logger.SetCondition(condition);
        }

        public void SetContinuousRating(float normalizedRating)
        {
            if (m_Logger != null)
                m_Logger.SetContinuousSubjectiveRating(normalizedRating);
        }

        public void SetRating0() => SetRating(0);
        public void SetRating1() => SetRating(1);
        public void SetRating2() => SetRating(2);
        public void SetRating3() => SetRating(3);
        public void SetRating4() => SetRating(4);
        public void SetRating5() => SetRating(5);
        public void SetRating6() => SetRating(6);
        public void SetRating7() => SetRating(7);
        public void SetRating8() => SetRating(8);
        public void SetRating9() => SetRating(9);
        public void SetRating10() => SetRating(10);

        public void ClearRating()
        {
            if (m_Logger != null)
                m_Logger.ClearSubjectiveRating();
        }

        public void EmergencyStop()
        {
            if (m_ComfortController != null)
                m_ComfortController.EmergencyStop();
            if (m_Logger != null)
                m_Logger.RecordMarker("manual_emergency_stop");
        }

        public void ResumeAfterEmergencyStop()
        {
            if (m_ComfortController != null)
                m_ComfortController.ResumeAfterEmergencyStop();
            if (m_Logger != null)
                m_Logger.RecordMarker("manual_resume");
        }

        void SetRating(int rating)
        {
            if (m_Logger != null)
                m_Logger.SetSubjectiveRating(rating);
        }
    }
}
