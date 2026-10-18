# VR 晕动症基础模块

## 新增：动作时序回放与记录

`CybersicknessRiskReplay` 兼容四列旧 CSV，并支持 `prediction_id`、`alarm_id`、
`source_timestamp_s` 和 `monitor_until_s`。同一报警的心跳沿用编号，只记录一次
`alarm_received`。原始分析时间与本地回放时间分开保存，不按心跳伪造新预测。
时间倒退或重复时间戳的回放会被拒绝，不排序拼接成另一条轨迹。

默认启用 Research Profile：一次决策确认，风险平滑 1 秒、决策间隔 0.1 秒、
最短干预 10 秒、恢复等待 3 秒、倍率渐变 2 秒。重复的同一目标不会重新开始干预。
研究 CSV 使用 10 秒报警保持及 12 秒报警冷却，均为工程设置。

回放自动添加 `CybersicknessActionRecorder`，产生三份文件：

- `_events.csv`：报警接收、目标变化、动作开始、达到 0.80 倍率、恢复开始和完成；
- `_frames.csv`：逐帧目标与输出倍率、原始/回放时间、报警编号、有效监测区间积分及恢复阶段；
- `_summary.json`：低于 0.99 倍率的占用、`∫(1-倍率)dt` 强度及恢复收尾，手动停止/超时的截断标记。

`Output Directory` 为空时使用既有 `Application.persistentDataPath/CybersicknessLogs/`。
EOF 不会立即清除最后一次报警：先完成保持，再恢复，最长收尾 30 秒。循环回放先
收尾再重置，紧急停止状态需显式恢复。旧 CSV 没有预测区间元数据时，按每条样本
后三秒推定监测区间；正式研究使用带元数据的导出 CSV。

倍率为控制器输出命令；连接 `CybersicknessMoveProvider` 后才传递给移动组件。
它不等同于测量到的移动速度。主日志仍独立记录 Rig 速度。未连接组件也可检查
动作状态，但不能声称测到了实际行走或症状变化。

`CybersicknessActionValidation.RunReplayList` 可在批处理中导出确定性桌面轨迹，
此模式显式使用无头动回退分支。实时 Play 模式继续使用实际 HMD 回退分支。
逐帧模拟时间与 Stopwatch 计算开销分别记录；正式时序比较仅使用 1 倍速。
这些检查不测量头显显示链路时延，也不提供症状减缓证据。

本目录是 `VR-Cybersickness-BCI` 项目的第一阶段代码。它在不改变 VisionMol 分子功能的前提下，增加一个可逐步接入 MainScene 的晕动症实验基础层。

## 当前实现

### 1. `CybersicknessLogger`

按固定采样间隔写入 CSV，默认保存到：

```text
Application.persistentDataPath/CybersicknessLogs/
```

记录内容包括：

- UTC 时间、Unity 时间、帧号和场景名；
- 头显位置与四元数姿态；
- 头部线速度、角速度和 Rig 线速度；
- 帧时间、估算 FPS；
- 风险原始值、平滑值、风险等级和当前干预；
- 主观 0–10 评分；
- 实验条件、刺激和人工停止等 marker。

### 2. `CybersicknessComfortController`

这是一个可解释的工程基线，不是临床诊断模型。它将三个特征归一化后加权：

```text
risk_raw = 0.25 * head_linear_motion
          + 0.20 * head_angular_motion
          + 0.15 * head_angular_acceleration
          + 0.15 * visual_physical_mismatch
          + 0.15 * frame_degradation_and_jitter
          + 0.10 * exposure_duration
```

风险值经过指数平滑后分为 Low、Moderate、High、Critical 四级。默认策略只调整连续移动速度，不自动关闭整个 XR 系统：

| 风险等级 | 默认速度倍率 |
| --- | ---: |
| Low | 1.00 |
| Moderate | 0.75 |
| High | 0.50 |
| Critical | 0.25 |

`EmergencyStop()` 和 `ResumeAfterEmergencyStop()` 可绑定到安全按钮。控制器还提供 `SetExternalRisk(float)`，后续 EEG/BCI 模块可以直接输入 0–1 风险值；如果外部数据超过 2 秒没有更新，会自动回退到头显运动基线。

### 3. `CybersicknessMoveProvider`

这是 `XR Interaction Toolkit 2.5.4` 的 `DynamicMoveProvider` 的薄封装，增加 `ComfortMultiplier` 属性。没有把它挂到 XR Origin 时，日志和风险估计仍可独立运行；只有需要自适应连续移动时才替换原来的连续移动 Provider。

### 4. `CybersicknessExperimentMarker`

为 Unity UI 按钮提供无厂商依赖的入口：

- `StartSession()` / `EndSession()`；
- `MarkCondition()` / `MarkStimulus()`；
- `SetRating0()`–`SetRating10()`；
- `EmergencyStop()` / `ResumeAfterEmergencyStop()`。

### 5. 实验控制器和风险回放

`CybersicknessExperimentController` 提供一个可重复的轻量移动刺激：编辑器中
使用 `W/S` 前进或后退、`A/D` 转向，`Space` 开始/停止刺激，`E` 开始/结束
会话，`Esc` 紧急停止，数字 `1/2/3` 切换 A/B/C 条件：

- `1`：No Adaptation；
- `2`：Fixed Comfort；
- `3`：Adaptive Comfort。

Quest 控制器的连续移动仍由 XR Interaction Toolkit 的 Move Provider 负责；
实验控制器只负责条件、marker 和编辑器键盘冒烟测试。

`CybersicknessStimulusGeometry` 会在运行时生成一条简单走廊、地面和重复标记，
方便比较同一运动轨迹下的 A/B/C 条件。它只用于实验场景，不会改写原始模型场景。

`CybersicknessRiskReplay` 接收以下格式的 CSV，并通过同一个
`SetExternalRisk(risk, quality, source)` 接口注入风险：

```csv
timestamp_s,risk,quality,source
0.0,0.20,1.0,replay
1.0,0.75,0.95,replay
```

项目内的 `Assets/Cybersickness/Replay/risk_replay_demo.csv` 可用于首次回放。
把它拖到 Risk Replay 的 Replay Asset，勾选 Auto Play，运行时即可观察风险、
速度倍率和超时回退。

## 接入场景的步骤

### 一键设置（第一次冒烟测试推荐）

在 Unity 中打开一个包含 Camera 的场景，然后选择：

`VR BCI > Create Minimal Cybersickness Loop in Active Scene`

编辑器工具会创建 `CybersicknessSystems`，添加 Logger、Comfort Controller 和
Experiment Marker，并在找到 `Camera.main` 时自动绑定。对话框确认后保存场景。
这个工具只在编辑器中运行，不会进入最终播放器构建。

### 手动设置

1. 使用 Unity **2022.3.17f1c1** 打开项目。
2. 在当前场景创建空物体 `CybersicknessSystems`。
3. 添加 `CybersicknessLogger`、`CybersicknessComfortController` 和 `CybersicknessExperimentMarker`。
4. 将 XR Origin 的相机拖到 Logger 和 Controller 的 Head Transform；若为空，脚本会尝试使用 `Camera.main`。
5. 先只运行一次实验，确认 CSV 能生成，再把 marker 方法绑定到实验 UI。
6. 如果场景确实使用连续移动，再将 XR Origin 上的连续移动 Provider 替换为 `CybersicknessMoveProvider`，并在 Controller 中拖入该组件。
7. 如果当前场景只使用 Teleport，不要强行替换；先做数据记录和离线分析。

## 当前边界

- Unity 目前没有接入实时 EEG 厂商 SDK、LSL 或 BrainFlow；离线研究已读取公开 EEG/头动/自报数据并完成主实验，见 `research/status.md`。合成数据仅用于软件检查。
- Unity 默认本地规则分数是可解释的 HMD-only 工程基线；外部论文回放是预警动作信号，两者都不能直接称为医学判断或经过验证的症状概率。
- 代码没有自动修改 `MainScene`，因此不会破坏现有 VisionMol 场景；需要在 Unity Inspector 中显式挂载和连线。
- 正式被试实验前应加入伦理/指导教师批准、坐姿、可随时退出和人工观察等安全流程。

## Python 离线管线

`analysis/README.md` 描述从原始 EEG CSV 到风险回放的完整流程。最小测试：

以下为原有 `00`-`07` 教学管线。论文实验须使用 `research/README.md` 的
`08` 之后入口，以及至少五个满足质量要求的被试进行拟合/校准/测试隔离。

```powershell
cd analysis
python 00_generate_synthetic.py --output data/synthetic_eeg.csv
python 02_preprocess_eeg.py data/synthetic_eeg.csv --output data/preprocessed_eeg.npz
python 03_extract_features.py data/preprocessed_eeg.npz --output data/eeg_features.csv
```

模型训练前需要安装 `analysis/requirements.txt`，并准备至少两个 subject/session
组，以便进行按被试隔离的验证。

## 下一步

### 论文预测流

论文用的未来 6 秒预测在 `analysis/08_prepare_forecast.py` 之后，详见
`research/README.md`。`11_export_forecast_replay.py` 必须选择单个
subject/session/model/seed，导出 0.1 秒心跳，避免 3 秒预测步长触发
控制器现有的 2 秒超时。其 risk=0.7/0.0 是已应用预警规则后的触发信号，
不代表医学严重度或概率。信号间断不填充，质量门控和失联回退继续有效。

控制器现在按每帧经过的时间平滑外部风险，而不是用单帧时长乘以消息次数；
因此平滑时间不随心跳频率改变。真实头显上的端到端执行延迟仍需测量。

`CybersicknessForecastValidation.RunBatchChecks` 已在 Unity 2022.3.17f1
中通过九项编辑器检查，结果为 `research/results/unity_validation.json`。
公开数据主方案当前未产生可用的门控预警，因此还不能据此开展疗效试验。

连续评分 UI 可绑定 `ExperimentMarker.SetContinuousRating(float)`，范围为 0–1。
日志新增归一化评分、来源、更新时间和评分年龄；原 `rating` 列仍保留离散
0–10 语义。两种来源不可直接当作同一量表。`MarkCondition` 现在同时更新
`condition` 列和标记；新会话清空上一段评分，防止陈旧标签继承。

1. 阅读 `research/status.md` 和真实实验结果，评估预警可行性；
2. 用 `risk_replay_demo.csv` 检查目标设备上的显示、速度变化、超时回退与 marker；
3. 确认 EEG 设备型号、SDK、时间同步和执行延迟，再实现实时适配；
4. 仅在预测门槛、设备条件和审批满足后，按 `research/pilot_protocol.md` 开展探索性试点。
