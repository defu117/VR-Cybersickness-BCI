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
risk_raw = 0.45 * head_linear_motion
          + 0.35 * head_angular_motion
          + 0.20 * frame_time_degradation
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

## 接入 MainScene 的步骤

1. 使用 Unity **2022.3.17f1c1** 打开项目。
2. 在 `Assets/Scenes/MainScene.unity` 创建空物体 `CybersicknessSystems`。
3. 添加 `CybersicknessLogger`、`CybersicknessComfortController` 和 `CybersicknessExperimentMarker`。
4. 将 XR Origin 的相机拖到 Logger 和 Controller 的 Head Transform；若为空，脚本会尝试使用 `Camera.main`。
5. 先只运行一次实验，确认 CSV 能生成，再把 marker 方法绑定到实验 UI。
6. 如果场景确实使用连续移动，再将 XR Origin 上的连续移动 Provider 替换为 `CybersicknessMoveProvider`，并在 Controller 中拖入该组件。
7. 如果当前场景只使用 Teleport，不要强行替换；先做数据记录和离线分析。

## 当前边界

- 目前没有接入具体 BCI 厂商 SDK、EEG、LSL 或 BrainFlow；这是为了避免在设备型号未确认前引入错误依赖。
- 当前风险模型是可解释的 HMD-only 基线，不能直接宣称为晕动症医学判断。
- 代码没有自动修改 `MainScene`，因此不会破坏现有 VisionMol 场景；需要在 Unity Inspector 中显式挂载和连线。
- 正式被试实验前应加入伦理/指导教师批准、坐姿、可随时退出和人工观察等安全流程。

## 下一步

1. 在 Unity 中验证 `MainScene` 能打开并生成第一份 CSV；
2. 根据实际场景确认使用 Teleport 还是 Continuous Move；
3. 加入固定实验条件（无干预 / 固定舒适 / 自适应舒适）；
4. 再根据 BCI 设备型号决定使用厂商 SDK、BrainFlow 或 LSL；
5. 最后把 EEG 风险值通过 `SetExternalRisk` 接入，而不是一开始重写 VisionMol 的交互逻辑。
