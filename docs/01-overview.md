# 01 项目一页纸

## 一句话

把实验室面部仿真研究里负责"物理计算"的那一层，从 **Maya + Ziva** 换成 **Blender + FEBio**，让研究在 Ziva 停售之后还能继续，并且整套计算变得开源、可检查、可复现。

## 背景

实验室的研究（论文 *Beneath the Skin*）做的是一个**控制器**：给定一个目标表情（比如发 "AA" 音），它算出脸上几百个控制点（landmark）该怎么动，让肌肉自然地变成那个表情。控制器是实验室自己的成果。

控制器之下，还需要一个**物理引擎**来算软组织在重力、骨头带动下怎么变形。这一层现在用的是 Ziva，一个装在 Maya 里的商业插件。landmark 本身不进物理，控制器输出里进物理的只有下颌的转动（[03](03-asset.md) 第 4 节）。问题是：

- Ziva 已经在 2024 年 4 月停售（Unity 公告 *An update about Ziva*），许可到期后就不能再用；
- Ziva 是闭源的，内部怎么算的看不到，不方便写进论文的方法部分。

FEBio 是一个专门为生物力学开发、经过同行评审的开源有限元软件，可以接替这一层。Blender 是免费开源的 3D 软件，可以接替 Maya，用来操作和显示。

## 这个项目要交付什么

**第一阶段（v0.1 原型）**：用实验室提供的资产（颅骨、下颌、牙齿、嘴唇肌肉），在 Blender 里算出"下颌张合带动嘴唇"的物理过程，由 FEBio 计算。结果要通过合理性检查，并且实验室研究员把它和以前 Ziva 的结果并排看过以后，认为可以用于继续研究。

**原型机**：实验室负责人期待 1–2 周出。定义和路径见 [09](09-roadmap-and-tasks.md) 第 1 节，项目负责人已确认（2026-11-11，11 的 P-05），目标日期 2026-11-17。

**我们不是要复刻 Ziva**（ADR-17）。实验室的成果是控制器，物理层只要让控制器能继续工作、结果合理就够了。实验室会议也说：解出和 Ziva 一样的数值不是成功标准，实验看的是动作本身，所以模型按真人大小算（ADR-31）。和 Ziva 的差别会算出来，但只作参考，不当合格线。

**Hill 肌肉力**：实验室负责人希望顶层设计把它考虑进去。按实验室代码，Hill 力是控制器目标函数里的一项，物理层里没有主动收缩；所以第一阶段物理层先输出每块组织的应变能，只作诊断（它替换不了目标函数里的近似，ADR-33），纤维方向和激活留到第二阶段。

更具体的要求见 [02 需求](02-requirements.md)。

## 不在第一阶段做的事

- 移植实验室的控制器（优化算法、表情过渡）；第一阶段只接收控制器已经算好的结果。
- 钢琴式表情界面、完整的面部（几十块肌肉）、皮肤层。
- 逐项、逐点复刻 Ziva 的行为。两者的算法不同，Ziva 的参数很可能也只是默认值，对齐它的意义不大。
- 任何医学结论。

## 现在做到哪了（2026-11-10）

| 已完成 | 证据 |
|---|---|
| 代码仓库、开发环境、自动检查 | 本机 `E:\Codebase\asrp`；GitHub 私有仓库 `JoKFA/FEBio_Blender_Init`（ADR-14） |
| 确认 FEBio 能在本机算动力学（重力 + 骨头带动软组织） | `spikes/s1_dynamic_jaw.py`，每次自动检查都会重跑 |
| FEBio 的结果能逐帧放回 Blender 播放 | `tools/check_playback.py`，误差小于 0.000001 mm |
| 实验室资产的完整盘点 | [03 资产说明](03-asset.md)，`tools/mb_inventory.py`、`tools/asset_report.py` |
| 真实网格、landmark 权重和关节已经导出。网格和 `.mb` 逐点核对过；权重和关节目前只有 Maya 自检 | [03](03-asset.md) 第 12 节，`tools/maya_export.py`、`tools/check_lab_export.py` |
| 真实资产已经进了 Blender，下颌能绕真实铰链转动 | `tools/blender_import_preview.py`，结果在 `data/preview/` |
| Ziva 机器要跑的脚本已经准备好，并在普通 Maya 上排练过（需要 Ziva 的部分只能到现场验证） | [12](12-lab-export-checklist.md) 第二部分，`tools/ziva_machine_export.py`、`tools/rehearse_ziva_export.py` |
| 任何电脑都能运行的自动检查 | `uv run python tools/verify.py` |
| 对照实验室论文做了一次需求审计：论文里每种用法对物理层意味着什么，第一阶段覆盖多少；并定了 7 个新决定 | [02](02-requirements.md) 第 4 节的对照表、[10](10-decisions.md) ADR-21 到 ADR-27、[13](13-explanations.md) E-04 |
| 场景描述和运动的格式定稿，`asrp check` 能查出场景和运动里的错误（T-05） | `uv run asrp check tests/fixtures/s1/scene.json tests/fixtures/s1/trajectory.json`，[09](09-roadmap-and-tasks.md) T-05 |
| 实验室资产能一条命令导入成场景描述，并通过 `asrp check`（T-02，里程碑 M1 完成；留下一处缺口：landmark 蒙皮矩阵还没换算成毫米和 Z 轴朝上，见 [09](09-roadmap-and-tasks.md) T-09） | `uv run asrp import-asset data/lab_export <输出文件夹>`，[09](09-roadmap-and-tasks.md) T-02 |
| 读完实验室控制器源码：landmark 和物理的关系、优化时物理不在环（部分验证，11 的 Q20）、Hill 模型的位置、各实验怎么做、运动文件的格式；目标姿态已经拿到 | [03](03-asset.md) 第 13 节，[10](10-decisions.md) ADR-28 到 ADR-35，[13](13-explanations.md) E-05 |
| 更正了粘连权重的读法（按强推断，默认值 1.0 待 A-33 确认）：上唇 74 个顶点连颅骨、下唇 76 个连下颌，嘴角经口角组织连骨头；第一阶段的粘连方案定了 | `uv run python tools/asset_report.py data/asset_inventory.json`，[03](03-asset.md) 第 6 节，ADR-32 |
| 被哈希的数据在任何电脑上检出都逐字节相同（`.gitattributes`） | 打开 `core.autocrlf` 克隆后跑测试，[08](08-engineering-standards.md) 第 10 节 |

下一步是原型机：T-03、T-07（第 1、2 步）、T-08 的外壳 → T-06a，见 [09 路线图与任务](09-roadmap-and-tasks.md) 第 1 节。

## 谁参与、各自负责什么

| 角色 | 负责 |
|---|---|
| 项目负责人 | 定优先级、拍板决策、和实验室沟通、最终验收 |
| 实验室 | 提供资产、配合 Ziva 机器上的导出、回答待决问题、评审结果（[07](07-validation.md) 第 4.4 节） |
| 开发者（人或 AI 开发会话） | 按任务卡开发，交付代码、测试和证据 |
| 审查者 | 按开发规范和任务卡检查每一个合并请求 |

## 最需要尽快解决的三件事

1. **约 Ziva 机器，趁许可还有效拿到只有它能给的数据**（ADR-35）：Ziva 的完整设置和权重表、一条运动的参考结果、Ziva 存的各物体网格（尤其嘴角链条上的）。许可哪天到期（Q5）要先问清楚，现有的两条线索都没有核实。步骤见 [12 导出清单](12-lab-export-checklist.md) 第二部分；第二阶段要的多网格、多运动，脚本也已支持（T-19），可以同一次做。
2. **把 5 个问题发给实验室，并要运动文件**：可以直接转发的一页在 [12](12-lab-export-checklist.md) 第三部分；运动文件 `combined_checkpoints.pkl` 不在源码仓库里（D2）。
3. **原型机**：定义已确认（11 的 P-05），目标日期 2026-11-17；按 09 第 1 节的路径做 T-03、T-07、T-08 → T-06a。这几张卡都不等实验室。

第二阶段投入之前还有一道关：T-17、T-18 复核 FEBio 撑不撑得起第二阶段（ADR-26）；它们随时可以做，不挡 M3。
