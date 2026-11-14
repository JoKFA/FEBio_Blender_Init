# ASRP 文档总览

给谁看：每一位新加入的开发者、审查者和实验室成员。读完能知道：先读哪几份、每份回答什么问题、仓库里的文件放在哪。不包括：项目的内容本身，那在 [01](01-overview.md) 以后的各份里。

这套文档是项目的**唯一依据**。文档和代码不一致时，以文档为准，并且先改文档、再改代码。

任务的状态、顺序和验收标准只写在 [09 路线图与任务](09-roadmap-and-tasks.md)，还开着的问题和风险只写在 [11](11-risks-and-questions.md)，其他文档只链过去。

## 先读哪几份

| 你是谁 | 按顺序读 |
|---|---|
| 第一次接触项目的任何人 | [01 项目一页纸](01-overview.md) → [术语表](glossary.md) → [15 原型机](15-prototype.md) |
| 实验室成员 | 01 → [02 需求](02-requirements.md) → [03 资产说明](03-asset.md) → [14 实验室的操作流程](14-ziva-demo-walkthrough.md) → [11 风险与待决问题](11-risks-and-questions.md) → [12 导出清单](12-lab-export-checklist.md)（第三部分是给实验室的问题） |
| 开发者 | 01 → 02 → 03 → [04 系统设计](04-architecture.md) → [05 Ziva 到 FEBio 的对应](05-ziva-to-febio.md) → [07 验证与验收](07-validation.md) → [08 开发规范](08-engineering-standards.md) → [10 决策记录](10-decisions.md) → [09 路线图与任务](09-roadmap-and-tasks.md) 里分给你的任务卡 |
| 审查者 | 08 开发规范 → 07 验证与验收 → 被审查任务的任务卡 |
| 想看原型机动起来、自己跑一遍 | [15](15-prototype.md)，或仓库根目录的 [README](../README.md) |
| 读的时候有疑问 | 先查 [13 设计解释](13-explanations.md) 的目录；没有的话问出来，答完补进 13 |

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
| 15 | [原型机](15-prototype.md) | 原型机长什么样、怎么自己跑、跑出的数字说明什么、不说明什么 |
| — | [术语表](glossary.md) | 文档里出现的专业词是什么意思 |
| — | [templates/](templates/) | 任务卡和合并请求的模板 |

旧文档 `spec-v0.1.md`、`lab-questions.md` 的内容已经并入上面这套文档，只保留跳转说明。

## 仓库目录

✅ 提交进仓库；🚫 被 git 忽略，只在本机。**仓库放项目本身，不放开发过程**：一次性的脚本和带日期的工作计划不进仓库（08 第 1 节）。新功能按 [04](04-architecture.md) 第 3 节放，不要自己新建顶层目录。

```
asrp/
├─ README.md                  GitHub 首页：原型机动图、运行命令、安装、自动检查、Blender 插件、回放
├─ AGENTS.md                  给开发者和 AI 开发会话的项目规则
├─ pyproject.toml  uv.lock    Python 依赖（Python 3.13）
├─ .github/                   合并请求模板
├─ .claude/verify.json        自动检查的入口，和 tools/verify.py 相同
├─ .gitattributes             data/、tests/fixtures/ 按字节检出，哈希在任何电脑上都对得上（08 第 10 节）
│
├─ docs/                      设计文档（本目录），唯一依据
│  ├─ 01 … 15、glossary.md    见上面的"全部文档"
│  └─ templates/              任务卡、合并请求模板
│
├─ src/
│  ├─ asrp_core/              核心程序，不能 import bpy
│  │  ├─ cli.py               命令行 asrp（doctor、check、import-asset、convert-motion、run）
│  │  ├─ doctor.py            找 FEBio、Blender，查路径
│  │  ├─ febio.py             调用 FEBio、读日志
│  │  ├─ playback.py          回放包（表面网格 + PC2 点缓存）
│  │  ├─ tetmesh.py           四面体网格的检查和读写（ADR-20）
│  │  ├─ scene.py             场景描述 scene.json 的格式和校验（asrp check）
│  │  ├─ trajectory.py        运动 trajectory.json 的格式、铰链运动生成；实验室运动文件的受限读取和转换（asrp convert-motion）
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
│  └─ session.py              一次 asrp run 的子进程：读输出、进度、取消（不含 bpy）
│
├─ tests/                     自动测试（pytest）
│  ├─ fixtures/s1/            示例 scene.json、trajectory.json，由同目录的 build.py 生成
│  ├─ test_prototype.py       真实嘴唇整条运行（约 2 分钟；只有验证门的 full 级设 ASRP_SLOW=1 跑它，docs、core 级不跑；单独跑 pytest 时要自己设）
│  ├─ test_docs_references.py 文档里的相对链接都指向存在的文件；引用的 T-、ADR-、E- 编号都有定义
│  ├─ test_no_lab_files.py    不许实验室和厂商文件进 git 的检查的测试
│  ├─ test_verify_gate.py     验证门本身
│  ├─ test_line_endings.py    被跟踪的文本文件一律 LF
│  └─ test_*.py               其余是各模块的测试，文件名对应模块名
│
├─ spikes/                    试验代码，不是产品代码，不要在上面继续开发。验证门和测试还在用其中 s1、s2_lips、s3 三个文件
├─ tools/                     检查、导出、分析、渲染工具，不是产品代码
│  ├─ verify.py               "完成"的定义，分 docs / core / full 三级（08 第 6 节）
│  ├─ check_no_lab_files.py   不许实验室和厂商文件进 git 的检查（验证门每级都跑）
│  ├─ build_tetmesh.py        生成嘴唇四面体网格 data/tetmesh/lips.json，只显式跑一次（ADR-20）
│  ├─ lip_attachments.py      导出嘴唇的四组粘连顶点集 data/lab_export/lip_attachments.json（T-03）
│  ├─ placeholder_jaw_motion.py   写测试用的下颌铰链运动 trajectory.json（张开 12°）。它只是测试输入，实验室的真实运动由 T-10 转换
│  ├─ ziva_comparison.py      我们的嘴唇对 Ziva 的两次运行：导入、转换、运行、逐帧比，写 data/preview/ziva_comparison.json（T-34；需要仓库外的数据）
│  ├─ landmark_layer_check.py 我们的 landmark 层对实验室自己的公式和数据（需要实验室自己的文件）
│  ├─ render_prototype.py     在 Blender 里加载回放包、逐帧核对、渲染
│  ├─ check_blender_addon.py  check_playback.py  check_panel.py   插件、回放、面板的检查（验证门会跑）
│  ├─ panel_windowed_check.py 面板的定时器路径，带窗口的 Blender，手动跑，不在验证门里
│  ├─ mb_inventory.py  asset_report.py     不开 Maya 读 .mb，打印 03 里的数字
│  ├─ maya_export.py  check_lab_export.py  本机 Maya 导出网格、权重、关节并逐点核对（12 第一部分）
│  ├─ blender_import_preview.py            导出结果进 Blender，渲染预览
│  ├─ ziva_machine_export.py               在 Ziva 机器上采集（12 第一部分）
│  ├─ rehearse_ziva_export.py              在普通 Maya 上排练上面那个脚本
│  └─ lab_trip_manifest.py                 给一趟上机取回的数据写清单和指向它的 `.local/ziva_trip_pointer.json`
│                              一次性的试验、数字脚本和讲解页的源文件还在 spikes/ 和 tools/ 下，由 T-38 移出仓库，这里不逐个列
│
├─ data/                      导出和派生数据（ADR-19）
│  ├─ lab_export/        ✅   网格 OBJ、mesh_report.json、skin_skinCluster7.json、joints.json、
│  │                          lip_attachments.json；T-10 转换后的运动放 trajectories/；
│  │                          ziva_trip_pointer.json 指向仓库外的 Ziva 机器数据
│  │  └─ manual_maya_obj/     手动导的下巴、嘴唇、颅骨、两只眼睛和一个 .blend，只作参考，产品不读
│  ├─ preview/           ✅   Blender 预览图和归档的运行报告，15 的数字来源；README 里的动图 prototype_motion.gif
│  ├─ tetmesh/           ✅   嘴唇四面体网格 lips.json，由 tools/build_tetmesh.py 生成一次（ADR-20）
│  └─ asset_inventory*.json  🚫  .mb 的完整清单，约 40 MB，能重新生成
│
├─ assets/               🚫   实验室原始 .mb，绝不提交（N-06）
└─ runs/                 🚫   每次求解一个文件夹（结构见 04 第 4 节）
```

## 文档怎么维护

- **谁都可以提修改**，但要走和代码一样的流程：开分支、提合并请求、至少一人审过再合并（见 08）。
- **改设计先改文档。** 任务做到一半发现设计不对，先停下来改 04/05 并说明原因，审过后再继续写代码。
- **每份文档说现在什么是真的。** 过程、历史和被推翻的判断写进 13，决定写进 10，还没定的事写进 11，任务状态写进 09。
- **一个事实只在一处写。** 需求在 02，设计在 04，Ziva 到 FEBio 的对应和坑在 05，资产在 03，验证在 07。别处链过去。
- **每个数字都要能复现。** 文档里写的实测数字，要注明是哪个脚本或命令得出的，或指向 13 里的条目。
- **解释写进 13。** 回答"为什么要这样"这类问题时，如果答案要翻好几份文档才拼得出来，就整理成 13 里的一条，并在相关文档的对应位置链过去。
- 文档用中文写，代码、文件名、命令保持英文。专业词第一次出现时解释，并收进术语表。
- 每份文档开头用两三句话写清：给谁看、读完能做什么、不包括什么。
