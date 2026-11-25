# ASRP 文档总览

给谁看：项目负责人、开发者（含每次从零读起的 AI 开发会话）、审查者与实验室研究员。
这套文档是项目的**唯一依据**：代码与文档不一致时，先确认并改文档，再改代码（[ADR-12](decisions/ADR-12.md)）。

## 项目现在在哪（2026-11-24）

- **已交付基线（原型机一、二）**：单嘴唇 + 骨头在 Blender 里三步跑通（下颌张开 12°、实验室中性到 AA、甩头），与 Ziva 逐帧对比完成；操作与数字见 [15 原型机结果页](15-prototype.md)。
- **当前主线（地基阶段 v2，[T-42](tasks/T-42.md)–[T-52](tasks/T-52.md)）**：把单组织冷启动原型重构为可长期演进的四边界核心（**场景、建造、段、结果**），支撑多组织、皮肤、连续段续算、`asrp_query` 训练查询，同时直接承接实验室演示场景、第二族场景以及在 Blender 里从零搭建的新模型（[T-39](tasks/T-39.md)）。
- **核心架构**：直接看 **[architecture/README.md](architecture/README.md)**（原型 v1 架构已完整归档至 [archive/prototype/04-v1-architecture.md](archive/prototype/04-v1-architecture.md)）。

---

## 按角色一步直达

| 你是谁 / 要干什么 | 直接读这几份（不要通读全库） |
|---|---|
| **第一次了解项目** | [01 项目一页纸](01-overview.md) → [术语表](glossary.md) → [09 路线图与任务](09-roadmap-and-tasks.md)（想看已跑通演示再看 [15](15-prototype.md)） |
| **查正在生效的参数、门限或实测值** | [00 现行生效设定速查](00-current-settings.md)（全库唯一汇总表，附出处与限定语） |
| **拿一张任务卡开工（人或 AI 会话）** | 起步只读：[01](01-overview.md) → [术语表](glossary.md) → [08 开发规范](08-engineering-standards.md) → [10 决策记录](10-decisions.md) 顶部“现行铁律”；然后**只读 `docs/tasks/T-xx.md` 和卡里点名的文件** |
| **了解地基架构（v2）** | [architecture/README.md](architecture/README.md) → 按需点进三份专题页（场景与数据 / 建造与粘连 / 会话与结果） |
| **做物理建模或查 FEBio 坑** | [05 Ziva 到 FEBio 对应](05-ziva-to-febio.md) + [05 FEBio 踩坑清单](05-febio-pits.md) + [03 资产说明](03-asset.md) |
| **做验证、写检查或代码审查** | [08 开发规范](08-engineering-standards.md) + [07 验证与验收](07-validation.md) + 对应单张任务卡 |
| **看风险、拍板项、下次上机要取什么** | [11 风险与待决问题](11-risks-and-questions.md) + [12 导出清单](12-lab-export-checklist.md) |
| **实验室成员** | [01](01-overview.md) → [15 原型机](15-prototype.md)（[English](15-prototype.en.md)） → [12 导出清单](12-lab-export-checklist.md)（“给实验室的一页”是可直接回复的 3 个问题） |
| **读文档时遇到“为什么这样定”** | 查 [13 设计解释](13-explanations.md) 目录，只点开对应的 `explanations/E-xx.md` |

---

## 文档结构（三层分明）

### 第一层：现行主线（地基阶段与长期产品）

| 文档 / 目录 | 回答什么问题 |
|---|---|
| [00-current-settings.md](00-current-settings.md) | 现行线程、FEBio 运行、材料、单位、网格、粘连、门限、实测基线与环境版本一页查全 |
| [01-overview.md](01-overview.md) | 项目一页纸：换什么、原型已交付什么、现在地基做什么、接下来怎么演进 |
| [02-requirements.md](02-requirements.md) | 替代目标（ADR-45）、产品能力需求、通用硬约束（N-01..07）与论文用法对照 |
| **[architecture/](architecture/README.md)** | **主系统架构（地基 v2）**：四处边界、模块与 CLI、场景版本、建造与粘连、会话与结果、`asrp_query`、实验室代码分界 |
| [03-asset.md](03-asset.md) / [03-lab-source.md](03-lab-source.md) | 实验室两族全脸场景事实（41 组织/2 皮肤/10 骨/140 粘连边/84 运动）、单位与轴、只读源码笔记 |
| [05-ziva-to-febio.md](05-ziva-to-febio.md) / [05-febio-pits.md](05-febio-pits.md) | Ziva 到 FEBio 物理映射、单位与物理尺度、求解与阻尼设置；以及 27 条实测踩坑速查 |
| [06-ui.md](06-ui.md) | Blender 宿主约定、地基新面板待补设计缺口，以及已交付原型面板精简规格 |
| [07-validation.md](07-validation.md) | 地基四项研究员签收与裁判分工、管线与合理性检查、下颌直线廉价对照、Ziva 对比口径与排查 |
| [08-engineering-standards.md](08-engineering-standards.md) | 仓库边界、环境、分支/提交、代码与测试规矩、验证门分级、文档维护规矩 |
| [09-roadmap-and-tasks.md](09-roadmap-and-tasks.md) + `tasks/` | 地基主线（`T-42..T-52`）、地基之上五组演进方向，以及活跃任务卡索引 |
| [10-decisions.md](10-decisions.md) + `decisions/` | 按主题浓缩的现行铁律总览，以及 43 条生效中独立决策文件（`ADR-xx.md`） |
| [11-risks-and-questions.md](11-risks-and-questions.md) | 负责人待拍板项、地基 13 项不定项总表、实验室待答/待取清单、活跃风险与假设台账 |
| [12-lab-export-checklist.md](12-lab-export-checklist.md) | 下次上 Ziva 机器要取的清单（`D12–D22`）与发给实验室的 3 个问题 |
| [13-explanations.md](13-explanations.md) + `explanations/` | 长期有效的设计解释（`E-11/13/20/22/24`）、T-34 逐帧基线（`E-19`）及归档解释索引 |
| [glossary.md](glossary.md) | 全项目统一术语表（含 15 个地基核心术语与旧分法说明） |
| [templates/](templates/) | 任务卡和合并请求模板 |

### 第二层：已交付原型与实验室操作参考（非当前开发主线）

| 文档 | 说明 |
|---|---|
| [15-prototype.md](15-prototype.md)（[English](15-prototype.en.md)） | 已交付原型机一、二的实测结果页（数字自动绑定 `data/preview/` 存档） |
| [16-pipeline.md](16-pipeline.md)（[English](16-pipeline.en.md)） | 当前原型已跑通的 12 步实操命令流（地基新命令见 `architecture/README.md`，待 `T-47` 切换后更新） |
| [14-ziva-demo-walkthrough.md](14-ziva-demo-walkthrough.md) | 2026-11-10 实验室 Maya + Ziva 与钢琴界面操作录像记录 |
| [17-paper-outline.md](17-paper-outline.md) | 系统论文大纲（草稿）：把原型机写成系统论文的贡献点、形式化、结构、投稿前要先解决的问题（待和项目负责人讨论） |

### 第三层：归档（`archive/` — 原样保存历史事实，平时不用读）

- `archive/prototype/`：已交付原型 v1 架构（原 `04` §1–12）、原型粘连试验流水账、原型面板完整规格、原型验收步骤、原型 M0–M5 里程碑、首次上机详细日志。
- `archive/tasks/`（30 张）：已完成、取消或已并入地基的任务卡。
- `archive/decisions/`（11 条）：被取代或已完成历史使命的旧决策。
- `archive/explanations/`（18 篇）：历次审计记录、2026-11-24 证据与实测台账（[E-23](archive/explanations/E-23.md)）和阶段性旧解释。
- [archive/11-resolved-issues.md](archive/11-resolved-issues.md)：已关闭的拍板项、问题、数据、风险与假设。

---

## 仓库目录

✅ 提交进私有仓库；🚫 被 git 忽略，只在本机。仓库只放项目本身，不放一次性脚本和带日期的工作计划（[08](08-engineering-standards.md) 第 1 节）。

```text
asrp/
├─ README.md                  仓库首页：原型动图、安装、运行、自动检查与插件回放
├─ pyproject.toml  uv.lock    Python 3.13 依赖与工具配置
├─ .gitattributes             data/、tests/fixtures/ 按字节检出，避免换行符破坏哈希
├─ .github/                   合并请求模板
├─ AGENTS.md  CLAUDE.md  .claude/   🚫 本机开发工具配置，每机自管（验证门拒绝被跟踪）
├─ .local/                    🚫 本机路径指针（如 ziva_trip_pointer.json 指向仓库外 Ziva 数据）
│
├─ docs/                      设计文档（本目录），唯一依据
├─ src/asrp_core/             核心程序（严禁 import bpy）：
│  ├─ cli.py                  命令行：doctor、check、import-asset、convert-motion、set-motion-title、list-motions、run、compare
│  ├─ asset/                  实验室导出导入、唯一单位与轴换算（coords.py）、蒙皮换算（skin.py）
│  ├─ scene.py / trajectory.py / motions.py   场景描述、运动格式与运动列表
│  ├─ tetmesh.py / embed.py   四面体校验加载与表面嵌入
│  ├─ generate.py / febio.py / run.py / simulate.py   .feb 生成、FEBio 调用、运行外壳与全流程编排
│  ├─ plausibility.py / compare.py / ziva_compare.py  合理性检查与 Ziva 对比
│  ├─ skinning.py / final_shape.py / playback.py / provenance.py / doctor.py
├─ blender_addon/asrp_blender/  Blender 5.2 插件（只管界面，无第三方依赖）
├─ tests/                     自动化测试（含 docs 级、core 级和真实嘴唇慢测试）
├─ tools/                     verify.py、check_no_lab_files.py、build_tetmesh.py、prototype_numbers.py、导出与渲染工具
├─ data/                      导出与派生数据（ADR-19）：
│  ├─ lab_export/        ✅   网格 OBJ、mesh_report、skinCluster7、joints、lip_attachments、trajectories/
│  ├─ preview/           ✅   归档运行报告、对比 JSON、预览图与动图（15 的数字来源）
│  ├─ tetmesh/           ✅   离线生成一次并锁哈希的 lips.json（细）与 lips_lattice.json（粗）
│  └─ asset_inventory*.json  🚫 .mb 清单（约 40 MB，可重生成）
├─ assets/                    🚫 实验室原始 .mb 场景（绝不提交，N-06）
└─ runs/                      🚫 每次运行的输出目录（绝不提交）
```

---

## 文档怎么维护（精要，细则见 [08 第 7 节](08-engineering-standards.md)）

1. **主线永远写“现在什么是真的”**：原型或历史过程不再占主文档篇幅，原样移进 `docs/archive/`，不删除数字和证据。
2. **一处权威、别处链接**：生效参数只改 [00](00-current-settings.md) 与原设计页；任务状态只改 [09](09-roadmap-and-tasks.md) 与 `tasks/T-xx.md`；未决项只改 [11](11-risks-and-questions.md)。
3. **代码出处用稳定符号，不写裸行号**：文档引用代码时写 `模块路径 + 函数/常量/命令行选项名`，不写易随编辑漂移的 `file.py:<行号>`。
4. **洁净与可核查**：本机绝对路径与证据目录只写在 [E-23](archive/explanations/E-23.md)；文档和 git 提交中不写 AI 模型和厂商名（`CLAUDE.md` / `.claude/` 作为被仓库忽略的字面文件名规则除外）；中英对照页（`15-prototype.en.md`、`16-pipeline.en.md`）随中文同步；改完必跑 `uv run python tools/verify.py --level docs`（合并前跑完整 `verify.py`）。
