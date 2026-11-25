# ADR-37：原型机实现里自己定下的几条规矩

> **归档说明**：原型机 v1 实现细则，多条已由 [ADR-38](../../decisions/ADR-38.md) 与地基 [ADR-46](../../decisions/ADR-46.md)–[ADR-50](../../decisions/ADR-50.md) 细化或取代。

| 项目 | 内容 |
|---|---|
| **状态** | ✅ 已定（2026-11-11，[T-06a](../tasks/T-06a.md) PR #8 审查后；第 1、3、7 条由 [ADR-38](../../decisions/ADR-38.md) 改写，多条由 2026-11-24 地基 ADR 修订/补充） |
| **关联决策** | [ADR-15](../../decisions/ADR-15.md)、[ADR-30](../../decisions/ADR-30.md)、[ADR-38](../../decisions/ADR-38.md)、[ADR-41](../../decisions/ADR-41.md)、[ADR-46](../../decisions/ADR-46.md)、[ADR-48](../../decisions/ADR-48.md)、[ADR-49](../../decisions/ADR-49.md)、[ADR-50](../../decisions/ADR-50.md)、[ADR-52](../../decisions/ADR-52.md) |
| **相关文档** | [04 架构](../prototype/04-v1-architecture.md)（第 4、5.1、9 节）、[05 常见坑](../../05-febio-pits.md)（坑 17、18）、[07 验证](../../07-validation.md)（第 3 节） |

---

## 当前生效结论

以下按原条号列出各条的现行状态（并标明 2026-11-24 地基目标，尚未实现的部分按关联任务推进）：

1. **FEBio 线程数（已被 [ADR-38](../../decisions/ADR-38.md) 改写）**：默认不再是单线程，改为默认 4 线程；需要回放文件逐位相同时用 `asrp run --threads 1`（同时设 `OMP_NUM_THREADS` 和 `MKL_NUM_THREADS`，见 [ADR-38](../../decisions/ADR-38.md) 第 7 条）。
2. **合理性检查结果语义（2026-11-24 由 [ADR-50](../../decisions/ADR-50.md) 细化）**：
   - 现行有三种结果：`true`、`false`、`null`（没运行）；只有明确 `false` 算失败，整段运动算完 (a) 须为 `true`，没运行的写进运行报告的 `not_run`（[07](../../07-validation.md) 第 3 节）。
   - 地基目标细化为：硬门槛失败或必做检查缺失拒绝发布，按适用性声明的不适用项记原因但不签相应状态。
3. **沉降形状与检查 (c)（已由 [ADR-38](../../decisions/ADR-38.md) 改写，[ADR-49](../../decisions/ADR-49.md)/[ADR-50](../../decisions/ADR-50.md) 补充）**：
   - 原“第 14 帧”已改为运动文件的 `settle_until_frame`；仅当第 0 到沉降帧所有被用到的驱动源都停在静止位置时才写沉降形状并做检查 (c)，未写该键时两者都不做（补充 [ADR-30](../../decisions/ADR-30.md)，[ADR-38](../../decisions/ADR-38.md) 第 3 条）。
   - 2026-11-24 补充：非中性起步不签“已沉稳”，追加段不自动补沉降。
4. **缺帧不留结果（2026-11-24 由 [ADR-49](../../decisions/ADR-49.md)/[ADR-50](../../decisions/ADR-50.md) 升级）**：
   - 现行：整段运动未全部算完或日志缺帧时 (a) 失败，运行文件夹只写 `run_report.json`，不写位置、显示网格和回放包（[04](../prototype/04-v1-architecture.md) 第 4、9 节：绝不显示不完整或旧的结果）。
   - 地基目标升级为独立尝试目录加整目录原子发布，失败留诊断、父状态不受影响。
5. **命名与字符集（2026-11-24 分 v1/v2，[ADR-46](../../decisions/ADR-46.md)）**：
   - **v1（现行）**：名字兼作引用键，保留旧校验——软组织、骨头、锚、驱动源、连接的名字只能用 ASCII 字母、数字、`_`、`-`、`.`，不符合是错误；写入 FEBio 时另做 XML 转义（防 `&`、`<`、空格破坏输入，[04](../prototype/04-v1-architecture.md) 第 5.1 节）。
   - **v2（地基目标，[T-44](../../tasks/T-44.md)、[T-45](../../tasks/T-45.md)）**：稳定 ID 与显示名分开——稳定 ID 由核心生成、用 ASCII 安全字符，显示名允许 Unicode、空格及重名，引用按 ID，FEBio 里的标识由编号表生成，路径不直接拼显示名。
6. **没有粘连的骨头（2026-11-24 分原型/地基目标，[ADR-48](../../decisions/ADR-48.md)/[ADR-52](../../decisions/ADR-52.md)）**：
   - **原型（现行不变）**：没有粘连的骨头（嘴唇模型里的上下牙）不写进 FEBio（刚体没有碰撞，[05](../../05-ziva-to-febio.md) 第 1 节，不连任何东西不影响结果）。
   - **地基目标（[T-46](../../tasks/T-46.md)）**：三项分别判定——场景保留骨头身份，建造明确记录是否参与物理求解，声明输出面的给定运动刚体仍可按实际变换生成原序 `physics` 顶点（[ADR-52](../../decisions/ADR-52.md)）；已纳入物理建造的可驱动骨头首段无运动也预分配完整通道（[ADR-48](../../decisions/ADR-48.md)）；不能因无粘连就删掉研究员要读的手或下颌。
7. **派生驱动源（已由 [ADR-38](../../decisions/ADR-38.md) 改写并由 [ADR-41](../../decisions/ADR-41.md) 扩展）**：
   - 派生驱动源只在被用到时计算；现改为来源整个刚体运动的 `factor` 倍（转动向量和平移一起按比例缩），来源不需要铰链，“偏离纯转动”警告和 10⁻⁶ 阈值已去掉（[ADR-38](../../decisions/ADR-38.md) 第 6 条）；后由 [ADR-41](../../decisions/ADR-41.md) 扩展 `relative_to`。

---

## 依据与边界

- **来源**：本条记录原型机（[T-06a](../tasks/T-06a.md)）实现时在代码里定下的决定，此前只写在代码头部和 [09](../../09-roadmap-and-tasks.md) 的任务卡里。
- **原因**：写生成器和合理性检查时必须选定明确答案；不记下来，下一个人会按另一个答案改；原第 1 条对应 `R-06` 的 (a) 要求逐位相同，其余确保“算不完”、“没法判断”、“名字坏了”能说清楚而不是悄悄通过。
- **影响**：`src/asrp_core/febio.py`、`generate.py`、`simulate.py`、`plausibility.py`、`scene.py`。
  - 关联文档：[04](../prototype/04-v1-architecture.md) 第 4、5.1、9 节、[07](../../07-validation.md) 第 3 节、[05 常见坑](../../05-febio-pits.md) 坑 17、18。

---

## 历史与修订

- **2026-11-11 初定中被后续改写的原条款**：
  - 原第 1 条（单线程默认）：启动每个 FEBio 都带 `OMP_NUM_THREADS=1`（`febio.ENV`，记进溯源），确保同一 `.feb` 逐位重复、回放文件逐位相同（[ADR-15](../../decisions/ADR-15.md) 的 (a)）。
    - 代价为嘴唇 50 帧从 27 秒变成 45 秒（0.90 秒/帧，证据见 [05 常见坑](../../05-febio-pits.md) 坑 17）；同日被 [ADR-38](../../decisions/ADR-38.md) 改写为默认 4 线程。
  - 原第 3 条：原按“第 0 到 14 帧”判断沉降，同日被 [ADR-38](../../decisions/ADR-38.md) 改为 `settle_until_frame`。
  - 原第 7 条：嘴角锚原只取 `jaw01` 绕铰链转角，偏离纯转动超过 10⁻⁶ 时 `asrp check` 和运行报告打警告（[04](../prototype/04-v1-architecture.md) 第 5.1 节）；同日被 [ADR-38](../../decisions/ADR-38.md) 改写为 SE(3) 缩放并移除阈值。
- **初定时放弃的方案**：多线程运行（当时快 40% 但结果最后一位不重复，后在 [ADR-38](../../decisions/ADR-38.md) 改回默认 4 线程并定 1×10⁻⁹ mm 标准）；把 `null` 当失败（真实数据上“没有 hard 粘连”、“运动在第 14 帧前就开始”均合法）。

---

返回 [决策索引](../../10-decisions.md)
