using UnityEngine;
using UnityEngine.XR.Interaction.Toolkit.Samples.StarterAssets;

namespace VRBCI.Cybersickness
{
    /// <summary>
    /// Optional movement provider that exposes a safe, runtime-adjustable speed
    /// multiplier for the adaptive comfort controller.
    ///
    /// Keep the multiplier at 1 when no intervention is active. The component
    /// does not change input actions or the XR Origin hierarchy.
    /// </summary>
    [AddComponentMenu("VR BCI/Cybersickness Move Provider")]
    public sealed class CybersicknessMoveProvider : DynamicMoveProvider
    {
        [SerializeField, Range(0f, 1f)]
        [Tooltip("Multiplier applied to the desired continuous movement speed.")]
        float m_ComfortMultiplier = 1f;

        /// <summary>
        /// Current movement multiplier. A value of zero suppresses continuous
        /// movement while preserving the provider and its input bindings.
        /// </summary>
        public float ComfortMultiplier
        {
            get => m_ComfortMultiplier;
            set => m_ComfortMultiplier = Mathf.Clamp01(value);
        }

        /// <inheritdoc />
        protected override Vector3 ComputeDesiredMove(Vector2 input)
        {
            return base.ComputeDesiredMove(input) * m_ComfortMultiplier;
        }
    }
}
