using System.Collections.Generic;
using UnityEngine;

namespace VRBCI.Cybersickness
{
    /// <summary>
    /// Builds a deliberately simple corridor at runtime for repeatable Editor
    /// and Quest smoke tests. It is not intended to replace a production scene.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("VR BCI/Cybersickness Stimulus Geometry")]
    public sealed class CybersicknessStimulusGeometry : MonoBehaviour
    {
        [SerializeField] bool m_CreateAtRuntime = true;
        [SerializeField, Min(2f)] float m_CorridorWidth = 8f;
        [SerializeField, Min(10f)] float m_CorridorLength = 160f;
        [SerializeField, Min(2f)] float m_WallHeight = 4f;
        [SerializeField, Min(2f)] float m_ObstacleSpacing = 12f;

        readonly List<GameObject> m_GeneratedObjects = new List<GameObject>();

        void Start()
        {
            if (m_CreateAtRuntime)
                Build();
        }

        void OnDestroy()
        {
            for (int i = 0; i < m_GeneratedObjects.Count; i++)
            {
                if (m_GeneratedObjects[i] != null)
                    Destroy(m_GeneratedObjects[i]);
            }
            m_GeneratedObjects.Clear();
        }

        public void Build()
        {
            if (m_GeneratedObjects.Count > 0)
                return;

            Material floorMaterial = CreateMaterial(new Color(0.16f, 0.18f, 0.22f));
            Material wallMaterial = CreateMaterial(new Color(0.35f, 0.40f, 0.48f));
            Material markerMaterial = CreateMaterial(new Color(0.12f, 0.55f, 0.95f));

            GameObject floor = GameObject.CreatePrimitive(PrimitiveType.Plane);
            floor.name = "GeneratedStimulusFloor";
            floor.transform.position = new Vector3(0f, 0f, m_CorridorLength * 0.5f - 10f);
            floor.transform.localScale = new Vector3(m_CorridorWidth / 10f, 1f, m_CorridorLength / 10f);
            floor.GetComponent<Renderer>().sharedMaterial = floorMaterial;
            m_GeneratedObjects.Add(floor);

            CreateWall("GeneratedStimulusWallLeft", -m_CorridorWidth * 0.5f, wallMaterial);
            CreateWall("GeneratedStimulusWallRight", m_CorridorWidth * 0.5f, wallMaterial);

            int markerCount = Mathf.FloorToInt(m_CorridorLength / m_ObstacleSpacing);
            for (int i = 1; i <= markerCount; i++)
            {
                GameObject marker = GameObject.CreatePrimitive(PrimitiveType.Cube);
                marker.name = "GeneratedStimulusMarker_" + i.ToString("D2");
                marker.transform.position = new Vector3(0f, 0.15f, i * m_ObstacleSpacing - 10f);
                marker.transform.localScale = new Vector3(m_CorridorWidth * 0.8f, 0.1f, 0.35f);
                marker.GetComponent<Renderer>().sharedMaterial = markerMaterial;
                m_GeneratedObjects.Add(marker);
            }
        }

        void CreateWall(string name, float x, Material material)
        {
            GameObject wall = GameObject.CreatePrimitive(PrimitiveType.Cube);
            wall.name = name;
            wall.transform.position = new Vector3(x, m_WallHeight * 0.5f, m_CorridorLength * 0.5f - 10f);
            wall.transform.localScale = new Vector3(0.2f, m_WallHeight, m_CorridorLength);
            wall.GetComponent<Renderer>().sharedMaterial = material;
            m_GeneratedObjects.Add(wall);
        }

        static Material CreateMaterial(Color color)
        {
            Shader shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            Material material = new Material(shader) { color = color };
            return material;
        }
    }
}
