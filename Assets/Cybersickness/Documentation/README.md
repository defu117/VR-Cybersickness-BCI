# VR 晕动症基础模块

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

- 目前没有接入具体 BCI 厂商 SDK、EEG、LSL 或 BrainFlow；`analysis/` 先使用合成数据和 CSV 回放，避免在设备型号未确认前引入错误依赖。
- 当前风险模型是可解释的 HMD-only 基线，不能直接宣称为晕动症医学判断。
- 代码没有自动修改 `MainScene`，因此不会破坏现有 VisionMol 场景；需要在 Unity Inspector 中显式挂载和连线。
- 正式被试实验前应加入伦理/指导教师批准、坐姿、可随时退出和人工观察等安全流程。

## Python 离线管线

`analysis/README.md` 描述从原始 EEG CSV 到风险回放的完整流程。最小测试：

```powershell
cd analysis
python 00_generate_synthetic.py --output data/synthetic_eeg.csv
python 02_preprocess_eeg.py data/synthetic_eeg.csv --output data/preprocessed_eeg.npz
python 03_extract_features.py data/preprocessed_eeg.npz --output data/eeg_features.csv
```

模型训练前需要安装 `analysis/requirements.txt`，并准备至少两个 subject/session
组，以便进行按被试隔离的验证。

## 下一步

1. 在实验场景中重复 A/B/C 条件并检查 marker；
2. 用 `risk_replay_demo.csv` 验证外部风险和 2 秒超时回退；
3. 记录 HMD CSV 后运行 `analysis/04_align_hmd_eeg.py`；
4. 准备至少两个 subject/session，再运行基线模型比较；
5. 设备型号确认后，再把 Risk Replay 替换为厂商 SDK、BrainFlow 或 LSL 适配器。
