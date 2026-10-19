"""Render Chinese result/interpretation documents from archived complete tables."""
import json
from pathlib import Path
import shutil
import numpy as np
import pandas as pd
from forecasting.dataset import sha256

ROOT = Path(__file__).resolve().parent.parent
RESEARCH = ROOT / "research"
PRIMARY = "i30_d3"
NAMES = {"last_report": "最近已到达评分保持", "feedback_history_hgb": "评分历史 HGB", "feedback_motion_hgb": "评分历史＋运动 HGB"}


def load(dataset):
    folder = RESEARCH / f"results/feedback_v4_{dataset}"
    summary = pd.read_csv(folder / "summary.csv")
    paired = pd.read_csv(folder / "paired_uncertainty.csv")
    metrics = pd.read_csv(folder / "subject_metrics.csv", dtype={"subject": str})
    return summary, paired, metrics


def pair(paired, metric, baseline="feedback_history_hgb", comparison="feedback_motion_hgb"):
    return paired[paired.condition.eq(PRIMARY) & paired.metric.eq(metric) & paired.baseline.eq(baseline) & paired.comparison.eq(comparison)].iloc[0]


def numeric_table(summary):
    rows = summary[summary.condition.eq(PRIMARY)].set_index("model")
    text = ["| 方法 | 原生峰值 MAE | 可用动作召回 | 误警/分钟 | 动作占用 |", "|---|---:|---:|---:|---:|"]
    for name in NAMES:
        r = rows.loc[name]
        text.append(f"| {NAMES[name]} | {r.mae:.4f} | {r.usable_recall:.2%} | {r.false_alarms_per_min:.4f} | {r.occupied_fraction:.2%} |")
    return text


def interpretation(paired):
    mae, action = pair(paired, "mae"), pair(paired, "usable_recall")
    if mae.ci_high < 0:
        error = "运动增强相对评分历史的误差差值区间低于零，为本队列、主条件中的探索性增量信息证据。"
    elif mae.ci_low > 0:
        error = "运动增强相对评分历史的误差差值区间高于零，主条件下表现更差。"
    else:
        error = "运动增强相对评分历史的误差差值区间跨零，未获得稳定增量信息证据。"
    if action.ci_low > 0:
        timely = "可用动作召回差值区间高于零，但仍仅代表固定离线执行配置中的动作机会。"
    elif action.ci_high < 0:
        timely = "可用动作召回差值区间低于零，主条件下也更低；误警和占用下降伴随可用命中损失，不能解释为同等效果下减少干预。"
    else:
        timely = "可用动作召回没有获得区间高于零的稳定改善证据，不能据此声称更适合及时干预。"
    versus_hold = pair(paired, "mae", "last_report", "feedback_motion_hgb")
    if versus_hold.ci_high < 0:
        baseline = "运动增强相对最近报告保持的 MAE 差值区间也低于零。"
    else:
        baseline = "运动增强相对最近报告保持的 MAE 尚未获得差值区间低于零的改善证据。"
    return error + timely + baseline


def write_documents():
    complete = json.loads((RESEARCH / "results/feedback_v4_completion.json").read_text(encoding="utf-8"))
    if complete["status"] != "complete":
        raise ValueError("Incomplete study must not be presented as complete")
    original, op, om = load("original")
    secondary, sp, sm = load("secondary")
    main_mae, main_action = pair(sp, "mae"), pair(sp, "usable_recall")
    history_hold = pair(sp, "mae", "last_report", "feedback_history_hgb")
    motion_hold = pair(sp, "mae", "last_report", "feedback_motion_hgb")
    audit_dir = RESEARCH / "results/feedback_v4_audit"
    oa = json.loads((audit_dir / "original/summary.json").read_text(encoding="utf-8"))
    sa = json.loads((audit_dir / "secondary/summary.json").read_text(encoding="utf-8"))
    age = pd.read_csv(audit_dir / "secondary/condition_availability.csv").set_index("condition").loc[PRIMARY]
    text = ["# 数据协议、低频反馈和文献比较：v4 完成报告", "", "日期：2026-10-19。", "",
            "## 1. 本轮交付", "",
            "已完成两源编号/评分/缺失审计、固定反馈可用性协议、完整模型评估、逐编号不确定性和针对性文献比较。",
            f"共 {complete['folds']} 个留编号/种子折、{complete['model_condition_seed_id_combinations']} 个模型/条件/编号/种子评估组合。",
            "三个模型是最近报告保持、评分历史 HGB 和评分历史加运动 HGB；反馈间隔 15/30/60 秒、延迟 0/3/6 秒，共 9 条件。",
            "HGB 为直方图梯度提升树；回归使用编号等总量基础权重，事件分类在基础权重上再平衡类别，最终分类权重不保证编号等总量。详见 feedback_v4_implementation_notes.md。",
            "协议与拟合代码已在反馈模型拟合前本地冻结；已有 v1–v3 结果可见，本轮属于探索性分析。", "",
            "## 2. 数据和输入可用性核查", "",
            f"- 第一源审计 69 段，纳入 {oa['included_recordings']} 段、{oa['included_identifiers']} 个作者编号、每条件 {oa['windows_per_condition']} 个窗口。",
            f"- 第二源审计 428 段，属性冲突/无法确认的 38 个编号对应 349 段整组排除，纳入 {sa['included_recordings']} 段、{sa['included_identifiers']} 个作者编号、每条件 {sa['windows_per_condition']} 个窗口。",
            "- 全部纳入窗口的评分目标、越阈时刻及历史运动特征均从原始记录重算一致；9 条件使用同一窗口队列。",
            "- 第二源 37 段包含局部运动缺失，仅使用历史完整的窗口；不进行未来插值或用未来报告填补。",
            "- 未发现跨编号精确序列重复；PA112/PA114 静态属性重合，但不足以判定同一人，不擅自合并。真实身份及跨编号别名仍需作者确认。",
            "- 每次反馈记录采样、请求和到达时间；预测只读取已经到达的报告，当前真实和未来评分只用于标签/评价。",
            f"- 主条件第二源的窗口平均评分年龄为 {age.mean_feedback_age_s:.2f} 秒、最大 {age.max_feedback_age_s:.2f} 秒；3 秒传输延迟并不等于只有 3 秒陈旧度。",
            "- 保存频率与值变化频率均已统计，但没有实际报告按钮事件，无法恢复真实报告次数、反应时间或填报负担。", "",
            "第一源 43 段中 38 段含不在 0.1 档位的连续导出值；作者描述与导出记录的对应机制尚未确认，未对评分强制取整。第二源保留原生整数 FMS。", "",
            "详见 [第一源审计](results/feedback_v4_audit/original/report_zh.md)、[第二源审计](results/feedback_v4_audit/secondary/report_zh.md)。", "",
            "## 3. 主结果：第二源，30 秒反馈 / 3 秒延迟", ""]
    text += numeric_table(secondary)
    text += ["", "原生尺度为 0–20 FMS；各编号先平均 3 个随机种子，再按编号宏平均。", "",
             f"运动增强减评分历史的 MAE 差值为 **{main_mae.difference:.4f}**，描述性 95% 区间 **[{main_mae.ci_low:.4f}, {main_mae.ci_high:.4f}]**（{int(main_mae.identifiers)} 个配对编号）。",
             f"可用动作召回差值为 **{main_action.difference*100:.2f} 个百分点**，区间 **[{main_action.ci_low*100:.2f}, {main_action.ci_high*100:.2f}] 个百分点**。", "",
             f"评分历史相对最近报告保持的 MAE 差值为 {history_hold.difference:.4f}，区间 [{history_hold.ci_low:.4f}, {history_hold.ci_high:.4f}]；运动增强相对保持为 {motion_hold.difference:.4f}，区间 [{motion_hold.ci_low:.4f}, {motion_hold.ci_high:.4f}]。两者区间均跨零，表中的平均误差降低尚不能说明稳定超过保持基线。", "",
             interpretation(sp), "",
             "误警、占用约束只在校准编号的主条件上选择阈值；测试编号及其他反馈条件可能超限，不能把校准预算当作逐人保证。", "",
             "| 数据源 | 方法 | 主条件误警超限折 | 主条件占用超限折 |", "|---|---|---:|---:|"]
    for dataset, metrics in (("第一源", om), ("第二源", sm)):
        for model in ("feedback_history_hgb", "feedback_motion_hgb"):
            part = metrics[metrics.condition.eq(PRIMARY) & metrics.model.eq(model)]
            text.append(f"| {dataset} | {NAMES[model]} | {int(part.false_budget_exceeded.sum())}/{len(part)} | {int(part.occupancy_budget_exceeded.sum())}/{len(part)} |")
    text += ["", "表中是编号/种子折，不是新增参与者数量。提前量只在命中子集定义，未命中为 NA，详细指标见逐编号结果。", "",
             "![第二源反馈条件结果](results/feedback_v4_secondary/feedback_conditions.png)", "",
             "其他 8 条件是固定阈值转用的敏感性分析，不据其最佳单点另立主结论。全部结果与配对区间见结果目录。", "",
             "## 4. 第一源的支持性分析", ""]
    text += numeric_table(original)
    or_mae, or_action = pair(op, "mae"), pair(op, "usable_recall")
    text += ["", "原生尺度为 0–1，不与第二源的 MAE 数值直接比较。这里仅输入头动，不检验 EEG 增益，队列仍受既有 EEG 质量筛选影响。",
             "v4 与 v3 的输入及训练权重不同，不将跨版本误差差异当作同条件方法提升证据。",
             f"运动增强减评分历史 MAE：{or_mae.difference:.4f}，区间 [{or_mae.ci_low:.4f}, {or_mae.ci_high:.4f}]。",
             f"可用动作召回差值：{or_action.difference*100:.2f} 个百分点，区间 [{or_action.ci_low*100:.2f}, {or_action.ci_high*100:.2f}]。",
             interpretation(op), "",
             "## 5. 文献定位与论文写法", "",
             "已完成 [文献比较及证据分层](feedback_v4_literature_zh.md)，覆盖评分辅助预测、个体化、少样本预测与自适应干预。",
             "加入评分、个体化或连接预测和干预本身已有相关研究。本轮定位为信息可用性与动作机会的可复现评估，尚不能将 HGB 或该应用组合视为独立算法创新。",
             "已核对原始摘要与官方/作者全文的内容分开标记；未取得的全文不假装精确复现，不用异任务指标声称全面优于现有方法。",
             "可供整合入论文的 [中文方法、结果和证据边界补充稿](feedback_v4_paper_addendum_zh.md) 单独保存，原稿和旧 PDF 保留。", "",
             "## 6. 尚未解决的事项", "",
             "1. 作者编号与真实身份映射，尤其 PA112/PA114 的属性重合；目前结论依赖按作者编号分组的假设。",
             "2. 真实报告事件、人的填报反应和提示影响；抽稀原记录不能测量这些因素。",
             "3. 新场景/新记录验证和最接近文献的完整同条件对照；目前只有编号隔离，场景未整体留出。本轮区间为探索描述且未作多重比较校正。",
             "4. 真实头显采集到显示的时延、症状与任务表现；没有新增真人实验或症状减缓证据。", "",
             "## 7. 复现与完整性", "",
             "准备：`analysis/30_prepare_feedback_v4.py`；冻结：`31_freeze_feedback_v4.py`；计算：`32_run_feedback_v4.py`；归档：`33_report_feedback_v4.py`；本报告：`34_write_feedback_documents.py`。",
             "具体命令见 research/README.md。当前锁、完整网格、逐编号结果、阈值搜索及来源校验值均在 results/feedback_v4*。",
             "完整逐窗口输入/预测和原始流位于 Git 忽略的 analysis/data 与 analysis/runs；共享报告只保存审计、分组、结果及校验信息。",
             "初次拟合前的 pandas 只读数组故障及修复已记录，首次失败没有拟合模型；前后锁均保留。见 results/feedback_v4_execution_notes.md。",
             "本轮没有新增或运行单元测试、没有重跑 Unity 验收；数据与结果完整性核查属于本轮研究审计。"]
    (RESEARCH / "progress_feedback_v4_zh.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    paper = ["# 低频症状反馈可行性分析：论文补充稿", "",
             "本稿供整合至论文方法、结果和讨论；不代表已完成投稿。日期：2026-10-19。", "",
             "## 方法：研究设计与任务", "",
             "本研究对两套公开晕动症数据进行独立二次分析。第二源以作者 PA 编号分组，在属性冲突记录整组排除后保留 48 个编号、79 段记录。第一源采用既有质量筛选队列的 13 个编号、43 段记录，仅使用其头动特征。编号对应的真实身份及跨编号别名无法独立确认，结果依赖于作者编号分组假设。",
             "在每段评分记录起点建立 15、30 或 60 秒请求日程，并设置 0、3 或 6 秒传输延迟。请求值仅取此前、允许间隔内的最近评分；在预测时刻，只能使用已经到达的报告。每次报告保留采样、请求和到达时刻。过去报告可以保持，未到达报告不得回填。9 种条件采用共同窗口队列。",
             "模型每 3 秒预测未来 6 秒记录评分峰值，并另行预测评分加重事件。原生增量阈值分别为 0–1 评分的 0.1，以及 0–20 FMS 的 1 分。这些是研究标签，不是医学诊断或症状改善阈值。当前真实评分只用于离线标签与评价，不参与部署输入或报警分数计算。", "",
             "## 方法：对照、划分与动作评价", "",
             "对照包括最近已到达评分保持、固定 HGB 评分历史模型，以及同参数的评分历史加运动模型。运动仅使用过去 9 秒的因果统计，不输入 EEG、人口属性或编号。每个留出编号的剩余编号划分为拟合和校准组；三组隔离，种子固定为 7、19、42。训练按编号加权，条件间不将重复标签视为独立参与者。",
             "回归器使用每编号总量相同的基础权重；分类器先构建这一基础权重，再按拟合组加权后的正负类别总量平衡类别，因此其最终编号总量可能不同。校准和测试均按编号宏平均。",
             "报警阈值仅在校准组主条件（30 秒请求、3 秒延迟）确定，在宏平均误警 0.5 次/分钟、占用 20% 预算内最大化可用动作召回；阈值原样用于测试组所有条件。倍率达到 0.80 后距离评分事件仍至少提前 2 秒定义为可用机会。该倍率为控制器命令，不是测得的身体运动或治疗生效。",
             "主要指标是第二源主条件中运动增强相对评分历史的原生峰值 MAE 差值。先平均编号内种子，再作编号宏平均；配对区间采用 2,000 次编号 bootstrap。无事件编号不进入召回平均，仍进入误警和占用平均。其他条件和第一源均作为探索性补充。", "",
             "## 结果", ""]
    paper += numeric_table(secondary)
    paper += ["", f"第二源主条件下，运动增强相对评分历史 MAE 差值为 {main_mae.difference:.4f}（描述性 95% 区间 [{main_mae.ci_low:.4f}, {main_mae.ci_high:.4f}]）；可用动作召回差值为 {main_action.difference*100:.2f} 个百分点（[{main_action.ci_low*100:.2f}, {main_action.ci_high*100:.2f}]）。",
              f"评分历史相对最近报告保持的 MAE 差值区间为 [{history_hold.ci_low:.4f}, {history_hold.ci_high:.4f}]，运动增强相对保持为 [{motion_hold.ci_low:.4f}, {motion_hold.ci_high:.4f}]，均跨零。",
              interpretation(sp), "",
              "## 讨论：信息可用性与已有工作", "",
              "[Ryu 与 Kim](https://scholar.korea.ac.kr/item/d20b92d1-569b-445d-bcf8-db22ce5abf5f)已经使用运动和 FMS 进行预测，"
              "[Tasnim 等](https://pubmed.ncbi.nlm.nih.gov/38437124/)讨论个体化预测，"
              "[Terzioğlu 等](https://link.springer.com/article/10.1007/s00371-024-03505-0)研究预测辅助的渲染调整。"
              "因此，本研究的候选价值在于显式约束评分可用性并检验运动的增量价值和动作机会；这仍需要进一步的同条件文献对照与独立验证，不能由方法组合本身证明新颖性。", "",
              "## 证据层次与限制", "",
              "**算法层面：**本结果反映特定公开队列、任务及模拟反馈条件下的预测表现。主观评分保存频率不同于实际报告频率；PA112/PA114 属性重合与跨编号别名仍需确认，不能将编号隔离称为独立认证的真实身份隔离。",
              "**执行层面：**动作机会来自既有已进行 Unity 对照的离线控制模型；本轮没有新增头显端验收。执行输出、占用和提前量用于说明软件行为，不能代替采集、网络和显示的端到端时延。",
              "模拟减速后没有重新生成运动输入或症状轨迹，故固定输入回放也不构成真实闭环策略效果或稳定性验证。",
              "**干预层面：**本项目没有新增受试者减缓实验。离线症状轨迹不随模拟动作改变，所以无法估计动作对症状的因果影响。报告抽稀也不能说明负担降低或依从性提高。后续需要真实反馈协议、适当审批的对照实验及症状和任务结果。", "",
              "两源评分尺度、运动含义和队列筛选不同，不跨源直接比较 MAE。场景未整体留出，不声称跨场景泛化。描述性区间未作多重比较校正，敏感性条件不得替代预设主条件。"]
    paragraphs = []
    for line in paper:
        if paragraphs and paragraphs[-1] and line and not (paragraphs[-1].startswith("|") and line.startswith("|")):
            paragraphs.append("")
        paragraphs.append(line)
    (RESEARCH / "feedback_v4_paper_addendum_zh.md").write_text("\n".join(paragraphs) + "\n", encoding="utf-8")
    integrity = {"completion": complete, "source_sha256": {"analysis/33_report_feedback_v4.py": sha256(ROOT / "analysis/33_report_feedback_v4.py"),
                 "analysis/34_write_feedback_documents.py": sha256(Path(__file__))}, "artifact_sha256": {}}
    candidates = [*sorted(RESEARCH.glob("feedback_v4*")), RESEARCH / "progress_feedback_v4_zh.md",
                  *sorted((RESEARCH / "results").glob("feedback_v4*"))]
    for path in candidates:
        for file in ([path] if path.is_file() else sorted(path.rglob("*"))):
            if file.is_file() and file.name != "feedback_v4_integrity.json":
                integrity["artifact_sha256"][str(file.relative_to(ROOT))] = sha256(file)
    (RESEARCH / "results/feedback_v4_integrity.json").write_text(json.dumps(integrity, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": "complete", "report": "research/progress_feedback_v4_zh.md", "artifacts_hashed": len(integrity["artifact_sha256"])}))


if __name__ == "__main__":
    write_documents()
