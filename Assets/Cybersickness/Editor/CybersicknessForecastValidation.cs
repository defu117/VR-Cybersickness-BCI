using System;
using System.IO;
using System.Reflection;
using UnityEditor;
using UnityEngine;

namespace VRBCI.Cybersickness.Editor
{
    /// <summary>Deterministic Editor checks; creates temporary objects and saves no scene.</summary>
    public static class CybersicknessForecastValidation
    {
        static readonly BindingFlags PrivateInstance = BindingFlags.Instance | BindingFlags.NonPublic;

        public static void RunBatchChecks()
        {
            GameObject root = new GameObject("ForecastValidationTemporary");
            TextAsset replayAsset = null;
            string output = Path.Combine(Path.GetDirectoryName(Application.dataPath), "analysis", "runs", "unity_validation.json");
            try
            {
                var first = AddController(root, "EveryFrame");
                var second = AddController(root, "EveryTenFrames");
                for (int i = 0; i < 100; i++)
                {
                    first.SetExternalRisk(0.7f, 1f, "validation", 0d);
                    if (i % 10 == 0)
                        second.SetExternalRisk(0.7f, 1f, "validation", 0d);
                    Invoke(first, "Update");
                    Invoke(second, "Update");
                }
                Require(Mathf.Abs(first.SmoothedRisk - second.SmoothedRisk) < 0.00001f,
                    "Smoothing depends on external message frequency.");
                Require(first.SmoothedRisk > 0.001f, "Cadence check did not advance the smoothing state.");

                var invalid = AddController(root, "InvalidQuality");
                invalid.SetExternalRisk(0.7f, float.NaN, "invalid", 0d);
                Require(!invalid.ExternalRiskEnabled, "NaN quality accepted.");
                invalid.SetExternalRisk(0.7f, float.PositiveInfinity, "invalid", 0d);
                Require(!invalid.ExternalRiskEnabled, "Infinite quality accepted.");
                invalid.SetExternalRisk(0.7f, 1f, "valid", 0d);
                invalid.SetExternalRisk(0.7f, 0.1f, "low_quality", 0d);
                Require(!invalid.ExternalRiskEnabled && invalid.ExternalRiskStale, "Low quality did not fall back.");

                first.SetExternalRisk(0.7f, 1f, "timeout", 0d);
                SetField(first, "m_LastExternalRiskTime", Time.unscaledTime - 3f);
                Invoke(first, "Update");
                Require(!first.ExternalRiskEnabled && first.ExternalRiskStale, "Timeout did not fall back.");
                Require(first.ExternalRiskSource == "hmd_fallback", "Timeout source not recorded.");

                second.EmergencyStop();
                Require(second.EmergencyStopped && second.AppliedSpeedMultiplier == 0f, "Emergency stop failed.");
                second.ResumeAfterEmergencyStop();
                Require(!second.EmergencyStopped && second.AppliedSpeedMultiplier == 1f, "Manual resume failed.");

                GameObject replayObject = new GameObject("Replay");
                replayObject.transform.parent = root.transform;
                var replay = replayObject.AddComponent<CybersicknessRiskReplay>();
                replayAsset = new TextAsset("timestamp_s,risk,quality,source\nNaN,0.7,1,test\n0,NaN,1,test\n1,0.7,NaN,test\n2,0.7,1,test\n");
                SetField(replay, "m_ReplayAsset", replayAsset);
                Require((bool)Invoke(replay, "LoadSamples") && replay.SampleCount == 1, "Malformed replay rows were not rejected.");

                var loggerObject = new GameObject("RatingContract");
                loggerObject.SetActive(false);
                loggerObject.transform.parent = root.transform;
                var logger = loggerObject.AddComponent<CybersicknessLogger>();
                SetField(logger, "m_AutoStart", false);
                Invoke(logger, "Awake");
                logger.SetContinuousSubjectiveRating(0.37f);
                Require(Mathf.Abs(logger.CurrentNormalizedRating - 0.37f) < 0.00001f &&
                        logger.CurrentRatingSource == "custom_continuous_0_1" && !float.IsNaN(logger.RatingUpdateTime),
                    "Continuous rating or provenance was lost.");
                foreach (float value in new[] { float.NaN, float.PositiveInfinity, -0.1f, 1.1f })
                    logger.SetContinuousSubjectiveRating(value);
                Require(Mathf.Abs(logger.CurrentNormalizedRating - 0.37f) < 0.00001f,
                    "Invalid rating replaced the valid report.");
                logger.SetSubjectiveRating(7);
                Require(Mathf.Abs(logger.CurrentNormalizedRating - 0.7f) < 0.00001f &&
                        logger.CurrentRatingSource == "manual_discrete_0_10", "Discrete rating scale provenance failed.");
                logger.ClearSubjectiveRating();
                Require(float.IsNaN(logger.CurrentNormalizedRating) && float.IsNaN(logger.RatingUpdateTime) &&
                        logger.CurrentRatingSource == string.Empty, "Cleared rating remained active.");
                var marker = loggerObject.AddComponent<CybersicknessExperimentMarker>();
                Invoke(marker, "Awake");
                marker.MarkCondition("condition_A");
                Require(logger.CurrentCondition == "condition_A", "Condition marker did not update the log condition.");

                Directory.CreateDirectory(Path.GetDirectoryName(output));
                File.WriteAllText(output, "{\"status\":\"passed\",\"checks\":[\"cadence_independent_smoothing\",\"finite_quality\",\"quality_fallback\",\"timeout_fallback\",\"emergency_stop_resume\",\"finite_replay_rows\",\"continuous_rating_contract\",\"rating_scale_provenance\",\"condition_marker_state\"],\"scope\":\"Editor contract checks; no XR hardware or participant efficacy validation\"}");
                Debug.Log("Forecast integration checks passed: " + output);
            }
            catch (Exception error)
            {
                Debug.LogException(error);
                if (Application.isBatchMode)
                    EditorApplication.Exit(1);
                throw;
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(root);
                if (replayAsset != null)
                    UnityEngine.Object.DestroyImmediate(replayAsset);
            }
        }

        static CybersicknessComfortController AddController(GameObject root, string name)
        {
            var child = new GameObject(name);
            child.transform.parent = root.transform;
            var controller = child.AddComponent<CybersicknessComfortController>();
            Invoke(controller, "Awake");
            return controller;
        }

        static object Invoke(object target, string method)
        {
            return target.GetType().GetMethod(method, PrivateInstance).Invoke(target, null);
        }

        static void SetField(object target, string name, object value)
        {
            target.GetType().GetField(name, PrivateInstance).SetValue(target, value);
        }

        static void Require(bool condition, string message)
        {
            if (!condition)
                throw new InvalidOperationException(message);
        }
    }
}
