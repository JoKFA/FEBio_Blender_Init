# ADR-38：审计后的小修：运行报告、检查和线程数

| 项目 | 内容 |
|---|---|
| **状态** | ✅ 已定（2026-11-11；2026-11-12 修订第 3 条与补记第 10 条；2026-11-13/24 状态与地基补充） |
| **关联决策** | 第 6 条经 [ADR-41](ADR-41.md) 扩展；第 3、7、8、10 条由 [ADR-47](ADR-47.md)–[ADR-50](ADR-50.md)、[ADR-52](ADR-52.md) 补充 |
| **相关文档** | [04 架构](../archive/prototype/04-v1-architecture.md)（第 4、5.1、5.2 节）、[05 常见坑](../05-febio-pits.md)（坑 17）、[07 验证](../07-validation.md)（第 2、3、4 节）、[E-08](../archive/explanations/E-08.md) |

---

## 当前生效结论

来源：本条记录审计（[E-08](../archive/explanations/E-08.md) 第 1 到 6、9、14、15 条，及第 16 条在 [15](../15-prototype.md) 上的答案）之后的一批小修；项目负责人 2026-11-11 接受了审计顺序，排在最前。

1. **运动文件写自己的来源**：`asrp-trajectory/1` 加可选键 `source_tag`，取值与场景参数同一套三个：`lab_setting`、`ziva_default`、`ours`（别的值是错误）；报告运动行来源取它，没写记 `unstated`，不再从说明文字猜。代用运动工具写 `ours`。
2. **模型专属说明放进场景**：`asrp-scene/1` 加可选 `simplifications`（非空字符串列表，空不写）；导入器写入原写死的三句说明，运行报告的 `simplifications`（取代 `attachments_not_built`）照抄场景列表，场景没写则为空列表，所以方块场景的报告里不再出现嘴唇的说明。
3. **沉降帧由运动文件说明**：`asrp-trajectory/1` 加可选整数 `settle_until_frame`（0 ≤ n < 帧数；n 是只有重力的沉降的最后一帧，第 0 到 n 帧所有被用到的驱动源均停在静止位置）。
   - 满足且 n > 0 时写 `physics/settled_frame{n}.json` 和 `.obj`，检查 (c) 用第 `max(1, n−4)` 到 n 帧（不含第 0 帧，2026-11-12 修订；n = 0 时检查 (c) 与沉降形状都不做，`simulate.SETTLE_FRAMES`）。
   - 提前动或未写该键时不写沉降形状、(c) 没运行（未写时原因写“运动文件没说沉降到哪一帧”）；`settled_shape` 多一项 `frame`（无则 `null`）；代用运动写 14；常量 `SETTLED_FRAME` 和 `SAG_FRAMES` 去掉。
   - 2026-11-24 地基补充：迁入独立模块 `checks`，按对象和段用途声明适用性，非中性起步不签“已沉稳”（[ADR-49](ADR-49.md)、[ADR-50](ADR-50.md)）。
4. **检查 (c) 范围按模型估计**：预期下垂（几何毫米）= ρ·|g|·k·L² ÷ (2E)（ρ 和 E 是软组织的密度和杨氏模量，|g| 是场景重力的长度，k 是物理尺度），L 为“无粘连自由显示顶点”到“最近被抓住（权重 > 0）显示顶点”的最大静止直线距离（几何毫米）。
   - 通过标准：估计值 ÷ 10 ≤ 实测平均下垂 ≤ 估计值 × 10；无粘连或无自由顶点仍“没运行”；去掉固定范围 `SAG_RANGE_MM`，报告写入估计值、L 与范围。
5. **运行报告不把单组织耗时与全脸预算并排**：去掉 `SPEED_BUDGET_S_PER_FRAME`、`budget_s_per_frame`、`budget_note` 和命令行“budget 2.5”，耗时照报（全脸暂定预算见 [02](../02-requirements.md) `N-07` 和 `Q12`）。
   - 2026-11-13/24 状态：Ziva 只留嘴唇速度已实测（[E-15](../archive/explanations/E-15.md)）；[T-34](../archive/tasks/T-34.md)（✅ 2026-11-13）已把速度表放进对比报告，未放进运行报告。
     - 详见 `tools/ziva_comparison.py` 的 `speed` 及 [T-34](../archive/tasks/T-34.md) 卡（做法第 6 步和输出一节）。
6. **派生驱动源取整个刚体运动的一部分**（经 [ADR-41](ADR-41.md) 增加 `relative_to`）：
   - 对来源每帧变换 T 取 exp(factor·log T)（SE(3) 指数/对数：转动向量 w，θ = |w|，V = I + (1−cosθ)/θ²[w]× + (θ−sinθ)/θ³[w]×²，u = V⁻¹t；结果转动 exp(factor·w)，平移 V(factor·w)·(factor·u)；θ < 10⁻⁸ 取 V = I）。
   - 绕铰链的纯转动，结果仍是绕同一个铰链转 `factor` × 角度，和以前一样；三个轴都转的下颌也能算，来源不需铰链，去掉“不是纯转动”警告、`hinge_deviation` 和 10⁻⁶ 阈值；相对静止转 π 或更多的帧仍拒绝。
7. **FEBio 默认 4 线程**：`febio.DEFAULT_THREADS = 4`，同时设 `OMP_NUM_THREADS` 和 `MKL_NUM_THREADS`，取 min(要求的, 本机核数)，`asrp run --threads N` 可改，实际线程记入溯源（`febio_env`）。
   - 复现标准：默认重跑每点每帧坐标差不超过 1×10⁻⁹ mm；`--threads 1` 回放文件逐位相同，和以前一样，要求逐位相同的测试用 1 线程。
   - 2026-11-24 地基补充：线程数与求解环境由会话锁定，旧场景迁移仍守 `1e-9 mm` 并分别记录 1 线程与默认线程（[ADR-47](ADR-47.md)、[ADR-48](ADR-48.md)）。
8. **运行报告加“网格健康”**（整段算完时）：
   - 检查 (d)“四面体网格保持有效”：每帧每四面体有向体积 ÷ 静止体积，有 ≤ 0 即不通过，报最小体积比及帧、最大体积比、翻转四面体数（各帧相加）和有翻转帧数。
   - 只报告不判通过的 `return_to_settled`：沉降形状存在时，第 n 帧后所有被用到驱动源回到静止（10⁻⁹ 内）的帧上，四面体节点离第 n 帧最大和平均距离，无则 `{"frames": []}`。
   - 2026-11-24 地基补充：网格健康迁入 `checks`（[ADR-50](ADR-50.md)）。
9. **真实嘴唇运行进验证门**：`tools/verify.py` 带 `ASRP_SLOW=1` 跑测试，`tests/test_prototype.py` 每次都跑（全文件最多两次真实嘴唇运行，重跑按第 7 条 1×10⁻⁹ mm 标准）。
10. **结果存成 `.npy` 数组，日志不再装坐标**（[T-25](../archive/tasks/T-25.md)，2026-11-12 补记）：
    - `.feb` 将节点位置写进 `positions.txt` 而不进 `model.log`；算完存成 `physics/positions.json`（`asrp-positions/2`）+ `positions.npy`（float64，帧 × 节点 × 3，几何毫米）。
    - 显示网格同样存成 `display.json`（`asrp-display/2`）+ `display.npy`，再删 `positions.txt`；进度只读日志新增部分；保留 12 位有效数字，回放包逐字节相同（[04](../archive/prototype/04-v1-architecture.md) 第 4 节）。
    - 2026-11-24 地基补充：float64 `.npy` 加 JSON 头纳入按对象、参考表面、结果层（`physics`/`final`）与绝对帧索引的结果清单（[ADR-52](ADR-52.md)）。
11. **[15](../15-prototype.md) 的数字由程序从存档报告生成**：`tools/prototype_numbers.py` 写数字表，`tests/test_prototype_page.py` 在表与报告不一致时让验证门失败。

---

## 关键证据与影响

- **线程实测（全项目唯一线程表）**：`spikes/audit_threads.py`（原型机 `.feb`，50 步）：1 线程 56.2 秒，4 线程 26.8 秒，8 线程 29.7 秒，16 线程 38.6 秒；4 线程比 1 线程最多差 1×10⁻¹⁰ mm（存档参考运行自己的用时另见 [15](../15-prototype.md) 第 3 节）。
- **下垂估计验证**（真实嘴唇，k = 0.67）：L = 25.05 mm（9,433 自由顶点、807 被抓住），估计 0.146 mm，实测平均 0.0952 mm（比值 0.65，对应悬臂杆平均下垂约 2/3）。
  - E 乘 10 实测 0.0106 mm、E 除以 10 实测 0.93 mm（即实测与 1/E 成正比，和估计一致）；原固定范围在 E 乘 10 时曾把正确运行误判失败（[E-08](../archive/explanations/E-08.md) 第一个实验）。
- **回到沉降起点**：来回 10 次运行里回到起点离第 14 帧 0.004 mm（[E-08](../archive/explanations/E-08.md)），原型机 `return_to_settled` 在第 50 帧约 0.004 mm。
- **第 10 条数组存储实测**（FEBio 4.13，4 线程，参考运行存档在 `data/preview/`）：
  - 原型机 51 帧：运行文件夹 82 MB → 45 MB，`model.log` 20 MB → 0.15 MB；大头为 `display.npy` 12.0 MB、`positions.npy` 9.4 MB、`playback.pc2` 6.0 MB，输入约 15 MB（含 4 MB 蒙皮权重 JSON）。
  - 事后处理 3.7 秒 → 1.0 秒（1 线程前后对比每个显示顶点差恰好 0，`playback.pc2` 逐字节相同）。
  - 来回 10 次（375 帧）：文件夹 618 MB → 220 MB，事后处理 24 秒 → 4.9 秒，漂移的数字没变（闭合帧离第 14 帧 4.129×10⁻³ mm），张开峰值差在 1.5×10⁻¹⁰ mm 内，无翻转四面体。
  - **未达原“小一个数量级”目标**：[T-25](../archive/tasks/T-25.md) 原验收要求小一个数量级以上未达到（float64 数组为文本一半），但日志降至 0.15 MB、解析时间少四分之三、进度读取不再随日志变长。
- **2026-11-11 验证门实测**：`uv run python tools/verify.py` 309 个测试通过、1 个跳过，约 3 分 54 秒（含真实嘴唇运行）；`.claude/verify.json` 的 Stop 钩子超时由 240 秒提至 600 秒。
- **影响**：
  - 核心：`src/asrp_core/` 的 `trajectory.py`、`scene.py`、`asset/lab.py`、`simulate.py`、`plausibility.py`、`febio.py`、`generate.py`、`run.py`、`cli.py`；
  - 插件与工具：`blender_addon/`（`playback.json` 按 UTF-8 读）、`tools/verify.py`、`tools/prototype_numbers.py`、`tools/placeholder_jaw_motion.py`、`tests/test_prototype_page.py`；
  - 文档：[02](../02-requirements.md) `R-06`/`N-07`、[04](../archive/prototype/04-v1-architecture.md) 第 4、5.1、5.2 节、[05 常见坑](../05-febio-pits.md) 坑 17；
  - 另涉 [07](../07-validation.md) 第 2、3 节、[T-06b](../tasks/T-06b.md)、[术语表](../glossary.md)。

---

## 历史与修订

- **原因摘要**：
  - 1、2、4、5 把只属于一个场景或一次运行的东西写成了常量，现消除硬编码；3 把第 14 帧交还运动文件（它是实验室运动的约定，不是我们代码的常数）；
  - 6 应对三轴转动下颌（原 [03](../03-asset.md) 第 13.2 节，见 [03 实验室源码](../03-lab-source.md)），只取一个轴的转角会丢掉其余的运动；
  - 7 避免单线程为第 10 位小数付出一半速度代价；8 补足盲区：(b)/(b2) 按做法必然成立（节点并进了刚体），现有检查查不出网格坏掉；
  - 9 真实数据上的回归要每次都跑才有用；10 消除 51 帧 75 MB 文本坐标及每 0.1 秒重读整份日志；11 防止手抄数字与报告脱节。
- **放弃的方案**：(a) 派生驱动源继续只取铰链转角或球面插值加平移线性插值（04 原预案）；(b) 检查 (c) 继续固定范围；(c) 默认 8 或 16 线程（比 4 线程慢，见上线程实测）；(d) 第 10 条用 float32（破坏 1×10⁻⁹ mm 复现标准）或压缩 `.npz`（同数压缩字节未必相同导致哈希变化）。
- **2026-11-12 修订（第二轮审计）**：原第 3 条写成“第 max(0, n−4) 到 n 帧”，代码实际为第 `max(1, n−4)` 到 n 帧（不含第 0 帧：它是静止姿态，不是沉降后的位置）。
  - 且 n = 0 时检查 (c) 和沉降形状都不做（`simulate.SETTLE_FRAMES`，[04](../archive/prototype/04-v1-architecture.md) 第 5.2 节、[07](../07-validation.md) 第 3 节）。
- **2026-11-13 状态更新**：Ziva 只留嘴唇速度实测为 Maya 求解器日志最后 46 行平均每步 0.0095 秒（连写文件导出每帧 1.03 秒，[E-15](../archive/explanations/E-15.md)）。
  - 一块组织的耗时现在有数可比：是同一种时间（每步的求解时间），但边界条件和问题规模不同（关掉其余组织的敏感性实验，[07](../07-validation.md) 第 4 节），由 [T-34](../archive/tasks/T-34.md) 决定是否入运行报告（后确定入对比报告）。

---

返回 [决策索引](../10-decisions.md)
