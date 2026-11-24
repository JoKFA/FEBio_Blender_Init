# ASRP 文档总览

给谁看：每一位新加入的开发者、审查者和实验室成员。读完能知道：先读哪几份、每份回答什么问题、仓库里的文件放在哪。不包括：项目的内容本身，那在 [01](01-overview.md) 以后的各份里。

这套文档是项目的**唯一依据**。文档和代码不一致时，以文档为准，并且先改文档、再改代码。

任务的状态、顺序和验收标准只写在 [09 路线图与任务](09-roadmap-and-tasks.md)，还开着的问题和风险只写在 [11](11-risks-and-questions.md)，其他文档只链过去。

## 先读哪几份

| 你是谁 | 按顺序读 |
|---|---|
| 第一次接触项目的任何人 | [01 项目一页纸](01-overview.md) → [术语表](glossary.md) → [15 原型机](15-prototype.md) |
| 实验室成员 | 01 → [02 需求](02-requirements.md) → [03 资产说明](03-asset.md) → [14 实验室的操作流程](14-ziva-demo-walkthrough.md) → [11 风险与待决问题](11-risks-and-questions.md) → [12 导出清单](12-lab-export-checklist.md)（第三部分是给实验室的问题） |
| 开发者（含 AI 开发会话） | 先读起步文档：01 → 术语表 → [08 开发规范](08-engineering-standards.md) → [10 决策记录](10-decisions.md) 最前面的"现在生效的是什么"（只读这一段）；接着按下面"开发者按事选读"只读和你当前任务有关的一两份，**不要通读全部文档** |
| 审查者 | 08 开发规范 → [07 验证与验收](07-validation.md) → 被审查任务的任务卡 |
| 想看原型机动起来、自己跑一遍 | [15](15-prototype.md)，或仓库根目录的 [README](../README.md) |
| 读的时候有疑问 | 先查 [13 设计解释](13-explanations.md) 的目录；没有的话问出来，答完补进 13 |

### 开发者按事选读

读完上面的起步文档，就知道了项目是什么、词是什么意思、开发规矩和现在生效的决定。往后按手上的事选读：

- **手里有任务卡（一次只做一张）**：在 [09 路线图与任务](09-roadmap-and-tasks.md) 里**只读分给你的那一张**，再只读任务卡里写明要遵守的文档和章节；没点到的不用提前通读。
- **没有任务卡，或需要补背景**：看下面这张表，你现在做哪类事，就只加读对应的一两份。

| 你现在要做什么 | 加读 |
|---|---|
| 搞清从 Maya 到 Blender 的整条流程，以及每步用哪条命令和哪些 `.py` 文件 | [16 从 Maya 到 Blender 的完整流程](16-pipeline.md)（想顺便看原型机怎么跑、数字说明什么，再看 [15 原型机](15-prototype.md)） |
| 改软件结构、数据流向、文件格式，或和实验室代码的分界 | [04 系统设计](04-architecture.md)（只看涉及的章节） |
| 改 Ziva 到 FEBio 的设置对应，或查其中的坑 | [05 Ziva 到 FEBio 的对应](05-ziva-to-febio.md)（要核对实验室原本的 Ziva 设置值时，查 [03 资产说明](03-asset.md) 对应部分） |
| 处理实验室的 Maya 场景、运动文件，或查实验室代码怎么跑 | [03 资产说明](03-asset.md) |
| 从实验室机器导出数据、核对已拿到的数据，或了解实验室在 Maya + Ziva 里的工作方式 | 取数与核对看 [12 导出清单](12-lab-export-checklist.md)；实验室的操作流程看 [14 实验室的操作流程](14-ziva-demo-walkthrough.md) |
| 改 Blender 里的 ASRP 面板 | [06 界面设计](06-ui.md)（涉及和核心程序的分界或文件格式时，查 [04 系统设计](04-architecture.md) 对应章节） |
| 写验证、和 Ziva 比结果，或核对算不算做到 | [07 验证与验收](07-validation.md)；核对功能要求和验收标准时加读 [02 需求](02-requirements.md) |
| 改需求、改设计，或看还有哪些没定的事和风险 | [02 需求](02-requirements.md)、[11 风险与待决问题](11-risks-and-questions.md)（改设计前先按 10 开头的索引查清相关的已有决定） |

**下面几份不要通读，按需查就行：**

- **[09 路线图与任务](09-roadmap-and-tasks.md)**：只读分给你的那一张任务卡。
- **[10 决策记录](10-decisions.md)**：只读最前面的"现在生效的是什么"，再按需翻具体条目。
- **[13 设计解释](13-explanations.md)**：有疑问时先查目录，只读对应条目。
- **[archive/09-completed-tasks.md](archive/09-completed-tasks.md)** 和 **[archive/13-audit-history.md](archive/13-audit-history.md)**：原样保存的历史（已完成和取消的任务卡、历次审计记录和已过时的解释）。**平时不用读**，只在别的文档引用到里面的 `T-xx`、`E-xx` 编号时再去查。

## 全部文档

| 编号 | 文档 | 回答什么问题 |
|---|---|---|
| 01 | [项目一页纸](01-overview.md) | 项目在换什么、哪些是我们做的、现在到哪了 |
| 02 | [需求](02-requirements.md) | 做出来的东西要能干什么、怎样算做到了 |
| 03 | [资产说明](03-asset.md) | 实验室给的 Maya 场景里有什么、Ziva 的设置值是多少、运动文件是什么格式、实验室的代码怎么跑 |
| 04 | [系统设计](04-architecture.md) | 软件分成哪几块、数据怎么流动、文件长什么样、和实验室的代码怎么分界 |
| 05 | [Ziva 到 FEBio 的对应](05-ziva-to-febio.md) | Ziva 里的每样设置，到 FEBio 里怎么表达，有哪些坑 |
| 06 | [界面设计](06-ui.md) | Blender 里的 ASRP 面板长什么样、现在能做什么 |
| 07 | [验证与验收](07-validation.md) | 怎么证明结果是对的、和 Ziva 比什么 |
| 08 | [开发规范](08-engineering-standards.md) | 代码放哪、怎么提交、怎么测试、什么叫"完成" |
| 09 | [路线图与任务](09-roadmap-and-tasks.md) | 分几步走、每一步的任务卡、状态 |
| 10 | [决策记录](10-decisions.md) | 做过哪些关键决定、为什么、放弃了什么 |
| 11 | [风险与待决问题](11-risks-and-questions.md) | 还没定的事、要问实验室的事、可能出问题的地方 |
| 12 | [导出清单](12-lab-export-checklist.md) | 从实验室机器上已经拿到了哪些数据、怎么拿的、下次还要取什么、问实验室什么 |
| 13 | [设计解释（问答）](13-explanations.md) | 看文档、做任务时冒出的"为什么要这样""这一步从哪来"，包括 Ziva 机器上实测的结果（E-11） |
| 14 | [实验室的操作流程](14-ziva-demo-walkthrough.md) | 实验室在 Maya + Ziva 里怎么工作、钢琴界面怎么用（2026-11-10 演示录像） |
| 15 | [原型机](15-prototype.md)（[English](15-prototype.en.md)） | 原型机长什么样、怎么自己跑、跑出的数字说明什么、不说明什么 |
| 16 | [从 Maya 到 Blender 的完整流程](16-pipeline.md)（[English](16-pipeline.en.md)） | 从 Maya 导出到 Blender 播放、和 Ziva 对比，一共哪几步、每一步用哪条命令和哪些 `.py` 文件 |
| — | [术语表](glossary.md) | 文档里出现的专业词是什么意思 |
| — | [templates/](templates/) | 任务卡和合并请求的模板 |
| — | [archive/09-completed-tasks.md](archive/09-completed-tasks.md) | 已完成和取消的任务卡，整张原样保存；平时不用读 |
| — | [archive/13-audit-history.md](archive/13-audit-history.md) | 历次审计记录和已过时的解释，整条原样保存；平时不用读 |

## 仓库目录

✅ 提交进仓库；🚫 被 git 忽略，只在本机。**仓库放项目本身，不放开发过程**：一次性的脚本和带日期的工作计划不进仓库（08 第 1 节）。新功能按 [04](04-architecture.md) 第 3 节放，不要自己新建顶层目录。

```
asrp/
├─ README.md                  GitHub 首页：原型机动图、运行命令、安装、自动检查、Blender 插件、回放
├─ pyproject.toml  uv.lock    Python 依赖（Python 3.13）
├─ .github/                   合并请求模板
├─ AGENTS.md  CLAUDE.md  .claude/   🚫  本机 AI 开发用的文件，每台机器自己的，不进仓库（验证门拒绝被跟踪）；自动检查的命令是 `uv run python tools/verify.py --level auto`
├─ .gitattributes             data/、tests/fixtures/ 按字节检出，哈希在任何电脑上都对得上（08 第 10 节）
│
├─ docs/                      设计文档（本目录），唯一依据
│  ├─ 01 … 16、glossary.md    见上面的"全部文档"
│  ├─ archive/                归档，整张整条原样保存，平时不用读
│  │  ├─ 09-completed-tasks.md   已完成和取消的任务卡
│  │  └─ 13-audit-history.md     历次审计记录和已过时的解释
│  └─ templates/              任务卡、合并请求模板
│
├─ src/
│  ├─ asrp_core/              核心程序，不能 import bpy
│  │  ├─ cli.py               命令行 asrp（doctor、check、import-asset、convert-motion、list-motions、run）
│  │  ├─ doctor.py            找 FEBio、Blender，查路径
│  │  ├─ febio.py             调用 FEBio、读日志
│  │  ├─ playback.py          回放包（表面网格 + PC2 点缓存）
│  │  ├─ tetmesh.py           四面体网格的检查和读写（ADR-20）
│  │  ├─ scene.py             场景描述 scene.json 的格式和校验（asrp check）
│  │  ├─ trajectory.py        运动 trajectory.json 的格式、铰链运动生成；实验室运动文件的受限读取和转换（asrp convert-motion）
│  │  ├─ motions.py           导出文件夹里有哪些运动（asrp list-motions，面板的运动列表）
│  │  ├─ compare.py           两份结果差多少：逐帧的平均、P95、最大，下垂，晃动，翻转的面（T-34）
│  │  ├─ generate.py          生成器：scene + trajectory → FEBio 输入 .feb（真实大小、× k，粘连）
│  │  ├─ embed.py             把显示网格嵌进四面体网格，算出每帧显示顶点位置
│  │  ├─ simulate.py          asrp run 的整条流程：生成 → FEBio → ÷ k → 嵌入 → 检查 → 回放包
│  │  ├─ skinning.py          landmark 层：deform = base + weights @ translations，读 skin_mm.json
│  │  ├─ final_shape.py       给实验室训练代码的接口：final_shape(model, 下颌转动, landmark 位置)，model 由 rest_model(scene.json) 得到，不经过 Maya（T-31）
│  │  ├─ plausibility.py      合理性检查 (a)(b)(b2)(c)(d)
│  │  ├─ run.py               运行外壳：运行文件夹、进度、取消、出错处理
│  │  ├─ provenance.py        溯源记录 provenance.json
│  │  └─ asset/               资产导入（asrp import-asset）
│  │     ├─ lab.py            读实验室导出，写 scene.json 和检查报告
│  │     ├─ coords.py         唯一的一份坐标换算
│  │     └─ skin.py           把 landmark 蒙皮换算成毫米、Z 轴朝上，写 landmarks/skin_mm.json
│
├─ blender_addon/asrp_blender/  Blender 插件，只管界面，不用第三方库
│  ├─ __init__.py             面板（英文）：Load result、Check backend、Run、Results、Checks
│  ├─ asset.py                三步流程：Open asset 建五个物体，把一次运行的结果放回这五个物体上（T-35）
│  └─ session.py              一次 asrp run 的子进程：读输出、进度、取消（不含 bpy）
│
├─ tests/                     自动测试（pytest）
│  ├─ fixtures/s1/            示例 scene.json、trajectory.json，由同目录的 build.py 生成
│  ├─ test_prototype.py       真实嘴唇整条运行（约 2 分钟；只有验证门的 full 级设 ASRP_SLOW=1 跑它，docs、core 级不跑；单独跑 pytest 时要自己设）
│  ├─ test_docs_references.py 文档里的相对链接和图片都指向存在、而且 git 收着的文件（大小写也要一致）；引用的 T-、ADR-、E- 编号都有定义；英文译文的数字和链接和中文原文一致
│  ├─ test_no_lab_files.py    不许实验室和厂商文件进 git 的检查的测试
│  ├─ test_verify_gate.py     验证门本身
│  ├─ test_one_off_files_gone.py  一次性开发文件（13 E-12 的清单）和本机 AI 开发文件一个都不能被跟踪
│  ├─ s1_dynamic_jaw.py  s2_lips_febio.py  s3_attachment.py  landmark_layer_check.py   原来的试验脚本，现在是被验证门和测试运行、导入的检查（不是 test_*.py）
│  ├─ test_line_endings.py    被跟踪的文本文件一律 LF
│  └─ test_*.py               其余是各模块的测试，文件名对应模块名
│
├─ tools/                     检查、导出、分析、渲染工具，不是产品代码
│  ├─ verify.py               "完成"的定义，分 docs / core / full 三级（08 第 6 节）
│  ├─ check_no_lab_files.py   不许实验室和厂商文件进 git 的检查（验证门每级都跑）
│  ├─ build_tetmesh.py        生成嘴唇四面体网格 data/tetmesh/lips.json，只显式跑一次（ADR-20）
│  ├─ lip_attachments.py      导出嘴唇的四组粘连顶点集 data/lab_export/lip_attachments.json（T-03）
│  ├─ placeholder_jaw_motion.py   写测试用的下颌铰链运动 trajectory.json（张开 12°）。它只是测试输入，实验室的真实运动由 T-10 转换
│  ├─ ziva_comparison.py      我们的嘴唇对 Ziva 的两次运行：导入、转换、运行、逐帧比，写 data/preview/ziva_comparison.json（T-34；需要仓库外的数据）
│  ├─ render_prototype.py     在 Blender 里加载回放包、逐帧核对、渲染
│  ├─ check_blender_addon.py  check_playback.py  check_panel.py   插件、回放、面板的检查（验证门会跑）
│  ├─ panel_windowed_check.py 面板的定时器路径，带窗口的 Blender，手动跑，不在验证门里
│  ├─ mb_inventory.py  asset_report.py     不开 Maya 读 .mb，打印 03 里的数字
│  ├─ maya_export.py  check_lab_export.py  本机 Maya 导出网格、权重、关节并逐点核对（12 第一部分）
│  ├─ blender_import_preview.py            导出结果进 Blender，渲染预览
│  ├─ ziva_machine_export.py               在 Ziva 机器上采集（12 第一部分）
│  └─ lab_trip_manifest.py                 给一趟上机取回的数据写清单和指向它的 `.local/ziva_trip_pointer.json`
│
├─ data/                      导出和派生数据（ADR-19）
│  ├─ lab_export/        ✅   网格 OBJ、mesh_report.json、skin_skinCluster7.json、joints.json、
│  │                          lip_attachments.json；T-10 转换后的运动放 trajectories/；
│  │                          ziva_trip_pointer.json 指向仓库外的 Ziva 机器数据
│  ├─ preview/           ✅   Blender 预览图和归档的运行报告，15 的数字来源；README 顶上的动图 prototype_aa_front.gif 和更早一次运行的 prototype_motion.gif
│  ├─ tetmesh/           ✅   嘴唇四面体网格 lips.json，由 tools/build_tetmesh.py 生成一次（ADR-20）
│  └─ asset_inventory*.json  🚫  .mb 的完整清单，约 40 MB，能重新生成
│
├─ assets/               🚫   实验室原始 .mb，绝不提交（N-06）
└─ runs/                 🚫   每次求解一个文件夹（结构见 04 第 4 节）
```

## 文档怎么维护

- **谁都可以提修改**，但要走和代码一样的流程：开分支、提合并请求、至少一人审过再合并（见 08）。
- **改设计先改文档。** 任务做到一半发现设计不对，先停下来改 04/05 并说明原因，审过后再继续写代码。
- **每份文档说现在什么是真的。** 解释写进 13，决定写进 10，还没定的事写进 11，任务状态写进 09。某一天的审计和核对记录、已经过时的解释，放 `archive/13-audit-history.md`；做完和取消的任务卡整张搬进 `archive/09-completed-tasks.md`（怎么搬见 08 第 9 节）。
- **一个事实只在一处写。** 需求在 02，设计在 04，Ziva 到 FEBio 的对应和坑在 05，资产在 03，验证在 07。别处链过去。
- **每个数字都要能复现。** 文档里写的实测数字，要注明是哪个脚本或命令得出的，或指向 13 里的条目。
- **解释写进 13。** 回答"为什么要这样"这类问题时，如果答案要翻好几份文档才拼得出来，就整理成 13 里的一条，并在相关文档的对应位置链过去。
- 文档用中文写，代码、文件名、命令保持英文。专业词第一次出现时解释，并收进术语表。
- **英文译文跟着中文走。** 15、16 各有一份英文译文（`15-prototype.en.md`、`16-pipeline.en.md`），给不读中文的人看。中文那份是原文：先改中文，再照着改译文。译文里的数字或链接和原文对不上时，`tests/test_docs_references.py` 失败并指出是哪一个。
- 每份文档开头用两三句话写清：给谁看、读完能做什么、不包括什么。
