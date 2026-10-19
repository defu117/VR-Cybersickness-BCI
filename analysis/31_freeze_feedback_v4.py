"""Write the local protocol/source/data lock before any feedback model fitting."""
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
import sklearn
from forecasting.dataset import sha256

if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    lock = root / "research/results/feedback_v4_lock.json"
    paths = ["research/feedback_v4_protocol.md", "analysis/configs/feedback_v4.json",
             "analysis/30_prepare_feedback_v4.py", "analysis/31_freeze_feedback_v4.py",
             "analysis/32_run_feedback_v4.py", "analysis/forecasting/feedback.py",
             "analysis/forecasting/action.py", "analysis/forecasting/alerts.py",
             "analysis/forecasting/evaluation.py", "analysis/forecasting/dataset.py",
             "analysis/forecasting/secondary.py", "analysis/configs/action_v3.json"]
    sources = {p: sha256(root / p) for p in paths}
    data = {name: {"path": f"analysis/data/processed/feedback_v4/{name}.csv",
                   "sha256": sha256(root / f"analysis/data/processed/feedback_v4/{name}.csv"),
                   "audit_summary_sha256": sha256(root / f"research/results/feedback_v4_audit/{name}/summary.json")}
            for name in ("original", "secondary")}
    stable = {"date": "2026-10-19", "status": "exploratory_local_freeze_before_first_feedback_fit",
              "source_sha256": sources, "data": data, "python": platform.python_version(), "sklearn": sklearn.__version__}
    if lock.exists():
        old = json.loads(lock.read_text(encoding="utf-8"))
        if {k: v for k, v in old.items() if k != "runtime_clock_utc"} != stable:
            raise SystemExit("Existing freeze differs. Preserve old runs and use an explicit new version.")
        print("Existing identical freeze retained.")
    else:
        stable["runtime_clock_utc"] = datetime.now(timezone.utc).isoformat()
        lock.write_text(json.dumps(stable, indent=2, ensure_ascii=False), encoding="utf-8")
        print("Frozen before feedback fitting:", lock)
