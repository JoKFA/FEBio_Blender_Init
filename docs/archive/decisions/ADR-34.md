# ADR-34：确认 M1 留下的选择

> **归档说明**：M1 原型期导入选择；场景格式与大文件约定已由 [ADR-46](../../decisions/ADR-46.md)–[ADR-51](../../decisions/ADR-51.md) 接替。

| 项目 | 内容 |
|---|---|
| **状态** | ✅ 已定（2026-11-10；2026-11-12 补完蒙皮换算；2026-11-24 部分由 `asrp-scene/2` 地基决策取代） |
| **关联决策** | 第 2、3、4、5 条由 [ADR-46](../../decisions/ADR-46.md)、[ADR-47](../../decisions/ADR-47.md)、[ADR-48](../../decisions/ADR-48.md)、[ADR-51](../../decisions/ADR-51.md) 部分取代 |
| **相关文档** | [04 架构](../prototype/04-v1-architecture.md)（第 4、5.1 节）、[09 任务](../../09-roadmap-and-tasks.md)、[T-09](../tasks/T-09.md)、[T-10](../../tasks/T-10.md) |

---

## 当前生效结论

- **持续有效的约定**：
  1. **帧数怎么查**：场景只记帧率，帧数由 `trajectory.json` 给出；`asrp check` 带上运动时，运动的帧率和场景不一致就报错（[04](../prototype/04-v1-architecture.md) 第 5.1 节）。
  - **第 6 条（下颌铰链）**：来自 `joints.json`，来源标“实验室设置”。
  - **第 7 条（空粘连提醒）**：导入结果带一条提醒（嘴唇还没有任何粘连），属预期，已在 [T-06a](../tasks/T-06a.md) 加上粘连后消失（已兑现：`import PASSED: scene check 0 errors, 0 warnings`）。
  - **蒙皮矩阵换算（2026-11-12 [T-09](../tasks/T-09.md) 已补上）**：导入模块 `src/asrp_core/asset/` 在导入时一次换算成毫米和 Z 轴朝上（`N-01`）。
    - 写入换算好的 `landmarks/skin_mm.json`，不再原样拷贝 `landmarks/skin_skinCluster7.json`（[04](../prototype/04-v1-architecture.md) 第 4 节）。
  - **矩阵行/列向量约定**：运动文件 `trajectory.json` 用**列向量**约定，Maya 的矩阵是**行向量**约定，[T-10](../../tasks/T-10.md) 转换时要转置。
- **新旧格式分流（2026-11-24 状态）**：
  - 原第 2、3、4、5 条仅保留给 `asrp-scene/1` 与 `legacy-v1` 兼容：
    2. **粘连两种类型**：`hard`（硬绑定，刚度为空）和 `spring`（刚度 × 权重）；
    3. **粘连权重**：以稀疏列表 `[[顶点, 权重], ...]` 直接写在 `scene.json` 里，单个粘连超过一万项时再改成引用文件；
    4. **四面体网格**：导入时原样拷进输出文件夹的 `meshes/`，场景引用这份拷贝；
    5. **临时值来源标注**：一律带来源标注（实验室设置 / Ziva 默认值 / 我们定的）和说明。
  - `asrp-scene/2`（地基目标，待实现）改为小清单配按内容摘要共享的 `blobs/<sha256>`、三层粘连表达，以及分记“值从哪来／程序怎么处理”的双向导入台账（[ADR-46](../../decisions/ADR-46.md)、[ADR-47](../../decisions/ADR-47.md)、[ADR-48](../../decisions/ADR-48.md)、[ADR-51](../../decisions/ADR-51.md)）。

---

## 历史与修订

- **2026-11-10 初定背景**：上述选择均在 [T-02](../tasks/T-02.md)、[T-05](../tasks/T-05.md) 实现时定下、当时未及请项目负责人确认；同日项目负责人全部采纳，文档中的“待确认”去掉。放弃了：无。
- **M1 留下的缺口及补齐（2026-11-12）**：M1 时 `landmarks/skin_skinCluster7.json` 为原样拷贝，蒙皮矩阵仍是场景单位、Y 轴朝上。
  - 当时在 [09](../../09-roadmap-and-tasks.md) 的 M1 状态注明并归 [T-09](../tasks/T-09.md) 完成；2026-11-12 已在 `src/asrp_core/asset/` 补上，改写 `landmarks/skin_mm.json`。

---

返回 [决策索引](../../10-decisions.md)
