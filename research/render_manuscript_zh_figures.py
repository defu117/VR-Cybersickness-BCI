"""Generate Chinese scientific plots from unchanged archived aggregate results."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def main():
    font_path = Path("C:/Windows/Fonts/simhei.ttf")
    if not font_path.is_file():
        raise FileNotFoundError("Chinese plot font required: C:/Windows/Fonts/simhei.ttf")
    font_manager.fontManager.addfont(str(font_path))
    family = font_manager.FontProperties(fname=str(font_path)).get_name()
    plt.rcParams.update({"font.family": family, "font.size": 10, "axes.unicode_minus": False,
                         "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})
    root = ROOT / "results" / "main_h6"
    output = root / "figures_zh"
    output.mkdir(exist_ok=True)
    metrics = pd.read_csv(root / "subject_metrics.csv", dtype={"subject": str})
    summary = pd.read_csv(root / "summary.csv")
    labels = {"eeg_ridge": "仅脑电岭回归", "fusion_cnn_lstm": "融合 CNN-LSTM", "fusion_cqr": "融合 CQR",
              "fusion_hgb": "融合 HGB", "fusion_ridge": "融合岭回归", "fusion_state": "估计当前状态后持平",
              "hmd_ridge": "仅头显岭回归", "oracle_rating_persistence": "真实当前评分持平*", "time_hgb": "仅时间 HGB"}
    mae = metrics[metrics.policy == "gated"].groupby(["model", "subject"]).mae.mean().unstack(0)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for i, name in enumerate(mae.columns):
        values = mae[name].dropna().to_numpy()
        ax.scatter(np.full(len(values), i), values, alpha=.65, s=20)
        ax.scatter([i], [values.mean()], marker="_", c="black", s=230, zorder=5)
    ax.set_xticks(range(len(mae.columns)), [labels[c] for c in mae.columns], rotation=30, ha="right")
    ax.set_ylabel("留出参与者的未来峰值评分 MAE")
    ax.set_title("各留出参与者的预测误差")
    fig.text(.99, .01, "* 需要当前真实自报评分，不属于纯被动传感器模型", ha="right", fontsize=8)
    fig.tight_layout(rect=(0, .04, 1, 1))
    for extension in ("png", "pdf"):
        fig.savefig(output / f"subject_mae_zh.{extension}", dpi=220)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.8))
    selected = summary[summary.model.isin({"fusion_hgb", "fusion_cqr", "fusion_cnn_lstm"})]
    collisions = {}
    for row in selected.itertuples():
        color, marker = ("tab:blue", "o") if row.policy == "raw" else ("tab:orange", "s")
        ax.scatter(row.false_alarms_per_min, row.event_recall, c=color, marker=marker, s=55)
        key = (round(row.false_alarms_per_min, 1), round(row.event_recall, 2))
        offset = collisions.get(key, 0)
        collisions[key] = offset + 1
        policy = "未门控" if row.policy == "raw" else "门控"
        ax.annotate(f"{labels[row.model]}（{policy}）", (row.false_alarms_per_min, row.event_recall),
                    xytext=(7, 8+14*offset), textcoords="offset points", fontsize=8,
                    arrowprops={"arrowstyle": "-", "color": color, "lw": .5})
    ax.set(xlabel="每有效监测分钟的误警次数", ylabel="事件片段召回率", title="预警负担与事件召回的权衡")
    ax.set_ylim(-.05, 1.08)
    ax.set_xlim(-.01, max(.05, selected.false_alarms_per_min.max()*1.8+.02))
    fig.tight_layout()
    for extension in ("png", "pdf"):
        fig.savefig(output / f"warning_tradeoff_zh.{extension}", dpi=220)
    plt.close(fig)
    print(output)


if __name__ == "__main__":
    main()
