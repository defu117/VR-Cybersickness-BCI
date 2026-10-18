using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEditor;
using UnityEngine;
using Debug = UnityEngine.Debug;

namespace VRBCI.Cybersickness.Editor
{
    public static class CybersicknessActionValidation
    {
        static readonly BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
        static void Require(bool ok, string message) { if (!ok) throw new InvalidOperationException(message); }

        public static void RunBatchChecks()
        {
            string directory = Path.Combine(Path.GetDirectoryName(Application.dataPath), "analysis", "runs", "action_validation");
            Directory.CreateDirectory(directory);
            var root = new GameObject("ActionValidationTemporary");
            var assets = new List<TextAsset>();
            var checks = new List<string>();
            var watch = Stopwatch.StartNew();
            try
            {
                CybersicknessForecastValidation.RunBatchChecks();
                checks.Add("existing_nine_contract_checks");
                var controller = root.AddComponent<CybersicknessComfortController>();
                var replay = root.AddComponent<CybersicknessRiskReplay>();
                var events = new List<CybersicknessComfortController.TimingEvent>();
                controller.TimingEventRecorded += events.Add;
                var csv = new System.Text.StringBuilder("timestamp_s,risk,quality,source,prediction_id,alarm_id,source_timestamp_s\n");
                for (int i=0; i<=30; i++)
                    csv.AppendLine((i / 10d).ToString("R", CultureInfo.InvariantCulture) + ",0.7,1,synthetic,p0,a0,100");
                var asset = new TextAsset(csv.ToString()); assets.Add(asset);
                replay.SetReplayAsset(asset);
                Require(replay.StartReplayAt(0f, true, Path.Combine(directory, "last_alarm")), "Replay failed to start.");
                Advance(replay, controller, 40f);
                Require(replay.LastReplayStatus == "recovered", "Final alarm did not recover normally.");
                Require(events.Count(e=>e.type=="alarm_received") == 1, "Heartbeat duplicated an alarm.");
                Require(events.Any(e=>e.type=="action_effective"), "Last positive alarm was truncated.");
                Require(events.First(e=>e.type=="recovery_started").localTime > 10d, "Recovery ignored minimum duration.");
                Require(events.Any(e=>e.type=="recovery_completed"), "Recovery completion missing.");
                checks.AddRange(new[]{"deduplicated_heartbeats","last_alarm_hold_and_tail","action_and_recovery_events"});
                float firstStart = controller.InterventionStartTime;
                events.Clear();
                replay.StartReplayAt(0f, true, Path.Combine(directory, "repeated_replay"));
                Advance(replay, controller, 40f);
                Require(events.Count(e=>e.type=="alarm_received")==1 &&
                    Mathf.Abs(firstStart-controller.InterventionStartTime)<.02f, "Replay state leaked across runs.");
                checks.Add("repeat_resets_clock_and_alarm_identity");

                controller.ResetForReplay(true, 0f); controller.ConfigureResearchReplay();
                for (int i=1; i<=1800; i++)
                {
                    float now = i / 60f;
                    controller.SetSimulationReceiptTime(now);
                    controller.SetExternalRiskSample(.7f, 1f, "synthetic", now, "p", "a");
                    controller.AdvanceSimulationFrame(1f/60f, now);
                }
                Require(controller.InterventionStartTime < 2f, "Sustained risk refreshed episode start.");
                for (int i=1801; i<=2100; i++)
                {
                    float now=i/60f; controller.SetSimulationReceiptTime(now);
                    controller.SetExternalRiskSample(0f,1f,"synthetic",now,"p","");
                    controller.AdvanceSimulationFrame(1f/60f,now);
                }
                Require(controller.AppliedSpeedMultiplier >= .99f, "Sustained risk prevented recovery.");
                checks.Add("sustained_high_does_not_restart_episode");

                replay.StartReplayAt(0f,true,Path.Combine(directory,"manual_stop"));
                replay.AdvanceReplayAt(1f); controller.AdvanceSimulationFrame(1f/60f,1f);
                replay.StopReplay();
                Require(File.ReadAllText(Path.Combine(directory,"manual_stop_summary.json")).Contains("\"truncated\":true"),
                    "Manual stop not marked truncated.");
                checks.Add("manual_stop_truncated");

                replay.StartReplayAt(0f,true,Path.Combine(directory,"emergency_tail"));
                controller.EmergencyStop(); Advance(replay,controller,40f);
                Require(replay.LastReplayStatus=="tail_timeout", "Unrecovered emergency tail did not time out.");
                Require(controller.EmergencyStopped, "Replay bypassed emergency stop.");
                controller.ResumeAfterEmergencyStop();
                checks.Add("emergency_tail_timeout");

                foreach (string input in new[]{"timestamp_s,risk\n0,0\n1,0.7\n", "timestamp_s,risk\n2,0\n1,0.7\n"})
                {
                    var legacy=new TextAsset(input); assets.Add(legacy); replay.SetReplayAsset(legacy);
                    Require(replay.SampleCount == (input.Contains("2,0") ? 0 : 2), "Legacy parsing or reset rejection failed.");
                }
                checks.Add("legacy_csv_and_nonmonotonic_rejection");
                var moveObject=new GameObject("MoveProviderContract");
                moveObject.SetActive(false); moveObject.transform.parent=root.transform;
                var provider=moveObject.AddComponent<CybersicknessMoveProvider>();
                typeof(CybersicknessComfortController).GetField("m_MoveProvider",Private).SetValue(controller,provider);
                controller.SetManualComfortMultiplier(.6f);
                Require(Mathf.Abs(provider.ComfortMultiplier-.6f)<.00001f,"Move provider did not receive the applied multiplier.");
                checks.Add("move_provider_receives_applied_multiplier");
                watch.Stop();
                File.WriteAllText(Path.Combine(directory,"validation.json"), "{\"status\":\"passed\",\"checks\":["+
                    string.Join(",",checks.Select(x=>"\""+x+"\""))+"],\"wall_clock_compute_ms\":"+
                    watch.Elapsed.TotalMilliseconds.ToString("R",CultureInfo.InvariantCulture)+
                    ",\"scope\":\"deterministic desktop checks with explicit simulation clock, not XR latency or symptom efficacy\"}");
                Debug.Log("Action timing checks passed.");
            }
            catch(Exception error)
            {
                Debug.LogException(error);
                if(Application.isBatchMode) EditorApplication.Exit(1);
                throw;
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(root);
                foreach(var asset in assets) UnityEngine.Object.DestroyImmediate(asset);
            }
        }

        static void Advance(CybersicknessRiskReplay replay, CybersicknessComfortController controller, float maximum, string prefix=null)
        {
            var samples=new List<double>();
            for(int i=1;i<=Mathf.CeilToInt(maximum*60f)&&replay.IsPlaying;i++)
            {
                float now=i/60f;
                replay.AdvanceReplayAt(now);
                if(replay.IsPlaying)
                {
                    long start=Stopwatch.GetTimestamp();
                    controller.AdvanceSimulationFrame(1f/60f,now);
                    samples.Add((Stopwatch.GetTimestamp()-start)*1000d/Stopwatch.Frequency);
                }
            }
            if(prefix!=null && samples.Count>0)
            {
                samples.Sort();
                File.WriteAllText(prefix+"_compute.json","{\"frames\":"+samples.Count+
                    ",\"mean_update_ms\":"+samples.Average().ToString("R",CultureInfo.InvariantCulture)+
                    ",\"median_update_ms\":"+samples[samples.Count/2].ToString("R",CultureInfo.InvariantCulture)+
                    ",\"p95_update_ms\":"+samples[Math.Min(samples.Count-1,(int)(samples.Count*.95))].ToString("R",CultureInfo.InvariantCulture)+
                    ",\"includes_frame_logging\":true,\"scope\":\"Stopwatch wall-clock controller update including logging; separate from simulated time; not XR latency\"}");
            }
        }

        public static void RunExportedReplay()
        {
            string[] args=Environment.GetCommandLineArgs();
            string input=args[Array.IndexOf(args,"-replayCsv")+1];
            string prefix=args[Array.IndexOf(args,"-replayOutput")+1];
            var root=new GameObject("ExportedReplayTemporary");
            var asset=new TextAsset(File.ReadAllText(input));
            try
            {
                var controller=root.AddComponent<CybersicknessComfortController>();
                var replay=root.AddComponent<CybersicknessRiskReplay>();
                replay.SetReplayAsset(asset);
                Require(replay.StartReplayAt(0f,true,prefix),"Exported replay could not start.");
                Advance(replay,controller,7200f);
                Require(!replay.IsPlaying,"Replay exceeded maximum duration.");
            }
            finally { UnityEngine.Object.DestroyImmediate(root); UnityEngine.Object.DestroyImmediate(asset); }
        }

        public static void RunReplayList()
        {
            string[] args=Environment.GetCommandLineArgs();
            string list=args[Array.IndexOf(args,"-replayList")+1];
            foreach(string line in File.ReadAllLines(list))
            {
                if(string.IsNullOrWhiteSpace(line)) continue;
                string[] parts=line.Split('|');
                var root=new GameObject("ReplayListTemporary");
                var asset=new TextAsset(File.ReadAllText(parts[0]));
                try
                {
                    var controller=root.AddComponent<CybersicknessComfortController>();
                    var replay=root.AddComponent<CybersicknessRiskReplay>();
                    replay.SetReplayAsset(asset);
                    Require(replay.StartReplayAt(0f,true,parts[1]),"Replay list item could not start.");
                    Advance(replay,controller,7200f,parts[1]);
                    Require(!replay.IsPlaying,"Replay exceeded maximum duration.");
                }
                finally { UnityEngine.Object.DestroyImmediate(root); UnityEngine.Object.DestroyImmediate(asset); }
            }
            RunBatchChecks();
        }
    }
}
