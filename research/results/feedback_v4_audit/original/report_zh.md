# original 数据及反馈审计

日期：2026-10-19。

审计 69 段源记录；保留 43 段、13 个作者编号、每条件 1397 个窗口，共 9 条件。

原生尺度：0–1 连续评分。完整的原始评分目标、越阈时刻和历史运动特征均已重算核对。
原候选窗口未因本轮审计改变；参与者真实身份与跨编号别名仍无法独立确认。

入选记录中有 0 段包含局部缺失数值样本；只使用历史完整且已重算的窗口，不填补缺失运动。
模拟请求缺失合计 483 次（9 条件重复计数，不是真实自报次数）。
评分保存间隔、可观察值变化间隔和持平段均记录在 recordings.csv；值变化不能恢复真实按钮报告事件。

## 纳排和身份

同一作者编号全部记录整组划分；属性冲突/无法确认则整组排除。未通过属性相同、时钟重置或行数猜测身份。
规范化序列未发现跨编号精确重复；这一阴性检查不能排除非精确重复、重新编号或同一人的不同记录。

## 缺失、时钟和反馈到达

评分仅取请求时刻之前、最大允许间隔内的最近原始值；不插值、不读取未来报告。
预测只使用到达时刻不晚于预测时刻的报告，保留采样、请求、到达和年龄三类时间信息。
缺失请求不会刷新旧报告；旧值可以长期保持，其年龄和缺失次数单列。9 条件使用同一窗口交集。
第一源以毫秒接收时钟转秒、按既有规则处理启动缓存和重复时间；非启动重置排除。第二源保留前 420 数据行与原生秒。

## 排除原因

- outside_frozen_v3_candidate_cohort：14 段。
- invalid_native_rating_or_missing_rating：2 段。
- 0004_BL_SubjectiveCs.csv: empty/invalid clock：1 段。
- 0004_FN_SubjectiveCs.csv: empty/invalid clock：1 段。
- 0004_FR_SubjectiveCs.csv: empty/invalid clock：1 段。
- 0004_SN_SubjectiveCs.csv: empty/invalid clock：1 段。
- 0004_SR_SubjectiveCs.csv: empty/invalid clock：1 段。
- 0005_BL_SubjectiveCs.csv: empty/invalid clock：1 段。
- 0007_SN_SubjectiveCs.csv: empty/invalid clock：1 段。
- 1100_HH_SubjectiveCs.csv: empty/invalid clock：1 段。
- 1101_HN_SubjectiveCs.csv: non-startup clock reset; split into recordings before analysis：1 段。
- 1102_BL_SubjectiveCs.csv: empty/invalid clock：1 段。

## 导出评分的分辨率

43 段入选记录中有 38 段出现不在 0.1 网格上的连续导出值。
作者论文描述的报告档位与公开导出值并不完全对应；缺少按钮/控制器更新事件，无法判断各次连续数值变化的来源。
本分析保留原生导出值与预定 0.1 增量标签，不强行量化为离散档位，也不将数值变化频率视为主动报告频率。

逐记录清单：recordings.csv；排除记录：exclusions.csv；逐编号计数：identifier_counts.csv；
模拟请求与缺失统计：availability.csv；条件反馈年龄：condition_availability.csv；量表数值分辨率：rating_resolution.csv。

评分按公开导出值保留，不依据量表名称强制取整，也不把连续小变化解释为独立报告次数。
window_retention.csv 列出逐记录有效窗口与监测时长；第二源另报运动质量筛选前、仅按时间支持计算的候选网格比例，不能当作人群代表性。
feedback_staleness.csv 标记因缺失请求等原因超过一个名义周期的旧反馈。按冻结规则继续保留这些窗口，年龄作为输入，不依据结果追加排除。
模拟到达与实际用户反应不同，不能推断报告负担或症状减轻。
