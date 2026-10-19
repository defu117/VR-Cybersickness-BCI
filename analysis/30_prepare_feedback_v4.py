"""Audit identity/ratings/missingness and prepare causal simulated feedback."""
import json
from pathlib import Path
from forecasting.feedback import prepare_feedback

if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    config = json.loads((root / "configs/feedback_v4.json").read_text(encoding="utf-8"))
    for dataset in ("original", "secondary"):
        result = prepare_feedback(root, dataset, config, root.parent / f"research/results/feedback_v4_audit/{dataset}")
        print(json.dumps({k: v for k, v in result.items() if k not in ("motion_columns", "feedback_columns")}, ensure_ascii=False), flush=True)
