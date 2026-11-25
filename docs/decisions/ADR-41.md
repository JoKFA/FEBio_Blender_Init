# ADR-41：甩头的地基：头的驱动源、相对头的嘴角锚、阻尼做成场景参数

| 项目 | 内容 |
|---|---|
| **状态** | ✅ 已定（2026-11-12，[T-28](../archive/tasks/T-28.md)；2026-11-24 第 1、3 条由地基 ADR 部分修订，待实现） |
| **关联决策** | 第 1、3 条由 [ADR-47](ADR-47.md)、[ADR-48](ADR-48.md)、[ADR-49](ADR-49.md) 部分修订 |
| **相关文档** | [04 架构](../archive/prototype/04-v1-architecture.md)（第 4、5.1 节）、[05 Ziva→FEBio](../05-ziva-to-febio.md)（第 4 节）、[05 常见坑](../05-febio-pits.md)（坑 19、20）、[E-11](../explanations/E-11.md) |

---

## 当前生效结论

1. **头的驱动源 `head`（原型现行 vs 地基目标）**：
   - **现行（[T-28](../archive/tasks/T-28.md)）**：头为驱动源 `head`，颅骨和上牙跟着走，标 `absent_means_rest`（运动文件不写它时头停在静止，颅骨按固定骨头写进 FEBio，兼容只写 `jaw01` 的代用张嘴、AA、来回 10 次旧运动文件；只对标了的驱动源这样，别的驱动源缺运动仍是错误）。
   - **2026-11-24 地基目标修订（尚未实现，[T-46](../tasks/T-46.md)、[T-47](../tasks/T-47.md)）**：声明为可驱动且已纳入物理建造的骨头（含颅骨）不再因本段未给驱动而写成固定。
     - 从第一段起分配完整通道、首段无驱动给定零运动（[ADR-48](ADR-48.md)）；会话追加段省略已声明通道表示保持父末值而非回静止（[ADR-49](ADR-49.md)）。
2. **嘴角的锚相对头**：派生驱动源加可选 `relative_to`，T = T_head · exp(α · log(T_head⁻¹ · T_jaw))（[04](../archive/prototype/04-v1-architecture.md) 第 5.1 节）；头不动时结果逐位等于以前的公式。
3. **阻尼与求解器参数归属（原型现行 vs 地基目标）**：
   - **质量阻尼**：`solver.damping`（单位 s⁻¹，写成 FEBio 的 “mass damping” C，1/秒；0 什么都不写）仍是进入物理方程的场景物理参数；演示场景默认 0（与 Ziva 质量阻尼 0 一致）。地基目标下改它生成新场景版本、建造封存生效值（[ADR-47](ADR-47.md)）。
   - **Ziva 刚度阻尼不建（2026-11-24 状态）**：Ziva 实测刚度阻尼 0.001、质量阻尼 0（[03](../03-asset.md) 第 5 节、[E-11](../explanations/E-11.md)）；[T-37](../archive/tasks/T-37.md) 第 3 项定为不建。
     - FEBio 没有和刚度成正比的阻尼（[05](../05-ziva-to-febio.md) 第 4 节），不在场景也不在 FEBio 输入里，导入器说明和导入报告已写明（`src/asrp_core/asset/lab.py:109`、`:422-423`）。
   - **数值阻尼与每帧子步**：现行 `solver.numerical_damping_rhoi` 不写时取生成器 0，每帧子步数为场景参数（默认值均未改）；2026-11-24 地基目标（[ADR-47](ADR-47.md)）将数值阻尼 `rhoi` 和每帧子步默认值移出场景参数，归会话求解设置（旧场景已有数值按旧优先级迁入并留来源）；粘连阻尼另归各条粘连边。
4. **物理阻尼方块理论验证**：周期差 +0.091%，衰减率差 −0.27%，两个对照都按要求不过（[05](../05-ziva-to-febio.md) 第 4 节，`data/preview/t28_damped_cube.json`）。
5. **原未知嘴唇阻尼已核实**：见第 3 条 Ziva 实测状态（2026-11-12 时未知，等 `D6`）。

---

## 依据与边界

- **向后兼容证据**：代用张嘴、单线程，改代码前后 `model.feb`、`playback.json`、`playback.pc2`、`physics/` 的四个数组文件和表头、`settled_frame14.*` 逐字节相同。
  - 仅 `scene.json` 不同（导入器多写了头驱动源，`data/preview/t28_head_shake_report.json` 的 `stage2_before_after`）；甩头结果见 [T-28](../archive/tasks/T-28.md)。
- **影响**：[04](../archive/prototype/04-v1-architecture.md) 第 4、5.1 节、[05](../05-ziva-to-febio.md) 第 4 节、[05 常见坑](../05-febio-pits.md) 坑 19、20。
  - 关联任务与问题：[09](../09-roadmap-and-tasks.md) 的 [T-28](../archive/tasks/T-28.md)、[11](../11-risks-and-questions.md) 的 `P-09` 与 `D6`。

---

## 历史与修订

- **2026-11-12 初定与放弃项**：
  - 当时第 5 条记：嘴唇物理阻尼未知，等 Ziva 设置（`D6`），在此之前任何不为 0 的值标“我们定的”、只作演示。
  - 放弃了：(a) 把颅骨改成“每个运动文件都要写头的运动”（旧运动文件全要改）；(b) 先只调低数值阻尼（当时稳定靠它，[E-09](../archive/explanations/E-09.md) 发现五）；(c) 用 `rhoi` = 1 当“没有数值阻尼”（有弹簧时会吃掉振动，[05 常见坑](../05-febio-pits.md) 坑 20，要“没有”用 −2）。
- **2026-11-13 状态更新**：取回 Ziva 刚度阻尼 0.001、质量阻尼 0（[03](../03-asset.md) 第 5 节、[E-11](../explanations/E-11.md)）；`solver.damping` 为质量阻尼，取 0 即与 Ziva 一致；刚度阻尼属种类差别而非数值差别，归 [T-37](../archive/tasks/T-37.md) 第 3 项决定。
- **2026-11-24 状态更新**：[T-37](../archive/tasks/T-37.md) 第 3 项定为不建刚度阻尼；[ADR-47](ADR-47.md)、[ADR-48](ADR-48.md)、[ADR-49](ADR-49.md) 对第 1、3 条作出地基目标修订（见上方当前生效结论）。

---

返回 [决策索引](../10-decisions.md)
