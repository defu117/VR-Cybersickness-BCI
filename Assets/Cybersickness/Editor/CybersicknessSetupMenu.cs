using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using VRBCI.Cybersickness;

namespace VRBCI.Cybersickness.Editor
{
    /// <summary>
    /// Editor-only one-click setup for the first logging/comfort-control smoke test.
    /// It intentionally changes only the currently open scene.
    /// </summary>
    public static class CybersicknessSetupMenu
    {
        const string RootName = "CybersicknessSystems";

        [MenuItem("VR BCI/Create Minimal Cybersickness Loop in Active Scene")]
        public static void CreateMinimalLoop()
        {
            Scene scene = SceneManager.GetActiveScene();
            if (!scene.IsValid())
            {
                EditorUtility.DisplayDialog("VR BCI", "当前没有有效的活动场景。", "确定");
                return;
            }

            GameObject root = GameObject.Find(RootName);
            if (root == null)
            {
                root = new GameObject(RootName);
                Undo.RegisterCreatedObjectUndo(root, "Create cybersickness systems");
            }

            CybersicknessLogger logger = root.GetComponent<CybersicknessLogger>();
            if (logger == null)
                logger = Undo.AddComponent<CybersicknessLogger>(root);

            CybersicknessComfortController controller = root.GetComponent<CybersicknessComfortController>();
            if (controller == null)
                controller = Undo.AddComponent<CybersicknessComfortController>(root);

            CybersicknessExperimentMarker marker = root.GetComponent<CybersicknessExperimentMarker>();
            if (marker == null)
                marker = Undo.AddComponent<CybersicknessExperimentMarker>(root);

            CybersicknessExperimentController experiment = root.GetComponent<CybersicknessExperimentController>();
            if (experiment == null)
                experiment = Undo.AddComponent<CybersicknessExperimentController>(root);

            CybersicknessRiskReplay replay = root.GetComponent<CybersicknessRiskReplay>();
            if (replay == null)
                replay = Undo.AddComponent<CybersicknessRiskReplay>(root);

            CybersicknessStimulusGeometry geometry = root.GetComponent<CybersicknessStimulusGeometry>();
            if (geometry == null)
                geometry = Undo.AddComponent<CybersicknessStimulusGeometry>(root);

            Camera headCamera = Camera.main;
            if (headCamera == null)
                headCamera = Object.FindObjectOfType<Camera>();

            if (headCamera != null)
            {
                SetObjectReference(logger, "m_HeadTransform", headCamera.transform);
                SetObjectReference(controller, "m_HeadTransform", headCamera.transform);
            }

            CybersicknessMoveProvider moveProvider = Object.FindObjectOfType<CybersicknessMoveProvider>();
            if (moveProvider != null)
                SetObjectReference(controller, "m_MoveProvider", moveProvider);

            SetObjectReference(logger, "m_ComfortController", controller);
            SetObjectReference(marker, "m_Logger", logger);
            SetObjectReference(marker, "m_ComfortController", controller);
            SetObjectReference(experiment, "m_Logger", logger);
            SetObjectReference(experiment, "m_ComfortController", controller);
            SetObjectReference(experiment, "m_Marker", marker);
            SetObjectReference(replay, "m_ComfortController", controller);

            EditorUtility.SetDirty(root);
            EditorSceneManager.MarkSceneDirty(scene);
            Selection.activeGameObject = root;

            string cameraText = headCamera == null
                ? "未找到 Camera；运行前请在 Inspector 指定 Head Transform。"
                : "已绑定头部相机：" + headCamera.name;
            EditorUtility.DisplayDialog(
                "VR BCI 最小闭环已创建",
                "CybersicknessSystems 已添加 Logger、Comfort Controller、Experiment Marker、Experiment Controller 和 Risk Replay。\n" + cameraText + "\n\n按 Play 后会在 Console 输出 CSV 路径。编辑器中可用 1/2/3 切换 A/B/C，Space 开始刺激，E 开始/结束会话。",
                "确定");
        }

        static void SetObjectReference(Object target, string propertyName, Object value)
        {
            SerializedObject serialized = new SerializedObject(target);
            SerializedProperty property = serialized.FindProperty(propertyName);
            if (property == null)
                return;

            property.objectReferenceValue = value;
            serialized.ApplyModifiedPropertiesWithoutUndo();
        }
    }
}
