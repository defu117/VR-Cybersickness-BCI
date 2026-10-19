# 晕动症提前预警论文工作区

## 低频、延迟症状反馈 v4（2026-10-19）

方案：[feedback_v4_protocol.md](feedback_v4_protocol.md)；文献与证据分层：
[feedback_v4_literature_zh.md](feedback_v4_literature_zh.md)。完整评估已完成，共 183 折、
4,941 个模型/条件/编号/种子组合。见 [v4 总报告](progress_feedback_v4_zh.md) 和
[论文补充稿](feedback_v4_paper_addendum_zh.md)。审计输出位于 `results/feedback_v4_audit/`。

主条件下未支持当前运动增强方案：第二源 MAE 从评分历史的 2.5062 升至 2.5610，
可用动作召回从 6.66% 降至 2.66%。两种 HGB 相对最近报告保持的 MAE 差值区间均跨零。
完整性入口为 `results/feedback_v4_completion.json` 和 `results/feedback_v4_integrity.json`。

从项目根目录执行，保留原始数据和既有特征准备流程；新输出不覆盖 v1–v3：

```powershell
analysis/.venv/Scripts/python.exe analysis/30_prepare_feedback_v4.py
analysis/.venv/Scripts/python.exe analysis/31_freeze_feedback_v4.py
analysis/.venv/Scripts/python.exe analysis/32_run_feedback_v4.py --dataset original --output analysis/runs/feedback_v4_original_complete
analysis/.venv/Scripts/python.exe analysis/32_run_feedback_v4.py --dataset secondary --seeds 7 --output analysis/runs/feedback_v4_secondary_complete
analysis/.venv/Scripts/python.exe analysis/32_run_feedback_v4.py --dataset secondary --seeds 19 --output analysis/runs/feedback_v4_secondary_s19
analysis/.venv/Scripts/python.exe analysis/32_run_feedback_v4.py --dataset secondary --seeds 42 --output analysis/runs/feedback_v4_secondary_s42
analysis/.venv/Scripts/python.exe analysis/33_report_feedback_v4.py
analysis/.venv/Scripts/python.exe analysis/34_write_feedback_documents.py
```

以上计算命令针对新目录。已存在的运行只接受相同冻结身份继续；首次失败和修复记录见
`results/feedback_v4_execution_notes.md`。本次第二源种子 7 由初始三种子运行目录取出，
另两个种子从明确指定目录归档，不依结果选择重复计算。

先完成数据准备再冻结，首次模型拟合前保存协议、代码和准备表 SHA256。旧锁存在但
来源变化时脚本拒绝覆盖，应保留旧锁与运行并显式建立新版本。当前和未来真实评分
只用于标签、训练响应与评价，主模型特征仅包含已到达反馈和过去运动；模拟抽稀不
能证明真实自报负担或症状减轻。`33` 严格要求完整编号/种子/条件网格后才标为完成。

## 周报与研究交付包

- [2026-10-12 至 2026-10-18 周报](weekly_report_2026-10-18_zh.md)
- [2026-10-18 研究快照、校验值与使用说明](../deliverables/README.md)

## 新增：第二数据源与动作时序评估 v3

三项推进均已完成，先读 [完成报告](progress_v3_zh.md)。183 个留一标识/种子折、
19 项 Python 检查和 7 条 Unity 回放一致性检查均有归档证据；当前未证明稳定的
可用召回提升或真实症状减缓。完整性清单为 `results/reproducibility_v3.json`。

本轮方案见 `action_v3_protocol.md`，数据来源比较见 `second_dataset_sources.md`。
第二源已固定提交并完成审计：428 份 CSV 中纳入 79 段、48 个属性一致的 PA 编号，
产生 4,573 个预测窗口；38 个编号存在身份属性冲突，相关 349 段整组排除。
PA 编号来自原作者，不能独立核实真实身份。详见 `results/secondary_audit/audit_zh.md`。

运行入口（从项目 `analysis/` 目录执行）：

```powershell
.\.venv\Scripts\python.exe 21_acquire_secondary.py
.\.venv\Scripts\python.exe 22_prepare_secondary.py
.\.venv\Scripts\python.exe 23_run_action_v3.py data/processed/secondary_h6.csv --dataset secondary --output runs/action_v3_secondary
.\.venv\Scripts\python.exe 23_run_action_v3.py data/processed/public_h6.csv --dataset original --output runs/action_v3_original
.\.venv\Scripts\python.exe 25_prepare_action_checks.py
```

也可按 `--seeds 7`、`--seeds 19`、`--seeds 42` 分目录计算。
`26_archive_action_v3.py` 按 `--parts 7=目录 19=目录 42=目录` 合并，严格检查输入、
代码/协议校验值、被试隔离、全部窗口和完整三种子网格，保存完整性清单。
已有目录仅允许相同运行身份继续；输入、参数或代码变化后须使用新目录。

Unity 批处理入口为 `CybersicknessActionValidation.RunReplayList`，参数
`-replayList` 指向 `25_prepare_action_checks.py` 生成的 `runs/action_parity/jobs.txt`。
每行是 `绝对CSV路径|绝对输出前缀`。该入口还会复跑旧九项与新增时序检查。
`24_analyze_action_trace.py 输出前缀 --output 报告目录 --predictions 单轨迹预测CSV`
重算占用和强度，并与离线控制器核对。`27_benchmark_action_model.py` 单独报告
固定模型的单窗口评分开销；它不参与模型或阈值选择。

原有主实验、原稿及中英文 PDF 保留。第二源采用原生 FMS，当前评分不进入被动模型，
与源论文任务及第一源量表不同。桌面执行轨迹不构成真实症状减缓证据。

本工作区执行 2026-10-15 确认的研究计划：公开 EEG/头动数据上的未来 6 秒评分恶化预测、按被试隔离的评估、置信度门控和 Unity 回放。目标 venue 为下一轮合适的 ACM VRST 完整论文。

首先阅读 `protocol.md`、`source_audit.md` 和 `manuscript.md`。当前完成状态、实际运行产物和未完成项见 `status.md`。原始参与者数据、虚拟环境和上游代码放在 Git 忽略目录，不能把下载数据或上游代码当成本项目新贡献。

审阅版英文 PDF 位于项目的 `output/pdf/cybersickness_forecasting_draft.pdf`，不是 ACM 投稿模板。可在项目根目录安装 `research/requirements-document.txt` 后运行 `python research/build_manuscript_pdf.py` 重新生成；`manuscript.md` 为内容源文件。训练版本锁见 `analysis/requirements-research.lock.txt`，其中 PyTorch CPU 构建需使用官方 `https://download.pytorch.org/whl/cpu` 索引安装。

## 运行入口

在 `analysis/` 目录内：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-research.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-neural.txt
.\fetch_public_data.ps1
.\.venv\Scripts\python.exe 08_prepare_forecast.py --raw data/raw/juliete --output data/processed/public_h6.csv --tensors data/processed/public_h6.tensors.npz
.\.venv\Scripts\python.exe 09_train_forecast.py data/processed/public_h6.csv --output runs/public_h6
.\.venv\Scripts\python.exe 16_train_neural_forecast.py data/processed/public_h6.csv data/processed/public_h6.tensors.npz --output runs/public_h6_neural
.\.venv\Scripts\python.exe 15_merge_forecast_runs.py --features data/processed/public_h6.csv --parts 7=runs/public_h6 19=runs/public_h6 42=runs/public_h6 7=runs/public_h6_neural 19=runs/public_h6_neural 42=runs/public_h6_neural --output runs/public_h6_all
.\.venv\Scripts\python.exe 10_report_forecast.py runs/public_h6_all
.\.venv\Scripts\python.exe 14_archive_forecast_run.py runs/public_h6_all --output ../research/results/main_h6
.\.venv\Scripts\python.exe 20_warning_burden.py runs/public_h6_all --output ../research/results/main_h6
.\.venv\Scripts\python.exe 11_export_forecast_replay.py runs/public_h6_all/predictions.csv --subject 0001 --session FN --seed 7 --output runs/public_h6_all/replay_0001_FN.csv
```

`--resume` 只允许输入校验值、协议、模型列表和随机种子完全相同的运行继续。3/9 秒敏感性分析在准备和训练两个命令都传相同 `--horizon`，并用独立输出路径。

实际完成的主实验分三个经典模型种子目录训练，合并记录保存在 `results/main_h6/run.json`，无需为查看结果重新计算。深度对照是按新因果输入/目标重建的架构比较，不能称为原论文指标的精确复现。

## 次要分析

以 3 秒任务为例，9 秒使用对应参数和独立目录：

```powershell
.\.venv\Scripts\python.exe 08_prepare_forecast.py --raw data/raw/juliete --output data/processed/public_h3.csv --horizon 3
.\.venv\Scripts\python.exe 09_train_forecast.py data/processed/public_h3.csv --horizon 3 --models oracle_rating_persistence fusion_hgb fusion_cqr --output runs/public_h3_sensitivity
.\.venv\Scripts\python.exe 15_merge_forecast_runs.py --features data/processed/public_h3.csv --parts 7=runs/public_h3_sensitivity 19=runs/public_h3_sensitivity 42=runs/public_h3_sensitivity --output runs/public_h3_complete
.\.venv\Scripts\python.exe 10_report_forecast.py runs/public_h3_complete
.\.venv\Scripts\python.exe 14_archive_forecast_run.py runs/public_h3_complete --output ../research/results/horizon_h3
.\.venv\Scripts\python.exe 17_policy_feasibility.py data/processed/public_h3.csv --horizon 3 --output ../research/results/policy_h3
```

`17_policy_feasibility.py` 故意读取未来真实标签来诊断确认延迟，不能把它作为模型效果。主实验之外另设探索性的直接事件预测，记录在 `configs/alert_budget_exploratory_v2.json`；此设置是在看到 v1 负结果后增加，不是预设主分析。

```powershell
.\.venv\Scripts\python.exe 18_train_alert_budget.py data/processed/public_h6.csv --output runs/alert_budget_v2
.\.venv\Scripts\python.exe 19_merge_alert_runs.py --features data/processed/public_h6.csv --parts 7=runs/alert_budget_v2 19=runs/alert_budget_v2 42=runs/alert_budget_v2 --output runs/alert_budget_v2_complete --archive ../research/results/exploratory_v2
```

误警预算仅约束校准集上的经验误警率。新被试可能超过预算，模型输出的分数也不是校准过的症状概率。

`20_warning_burden.py` 按回放中的 10 秒保持时间计算有效监测窗口内的警告占用率，独立保存计算来源。该量位于控制器平滑和速度执行之前，不能称为实际减速时长、任务损失或症状改善。

Windows 受限临时目录导致 ensurepip/pytest 写入失败时，将 `TEMP`、`TMP` 指向工作区内预先创建的 `analysis/.tmp`，再运行命令。

## 软件验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe 12_generate_forecast_fixture.py
.\.venv\Scripts\python.exe 08_prepare_forecast.py --raw data/synthetic_raw --sfreq 100 --data-kind synthetic --output data/processed/synthetic_h6.csv
.\.venv\Scripts\python.exe 09_train_forecast.py data/processed/synthetic_h6.csv --output runs/synthetic_h6 --seeds 7
```

合成数据只检查程序是否运行。每份预测与报告都有 `data_kind` 标记；禁止与公开数据混用或作为论文效果结果。

## 研究交付与剩余依赖

代码、协议、主实验、审计和英文实证稿已完成。原文的精确复现、跨数据集验证、下一轮 venue 格式和真实受试者试点仍需要各自证据支持。当前主方案未显示可用的预警效果，不能直接开展基于该模型的疗效试验；Unity 回放与软件检查只证明系统接口和实现行为。
