# ASRP 文档总览

这套文档是项目的**唯一依据**。所有人（实验室、开发者、审查者、AI 开发会话）都按这里写的内容做事；文档和代码不一致时，以文档为准，并且先改文档、再改代码。

## 先读哪几份

| 你是谁 | 按顺序读 |
|---|---|
| 第一次接触项目的任何人 | [01 项目一页纸](01-overview.md) → [术语表](glossary.md) |
| 实验室成员 | 01 → [02 需求](02-requirements.md) → [03 资产说明](03-asset.md) → [11 风险与待决问题](11-risks-and-questions.md) → [12 导出清单](12-lab-export-checklist.md) |
| 开发者 | 01 → 02 → 03 → [04 系统设计](04-architecture.md) → [05 Ziva 到 FEBio 的对应](05-ziva-to-febio.md) → [07 验证与验收](07-validation.md) → [08 开发规范](08-engineering-standards.md) → [10 决策记录](10-decisions.md) → [09 路线图与任务](09-roadmap-and-tasks.md) 里分给你的任务卡 |
| 审查者 | 08 开发规范 → [07 验证与验收](07-validation.md) → 被审查任务的任务卡 |
| 读的时候有疑问 | 先查 [13 设计解释](13-explanations.md) 的目录；没有的话问出来，答完补进 13 |

## 全部文档

| 编号 | 文档 | 回答什么问题 |
|---|---|---|
| 01 | [项目一页纸](01-overview.md) | 这个项目是什么、为什么做、现在做到哪了 |
| 02 | [需求](02-requirements.md) | 做出来的东西要能干什么、怎样算做到了 |
| 03 | [资产说明](03-asset.md) | 实验室给的 Maya 场景里有什么、原型用哪些、还缺什么 |
| 04 | [系统设计](04-architecture.md) | 软件分成哪几块、数据怎么流动、文件长什么样 |
| 05 | [Ziva 到 FEBio 的对应](05-ziva-to-febio.md) | 实验室在 Ziva 里的每样设置，到新系统里怎么表达 |
| 06 | [界面设计](06-ui.md) | Blender 里的操作面板长什么样、怎么用 |
| 07 | [验证与验收](07-validation.md) | 怎么证明结果是对的、和 Ziva 差多少算合格 |
| 08 | [开发规范](08-engineering-standards.md) | 代码放哪、怎么提交、怎么测试、什么叫"完成" |
| 09 | [路线图与任务](09-roadmap-and-tasks.md) | 分几步走、每一步的任务卡、谁能先开始 |
| 10 | [决策记录](10-decisions.md) | 做过哪些关键决定、为什么、放弃了什么 |
| 11 | [风险与待决问题](11-risks-and-questions.md) | 还没定的事、要问实验室的事、可能出问题的地方 |
| 12 | [导出清单](12-lab-export-checklist.md) | 哪些数据已经从 Maya 导出、哪些要在 Ziva 机器上做、怎么做 |
| 13 | [设计解释（问答）](13-explanations.md) | 看文档、做任务时冒出的"为什么要这样""这一步从哪来"，答案在这里 |
| 14 | [实验室演示的 Ziva 操作流程](14-ziva-demo-walkthrough.md) | 2026-11-10 会议录像里看到的 Maya + Ziva 操作、读到的设置，和我们假设的对照 |
| — | [术语表](glossary.md) | 文档里出现的专业词是什么意思 |
| — | [templates/](templates/) | 任务卡和合并请求的模板 |

旧文档 `spec-v0.1.md`、`lab-questions.md` 的内容已经并入上面这套文档，只保留跳转说明。

## 仓库目录

✅ 提交进仓库；🚫 被 git 忽略，只在本机。"待开发"的模块按 [04](04-architecture.md) 第 3 节放，不要自己新建顶层目录。

```
asrp/
├─ README.md                  安装、自动检查、Blender 插件、回放的命令
├─ AGENTS.md                  给开发者和 AI 开发会话的项目规则
├─ pyproject.toml  uv.lock    Python 依赖（Python 3.13）
├─ .github/                   合并请求模板
├─ .claude/verify.json        自动检查的入口，和 tools/verify.py 相同
├─ .gitattributes             data/、tests/fixtures/ 按字节检出，哈希在任何电脑上都对得上（08 第 10 节）
│
├─ docs/                      设计文档（本目录），唯一依据
│  ├─ 01 … 13、glossary.md    见上面的"全部文档"
│  └─ templates/              任务卡、合并请求模板
│
├─ src/
│  ├─ asrp_core/              核心程序，不能 import bpy
│  │  ├─ cli.py               命令行 asrp（doctor、check、import-asset）
│  │  ├─ doctor.py            找 FEBio、Blender，查路径
│  │  ├─ febio.py             调用 FEBio、读日志
│  │  ├─ playback.py          回放包（表面网格 + PC2 点缓存）
│  │  ├─ tetmesh.py           四面体网格的检查和读写（ADR-20）
│  │  ├─ scene.py             场景描述 scene.json 的格式和校验（asrp check）
│  │  ├─ trajectory.py        运动 trajectory.json 的格式、铰链运动生成
│  │  └─ asset/               资产导入（asrp import-asset）
│  │     ├─ lab.py            读实验室导出，写 scene.json 和检查报告
│  │     └─ coords.py         唯一的一份坐标换算
│  │                          待开发：run.py、skinning.py、compare.py……
│
├─ blender_addon/asrp_blender/  Blender 插件，只管界面，不用第三方库
├─ tests/                     自动测试（pytest）
│  └─ fixtures/s1/            S1 写成的示例 scene.json、trajectory.json，由同目录的 build.py 生成
├─ spikes/                    一次性试验，不是产品代码
│  ├─ s1_dynamic_jaw.py       S1：FEBio 动力学、刚体铰链、重力方向
│  ├─ s2_tetmesh.py           S2：四面体化工具和包络各档的比较表（ADR-20）
│  └─ s2_lips_febio.py        S2：嘴唇四面体网格进 FEBio（重力沉降 smoke、下颌张开 jaw）
│
├─ tools/                     迁移、检查、渲染工具，不是产品代码
│  ├─ verify.py               "完成"的定义：测试 + doctor + 插件 + 回放检查
│  ├─ build_tetmesh.py        生成嘴唇四面体网格 data/tetmesh/lips.json，只显式跑一次（ADR-20）
│  ├─ check_blender_addon.py  check_playback.py  render_playback.py
│  ├─ mb_inventory.py  asset_report.py     不开 Maya 读 .mb，打印 03 里的数字（含粘连权重的读法）
│  ├─ maya_export.py  check_lab_export.py  本机 Maya 导出网格、权重、关节并逐点核对
│  ├─ blender_import_preview.py            导出结果进 Blender，渲染预览
│  ├─ ziva_machine_export.py               在 Ziva 机器上跑一次（12 第二部分）
│  ├─ rehearse_ziva_export.py              在普通 Maya 上排练上面那个脚本
│  └─ briefing/               讲解页的源文件（build.py、template.html、app.js）
│
├─ data/                      导出和派生数据（ADR-19）
│  ├─ lab_export/        ✅   网格 OBJ、mesh_report.json、skin_skinCluster7.json、joints.json；
│  │                          Ziva 机器上导出的文件收到后也放这里；T-10 转换后的运动放 trajectories/
│  │  └─ manual_maya_obj/     用 Maya 自带 OBJ 导出手动导的下巴、嘴唇、颅骨、两只眼睛和一个 .blend
│  │                          （提交 e24ff1b，原在 src/resources/）。只作参考，见 12 第一部分
│  ├─ preview/           ✅   Blender 预览图和 asset_preview.blend
│  ├─ briefing/          ✅   新成员讲解页 asrp-briefing.html
│  ├─ tetmesh/           ✅   嘴唇四面体网格 lips.json，由 tools/build_tetmesh.py 生成一次（ADR-20）
│  ├─ asset_inventory*.json  🚫  .mb 的完整清单，约 40 MB，能重新生成
│  └─ ziva_rehearsal/    🚫   排练的输出
│
├─ assets/               🚫   实验室原始 .mb，绝不提交（N-06）
└─ runs/                 🚫   每次求解一个文件夹（结构见 04 第 4 节）
```

给新成员的可交互讲解页在 `data/briefing/asrp-briefing.html`，双击就能打开，由 `tools/briefing/build.py` 生成。它内嵌实验室网格，只放在私有仓库里，不发到仓库以外的地方（ADR-19）。

## 文档怎么维护

- **谁都可以提修改**，但要走和代码一样的流程：开分支、提合并请求、至少一人审过再合并（见 08）。
- **改设计先改文档。** 任务做到一半发现设计不对，先停下来改 04/05 并说明原因，审过后再继续写代码。
- **每个数字都要能复现。** 文档里写的实测数字，要注明是哪个脚本或命令得出的。
- **定下来的事写进 10 决策记录；还没定的事写进 11。** 不要让决定只存在于聊天记录里。
- **解释写进 13。** 回答"为什么要这样"这类问题时，如果答案要翻好几份文档才拼得出来，就整理成 13 里的一条，并在相关文档的对应位置链过去。
- 文档用中文写，代码、文件名、命令保持英文。专业词第一次出现时解释，并收进术语表。
