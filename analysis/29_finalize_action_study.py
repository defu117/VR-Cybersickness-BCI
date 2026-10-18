"""Build the Chinese delivery report and archive auditable software evidence."""
from pathlib import Path
import gzip
import hashlib
import json
import shutil
import os
import platform
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).resolve().parent/'.tmp/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import scipy
import sklearn

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    root=Path(__file__).resolve().parents[1]
    research=root/'research';results=research/'results';evidence=results/'action_validation'
    for source,target,kind in [('action_parity','synthetic','synthetic'),('public_action_replays','public','public_derived')]:
        directory=root/'analysis/runs'/source;output=evidence/target;output.mkdir(parents=True,exist_ok=True)
        for path in sorted(directory.iterdir()):
            if path.name=='jobs.txt':continue
            if path.name.endswith('_frames.csv'):
                (output/(path.name+'.gz')).write_bytes(gzip.compress(path.read_bytes(),mtime=0))
            elif path.suffix in ('.csv','.json'):
                shutil.copyfile(path,output/path.name)
        (output/'scope.json').write_text(json.dumps({'data_kind':kind,'source':source,
            'frames':'losslessly compressed CSV; decompression recovers the original source bytes',
            'scope':'software-only evidence; no new participant experiment'},indent=2),encoding='utf-8')
    shutil.copyfile(root/'analysis/runs/action_validation/validation.json',evidence/'unity_validation.json')
    shutil.copyfile(root/'analysis/runs/final_action_unity.log',evidence/'unity_batch.log')
    summaries={s:pd.read_csv(results/f'action_v3_{s}/summary.csv').set_index('policy') for s in ['original','secondary']}
    metrics={s:pd.read_csv(results/f'action_v3_{s}/subject_metrics.csv') for s in summaries}
    fig,axes=plt.subplots(1,2,figsize=(9,3.6),sharey=True)
    for axis,(source,title) in zip(axes,[('original','Original EEG / head motion'),('secondary','Independent motion / FMS')]):
        for name,label,color in [('recall','Alarm-recall calibration','#2864a4'),('usable','Action-lead calibration','#c86628')]:
            values=[summaries[source].loc[name+'_b'+str(x).replace('.','p'),'usable_recall']*100 for x in [.1,.5,1.]]
            axis.plot([.1,.5,1.],values,'o-',color=color,label=label)
        axis.set_title(title);axis.set_xlabel('Calibration false-alarm budget (/min)')
        axis.set_xticks([.1,.5,1.]);axis.grid(axis='y',alpha=.2);axis.set_ylim(bottom=0)
    axes[0].set_ylabel('Usable event recall (%)');axes[1].legend(fontsize=8)
    fig.tight_layout();fig.savefig(evidence/'usable_recall_by_budget.png',dpi=200);plt.close(fig)
    lines=['# 三项研究工作：完成情况与实际结论','',
        '更新日期：2026-10-15。第二数据源审计与独立评估、Unity 动作时序记录、延迟感知校准对照均已完成。没有新增受试者实验。','',
        '## 1. 第二数据源','',
        '固定 Ryu/Kim 作者仓库提交 b8285924017f0f128cec98407914ced1073983e8，保存许可、下载与文件 SHA256。无表头 CSV 第一行保留，主分析使用前 420 行。', '',
        '428 份源 CSV 中，38 个 PA 编号存在性别/年龄/MSSQ 冲突，相关 349 段整组排除。纳入 79 段、48 个属性一致的 PA 编号，产生 4,573 个窗口、1,373 个恶化正窗口和 474 个标签定义的事件组。PA 编号不是本项目招募的人，无法独立确认真实身份或跨编号别名。','',
        '输入是过去 9 秒的运动统计，目标是未来 6 秒原生 FMS 增加至少 1 分；当前评分和人口属性不进入被动模型。第一源沿用 13 人有效记录、1,397 窗口和 0–1 评分增加 0.1 的任务。两者分别训练评估，不能直接比较不同刻度的 MAE，也不能将本任务称为源论文的精确复现。','',
        '## 2. Unity 与软件验收','',
        '已增加报警编号、原始/回放时间映射、报警接收、动作开始、达到倍率 0.80、恢复开始/完成事件，以及逐帧目标/输出倍率。修复重复高风险重置干预开始时间、EOF 截断末次报警和心跳浮点边界问题。有效监测区间精确积分；缺测间隙和恢复收尾分别处理。','',
        '四种明确标记为合成的回放与三条真实公开数据留出轨迹均已导出并核对。合成轨迹仅用于软件检查。19 项 Python 检查通过；Unity 原九项合同检查与新增时序、截断、循环重置和移动组件倍率接口检查通过。','',
        '原始事件 CSV、逐帧 CSV.gz、输入与来源、积分重算、一致性结果和完整 Unity 日志位于 results/action_validation。实际倍率最大一致性误差约 2.4×10⁻⁷；缺测区间不被计入有效监测时间。','',
        '确定性仿真固定 60 Hz、1 倍速，并显式使用无头动桌面回退分支。倍率是控制器输出命令；已验证向移动组件传递，但不能当作测量到的行走速度。Stopwatch 计算计时与模拟时钟分别记录，均不代表头显显示链路时延。','',
        '## 3. v3 方法对照','',
        '协议和代码在模型比较前冻结，见 action_v3_protocol.md 与 results/action_v3_protocol_lock.json。两个源完成 183 个留一标识/种子折，包含 1,098 个策略/标识/种子组合；拟合、校准和测试按标识隔离。阈值只由校准组选择。','',
        '主设置：校准误警预算 0.5 次/分钟，动作占用预算 20%，倍率达到 0.80 后距评分事件至少 2 秒才算可用命中。以下先平均每个标识的种子，再做标识宏平均。无事件标识不进入召回平均。','',
        '| 数据源 | 校准目标 | 可用动作召回 | 报警事件召回 | 误警/分钟 | 动作占用 |','|---|---|---:|---:|---:|---:|']
    for source,title in [('original','原公开 EEG/头动'),('secondary','第二公开运动/FMS')]:
        for mode,label in [('recall','报警召回'),('usable','可用动作召回')]:
            row=summaries[source].loc[mode+'_b0p5']
            lines.append(f'| {title} | {label} | {100*row.usable_recall:.2f}% | {100*row.event_recall:.2f}% | {row.false_alarms_per_min:.4f} | {100*row.occupied_fraction:.2f}% |')
    lines += ['',
        '第二源的可用动作召回增加约 0.43 个百分点，按标识配对 bootstrap 的描述性 95% 区间为 [-0.03, 1.22] 个百分点，仍跨零。平均误警减少约 0.0404 次/分钟、占用减少约 1.15 个百分点；这些负担变化不能替代主目标的提升证据。原源主预算下可用动作召回没有增加，1.0 次/分钟预算下反而下降。未支持跨来源、跨预算的一致改进。','',
        '![不同校准预算下的可用召回](results/action_validation/usable_recall_by_budget.png)','',
        '图中两个子图是不同数据源与标签定义，只用于各自内部比较。','',
        '### 新标识上的预算超限','']
    for source,title in [('original','原源'),('secondary','第二源')]:
        for policy,label in [('recall_b0p5','报警召回校准'),('usable_b0p5','延迟感知校准')]:
            part=metrics[source][metrics[source].policy==policy]
            lines.append(f'- {title}，{label}：误警超限 {int(part.false_budget_exceeded.sum())}/{len(part)} 折，占用超限 {int(part.occupancy_budget_exceeded.sum())}/{len(part)} 折。')
    lines += ['', '校准约束为经验宏平均约束，不保证每个新用户满足预算。原源有极短记录，逐人误警率不稳定；种子折并不是新增参与者。','',
        '### 回归对照','', '| 数据源与原生刻度 | 时间 HGB MAE | 传感器 Ridge MAE | 传感器 HGB MAE | 需在线评分的持平参考 MAE |', '|---|---:|---:|---:|---:|']
    for source,title in [('original','原源，0–1'),('secondary','第二源，0–20')]:
        reg=pd.read_csv(results/f'action_v3_{source}/regression_summary.csv').set_index('model')
        sensor='fusion' if source=='original' else 'motion'
        lines.append(f'| {title} | {reg.loc["time_hgb","mae"]:.4f} | {reg.loc[sensor+"_ridge","mae"]:.4f} | {reg.loc[sensor+"_hgb","mae"]:.4f} | {reg.loc["oracle_rating_persistence","mae"]:.4f} |')
    lines += ['', '两个源中，传感器 HGB 的观察到的平均误差均没有改善仅时间对照。持平参考需要实时自报，输入条件不同；它不属于被动传感器方法的公平替代。','',
        '## 判断与边界','',
        '三项实施工作已形成可复现产物；当前结果仍未证明稳定可用的提前预警或实际症状减缓。原有论文保持预研究定位，未把本轮结果改写成已完成的受试者减缓实验。','',
        '评分保存频率不等于真实报告频率，评分事件不是生理发作。公开症状是在原暴露条件下采集的，不能随本轮模拟动作改变后继续作为新策略的效果标签。真实减缓效果需要设备、参与者与相应审批支持。','',
        '复现入口见 README.md；逐折划分、选阈记录、逐人结果、配对区间和完整性清单见 results/action_v3_original 与 results/action_v3_secondary。']
    (research/'progress_v3_zh.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    preserved=json.loads((results/'implementation_start.json').read_text())
    checks={name:digest(root/name)==value for name,value in preserved.items()}
    if not all(checks.values()):raise ValueError('Pre-existing files or manuscripts changed')
    lock=json.loads((results/'action_v3_protocol_lock.json').read_text())
    frozen={name:digest(root/name)==value for name,value in lock['source_sha256'].items()}
    if not all(frozen.values()):raise ValueError('Frozen model/controller sources changed')
    python_result=ET.parse(results/'python_validation_v3.xml').getroot()
    suites=[python_result] if python_result.tag=='testsuite' else list(python_result)
    if sum(int(s.attrib.get('failures',0))+int(s.attrib.get('errors',0)) for s in suites):raise ValueError('Python checks failed')
    unity=json.loads((evidence/'unity_validation.json').read_text())
    if unity['status']!='passed':raise ValueError('Unity checks failed')
    parity=[json.loads(p.read_text()) for p in evidence.glob('*_analysis.json')]
    if len(parity)!=7 or not all(x.get('parity_passed') for x in parity):raise ValueError('Seven replay parity checks required')
    artifacts={}
    for folder in ['secondary_audit','action_v3_original','action_v3_secondary','action_validation']:
        for p in (results/folder).rglob('*'):
            if p.is_file():artifacts[p.relative_to(root).as_posix()]=digest(p)
    for name in ['python_validation_v3.xml','python_validation_v3.log','action_v3_protocol_lock.json','implementation_start.json']:
        path=results/name
        if path.exists():artifacts[path.relative_to(root).as_posix()]=digest(path)
    scripts=[*root.glob('analysis/2[1-9]_*.py'),root/'analysis/configs/action_v3.json',
             *root.glob('Assets/Cybersickness/Editor/Cybersickness*Validation.cs')]
    manifest={'status':'complete','scope':'public-data secondary analysis and desktop software; no new human study',
        'versions':{'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,
                    'scipy':scipy.__version__,'sklearn':sklearn.__version__,'matplotlib':matplotlib.__version__,'unity':'2022.3.17f1'},
        'model_folds':183,'policy_subject_seed_combinations':1098,'source_commit':'b8285924017f0f128cec98407914ced1073983e8',
        'python_tests':sum(int(s.attrib['tests']) for s in suites),'unity_checks':unity['checks'],'replay_parity_cases':7,
        'preserved_files':checks,'frozen_source_checks':frozen,'additional_sources':{p.relative_to(root).as_posix():digest(p) for p in scripts},
        'report_sha256':digest(research/'progress_v3_zh.md'),'artifact_sha256':artifacts}
    (results/'reproducibility_v3.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ['artifact_sha256','additional_sources','preserved_files','frozen_source_checks']},indent=2))

if __name__=='__main__':main()
