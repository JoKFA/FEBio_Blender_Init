# 05 Ziva 到 FEBio 的物理对应

给谁看：写或改 FEBio 模型生成器的开发者。
读完能知道：Ziva 的每类节点在 FEBio 里怎么表达、单位与物理尺度 `k` 怎么换算、旧嘴唇（`legacy-v1`）与地基长间距粘连各怎么实现，以及求解与物理阻尼设置。

> **关联文档**：27 条实测踩坑速查在 **[05-febio-pits.md](05-febio-pits.md)**；地基多物体粘连三层规范在 **[architecture/build-and-attachments.md](architecture/build-and-attachments.md)**；现行参数总表在 [00](00-current-settings.md)；原型期 T-07 / T-37 / T-06a 详细试验流水账原样归档在 [archive/prototype/05-v1-attachment-trials.md](archive/prototype/05-v1-attachment-trials.md)。
> **目标（[ADR-17](decisions/ADR-17.md)）**：搬运模型的物理结构与力学机制，而非逐点复刻 Ziva。

---

## 1. Ziva 到 FEBio 对应总表

状态：✅ 已实测验证 · 🔶 方案已定待实测 · ⏳ 地基/后续接入。

| Ziva 节点 / 概念 | 新系统表达（FEBio 4.13） | 状态与要点 |
|---|---|---|
| **zTissue**（软组织） | 四面体网格 + 弹性材料 | ✅ 嘴唇已跑通；拉伸/悬挂方块与理论差 `≤ 0.5%`（`tests/test_generate.py`） |
| **zTet**（四面体设置） | 细网格离线 fTetWild 生成提交（`lips.json`）；规则格子确定性生成（`lips_lattice.json` 或建造封存） | ✅ [ADR-20](decisions/ADR-20.md)、[ADR-44](decisions/ADR-44.md)、[ADR-47](decisions/ADR-47.md) |
| **zMaterial**（材料） | `neo-Hookean`（默认 Ziva 实测 `12 kPa / 0.4 / 1060 kg/m³`，`--tissue-settings ours` 为 `15 kPa / 0.45`） | 🔶 数值一致，本构不同（Ziva 为 `StVK` + `compressionResistance 20000`） |
| **zBone**（骨头） | FEBio 刚体：固定（`rigid_fixed`）或每帧完整刚体变换（平移 + 旋转向量） | ✅ S1 误差 `4×10⁻⁹ mm`，斜轴加平移跟住 `< 10⁻⁶ mm`（`test_a_plate_turning_about_a_tilted_axis_and_moving_is_followed`）；地基预分配全通道（[ADR-48](decisions/ADR-48.md)） |
| **zAttachment**（粘连） | 原型 `legacy-v1` 用硬绑或三向偏移弹簧；地基多物体可变形目标用仿射外推纯罚 `linear constraint` | ✅ 原型已跑通；🔶 地基合成 9 项已过，正式入口在 [T-49](tasks/T-49.md)–[T-51](tasks/T-51.md) |
| **zEmbedder**（嵌入） | 显示顶点按重心坐标绑定四面体（外部顶点按最近边界四面体外推，`embed.py`） | ✅ 嘴唇 65%（6,674 点）在体网格外、最远 `0.93 mm`，静止差 `7×10⁻¹⁴ mm`（`test_embedded_lips_at_rest_equal_the_lip_mesh`） |
| **landmark 蒙皮（`skinCluster7`）** | **不进 FEBio**；只有 `jaw01` 进物理，物理后纯几何叠加 `base + weights @ translations`（`skinning.py`） | ✅ 实测还原误差 `0.000016 mm`（[ADR-29](decisions/ADR-29.md)） |
| **zCloth**（皮肤） | **ANS 薄壳单元**贴附实体（**严禁 EAS 壳**，重启会崩，[05 坑 21](05-febio-pits.md)） | 🔶 8 组织 + ANS 壳门槛通过（[E-22](explanations/E-22.md)）；真实皮肤小片见 [T-51](tasks/T-51.md) |
| **碰撞** | 不建接触 | ✅ Ziva 实测全部关闭 |
| **zFiber**（肌肉纤维） | 当前不建主动收缩（实验室静态激活全 0）；每组织应变能延至地基后作诊断 | ⏳ [ADR-33](decisions/ADR-33.md) |
| **zSolver**（求解器） | 隐式动力学 `DYNAMIC`、广义 α、30 fps、每帧 1 子步（见第 4 节） | ✅ / 🔶 见第 4 节差异表 |

---

## 2. 单位换算与物理尺度 `k`

内部统一 **毫米（mm）、牛顿（N）、兆帕（MPa）、秒（s）**（质量单位吨 `t`），仅在导入时换算一次：
- `1 cm = 10 mm` · `12 kPa = 0.012 MPa` · `1060 kg/m³ = 1.06×10⁻⁹ t/mm³` · `9.81 m/s² = 9810 mm/s²`。

**几何单位与物理尺度分开（[ADR-22](decisions/ADR-22.md)、[ADR-31](decisions/ADR-31.md)、[ADR-36](decisions/ADR-36.md)）**：
- `units.mm_per_scene_unit = 0.962`：几何毫米换算（与控制器一致；模型为真人 ~1.5 倍）。
- `units.physics_length_scale (k) = 0.67`：将物理尺寸缩放到真人大小（颅骨 `216.6 → ~145 mm`）。
- **只缩放坐标、不缩放物理参数**：写入 FEBio 时所有节点坐标、刚体枢轴与弹簧端点乘 `k`，材料/重力/弹簧刚度（N/mm）保持真实物理值，读回位移除以 `k`（物理面积为 `几何面积 × k²`，且只换算一次）。`k = 1` 时 `.feb` 逐字节一致。
- **已验证**：悬挂杆 `k = 1, 2` 理论差 `0.22% / 0.43%`（比值 `2.004`）；弹簧方块 `k = 1, 2` 差 `< 1%`（`tests/test_generate.py`、`tests/s3_attachment.py`）。
- **与 Ziva 尺度边界**：Ziva 另有三轴缩放 `100` 的求解器变换（🔍 推断未核实），待 [D18](11-risks-and-questions.md) 校准；此前不拿尺度差异解释误差。

---

## 3. 粘连做法（`legacy-v1` 现行实现 vs 地基 v2）

### 3.1 地基多物体长间距粘连（主线，详见 [architecture/build-and-attachments.md](architecture/build-and-attachments.md)）

- 实验室 140 条粘连多隔着 `3–30+ mm`，含 49 条皮肤渐变权重边与 8 对重叠顶点网格，不能按组平均面积或退回 `tied-elastic`（[ADR-51](decisions/ADR-51.md)、[E-24](explanations/E-24.md)）。
- 粘连按**场景声明 / 逐点对应 / 后端记录**三层贯通，按边独立积分 `k_i = K × A_i × w_i × e_i`（`K = 0.1 N/mm³`，物理面积 `A_i`）；可变形目标先用“目标四面体局部仿射外推 + 纯罚 `linear constraint`（必写 `<laugon>0</laugon>`）”，可选后端 QR 合并，刚体偏心约束另验。

### 3.2 原型嘴唇兼容做法（`legacy-v1`，[ADR-32](decisions/ADR-32.md)、[ADR-48](decisions/ADR-48.md)）

旧嘴唇场景共用 `legacy-v1` 建造配置，保持原有四组粘连（共 807 顶点、权重全 1.0，周围肌肉与皮肤暂不建）：
- **`--attachments ours`（CLI 默认，细网格）**：上唇 74 点 `hard` 并入颅骨；下唇 76 点与两侧嘴角 348/309 点用 `spring`，基础刚度 `100 × E × h`（`E=12 kPa` 时 `1.94 N/mm`，导入时一次算定，手改 `E` 不重算）；嘴角连至旋转比例 `α = 0.5` 的派生锚刚体（`α ± 0.2` 敏感度达 `4.79 mm`）。
- **`--attachments ziva-soft`（Blender 面板粗格子默认）**：四组全为 `spring`，刚度 `= 0.1 N/mm³ × 组平均顶点面积 × k²`（`k=0.67` 时上唇 `0.105`、下唇 `0.113`、左/右嘴角 `0.0407 / 0.0431 N/mm`；粗格子上下唇共用节点不能用 `hard`）。

**计算点映射与三向偏移弹簧规则（`generate.py` 实现）**：
1. 每个显示点复用显示嵌入四面体的 4 个计算点；`hard` 取并集并入刚体（显示点精跟骨头，`8.4×10⁻¹¹ mm`）；同计算点冲突时留 `hard` 丢弹簧并计数，两不同刚体 `hard` 冲突报错。
2. **禁止零长度弹簧**（零长度弹簧无方向，刚度 `≥ 0.1 N/mm` 不收敛）：**每个节点三根弹簧**，沿世界 x/y/z 轴向锚点偏出 **`δ = 5 × 四面体边长中位数 × k`**（细网格嘴唇 `8.10 mm`）。
3. **滑移报警**：`asrp run` 报告各组 `max|u|÷δ`，超 **`0.1`** 标 `FLAG`（**不会自动重算**，要人加大 `δ` 重跑；当前仅可在 `generate.build(delta=...)` 调整，CLI 无此选项）。
4. **节点权重分配**：`刚度 = 基础刚度 × Σ w_v · λ̂_vj`，其中 `λ̂ = (λ̃ + 1/4) / 2`（四角各至少分到顶点权重的 `1/8`，防体网格外点某角为 `0`，确保 `K → ∞` 收敛到 `hard`）；对数分档使档内误差 `≤ 2%`（`SPRING_LEVEL_TOLERANCE`）。
5. **最大距离保护与边界**：任一显示点距嵌入四面体超四面体边长中位数的 **2 倍**（`MAX_DISTANCE_EDGES`）报错拒跑；第 0 帧非静止（误差 `> 10⁻⁹`）拒跑；无粘连骨头在原型不写进 FEBio（[ADR-37](archive/decisions/ADR-37.md) 第 6 条；地基按 [ADR-48](decisions/ADR-48.md) 决定）。

---

## 4. 求解设置与物理阻尼

| 设置 | 我方 FEBio 默认 | 与 Ziva 实测（[03](03-asset.md) §5）差异 |
|---|---|---|
| 分析类型 / 帧率 / 子步 | `DYNAMIC` · 帧率 `30 帧/秒`（时间步长 `1/30 s`）· `solver.substeps_per_frame = 1` | 一致（Ziva 源码注全质量 2，实测 1；整脸 AA 子步 2 对 1 差 `0.165 / 0.075 mm`） |
| 牛顿迭代与时间积分 | 广义 α · `BFGS` · 自动缩步（`max_retries = 8`、`dtmin = dt/256`） | Ziva 为 `BackwardEuler`、`Direct`、牛顿迭代最多 5 次 |
| 帧间运动插值 | 原型默认 `linear`（可选 `smooth`）；地基新会话默认分段线性（[ADR-54](decisions/ADR-54.md)） | 每帧 1 步时两者相同；Ziva 帧内曲线未量 |
| 重力 | `9810 mm/s²` 常量体载荷，**写入反号**（[05 坑 1](05-febio-pits.md)） | Ziva 为 `−9.8`（单位未核实 🔍，待 D18） |
| 物理与数值阻尼 | `solver.damping = 0`（质量阻尼）· `numerical_damping_rhoi = 0`（最强数值阻尼） | 质量阻尼同为 0；**FEBio 无刚度阻尼，不建 Ziva 的 `0.001`** |
| 材料与粘连 | `neo-Hookean` `12 kPa / 0.4 / 1060`；原型默认上唇 `hard` | Ziva 为 `StVK`（抗压 `20000`）与全软粘连 |

- **物理阻尼写法（FEBio `doc/` 手册 `type="mass damping"` 体载荷，非 `dyn_damping`）**：`<body_load name="damping" type="mass damping"><C>45.0</C></body_load>`（`f = −Cρv`，单位 `s⁻¹`，与 `k` 无关）；`solver.damping` 为 0 时不写，`.feb` 逐字节相同。
  - 硬方块 4 弹簧对理论验证（`spikes/t28_damped_cube.py`，周期 `0.1 s`、阻尼比 `0.05` 即 `C = 6.283/s`、步长 `1/600 s`，用无数值阻尼 `Newmark`：`rhoi = −2`、`β 1/4`、`γ 1/2`）：无阻尼周期差 `+0.091%`（≤2% ✅），阻尼衰减率差 `−0.27%`（≤10% ✅），无阻尼与 `C/10` 对照均判败；另测底面固定的软方块衰减率差 `−9.6%`（每周期约 10 采样点，🔍 推断源于采样粗）。
- **甩头时间步收敛现状（[T-33](tasks/T-33.md)）**：每帧 1–16 步相邻档最大差 `37%–194%`（未达 `5%` 门限）；`rhoi = −2`、C = 45 时每帧 1/2 步头不动对照也不衰减（`0.36 / 0.17 mm`），甩头幅度与衰减暂只作并排参考。
- **全部 27 条实测踩坑**：统一维护在 **[05-febio-pits.md](05-febio-pits.md)**，改生成器前必查。
