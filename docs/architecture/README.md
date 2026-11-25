# 系统架构总览（地基阶段 v2）

给谁看：开发者（人或 AI 会话）与审查者。
读完能知道：ASRP 现在的四处核心边界、模块划分、命令行入口、与实验室代码的分界，以及每份详细设计在哪个专题页。

> **架构基线说明**：本目录（`docs/architecture/`）是 **ASRP 的唯一现行系统架构**（2026-11-24 收敛，对应 [ADR-46](../decisions/ADR-46.md)–[ADR-54](../decisions/ADR-54.md) 与 [T-43](../tasks/T-43.md)–[T-52](../tasks/T-52.md)）。
> - 设计理由与取舍见 [E-24](../explanations/E-24.md)；本机实测与证据目录见 [E-23](../archive/explanations/E-23.md)；13 项待证不定项汇总在 [11 风险与待决问题](../11-risks-and-questions.md)。
> - 已交付原型机（v1，单嘴唇冷启动）的旧架构说明已完整归档至 [archive/prototype/04-v1-architecture.md](../archive/prototype/04-v1-architecture.md)。
> - **术语边界**（以 [术语表](../glossary.md) 为准）：**“资产”**专指实验室原始材料；核心管理的可变物理与显示定义统称**“场景版本”**；运行前发给宿主查看和高亮的只读清单叫**“场景视图”**。

## 专题导航

| 文档 | 涵盖内容 | 关联决策与任务 |
|---|---|---|
| **本页** | 四处核心边界、模块职责、CLI 全景（现行 + 新增）、与实验室代码的分界 | [ADR-46](../decisions/ADR-46.md)–[ADR-54](../decisions/ADR-54.md) |
| [scene-and-data.md](scene-and-data.md) | 六种落盘数据形态、版本与未知字段契约、场景版本库落盘与 `.blend` 引用 | [ADR-46](../decisions/ADR-46.md) · [T-44](../tasks/T-44.md)、[T-45](../tasks/T-45.md) |
| [build-and-attachments.md](build-and-attachments.md) | 五层设置归属、`legacy-v1`/`demo-v1`、计算网格、粘连三层表达与 FEBio 三路实现、骨头通道预分配与旧入口切换 | [ADR-47](../decisions/ADR-47.md)、[ADR-48](../decisions/ADR-48.md)、[ADR-51](../decisions/ADR-51.md) · [T-46](../tasks/T-46.md)、[T-49](../tasks/T-49.md)–[T-51](../tasks/T-51.md) |
| [sessions-and-results.md](sessions-and-results.md) | 会话状态树与七条规矩、检查与提交分工、结果层（`physics`/`final`）、`asrp_query` 训练查询、段界插值 | [ADR-49](../decisions/ADR-49.md)、[ADR-50](../decisions/ADR-50.md)、[ADR-52](../decisions/ADR-52.md)–[ADR-54](../decisions/ADR-54.md) · [T-47](../tasks/T-47.md)、[T-48](../tasks/T-48.md)、[T-50](../tasks/T-50.md)、[T-52](../tasks/T-52.md) |

---

## 1. 四处核心边界与三条工程原则

```text
  宿主（Blender 插件 / CLI / 实验室 Python）
        │  ① 场景：读场景视图、提交编辑（只存版本与状态引用）
        │  ④ 结果：按 (状态, 对象, 表面 ID, 层, 帧) 读原序顶点；训练走 asrp_query
        ▼
  ┌───────────────────────── asrp_core ─────────────────────────┐
  │  importers / scene  ──▶  build  ──▶  motion / sessions      │
  │   (场景版本库)          (不可变建造)    (状态树 + 独立尝试)   │
  │                             │               │               │
  │                             └───▶ backends/febio ──▶ checks │
  │                                                      results│
  └─────────────────────────────────────────────────────────────┘
```

三条不变原则（[ADR-03](../decisions/ADR-03.md)、[08](../08-engineering-standards.md)）：
1. **宿主只管界面与交互**：`blender_addon/` 不含求解逻辑、不装第三方库；`asrp_core/` 严禁 `import bpy`。
2. **模块与进程靠带版本的文件契约交接**：每步输入、建造记录、段样本与结果可独立检查、重放。
3. **只吃标准场景版本，不绑定单一来源**：无论来自实验室演示包（[T-45](../tasks/T-45.md)）、第二族场景，还是在 Blender 里从零新建的模型（[T-39](../tasks/T-39.md)），进入 `scene` 之后走同一套建造、会话与结果管线。

四处固定边界：

1. **场景（要模拟什么）**：对象、参考表面、材料、物理尺度、粘连声明、驱动通道和显示绑定声明；按内容 SHA-256 定版。
2. **建造（这一次具体怎样模拟）**：本次实验的计算网格、显示绑定、粘连逐点对应与传力写法、预分配驱动通道及输出点映射；不可变落盘。
3. **段（从哪个状态出发施加了什么运动）**：从指定父状态出发的时间范围、实际控制输入、解析后驱动样本与生效求解设置。
4. **结果（读到的是哪张表面的哪些点）**：公开 `physics` 和 `final` 两层，按 `(状态, 对象, 表面 ID, 层, 绝对帧)` 返回原始顶点顺序的世界坐标数组。

**变更影响**：接着算复用同一份建造与父状态；改场景材料先发布新场景版本再建造开新会话；仅改建造配置（换网格或粘连算法）可复用原场景版本，但须新建造、新会话；旧版本与旧实验保持可读。

---

## 2. 模块划分与职责

后端只实现 FEBio 这一个；等出现第二个真实求解器（如 ArtiSynth）再提取通用后端框架。

| 模块 | 对外入口 / 交付形式 | 独自负责 | 落地任务 |
|---|---|---|---|
| `importers` | `import_bundle()` → 场景版本、场景视图、导入台账 | 解析 Ziva 属性、Maya 坐标、旧资产、稀疏默认值与缺项；台账双向追查原值与处理方式（迁移期保留 `asset/` 兼容入口） | [T-45](../tasks/T-45.md) |
| `scene` | `load_revision()`、`inspect()`、`edit_revision()` | 场景身份与版本库、稳定 ASCII ID 与 Unicode 显示名分离、JSON Schema 拒收未知字段、大文件摘要共享与编辑历史 | [T-44](../tasks/T-44.md)、[T-45](../tasks/T-45.md) |
| `build` | `prepare(revision, profile)` → 不可变建造记录 | 加载离线细网格或生成并封存规则格子、建显示绑定与粘连逐点对应、预分配驱动通道、产出输出点映射（复用 `tetmesh`/`embed`） | [T-46](../tasks/T-46.md) |
| `motion` | `resolve(parent_controls, segment)` → 完整本段驱动 | 识别起步/追加/保持/复位、单位换算与插值、分离物理通道与四组 landmark 显示通道、校验未知非零通道（只读父末控制量，不读 `.dmp`） | [T-47](../tasks/T-47.md)、[T-52](../tasks/T-52.md) |
| `backends/febio` | `prepare_model()`、`write_initial()`、`write_restart()`、`read_segment()` | 翻译为 FEBio 单元/约束/号表，首次 `.feb` 与重启 `.rst` 共享编号表；交出原序全部原始运行事实，不判提交 | [T-46](../tasks/T-46.md)、[T-47](../tasks/T-47.md) |
| `sessions` | `create()`、`advance()`、`checkout()`、`replay()`、`drop_cache()` | 状态树、独立尝试目录（禁原地覆写 `.dmp`）、整目录原子提交、分支引用、失败恢复、删缓存重放 | [T-47](../tasks/T-47.md)、[T-48](../tasks/T-48.md) |
| `results` | `read_vertices()`、`export_playback()` | 用封存绑定还原原序显示顶点、做已验证显示后处理、产公开结果清单（`asrp-results/1`）与派生 PC2 | [T-44](../tasks/T-44.md)、[T-50](../tasks/T-50.md) |
| `checks` | `checks.evaluate(raw_run, candidate_results, rules)`；保留 `asrp compare` | 核执行完整性（含全量实际时间）、物理合理性（迁入原 `plausibility.py`）、显示面质量与 Ziva 对照；不改状态树 | [T-46](../tasks/T-46.md)、[T-48](../tasks/T-48.md) |
| `asrp_query` | 独立安装包，Python 3.9 `asrp_query.open_query(static_path)` | 面向实验室训练热循环的无状态进程内查询：一次载入 `query.json` 静态数据，按姿态返回四组 landmark 网格与下颌原序坐标（兼容旧 `rest_model`/`final_shape`） | [T-52](../tasks/T-52.md) |
| CLI 与插件 | CLI 暴露全部动作；插件只调 CLI、读场景视图与结果清单 | 拆解 `__init__.py` 为注册/场景高亮/后台作业 `RunJob`/回放；回放核对参考面、原始行号、静止坐标与连接（不再仅查顶点数） | [T-44](../tasks/T-44.md) |

**与当前原型代码的过渡差异**（实现切点）：
- 现行 `generate.py` 的 `build()` 把单组织模型、单段运动、FEBio 编号与 XML 绑死，且按本段有无驱动决定骨头固定或可动；第一刀由 [T-46](../tasks/T-46.md)/[T-47](../tasks/T-47.md) 切开。
- 现行 `asrp-scene/1` 用 `name` 当引用键且静默放过未知字段；新 `asrp-scene/2` 按稳定 ID 引用并由 JSON Schema 严格拒收未知可执行字段。
- 现行 `trajectory.py` 自动补第 0–14 帧沉降且只读嘴唇 900 个平移数与下颌（忽略眼周/额肌 2,700 个数，实验室 84 份运动中有 12 份只动眼或额头）；`motion` 模块按声明通道完整解析。
- 现行 `final_shape.py` 顶层导入 `scene` 绑死 Python 3.13 且仅出嘴唇；[T-52](../tasks/T-52.md) 抽离为独立 3.9 包 `asrp_query`。

---

## 3. 命令行入口全景

涉及存储库、会话或父状态的命令必须显式传入身份，不依赖宿主当前选中项。

### 现行已跑通命令（迁移期间保持兼容）

| 命令 | 用途 | 迁移去向 |
|---|---|---|
| `asrp doctor` | 查 FEBio、Blender、Python 与路径 | 长期保留 |
| `asrp check <scene> [trajectory]` | 校验 `asrp-scene/1` 与运动 | 迁移期保留，旧场景经适配器可读 |
| `asrp import-asset <export_dir> <out>` | 导入原型嘴唇资产（默认 `--tissue-settings lab`、`--attachments ours`、`--tetmesh 导出目录/../tetmesh/lips.json`） | 迁移期保留，全量包由 `import-bundle` 承接 |
| `asrp convert-motion` / `list-motions` / `set-motion-title` | 原型受限单段转换与运动列表管理 | 随 `motion` 模块扩展到非中性与全通道 |
| `asrp run <scene> <trajectory>` / `asrp run --feb <file.feb>` | 整段运行与直调底层执行器 | [T-47](../tasks/T-47.md) 通过两类补测后一次切到“新建会话→提交一段→导出”；`--feb` 长期保留 |
| `asrp compare <run_dir> <ziva_dir> --out <dir>` | 与 Ziva 逐帧对比、热力图与回放包 | 长期保留独立对照入口 |

### 地基新增命令（按任务卡落地）

| 任务卡 | 新增命令 |
|---|---|
| [T-44](../tasks/T-44.md) | `asrp scene inspect <rev> --store <dir>` · `asrp scene edit <rev> --store <dir> --patch <json>` · `asrp results inspect <results.json>` · `asrp results export-playback <results.json> --object <id> --surface <id> --layer <name> --out <dir>` |
| [T-45](../tasks/T-45.md) | `asrp import-bundle <bundle> --store <dir>` · `asrp scene inspect <rev> --store <dir> --edge <id>` |
| [T-46](../tasks/T-46.md) | `asrp build <rev> --store <dir> --profile <profile> --out <dir>` · 临时对比选项 `asrp run <scene> <motion> --candidate-build`（T-47 切换后移除） |
| [T-47](../tasks/T-47.md) | `asrp session create <rev> --store <dir> --profile <profile> --out <dir>` · `asrp session advance <session> --parent <state> --segment <file>` |
| [T-48](../tasks/T-48.md) | `asrp session checkout <session> --state <id>` · `asrp session advance … --branch <name> --expect <old-state>` · `asrp session replay <session> --state <id>` · `asrp session drop-cache <session>` |
| [T-49](../tasks/T-49.md)–[T-51](../tasks/T-51.md) | `asrp results read <results.json> --object <id> --surface <id> --layer <name> --frame <n> --out <file.npy>` · `asrp build inspect <build-record> --edge <id>` |
| [T-52](../tasks/T-52.md) | `asrp query export <rev> --store <dir> --out <dir>`（产出 `query.json` 静态数据，训练热循环直接进程内调 `asrp_query`） |

---

## 4. 与实验室代码的分界

| 环节 | 实验室原有（只读参考） | ASRP 承接方式 |
|---|---|---|
| 控制器优化、目标函数（距离/应变能/Hill 功）、LBS 梯度代理、钢琴界面、手指按压皮肤显示修正 | 实验室 Python 代码与数据 | **归实验室，我们不重写**；凡“替实验室决定 landmark 往哪走”的代码皆非产品 |
| 物理层（重力、下颌/颅骨驱动、粘连、多组织与皮肤动力学） | Ziva | `backends/febio` + `build` + `sessions`（输出 `physics` 层） |
| landmark 蒙皮叠加与已验证显示后处理 | Maya `skinCluster` | `results`（输出 `final` 层；未取得曲线绑定数据前不发布皮肤 `final`） |
| 训练每步无物理读取网格顶点 | Maya 读网格世界坐标 | 独立 Python 3.9 包 `asrp_query`（默认静止基底，输出 4 组 landmark 网格 + 下颌，输入输出保持实验室场景单位、Y 朝上） |
| 钢琴按键连续推进与回中性 | Maya 时间轴 + Ziva 缓存 | `sessions` 连续段续算（[T-47](../tasks/T-47.md)、[T-48](../tasks/T-48.md)）与中性根重新初始化 |
| 实验室脚本分析读数 | 脚本读顶点自算力/能量/体积 | `results` 按 `(状态, 对象, 表面 ID, 层, 帧)` 输出 float64 `.npy` 原序世界坐标 |

原型 v1 的完整 19 项实验室脚本逐条对照表保留在 [archive/prototype/04-v1-architecture.md](../archive/prototype/04-v1-architecture.md)。
