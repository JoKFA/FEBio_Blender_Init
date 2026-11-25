# 00 现行生效设定与关键事实速查

给谁看：项目负责人、开发者（含每次从零读起的 AI 会话）和实验室研究员。
读完能知道：项目里**所有已经定下、正在生效的设定值、门限、基线实测和边界**，一眼看到数值、限定语和权威出处。

> **怎么读这页**：
> - 本页只收**项目级生效设定、物理/几何/验证参数与实测基线**，不堆代码内部实现常数，也不写会随改代码失效的裸行号（代码出处统一写 `模块 + 稳定符号/选项名`）。
> - 状态标记：**`[现行]`** = 已在当前代码运行生效；**`[地基]`** = 2026-11-24 已定设计，随 `T-43`–`T-52` 落地。
> - 改任何一个生效数值，必须同步更新本页与对应权威设计页（[08](08-engineering-standards.md) 第 7 节）。

## 目录

1. [求解线程数与复现标准](#1-求解线程数与复现标准) · 2. [FEBio 运行与求解设置](#2-febio-运行与求解设置) · 3. [材料与本构（我们 vs Ziva）](#3-材料与本构我们-vs-ziva) · 4. [单位、物理尺度、重力与帧率](#4-单位物理尺度重力与帧率) · 5. [嘴唇两套四面体网格](#5-嘴唇两套四面体网格) · 6. [粘连刚度、权重与实现边界](#6-粘连刚度权重与实现边界) · 7. [自动检查、合理性与对比门限](#7-自动检查合理性与对比门限) · 8. [实验室场景规模与运动计数](#8-实验室场景规模与运动计数) · 9. [Ziva 实测设置与对比基线](#9-ziva-实测设置与对比基线) · 10. [环境版本与验证门](#10-环境版本与验证门) · 11. [仓库边界（进仓 vs 禁提交）](#11-仓库边界进仓-vs-禁提交)

---

## 1. 求解线程数与复现标准

| 项目 | 生效值 | 限定语与说明 | 出处 |
|---|---|---|---|
| 默认求解线程 `[现行]` | **`4` 线程**（`asrp run --threads 4`） | 同时设 `OMP_NUM_THREADS` 与 `MKL_NUM_THREADS`；本机细网格实测最快（见下表） | [ADR-38](decisions/ADR-38.md) · `febio.py` `DEFAULT_THREADS` |
| 同环境复现门限 `[现行]` | **坐标差 `≤ 1×10⁻⁹ mm`**（默认 4 线程） | 同机同输入重跑及拷贝运行文件夹重跑均须满足；不比含时间戳的 `.log`；实测最大差 `1×10⁻¹⁰ mm` | [02](02-requirements.md) R-06 · [ADR-15](decisions/ADR-15.md) |
| 逐位相同复现 `[现行]` | **`--threads 1`** | 单线程同输入重复跑，回放文件逐位相同（实测节点坐标差约 `1×10⁻¹³ mm`）；单线程粗格子重跑日志坐标逐字节相同（单次观测） | [05 坑 17](05-febio-pits.md) · [E-23](archive/explanations/E-23.md) |
| 跨环境复现 `[现行]` | 容差**先量再定**（不要求逐位相同） | 换一台 Windows 电脑和目录仅凭运行文件夹重跑，由 [T-14](tasks/T-14.md) 验证 | [02](02-requirements.md) R-06 · [11](11-risks-and-questions.md) A-38 |
| 线程实测用时（细网格嘴唇 51 帧） | 1 线程 `56.2 s` · **4 线程 `26.8 s`** · 8 线程 `29.7 s` · 16 线程 `38.6 s` | 本机实测，只覆盖细网格 51 帧 | [02](02-requirements.md) N-07 · [ADR-38](decisions/ADR-38.md) |

---

## 2. FEBio 运行与求解设置

| 项目 | 生效值 | 限定语与说明 | 出处 |
|---|---|---|---|
| FEBio 版本与定位 `[现行]` | **FEBio `4.13.0`**（随 FEBio Studio 安装） | 查找顺序 `ASRP_FEBIO` → `PATH` → `Program Files`；显式配错报 error，未安装仅 warn；不入仓不转发 | [08](08-engineering-standards.md) §2 · `doctor.py` `febio_exe` |
| 启动选项 `[现行]` | **`-noconfig -silent`**（必加 `-noconfig`），`-i/-o/-p`、cwd 设 `.feb` 目录 | 防止用户个人配置文件污染结果；取消时终止整个进程树；路径须纯 ASCII | [ADR-11](decisions/ADR-11.md) · [05 坑 3/4](05-febio-pits.md) · `febio.py` |
| 成败判定 `[现行]` | 退出码 `0` **且**日志含带空格的 `N O R M A L   T E R M I N A T I O N` | 还要算到结束时间；三条缺一条就判失败，这时用日志里的 `E R R O R   T E R M I N A T I O N` 或 `failed to converge` 说明原因（中途报不收敛、缩步重算成功不算失败） | `febio.py` `read_failure` · `run.py` `execute` |
| 超时默认值 `[现行]` | `asrp run --timeout` **`3600` 秒**；`febio.run` 函数默认 **`600` 秒** | 防止细网格长运行被误杀，也防止求解器死锁挂起 | `cli.py` `--timeout` · `febio.py` `run` |
| 隐式动力学与数值阻尼 `[现行]` | `DYNAMIC`、广义 α；`solver.numerical_damping_rhoi` = **`0`**（默认，最强数值阻尼） | 无物理阻尼时调小 `rhoi` 易算崩；含离散弹簧且 `0 < rhoi < 1` 会额外衰减；`rhoi = −2` 为无数值阻尼 Newmark | [ADR-05](decisions/ADR-05.md) · [05](05-ziva-to-febio.md) §4 · [05 坑 2/19/20](05-febio-pits.md) |
| 物理阻尼 `[现行]` | `solver.damping` = **`0`** s⁻¹（默认），非零写 `mass damping` 体载荷 `f = −Cρv` | 归场景物理声明（与 `k` 无关）；FEBio 无 Rayleigh 刚度阻尼，**不建 Ziva 刚度阻尼 `0.001`** | [05](05-ziva-to-febio.md) §4 · [ADR-41](decisions/ADR-41.md) |
| 子步与缩步重试 `[现行]` | `substeps_per_frame` = **`1`**；`max_retries = 8`、`opt_iter = 10`、`dtmin = dt/256`、`dtmax = dt` | 步数 `(frames−1)×substeps`，步长 `1/fps/substeps`；中途缩步重算成功不算失败但记入报告 | [05](05-ziva-to-febio.md) §4 · `generate.py` · `simulate.py` |
| 帧间插值 `[现行]` / `[地基]` | 原型 `motion_between_frames` 默认 `linear`（可选 `smooth`）；**地基新会话默认分段线性**，旧整段平滑显式保留 | 每帧 1 步时两者相同；地基段提交后样本封存，追加绝不改写历史 | [05](05-ziva-to-febio.md) §4 · [ADR-54](decisions/ADR-54.md) |
| 静默误算警告当失败 `[现行]` | 孤立节点被删、无法解析数字变 0、空输入、未知非零通道（地基）均按错误拦截 | FEBio 遇到 `np.float64(0.1)` 或孤立节点会静默继续，必须前置或后置拦截 | [05 坑 16/18](05-febio-pits.md) · [architecture/sessions-and-results.md](architecture/sessions-and-results.md) |
| 壳单元类型 `[地基]` | **必须用 `ANS` 壳**，严禁 `EAS` 壳 | 实测 FEBio 4.13 的 `EAS` 壳在重启续算时崩溃（`ANS` 通过 70 节点及 8 组织组合门槛） | [05 坑 21](05-febio-pits.md) · [E-22](explanations/E-22.md) |
| 续算存档与 `Step` 规则 `[地基]` | 续算须复制校验父档至独立 `attempts/`，**严禁原地覆写父档**；多阶段整算每段均写 `Step` | 原地覆写重试实测 12 次里 11 次“正常结束”却错走到第 70 帧；顶层 `Control` 后跟普通 `Step` 会覆盖顶层 `Control` | [05 坑 24](05-febio-pits.md) · [ADR-49](decisions/ADR-49.md) · [E-23](archive/explanations/E-23.md) |

---

## 3. 材料与本构（我们 vs Ziva）

| 参数 | 我们当前默认（`--tissue-settings lab`） | 实验室 Ziva 实测（2026-11-12，43 个 zMaterial 全部相同） | 出处与限定语  |
|---|---|---|---|
| 本构模型 | **`neo-Hookean`** | **`StVK`**，抗压参数 `compressionResistance = 20000` | 已知差异，受压反应不同（[03](03-asset.md) §1.3 · [05](05-ziva-to-febio.md) §4）  |
| 杨氏模量 `E` | **`12 kPa`**（`0.012 MPa`） | **`12 kPa`**（`youngsModulus = 12`，`Exp = 3`） | 来源标 `lab_setting`（[05](05-ziva-to-febio.md) §1）  |
| 泊松比 `ν` | **`0.4`** | **`0.4`** | 来源标 `lab_setting`  |
| 密度 `ρ` | **`1060 kg/m³`**（`1.06×10⁻⁹ t/mm³`） | **`1060`**（体积保持项 `0`） | 来源标 `lab_setting`  |
| 皮肤布料属性 `[地基]` | 随 [T-51](tasks/T-51.md) 接入 ANS 壳验证 | `BaraffWitkinZiva`；拉伸刚度 `5.0`、弯曲刚度 `1.0`、面密度 `0.1` | 仅演示场景带 2 层皮肤（[03](03-asset.md) §1）  |
| 肌肉纤维 `zFiber` | 当前不建（应变能延至地基之后） | 18 个纤维（嘴唇上无）；静态激活全 `0`，2 个接非 Ziva 上游，方向未取到 | 实测静态值，全程激活与被动作用待 [D21](11-risks-and-questions.md)（[ADR-33](decisions/ADR-33.md)）  |

---

## 4. 单位、物理尺度、重力与帧率

| 项目 | 生效值 | 限定语与说明 | 出处 |
|---|---|---|---|
| 内部统一单位 `[现行]` | **`mm – N – MPa – s`**（质量单位 `t`，密度 `t/mm³`） | 仅在导入边界 `asset/coords.py` 换算一次；格式标记 `mm-N-MPa-s` | [ADR-04](decisions/ADR-04.md) · [02](02-requirements.md) N-01 |
| 几何换算 `mm_per_scene_unit` | **`0.962 mm / 场景单位`** | 与实验室控制器 `9.62×10⁻⁴ m/单位` 一致；固定顺序：先场景变换（已由导出器完成）→ 换单位 → 转轴 `(x,y,z)→(x,-z,y)` | [03](03-asset.md) §4 · [ADR-16](decisions/ADR-16.md) · [ADR-31](decisions/ADR-31.md) |
| 物理长度尺度 `k` (`physics_length_scale`) | **`0.67`**（来源：我们定的） | FEBio 坐标 `= 几何毫米 × k`，读回 `÷ k`；按真人大小（颅骨 `216.6→145 mm`）设定；**只缩放长度，物理参数不缩放** | [ADR-22](decisions/ADR-22.md) · [ADR-31](decisions/ADR-31.md) · [ADR-36](decisions/ADR-36.md) |
| Ziva 求解器缩放（第三种尺度） | 三轴均为 **`100`**（`zSolverTransform`） | 🔍 **推断未核实**：100 Maya 单位 ≈ 1 m；与 `0.962` 及 `k = 0.67` 均不同，待 [D18](11-risks-and-questions.md) 校准 | [03](03-asset.md) §4 · [05](05-ziva-to-febio.md) §2 |
| 重力加速度与符号 `[现行]` | **`9810 mm/s²`**，物理方向 `-z`；**写入 FEBio 必反号** | 常量加载（`t = 0` 立即施加，无斜坡）；Ziva 设 `−9.8`（单位未核实 🔍） | [ADR-10](decisions/ADR-10.md) · [05 坑 1](05-febio-pits.md) |
| 帧率与沉降帧 `[现行]` | **`30 fps`**；实验室与代用运动默认 `settle_until_frame = 14` | 第 `0–14` 帧纯重力沉降，运动从第 `15` 帧起；第 14 帧仅用于回放对照，**不是**控制器训练底 | [03](03-asset.md) §3 · [ADR-30](decisions/ADR-30.md) · [ADR-38](decisions/ADR-38.md) |

---

## 5. 嘴唇两套四面体网格

两套网格均由 `tools/build_tetmesh.py` 离线生成一次并提交（格式 `asrp-tetmesh/1`），运行时由 `tetmesh.load` 校验 SHA-256 只读加载，**严禁运行时启动 fTetWild 或在缺失时悄悄回退**（[ADR-20](decisions/ADR-20.md)、[ADR-44](decisions/ADR-44.md)、[ADR-47](decisions/ADR-47.md)）。

| 属性 | 粗格子 `data/tetmesh/lips_lattice.json` | 细网格 `data/tetmesh/lips.json` |
|---|---|---|
| 定位与默认入口 | **Blender 面板默认**（配 `--attachments ziva-soft`），模拟 Ziva 粗四面体行为 | **CLI `import-asset` 默认**（`导出目录/../tetmesh/lips.json`，配 `--attachments ours`） |
| 生成方式与关键参数 | 确定性规则格子，步长 **`25.368 mm`**（对应 Ziva `tetSz = 26.37` × `0.962`），`kind = lattice` | fTetWild（`ATTEMPTS = 6`），包络 **`0.12 mm`**、目标边长 **`25.4 mm`** |
| 规模与质量 | **`224` 节点 / `126` 四面体**；不沿唇缝切开（上下唇共用节点） | **`6,747` 节点 / `26,721` 四面体**；最小二面角 `10.4°`、最小体积 `0.0043 mm³`、总体积 `64,752.8 mm³`；单连通流形、亏格 `3`、上下唇分离 `99%`、左右对称差 `0` |
| 显示点嵌入情况 | 规则格子包裹显示网格 | `10,240` 顶点中 `65%`（`6,674`）在四面体外，`95%` 距 `< 0.07 mm`，最远 `0.93 mm`；静止重建误差 `7×10⁻¹⁴ mm` |
| 原型运行特点 | 单次实测 `3.3–3.6 s`（[T-42](tasks/T-42.md) 第 5 项）；嘴只张一条缝，上唇跟动 `4.8–5.6 mm`；检查 (b) 为 `NOT RUN` | 单次约 `30 s`；上下唇分开运动，上唇中点仅动 `0.15 mm` |

---

## 6. 粘连刚度、权重与实现边界

### 原型兼容配置（`legacy-v1`，单嘴唇 4 组共 807 个不重复顶点，权重全为 `1.0`）

| 组别 | 顶点数 | `--attachments ours`（CLI 默认） | `--attachments ziva-soft`（面板粗格子默认，`k=0.67`） |
|---|---:|---|---|
| 上唇 → 颅骨 `zAttachment1` | 74（按稀疏默认 `1.0`） | `hard`（并入颅骨刚体） | `spring`：`0.105 N/mm`（均面积 `2.339 mm²`） |
| 下唇 → 下颌 `zAttachment2` | 76（显式 `1.0`） | `spring`：基础刚度 `100 × E × h`（`E=12 kPa` 时 `1.94 N/mm`） | `spring`：`0.113 N/mm`（均面积 `2.526 mm²`） |
| 左嘴角 `zAttachment9` | 348 | `spring`，连嘴角锚（`α = 0.5`，同上基础刚度） | `spring`：`0.0407 N/mm`（均面积 `0.907 mm²`） |
| 右嘴角 `zAttachment10` | 309 | `spring`，连嘴角锚（`α = 0.5`，同上基础刚度） | `spring`：`0.0431 N/mm`（均面积 `0.960 mm²`） |

- **弹簧防零长规则 `[现行]`**：每计算点 3 根沿世界轴偏出 `δ` 的弹簧（`δ = 5 × 四面体边长中位数 × k`，细网格嘴唇 `8.10 mm`）；滑移比 `max|u|÷δ > 0.1` 标 `FLAG`（不自动重算，改 `delta` 仅在 `generate.build` 参数中可用）；刚度按对数分档使档内误差 `≤ 2%`（`SPRING_LEVEL_TOLERANCE`）；导入后手改 `E` **不得**重算旧弹簧刚度（[ADR-48](decisions/ADR-48.md)）。
- **显示点到四面体保护 `[现行]`**：任一显示点距嵌入四面体超过 `2.0 × 四面体边长中位数`（`MAX_DISTANCE_EDGES`）直接拒跑。

### 地基多物体长间距粘连（`[地基]`，[ADR-51](decisions/ADR-51.md)、[architecture/build-and-attachments.md](architecture/build-and-attachments.md)）

- **逐点弹性刚度**：`k_i = K×A×w×e`（`K = 0.1 N/mm³`，物理面积 `A = 几何面积 × k²` 只换算一次，不跨边合并刚度）。
- **可变形目标优先候选**：目标四面体局部仿射外推参考点 + `<Constraints>` 纯罚 `linear constraint`，**必须显式写 `<laugon>0</laugon>` 和 `<rhs>0</rhs>`**（省略 `<laugon>` 无警告变硬，[05 坑 25](05-febio-pits.md)）；反力在求解器外重建（[05 坑 26](05-febio-pits.md)）；可选同边同支撑组 QR 合并（`k* = 1 N/mm`，最多 8 行/轴，尚未进 FEBio 实跑）；Ziva 参考点规律待 [D21](11-risks-and-questions.md) 实测。
- **粘连阻尼**：Ziva 实测 `0.01`，尚无经验证 FEBio 换算，弹性试验明标“未施加粘连阻尼”。

---

## 7. 自动检查、合理性与对比门限

| 检查 / 门限 | 生效标准 | 说明与出处 |
|---|---|---|
| 导出与导入精度 `[现行]` | `.mb` 对 OBJ `≤ 0.001` 场景单位；导入坐标换算误差 `< 0.001 mm`；下颌前后尺寸 `150.0 mm` | `tools/check_lab_export.py` · `tests/test_asset.py` · [07](07-validation.md) §2 |
| 输入正交与权重容差 `[现行]` | 蒙皮权重和、下颌旋转矩阵正交性、刚体轨迹矩阵误差均 `≤ 1×10⁻⁶`；第 0 帧静止误差 `≤ 1×10⁻⁹` | `skinning.py` · `final_shape.py` · `trajectory.py` · [05](05-ziva-to-febio.md) |
| 合理性 (a) 整段完成 `[现行]` | **必须 `true`**，无最终失败帧（中途缩步成功不算失败） | `plausibility.py` · [07](07-validation.md) §3 |
| 合理性 (b) `hard` 粘连 / (b2) 弹簧锚 `[现行]` | 逐帧相对刚体误差 **`< 0.001 mm`**（无 `hard` 组时 (b) 为 `null / NOT RUN`，不算失败） | `plausibility.py` · [07](07-validation.md) §3 |
| 合理性 (c) 重力沉降 `[现行]` | 自由顶点下移，末 5 帧均值在估计值 `ρ·|g|·k·L²/(2E)` 的 **`÷10` 到 `×10`** 之间 | 仅抓大错和重力反号，非精度证明（[ADR-38](decisions/ADR-38.md) · [07](07-validation.md) §3） |
| 合理性 (d) 四面体有效 `[现行]` | 整段每帧每四面体 `有向体积 / 静止体积 > 0` | 任一 `≤ 0` 立即失败（[07](07-validation.md) §3） |
| 末 10 帧晃动 `[代码缺口]` | **当前运行报告未实现**（相近只报告项为 `return_to_settled` 与 `relative_to_head`） | 见 [07](07-validation.md) §3（交负责人定补写或删要求） |
| 显示面健康参照线 `[现行]` | 只报告翻转面数与短边数（不设通过线），与 Ziva 并排（Ziva AA 物理 `0` 翻面，最终最多 `4`、末帧 `3`、短边 `37`） | [ADR-43](decisions/ADR-43.md) · [07](07-validation.md) §3 |
| 回放与训练接口精度 `[现行]` | Blender 回放误差 `< 0.001 mm`；`asrp compare` 回放包回读 `≤ 1×10⁻⁴ mm`；训练接口复现 145 份存档 `< 0.0001 mm`（实测最坏 `0.000007 mm`） | `check_playback.py` · `ziva_compare.py` · [E-13](explanations/E-13.md) |
| Ziva 对比与廉价对照 `[现行]` | 与 Ziva **不设数值合格线**（[ADR-17](decisions/ADR-17.md)）；每次物理验收须同时跑**下颌直线对照**，跑不过它的运动不算物理证据 | [07](07-validation.md) §4 |
| 地基骨头预分配迁移门限 `[地基]` | 固定骨改给定零位移后，同环境坐标差 **`≤ 1×10⁻⁹ mm`**（已单模型实测 `1.5×10⁻¹⁰ mm`，切换前须补两类用例） | [ADR-48](decisions/ADR-48.md) · [architecture/build-and-attachments.md](architecture/build-and-attachments.md) |

---

## 8. 实验室场景规模与运动计数

| 项目 | 带皮肤演示场景（Ziva 参考来源） | 不带皮肤训练场景（`g10-10`） | 说明与出处 |
|---|---:|---:|---|
| 软组织 `zTissue` / `zTet` | **41**（表面共 `117,302` 顶点，每块 `254–13,448`；`tetSize` `3.3–51.8` 场景单位） | **26** | [03](03-asset.md) §1 |
| 布料皮肤 `zCloth` | **2**（`47,142` 与 `15,905` 顶点，中位边长 `1.6 / 2.6 mm`） | **0** | 演示与按压/甩头脚本用带皮肤族 |
| 骨头 `zBone` | **10**（仅 `3` 块参与粘连；共 `193,257` 顶点） | **4** | 原型用 4 块（颅骨/下颌/上下牙） |
| 粘连 `zAttachment` | **140**（组织→骨 `42`、组织→组织 `36`、皮肤→骨 `22`、皮肤→组织 `40`） | **60** | 演示场景 `49` 条渐变边全以皮肤为源（`19` 皮肤→骨、`30` 皮肤→组织）；`12` 对多边网格中 **`8` 对**顶点重叠；`29%` 顶点离别的目标更近 |
| 纤维 `zFiber` / 材料 `zMaterial` | **18** / **43** | **18** / **26** | Ziva 节点类型仅用 `11` / `10` 种（共 23 种） |
| 嘴唇与 landmark | 嘴唇 `10,240` 顶点 / `20,480` 三角面；`300` 个 `oor` landmark（全脸 4 组共 `1,200`） | 同嘴唇与 4 组 | 下颌场景坐标 z 向尺寸 `155.92`（导入后 `150.0 mm`）；`jaw01` 枢轴 `(0.00, -121.71, -54.65) mm` |
| 实验室运动文件 `.pkl` | 过渡表 `167` 条 → `161` 目录 → `97` 条有文件 → **`84` 文件（`82` 份不同）**，每帧 **`3,603`** 数 | — | `46` 份动下颌（最大转角 `0.37°–6.65°`，中位 `2.3°`，90 分位 `5.2°`）；`12` 份只动眼或额头；AA 为 `22` 步、下颌 `−5.16°`（[03](03-asset.md) §3 · [E-23](archive/explanations/E-23.md)） |
| 嘴周真实切片（[T-50](tasks/T-50.md)） | `11` 组织 + `2` 骨 + `22` 边（约 `3,800` 参与顶点，规则格子约 `600` 节点上限） | — | [03](03-asset.md) §1 |

---

## 9. Ziva 实测设置与对比基线

| 实测项 | 数值 | 口径与限定语 | 出处 |
|---|---|---|---|
| Ziva 求解设置（实测） | 每帧 `1` 子步、牛顿最多 `5` 次、30 fps、`BackwardEuler`、`Direct`、刚度阻尼 `0.001`、质量阻尼 `0`、碰撞关 | 源码注释写“全质量子步 2”，以场景实测为准；整张脸 AA 子步 2 对 1 差 `0.165 mm`（沉降）/ `0.075 mm`（运动） | [03](03-asset.md) §5 · [E-11](explanations/E-11.md) |
| Ziva 求解速度（实验室 16 核机） | 整张脸平均每步 **`1.47–1.60 s`**（单步有 `>3 s`）；只留嘴唇每步 **`0.0095 s`** | 纯求解日志；含写文件导出为整张脸 `2.55 s/帧`、只留嘴唇 `1.03 s/帧`（不混用）；Ziva 实际线程数未量 | [02](02-requirements.md) N-07 · [E-15](archive/explanations/E-15.md) |
| Ziva 实际求解的规模（估算） | 41 块组织按各自 `tetSize` 估约 **`2,143` 点 / `4,452` 四面体**；两层皮肤 **`63,047`** 个顶点 | 按我们的实测规律：软组织约 `0.2–0.3 s/步`；皮肤照 Ziva 分辨率约 `7–8 s/步`（外推）；用粗的计算网格则合计 `1 s` 以内（推算，没有实测） | [E-22](explanations/E-22.md) |
| AA 第 36 帧对 Ziva 整张脸（物理层） | **粗格子：平均 `1.88` / 最大 `5.12 mm`**；**细网格：平均 `2.21` / 最大 `7.64 mm`** | 全部 `10,240` 嘴唇顶点；物理尺度未对齐前只报差别不解释原因（[15](15-prototype.md) 为绑定源） | [15](15-prototype.md) · [E-19](13-explanations.md) · [E-20](explanations/E-20.md) |
| Ziva 整张脸 vs Ziva 只留嘴唇 | 第 36 帧平均 `1.98` / 最大 `7.98 mm`（第 14 帧平均 `1.51` / 最大 `5.09 mm`） | 关掉其余 42 个物体的整体影响（边界条件不同，不代表求解器差异） | [07](07-validation.md) §4 · [E-15](archive/explanations/E-15.md) |
| 前 14 帧重力下垂（全部顶点平均 / 最大） | Ziva 整张脸 `0.29 / 1.2 mm`；Ziva 只留嘴唇 `1.78 / 5.39 mm`（未停稳）；我方原型细网格 `0.122 / 0.497 mm`（12 kPa，[15](15-prototype.md) 第 3.3 节的表） | Ziva 只留嘴唇第 14 帧仍在下落（相邻帧差 `0.365 mm`），停稳值待 [D17](11-risks-and-questions.md) | [07](07-validation.md) §4 · [11](11-risks-and-questions.md) §4 |
| 甩头晃动幅度（全部顶点最大） | Ziva 整张脸 **`2.731 mm`**（停后第 14 帧首次 `<0.04 mm`，第 28 帧持续）；我方单嘴唇 `0.121 mm`（原默认 `0.094 mm`） | 跨范围（Ziva 仅动颅骨与下颌、另 8 块骨未动）；我方到 16 子步仍未收敛（[T-33](tasks/T-33.md)），仅并排不作幅度结论 | [09](09-roadmap-and-tasks.md) · [E-19](13-explanations.md) |
| 来回 10 次（Ziva 整张脸） | 物理层每次回中性 `≤ 0.049 mm`（不累积）；蒙皮后每圈多偏 `0.524 mm`（第 10 圈 `5.238 mm`） | 蒙皮漂移来自运动文件去回程开环相加不为零，非物理层问题 | [02](02-requirements.md) · [E-11](explanations/E-11.md) |
| 训练查询计时（本机 Python 3.13） | 内存热查询 **`3.1–3.6 ms`**，载入 **`219–272 ms`**，起空 CLI 子进程约 **`275 ms`** | 仅测本机 3.13 + 嘴唇 `10,240` 点；实验室 Maya Python 3.9 与 5 输出耗时待 [D22](11-risks-and-questions.md) | [architecture/sessions-and-results.md](architecture/sessions-and-results.md) · [E-23](archive/explanations/E-23.md) |

---

## 10. 环境版本与验证门

| 组件 | 生效要求 | 说明与出处 |
|---|---|---|
| 操作系统 / 路径 | **Windows 11**；求解器看到的路径**必须纯 ASCII** | FEBio 对非 ASCII 路径可能失败（[08](08-engineering-standards.md) §2） |
| Python / 依赖管理 | 核心 **Python `3.13`**（匹配 Blender 5.2），用 **`uv`** 管理；`asrp_query` 独立包守 **Python `3.9`** 兼容线（仅标准库 + 兼容 NumPy，禁导 `asrp_core`） | `pyproject.toml` · [ADR-53](decisions/ADR-53.md) |
| Blender / FEBio | **Blender `5.2.x LTS`**（插件 manifest 最低写 `4.2.0`，未在 4.2 实测）；**FEBio `4.13.0`** | [08](08-engineering-standards.md) §2 · `blender_manifest.toml` |
| 版本号同步位置 | `pyproject.toml`、`blender_manifest.toml`、`src/asrp_core/__init__.py` 三处保持一致（现 `0.0.1`） | [08](08-engineering-standards.md) §8 |
| 验证门分级 | `--level docs`（~10 s，不跑 `test_lab_facts.py`）→ `--level core`（~3 min）→ `full` 不带参（6 min+，合并前唯一定义）；`--level auto` 仅用于开发过程 | `tools/verify.py` · [08](08-engineering-standards.md) §5 |

---

## 11. 仓库边界（进仓 vs 禁提交）

| 类别 | 策略 | 范围与出处 |
|---|---|---|
| 产品、测试、文档与派生数据 | ✅ **提交私有仓库**（`JoKFA/FEBio_Blender_Init`） | `src/`、`blender_addon/`、`tests/`、`tools/`、`docs/`、`data/lab_export/`、`data/preview/`、`data/tetmesh/`（`data/briefing/` 已在 `T-38` 移出，[ADR-19](decisions/ADR-19.md)） |
| 哈希文件检出保护 | ✅ **`.gitattributes` `-text`** | `data/` 与 `tests/fixtures/` 按字节检出，防 `core.autocrlf` 破坏哈希（[08](08-engineering-standards.md) §8） |
| 实验室原始材料与保密件 | ❌ **绝不提交，不外发** | `assets/`（`.mb`/`.ma`）、`runs/`、`.pkl`/`.abc`/`.f32`/`.zbuilder`/`.mll`/`.lic`、实验室论文与录像、实验室控制器源码（只读不拷，[ADR-28](decisions/ADR-28.md)）、FEBio 安装包 |
| 本机配置与过程文件 | ❌ **绝不提交** | `.local/`、`ziva_trip_pointer.json`、`AGENTS.md`、`CLAUDE.md`、`.claude/`（由 `tools/check_no_lab_files.py` 拦）；`spikes/` 与已移出的一次性文件（由 `tests/test_one_off_files_gone.py` 拦）；带日期工作计划（靠规矩，没有检查） |
