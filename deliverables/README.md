# 研究交付包（2026-10-18）

- [下载研究快照 ZIP](cybersickness_research_2026-10-18_3951cc6.zip)
- [SHA256 校验文件](cybersickness_research_2026-10-18_3951cc6.zip.sha256)
- [机器可读归档清单](manifest_2026-10-18.json)
- [本周周报](../research/weekly_report_2026-10-18_zh.md)
- [研究完成报告](../research/progress_v3_zh.md)

## 内容与来源

源提交：`3951cc6b088371770ed72f28036e8723c681d764`，分支：`cybersickness-baseline`。

压缩包包含 289 个文件：研究分析代码、Unity 晕动症模块、协议与数据审计、各轮对照结果、软件验证日志、中英文论文工作稿与 PDF，以及本周周报。体积约 3.06 MB。

ZIP SHA256：`d8d0bfa8f21e12fe43bf0f03dbd6b5af59fe6823007c84a2d2e1dbff3bff0576`。

已核对归档内 113 项既有 SHA256 记录，全部一致，并检查 ZIP 完整性。

## 使用方式

该包是研究文件集合，需要配合本仓库的完整 Unity 工程使用。解压后先阅读 `research/weekly_report_2026-10-18_zh.md`、`research/progress_v3_zh.md` 和 `research/README.md`。数据获取、训练与回放入口见后者；Python 依赖版本见 `analysis/requirements-research.lock.txt`。

完整工程可从本仓库的 `cybersickness-baseline` 分支获取。本地软件验收使用 Unity 2022.3.17f1；现有验收记录随包保存。本次打包仅执行归档完整性与校验值核对，没有重新运行模型训练或受试者实验。

原始记录、处理后的训练数据、完整运行目录、虚拟环境、上游下载代码和 Unity 缓存不在包内；数据需按获取脚本与来源许可自行准备。本地 Unity 环境配置修改未纳入本次研究提交。

## 研究状态

现有证据来自公开数据二次分析与桌面软件执行评估，没有新增受试者实验。v3 尚未显示稳定的可用动作召回提升，真实症状减缓效果仍需后续实验验证。论文是预研究工作稿，未完成投稿。
