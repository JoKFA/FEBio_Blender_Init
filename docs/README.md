# ASRP 文档总览

这套文档是项目的**唯一依据**。所有人（实验室、开发者、审查者、AI 开发会话）都按这里写的内容做事；文档和代码不一致时，以文档为准，并且先改文档、再改代码。

## 接下来做什么

原型机（真实嘴唇被下颌带动，由 FEBio 算出）已经跑通。**下一个里程碑是原型机二**：在它上面加 landmark 层，做中性到 AA 和甩头两个动作，再来回 10 次（定义见 [09](09-roadmap-and-tasks.md) 第 1 节）。原型机二的任务和现在的顺序、每个任务做到哪了，都在 [09](09-roadmap-and-tasks.md) 第 2 节和任务卡里。需要项目负责人拍板的事都列在 [11](11-risks-and-questions.md) 第 1 节（P-06、P-07、P-09、P-10）；只能到 Ziva 机器上才能知道的事，在 [12](12-lab-export-checklist.md) 第二部分。

## 先读哪几份

| 你是谁 | 按顺序读 |
|---|---|
| 第一次接触项目的任何人 | [15 原型机：怎么跑、跑出了什么](15-prototype.md)（先看结果）→ [01 项目一页纸](01-overview.md) → [术语表](glossary.md) |
| 实验室成员 | 15 → 01 → [02 需求](02-requirements.md) → [03 资产说明](03-asset.md) → [11 风险与待决问题](11-risks-and-questions.md) → [12 导出清单](12-lab-export-checklist.md) |
| 开发者 | 15 → 01 → 02 → 03 → [04 系统设计](04-architecture.md) → [05 Ziva 到 FEBio 的对应](05-ziva-to-febio.md) → [07 验证与验收](07-validation.md) → [08 开发规范](08-engineering-standards.md) → [10 决策记录](10-decisions.md) → [09 路线图与任务](09-roadmap-and-tasks.md) 里分给你的任务卡 |
| 审查者 | 08 开发规范 → [07 验证与验收](07-validation.md) → 被审查任务的任务卡 |
| 想看原型机动起来、自己跑一遍 | [15](15-prototype.md)，或仓库根目录的 [README](../README.md) |
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
| 15 | [原型机：怎么跑、跑出了什么](15-prototype.md) | 原型机长什么样、怎么自己跑、跑出的数字说明什么、不说明什么 |
| — | [术语表](glossary.md) | 文档里出现的专业词是什么意思 |
| — | [templates/](templates/) | 任务卡和合并请求的模板 |

旧文档 `spec-v0.1.md`、`lab-questions.md` 的内容已经并入上面这套文档，只保留跳转说明。

## 仓库目录

✅ 提交进仓库；🚫 被 git 忽略，只在本机。还没有的模块按 [04](04-architecture.md) 第 3 节放，不要自己新建顶层目录。

```
asrp/
├─ README.md                  GitHub 首页：原型机动图、三条运行命令、安装、自动检查、Blender 插件、回放
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
│  │  ├─ cli.py               命令行 asrp（doctor、check、import-asset、run）
│  │  ├─ doctor.py            找 FEBio、Blender，查路径
│  │  ├─ febio.py             调用 FEBio、读日志
│  │  ├─ playback.py          回放包（表面网格 + PC2 点缓存）
│  │  ├─ tetmesh.py           四面体网格的检查和读写（ADR-20）
│  │  ├─ scene.py             场景描述 scene.json 的格式和校验（asrp check）
│  │  ├─ trajectory.py        运动 trajectory.json 的格式、铰链运动生成
│  │  ├─ generate.py          生成器：scene + trajectory → FEBio 输入 .feb（真实大小、× k，粘连）
│  │  ├─ embed.py             把显示网格嵌进四面体网格，算出每帧显示顶点位置
│  │  ├─ simulate.py          asrp run 的整条流程：生成 → FEBio → ÷ k → 嵌入 → 检查 → 回放包
│  │  ├─ skinning.py          landmark 层：deform = base + weights @ translations，读 skin_mm.json
│  │  ├─ plausibility.py      合理性检查 (a)(b)(b2)(c)(d)
│  │  ├─ run.py               运行外壳：运行文件夹、进度、取消、出错处理
│  │  ├─ provenance.py        溯源记录 provenance.json
│  │  └─ asset/               资产导入（asrp import-asset）
│  │     ├─ lab.py            读实验室导出，写 scene.json 和检查报告
│  │     ├─ coords.py         唯一的一份坐标换算
│  │     └─ skin.py           把 landmark 蒙皮换算成毫米、Z 轴朝上，写 landmarks/skin_mm.json
│  │                          待开发：compare.py……
│
├─ blender_addon/asrp_blender/  Blender 插件，只管界面，不用第三方库
│  ├─ __init__.py             面板（英文）：Load result、Check backend、Run、Results、Checks
│  └─ session.py              一次 asrp run 的子进程：读输出、进度、取消（不含 bpy）
├─ tests/                     自动测试（pytest）
│  ├─ fixtures/s1/            S1 写成的示例 scene.json、trajectory.json，由同目录的 build.py 生成
│  ├─ cube_scene.py           生成器测试用的方块场景（有教科书答案）
│  ├─ test_generate.py        生成器、嵌入、合理性检查、asrp run（方块算例）
│  ├─ test_prototype.py       真实嘴唇整条运行（约 2 分钟；验证门每次都设 ASRP_SLOW=1 跑它，单独跑 pytest 时要自己设）
│  ├─ test_prototype_page.py  15 里生成的数字表和存档的参考运行一致（tools/prototype_numbers.py）
│  ├─ test_verify_gate.py     验证门本身：它必须带 ASRP_SLOW=1 跑真实嘴唇的测试，别的步骤不带
│  ├─ test_docs_references.py 文档里的相对链接都指向存在的文件；引用的 T-、ADR-、E- 编号都有定义
│  ├─ test_render_prototype.py 渲染工具遇到没有沉降形状的运行时给出明确的提示
│  ├─ hinge.py                测试用的小工具：从铰链变换反推转角（不是测试）
│  ├─ test_run.py             运行外壳（替身模式）
│  ├─ test_lip_attachments.py test_s3_attachment.py
│  └─ test_line_endings.py    被跟踪的文本文件一律 LF
│                              （其余 test_*.py：asset、asset_report、doctor、febio、lab_export、playback、scene、tetmesh、trajectory、ziva_capture）
├─ spikes/                    一次性试验，不是产品代码
│  ├─ s1_dynamic_jaw.py       S1：FEBio 动力学、刚体铰链、重力方向
│  ├─ s2_tetmesh.py           S2：四面体化工具和包络各档的比较表（ADR-20）
│  ├─ s2_lips_febio.py        S2：嘴唇四面体网格进 FEBio（重力沉降 smoke、下颌张开 jaw）
│  ├─ s3_attachment.py        S3（T-07）：弹簧和重力是否给出教科书答案、弹簧加硬是否趋近硬绑定
│  ├─ attachment_overlap.py   一次性测量：四组嘴唇粘连是否共用四面体计算点
│  ├─ audit_material.py       审计（E-08）：嘴唇的 E 乘 10、除以 10 各重跑一遍，比下垂和形状
│  ├─ audit_threads.py        审计（E-08）：同一份 .feb 用不同线程数，比用时和坐标
│  ├─ audit_cycles.py         审计（E-08）：张嘴来回多次，看形状会不会越跑越偏
│  ├─ audit_attachment.py     审计（E-09）：嘴角锚的比例、弹簧刚度各改一档，比形状
│  ├─ audit_skin_identity.py  审计（E-09）：landmark 蒙皮数据能不能直接用（四项核对）
│  ├─ audit_head_shake.py     审计（E-09）：甩头时嘴唇相对头晃多少
│  ├─ audit_aa_fit.py         审计（E-09）：只靠蒙皮够不够到 AA 目标、目标里嘴唇跟不跟下颌
│  └─ blender_background_run.py  试验：Blender 面板能不能在后台跑 asrp run、显示进度、取消
│
├─ tools/                     迁移、检查、渲染工具，不是产品代码
│  ├─ verify.py               "完成"的定义：ruff + 测试 + doctor + 插件 + 回放检查
│  ├─ build_tetmesh.py        生成嘴唇四面体网格 data/tetmesh/lips.json，只显式跑一次（ADR-20）
│  ├─ lip_attachments.py      导出嘴唇的四组粘连顶点集 data/lab_export/lip_attachments.json（T-03）
│  ├─ lip_attachments_preview.py  把四组粘连画在真实网格上，给人看
│  ├─ placeholder_jaw_motion.py   写代用的下颌运动 trajectory.json（张开 12°，没有实验室运动时用）
│  ├─ landmark_layer_check.py 我们的 landmark 层对实验室自己的公式和数据（需要实验室自己的文件），写 data/preview/landmark_layer_check.json
│  ├─ prototype_numbers.py    从存档的参考运行写出 15 里的数字表（--write 重写，--check 核对，验证门会跑）
│  ├─ render_prototype.py     在 Blender 里加载原型机的回放包、逐帧核对、渲染侧视图和逐帧动画
│  ├─ check_blender_addon.py  check_playback.py  render_playback.py
│  ├─ check_panel.py          面板的运行、结果、检查，对真实 asrp run 进程（命令行下的 Blender，验证门会跑）
│  ├─ panel_windowed_check.py 面板的定时器路径，带窗口的 Blender，手动跑，不在验证门里
│  ├─ mb_inventory.py  asset_report.py     不开 Maya 读 .mb，打印 03 里的数字（含粘连权重的读法）
│  ├─ maya_export.py  check_lab_export.py  本机 Maya 导出网格、权重、关节并逐点核对
│  ├─ blender_import_preview.py            导出结果进 Blender，渲染预览
│  ├─ ziva_machine_export.py               在 Ziva 机器上跑一次（12 第二部分）
│  ├─ rehearse_ziva_export.py              在普通 Maya 上排练上面那个脚本
│  └─ briefing/               讲解页的源文件（build.py、template.html、app.js）
│
├─ data/                      导出和派生数据（ADR-19）
│  ├─ lab_export/        ✅   网格 OBJ、mesh_report.json、skin_skinCluster7.json、joints.json、
│  │                          lip_attachments.json（四组嘴唇粘连顶点集，T-03）；
│  │                          Ziva 机器上导出的文件收到后也放这里；T-10 转换后的运动放 trajectories/
│  │  └─ manual_maya_obj/     用 Maya 自带 OBJ 导出手动导的下巴、嘴唇、颅骨、两只眼睛和一个 .blend
│  │                          （提交 e24ff1b，原在 src/resources/）。只作参考，见 12 第一部分
│  ├─ preview/           ✅   Blender 预览图和 asset_preview.blend；原型机的动图 prototype_motion.gif、
│  │                          三张侧视图 prototype_{rest,settled,open}.png、参考运行的
│  │                          prototype_run_report.json 和 prototype_provenance.json（15 的数字来源）；
│  │                          landmark_layer_check.json（T-09 对照实验室公式的存档结果）
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
