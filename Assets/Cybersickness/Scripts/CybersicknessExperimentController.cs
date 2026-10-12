using UnityEngine;

namespace VRBCI.Cybersickness
{
    /// <summary>
    /// Small, repeatable locomotion harness for the course experiment.
    /// Keyboard input is intended for Editor smoke tests; Quest controller
    /// input remains handled by the XR Interaction Toolkit move provider.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("VR BCI/Cybersickness Experiment Controller")]
    public sealed class CybersicknessExperimentController : MonoBehaviour
    {
        public enum ExperimentCondition
        {
            NoAdaptation,
            FixedComfort,
            AdaptiveComfort
        }

        [Header("References")]
        [SerializeField] Transform m_LocomotionRoot;
        [SerializeField] CybersicknessLogger m_Logger;
        [SerializeField] CybersicknessComfortController m_ComfortController;
        [SerializeField] CybersicknessExperimentMarker m_Marker;

        [Header("Stimulus")]
        [SerializeField] ExperimentCondition m_Condition = ExperimentCondition.NoAdaptation;
        [SerializeField, Min(0f)] float m_BaseSpeed = 0.75f;
        [SerializeField, Min(0f)] float m_BaseTurnSpeed = 25f;
        [SerializeField, Range(0f, 1f)] float m_FixedComfortMultiplier = 0.5f;
        [SerializeField] bool m_AutoMove;
        [SerializeField] bool m_AutoStartSession;
        [SerializeField] bool m_ShowEditorInstructions = true;

        bool m_SessionActive;
        bool m_StimulusActive;

        public ExperimentCondition CurrentCondition => m_Condition;
        public bool SessionActive => m_SessionActive;
        public bool StimulusActive => m_StimulusActive;

        void Awake()
        {
            ResolveReferences();
            ApplyCondition(false);
        }

        void Start()
        {
            if (m_AutoStartSession)
                StartSession();
        }

        void Update()
        {
            ResolveReferences();
            HandleEditorShortcuts();

            if (!m_StimulusActive)
                return;

            Vector2 input = ReadKeyboardInput();
            if (m_AutoMove)
                input.y = 1f;

            float multiplier = GetMovementMultiplier();
            if (m_LocomotionRoot != null)
            {
                m_LocomotionRoot.Translate(Vector3.forward * (input.y * m_BaseSpeed * multiplier * Time.unscaledDeltaTime), Space.Self);
                m_LocomotionRoot.Rotate(Vector3.up, input.x * m_BaseTurnSpeed * multiplier * Time.unscaledDeltaTime, Space.Self);
            }
        }

        public void StartSession()
        {
            ResolveReferences();
            m_SessionActive = true;
            if (m_Logger != null)
                m_Logger.StartRecording();
            if (m_Marker != null)
                m_Marker.StartSession();
            else if (m_Logger != null)
                m_Logger.RecordMarker("experiment_start");
            SetCondition(m_Condition);
        }

        public void EndSession()
        {
            StopStimulus();
            if (m_Marker != null)
                m_Marker.EndSession();
            else if (m_Logger != null)
                m_Logger.StopRecording();
            m_SessionActive = false;
        }

        public void StartStimulus()
        {
            m_StimulusActive = true;
            if (m_Logger != null)
                m_Logger.RecordMarker("stimulus_start");
        }

        public void StopStimulus()
        {
            if (!m_StimulusActive)
                return;
            m_StimulusActive = false;
            if (m_Logger != null)
                m_Logger.RecordMarker("stimulus_end");
        }

        public void ToggleStimulus()
        {
            if (m_StimulusActive)
                StopStimulus();
            else
                StartStimulus();
        }

        public void SetConditionNoAdaptation() => SetCondition(ExperimentCondition.NoAdaptation);
        public void SetConditionFixedComfort() => SetCondition(ExperimentCondition.FixedComfort);
        public void SetConditionAdaptiveComfort() => SetCondition(ExperimentCondition.AdaptiveComfort);

        public void SetCondition(ExperimentCondition condition)
        {
            m_Condition = condition;
            ApplyCondition(true);
        }

        public void SetRating(int rating)
        {
            if (m_Marker != null)
            {
                switch (Mathf.Clamp(rating, 0, 10))
                {
                    case 0: m_Marker.SetRating0(); break;
                    case 1: m_Marker.SetRating1(); break;
                    case 2: m_Marker.SetRating2(); break;
                    case 3: m_Marker.SetRating3(); break;
                    case 4: m_Marker.SetRating4(); break;
                    case 5: m_Marker.SetRating5(); break;
                    case 6: m_Marker.SetRating6(); break;
                    case 7: m_Marker.SetRating7(); break;
                    case 8: m_Marker.SetRating8(); break;
                    case 9: m_Marker.SetRating9(); break;
                    default: m_Marker.SetRating10(); break;
                }
            }
            else if (m_Logger != null)
                m_Logger.SetSubjectiveRating(rating);
        }

        public void EmergencyStop()
        {
            if (m_Marker != null)
                m_Marker.EmergencyStop();
            else if (m_ComfortController != null)
                m_ComfortController.EmergencyStop();
            StopStimulus();
        }

        public void ResumeAfterEmergencyStop()
        {
            if (m_Marker != null)
                m_Marker.ResumeAfterEmergencyStop();
            else if (m_ComfortController != null)
                m_ComfortController.ResumeAfterEmergencyStop();
        }

        void ResolveReferences()
        {
            if (m_Logger == null)
                m_Logger = GetComponent<CybersicknessLogger>();
            if (m_ComfortController == null)
                m_ComfortController = GetComponent<CybersicknessComfortController>();
            if (m_Marker == null)
                m_Marker = GetComponent<CybersicknessExperimentMarker>();
            if (m_LocomotionRoot == null && Camera.main != null)
                m_LocomotionRoot = Camera.main.transform.parent != null ? Camera.main.transform.parent : Camera.main.transform;
        }

        void ApplyCondition(bool writeMarker)
        {
            if (m_ComfortController != null)
            {
                switch (m_Condition)
                {
                    case ExperimentCondition.FixedComfort:
                        m_ComfortController.SetManualComfortMultiplier(m_FixedComfortMultiplier);
                        break;
                    case ExperimentCondition.AdaptiveComfort:
                        m_ComfortController.SetAutomaticIntervention(true);
                        break;
                    default:
                        m_ComfortController.SetManualComfortMultiplier(1f);
                        break;
                }
            }

            if (!writeMarker || m_Logger == null)
                return;

            string condition = m_Condition.ToString();
            m_Logger.SetCondition(condition);
        }

        float GetMovementMultiplier()
        {
            if (m_Condition == ExperimentCondition.AdaptiveComfort && m_ComfortController != null)
                return m_ComfortController.AppliedSpeedMultiplier;
            if (m_Condition == ExperimentCondition.FixedComfort)
                return m_FixedComfortMultiplier;
            return 1f;
        }

        Vector2 ReadKeyboardInput()
        {
            if (!Application.isEditor)
                return Vector2.zero;

            float forward = 0f;
            float turn = 0f;
            if (Input.GetKey(KeyCode.W) || Input.GetKey(KeyCode.UpArrow)) forward += 1f;
            if (Input.GetKey(KeyCode.S) || Input.GetKey(KeyCode.DownArrow)) forward -= 1f;
            if (Input.GetKey(KeyCode.A) || Input.GetKey(KeyCode.LeftArrow)) turn -= 1f;
            if (Input.GetKey(KeyCode.D) || Input.GetKey(KeyCode.RightArrow)) turn += 1f;
            return new Vector2(turn, forward);
        }

        void HandleEditorShortcuts()
        {
            if (!Application.isEditor)
                return;

            if (Input.GetKeyDown(KeyCode.Alpha1)) SetConditionNoAdaptation();
            if (Input.GetKeyDown(KeyCode.Alpha2)) SetConditionFixedComfort();
            if (Input.GetKeyDown(KeyCode.Alpha3)) SetConditionAdaptiveComfort();
            if (Input.GetKeyDown(KeyCode.Space)) ToggleStimulus();
            if (Input.GetKeyDown(KeyCode.E))
            {
                if (m_SessionActive) EndSession();
                else StartSession();
            }
            if (Input.GetKeyDown(KeyCode.Escape)) EmergencyStop();
        }

        void OnGUI()
        {
            if (!Application.isEditor || !m_ShowEditorInstructions)
                return;

            GUI.color = Color.white;
            GUILayout.BeginArea(new Rect(12f, 12f, 420f, 120f), GUI.skin.box);
            GUILayout.Label("Cybersickness experiment");
            GUILayout.Label("1/2/3: A NoAdaptation / B Fixed / C Adaptive");
            GUILayout.Label("Space: stimulus   E: session   Esc: emergency stop");
            if (m_ComfortController != null)
                GUILayout.Label(string.Format("Risk {0:0.00} ({1})  Speed x{2:0.00}", m_ComfortController.SmoothedRisk, m_ComfortController.CurrentRiskLevel, GetMovementMultiplier()));
            GUILayout.EndArea();
        }
    }
}
