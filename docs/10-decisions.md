# 10 决策记录

给谁看：项目负责人、开发者和 AI 开发会话。
读完能知道：现在必须遵守的架构与工程铁律是什么、哪些旧决定已被修订或归档，以及每条独立决策文件在哪里。
**怎么读**：开工前只读下面的“现行铁律速查”；只有需要查某条决定的依据、放弃方案或重开条件时，才点开对应的 `decisions/ADR-xx.md`。

---

## 现行铁律速查（按主题分组）

> 提示：[ADR-46](decisions/ADR-46.md)–[ADR-54](decisions/ADR-54.md) 是 2026-11-24 收敛的技术决定；其中面向实验室的 3 项过目清单集中在 [11](11-risks-and-questions.md) 第 1 节与 [E-23](archive/explanations/E-23.md)。

### 一、地基架构核心（2026-11-24 收敛，主线必守）

- **先打稳地基、宿主开放（[ADR-45](decisions/ADR-45.md)）**：先在实验室原本用 Ziva 的方式下替代物理层，核心长期演进不推翻重写；优先 Blender，Maya 保留为可选宿主。
- **场景版本库（[ADR-46](decisions/ADR-46.md)）**：场景归 `scene` 管理，按规范化清单 SHA-256 定版，`blobs/` 共享大文件；`.blend` 只存 `store_id` + 版本与状态引用；对外发只读**场景视图**；已发布版本首版不自动删除。
- **建造与网格（[ADR-47](decisions/ADR-47.md)）**：建造配置独立于场景，不可变**建造记录**封存网格、绑定、粘连与编号表；细网格离线生成锁哈希禁运行时调 fTetWild，规则格子可在建造时生成并封存。
- **骨头预分配与旧嘴唇兼容（[ADR-48](decisions/ADR-48.md)）**：纳入建造的可驱动骨头首段即分配完整通道（首段未动给零位移，不留兼容开关，回归门限 `1e-9 mm`）；两种旧嘴唇共用 `legacy-v1`，改材料不重算旧弹簧。
- **会话状态树与原子提交（[ADR-49](decisions/ADR-49.md)、[ADR-50](decisions/ADR-50.md)）**：状态与可删 `.dmp` 缓存分目录，每次尝试独立目录禁原地覆写父档，整目录原子发布；`checks` 算判定、`sessions` 执行提交，Ziva 对照独立签收。
- **粘连三层表达与候选做法（[ADR-51](decisions/ADR-51.md)）**：场景声明 / 逐点对应 / 后端记录三层贯通，按边独立积分 `k = K·A·w·e`（物理面积）不跨边合并；可变形目标先用仿射外推 + 纯罚线性约束（必写 `<laugon>0</laugon>`），可选后端 QR 合并，逐点模式作裁判。
- **结果层与训练查询（[ADR-52](decisions/ADR-52.md)、[ADR-53](decisions/ADR-53.md)）**：公开结果层只有 `physics` 与 `final`，按 `(状态, 对象, 表面 ID, 层, 帧)` 读原序坐标；训练查询独立打包为 Python 3.9 可进程内调用的 `asrp_query`（默认静止基底，五输出）。
- **段界插值（[ADR-54](decisions/ADR-54.md)）**：新会话默认分段线性，旧整段平滑显式保留，样本提交即封存，追加不改写历史。

### 二、长期工程与物理铁律

- **选型与架构隔离（[ADR-01](decisions/ADR-01.md)–[ADR-03](decisions/ADR-03.md)、[ADR-12](decisions/ADR-12.md)、[ADR-14](decisions/ADR-14.md)、[ADR-19](decisions/ADR-19.md)、[ADR-28](decisions/ADR-28.md)）**：物理用 FEBio、界面优先 Blender、求解与界面严格隔离；文档是唯一依据；托管于私有仓库 `JoKFA/FEBio_Blender_Init`；`data/lab_export/`、`data/preview/`、`data/tetmesh/` 可进私仓，原始 `.mb`/论文/录像/实验室源码绝不进仓（源码只读不拷）。
- **单位、重力与尺度（[ADR-04](decisions/ADR-04.md)、[ADR-10](decisions/ADR-10.md)、[ADR-16](decisions/ADR-16.md)、[ADR-22](decisions/ADR-22.md)、[ADR-31](decisions/ADR-31.md)、[ADR-36](decisions/ADR-36.md)）**：统一 `mm–N–MPa–s`；导入固定顺序“先场景变换 → 换单位 `0.962` → 转轴”；写 FEBio 时重力反号且坐标按 `k = 0.67` 缩放到真人大小（读回 `÷ k`，物理参数不缩放）。
- **物理机制与接口口径（[ADR-05](decisions/ADR-05.md)、[ADR-08](decisions/ADR-08.md)、[ADR-21](decisions/ADR-21.md)、[ADR-29](decisions/ADR-29.md)、[ADR-30](decisions/ADR-30.md)、[ADR-33](decisions/ADR-33.md)、[ADR-41](decisions/ADR-41.md)）**：用隐式动力学；只有骨头完整刚体变换进物理，landmark 在物理后叠加；控制器训练不推进物理、以静止形状作底；质量阻尼归场景参数（默认 0）；应变能延至地基之后作诊断。
- **复现、线程与验证（[ADR-11](decisions/ADR-11.md)、[ADR-15](decisions/ADR-15.md)、[ADR-17](decisions/ADR-17.md)、[ADR-23](decisions/ADR-23.md)、[ADR-25](decisions/ADR-25.md)、[ADR-38](decisions/ADR-38.md)、[ADR-43](decisions/ADR-43.md)）**：FEBio 必加 `-noconfig`；默认 4 线程（坐标差 `≤ 1e-9 mm`），`--threads 1` 逐位相同；不设对 Ziva 数值合格线，附目标距离/下唇跟随/表面健康参照线与网格敏感性报告。
- **两套嘴唇四面体网格（[ADR-20](decisions/ADR-20.md)、[ADR-44](decisions/ADR-44.md)）**：细网格 `lips.json`（fTetWild 包络 `0.12 mm`）与粗格子 `lips_lattice.json`（规则格子 `25.368 mm`，126 四面体）均离线生成锁哈希；粗格子不切开唇缝，在 AA 上上唇都被带动了（4.8–5.6 mm），整体对 Ziva 整张脸为平均 1.88–2.19 mm（细网格口唇分离，原型 AA 12.1 mm、9.3 mm、27.0 mm 与 0.4 mm 等对比细节见 [ADR-44](decisions/ADR-44.md) 与 [15](15-prototype.md)）。

### 三、读旧决策时的覆盖提示

| 旧条 | 现行状态与覆盖去向 |
|---|---|
| [ADR-07](decisions/ADR-07.md) / [ADR-16](decisions/ADR-16.md) / [ADR-18](decisions/ADR-18.md) | 场景变换移至本机 Maya 导出时完成；全量静态包导入由 [ADR-46](decisions/ADR-46.md) 承接 |
| [ADR-09](decisions/ADR-09.md) | PC2 保留为派生回放格式；正式结果层与身份核对以 [ADR-52](decisions/ADR-52.md) 为准 |
| [ADR-19](decisions/ADR-19.md) | `data/briefing/` 已在 `T-38` 移出仓库，现提交仅剩 `lab_export/`、`preview/`、`tetmesh/` |
| [ADR-20](decisions/ADR-20.md) / [ADR-32](decisions/ADR-32.md) / [ADR-36](decisions/ADR-36.md) | 嘴唇单组织细网格与 `ours`/`ziva-soft` 规则归入 `legacy-v1` 兼容配置，地基新场景按 [ADR-47](decisions/ADR-47.md)、[ADR-48](decisions/ADR-48.md)、[ADR-51](decisions/ADR-51.md) |
| [ADR-30](decisions/ADR-30.md) / [ADR-33](decisions/ADR-33.md) | 训练底为静止形状（非沉降帧），接口升级为 `asrp_query`（[ADR-53](decisions/ADR-53.md)）；应变能延至地基后 |

---

## 生效决策总索引（43 条，`docs/decisions/`）

### 地基架构决策（10 条）

| 编号 | 决策 | 日期 |
|---|---|---|
| [ADR-45](decisions/ADR-45.md) | 先打地基：在实验室原本用法下替代 Ziva 物理层；Blender 与 Maya 均为宿主选项 | 2026-11-16 |
| [ADR-46](decisions/ADR-46.md) | 场景归 `scene` 管理，按内容摘要定版并共享大文件，已发布版本首版保留 | 2026-11-24 |
| [ADR-47](decisions/ADR-47.md) | 建造配置独立；不可变建造记录封存有效选择与实际网格 | 2026-11-24 |
| [ADR-48](decisions/ADR-48.md) | 建造时预分配可动骨头通道；旧嘴唇沿用存量刚度与回归门限 | 2026-11-24 |
| [ADR-49](decisions/ADR-49.md) | 会话维护状态树，独立尝试目录，整目录发布，`.dmp` 为可清缓存 | 2026-11-24 |
| [ADR-50](decisions/ADR-50.md) | `checks` 计算判定，`sessions` 执行提交规则，Ziva 对照独立签收 | 2026-11-24 |
| [ADR-51](decisions/ADR-51.md) | 粘连三层表达，逐点保边与力臂；可变形目标先试仿射外推纯罚约束，合并放后端 | 2026-11-24 |
| [ADR-52](decisions/ADR-52.md) | 核心公开 `physics` 和 `final` 两层，按对象、表面 ID 和生产者区分数据 | 2026-11-24 |
| [ADR-53](decisions/ADR-53.md) | 训练查询独立打包为 Python 3.9 可调用的 `asrp_query`，默认静止基底 | 2026-11-24 |
| [ADR-54](decisions/ADR-54.md) | 新会话段默认分段线性，旧整段平滑显式保留，提交后样本封存 | 2026-11-24 |

### 核心工程、物理与验证决策（33 条）

| 编号 | 决策 | 状态注 |
|---|---|---|
| [ADR-01](decisions/ADR-01.md) | 物理计算用 FEBio | 持续生效 |
| [ADR-02](decisions/ADR-02.md) | 操作和显示用 Blender | 持续生效（ADR-45 补充 Maya 可选） |
| [ADR-03](decisions/ADR-03.md) | 求解在独立程序运行，靠文件交换数据 | 由 ADR-46/52 升级契约 |
| [ADR-04](decisions/ADR-04.md) | 单位统一为 `mm–N–MPa–s` | 持续生效 |
| [ADR-05](decisions/ADR-05.md) | 用动力学分析，不用准静态 | 持续生效 |
| [ADR-07](decisions/ADR-07.md) | 产品数据来自开放格式，`.mb` 只用来核对 | 导出分工以 ADR-18 为准 |
| [ADR-08](decisions/ADR-08.md) | landmark 作为物理之后的蒙皮层 | 由 ADR-29 确认、ADR-52 归 `final` |
| [ADR-09](decisions/ADR-09.md) | 结果回放用“表面网格 + 点缓存” | PC2 为派生回放，契约见 ADR-52 |
| [ADR-10](decisions/ADR-10.md) | 写入 FEBio 时重力反号 | 持续生效 |
| [ADR-11](decisions/ADR-11.md) | FEBio 一律加 `-noconfig` 运行 | 持续生效 |
| [ADR-12](decisions/ADR-12.md) | 以文档为唯一依据协作 | 持续生效 |
| [ADR-14](decisions/ADR-14.md) | 代码托管于 GitHub 私有仓库 | 持续生效 |
| [ADR-15](decisions/ADR-15.md) | 复现标准是“坐标一致”而非“文件一致” | 线程门限以 ADR-38 为准 |
| [ADR-16](decisions/ADR-16.md) | 导入顺序：先套变换 → 换单位 → 转坐标轴 | 变换已移至导出阶段（ADR-18） |
| [ADR-17](decisions/ADR-17.md) | 目标是让实验室继续研究，非逐点复刻 Ziva | 持续生效 |
| [ADR-18](decisions/ADR-18.md) | 本机 Maya 只作迁移工具；Ziva 机只做离不开 Ziva 的事 | 持续生效 |
| [ADR-19](decisions/ADR-19.md) | 私有仓库可存派生数据（`lab_export`/`preview`/`tetmesh`） | `data/briefing/` 已移出 |
| [ADR-20](decisions/ADR-20.md) | 嘴唇细网格用 fTetWild 紧包络生成一次并提交 | 由 ADR-44/47 扩展 |
| [ADR-21](decisions/ADR-21.md) | 骨头运动为每帧完整刚体变换 | 由 ADR-48 补通道预分配 |
| [ADR-22](decisions/ADR-22.md) | 几何单位与物理尺度分开 | `k` 取值与写法见 ADR-31/36 |
| [ADR-23](decisions/ADR-23.md) | 网格敏感性报告只报告不设通过线 | 持续生效 |
| [ADR-25](decisions/ADR-25.md) | 验收增加不依赖 Ziva 的指标（目标距离与下唇跟随） | 持续生效 |
| [ADR-28](decisions/ADR-28.md) | 实验室源码只读参考，是事实依据 | 持续生效 |
| [ADR-29](decisions/ADR-29.md) | 源码与实测确认：仅下颌转动进物理 | 持续生效 |
| [ADR-30](decisions/ADR-30.md) | 控制器优化时物理不在环，默认静止基底 | 接口升级为 `asrp_query`（ADR-53） |
| [ADR-31](decisions/ADR-31.md) | 物理尺度取真人大小（`k = 0.67`） | 持续生效 |
| [ADR-32](decisions/ADR-32.md) | 嘴唇四组粘连读法与嘴角锚近似 | 归 `legacy-v1`；多物体见 ADR-51 |
| [ADR-33](decisions/ADR-33.md) | Hill 肌肉力归控制器目标；应变能延至地基后作诊断 | 持续生效 |
| [ADR-36](decisions/ADR-36.md) | 坐标按 `×k` 写入 FEBio；嵌入四面体用于粘连 | 第 1 条持续；第 2 条归 `legacy-v1` |
| [ADR-38](decisions/ADR-38.md) | 4 线程默认、`settle_until_frame`、沉降估计公式与报告规矩 | 持续生效（部分由 ADR-47–52 扩展） |
| [ADR-41](decisions/ADR-41.md) | 甩头驱动源、相对头嘴角锚与场景级质量阻尼 | 持续生效 |
| [ADR-43](decisions/ADR-43.md) | 回放表面质量参照线（不比 Ziva 差，只报告） | 持续生效（ADR-50 延续） |
| [ADR-44](decisions/ADR-44.md) | 嘴唇粗格子与细网格并存 | 持续生效（ADR-47 纳入建造） |

---

## 已归档决策索引（11 条，`docs/archive/decisions/`）

以下旧决策已被完全取代或已完成原型期历史使命，原文原样保留：

| 编号 | 标题 | 归档原因 / 接替去向 |
|---|---|---|
| [ADR-06](archive/decisions/ADR-06.md) | 原型直接用实验室资产 | 原型已交付；地基通过 `scene` 版本兼顾实验室与新模型（ADR-46） |
| [ADR-13](archive/decisions/ADR-13.md) | 早期下唇粘连方案 | 已被 [ADR-32](decisions/ADR-32.md) 取代 |
| [ADR-24](archive/decisions/ADR-24.md) | 参考数据集范围扩大 | 已被 [ADR-35](archive/decisions/ADR-35.md) 精简并完成首轮采集 |
| [ADR-26](archive/decisions/ADR-26.md) | FEBio 选型复核关 | 2026-11-16 过关并保留 FEBio；速度预算见 [02](02-requirements.md) N-07 |
| [ADR-27](archive/decisions/ADR-27.md) | 方案 A 绑定强度参数化 | 已被 [ADR-32](decisions/ADR-32.md) 与 [ADR-51](decisions/ADR-51.md) 接替 |
| [ADR-34](archive/decisions/ADR-34.md) | M1 留下的选择 | 原型过渡选择，已被 [ADR-46](decisions/ADR-46.md)–[ADR-51](decisions/ADR-51.md) 接替 |
| [ADR-35](archive/decisions/ADR-35.md) | 2026-11-12 上机清单 | 首轮上机已完成；下次待取清单位于 [12](12-lab-export-checklist.md) |
| [ADR-37](archive/decisions/ADR-37.md) | 原型机实现小规矩 | 多条已由 [ADR-38](decisions/ADR-38.md) 与地基 [ADR-46](decisions/ADR-46.md)–[ADR-50](decisions/ADR-50.md) 取代 |
| [ADR-39](archive/decisions/ADR-39.md) | 下一个目标是原型机二 | 原型机二已交付；甩头验收口径待决项在 [11](11-risks-and-questions.md) `P-09` |
| [ADR-40](archive/decisions/ADR-40.md) | 早期 AA 拼法选择 | 已被 [ADR-42](archive/decisions/ADR-42.md) 退役取代 |
| [ADR-42](archive/decisions/ADR-42.md) | 正式 AA 用真实运动、退役甲乙拼法 | 旧拼法已于 2026-11-15 清理完毕；实测口径见 [00](00-current-settings.md) 与 [15](15-prototype.md) |
