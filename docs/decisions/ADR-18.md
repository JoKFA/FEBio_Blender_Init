# ADR-18：本机 Maya 只作迁移工具；Ziva 机器只做离不开 Ziva 的事

| 项目 | 内容 |
|---|---|
| **状态** | ✅ 已定（2026-10-30；第 4 条经 2026-11-03 补充并由 [ADR-24](../archive/decisions/ADR-24.md) 扩大；2026-11-24 核实第 2 条不变） |
| **关联决策** | [ADR-02](ADR-02.md)、[ADR-16](ADR-16.md)、[ADR-24](../archive/decisions/ADR-24.md)、[ADR-45](ADR-45.md) |
| **关联任务** | [T-02](../archive/tasks/T-02.md)、[T-09](../archive/tasks/T-09.md) |
| **相关文档** | [12](../12-lab-export-checklist.md)、[13](../13-explanations.md)（[E-11](../explanations/E-11.md)、[E-14](../archive/explanations/E-14.md)、[E-15](../archive/explanations/E-15.md)） |

## 当前生效结论

1. **本机迁移导出**：开发机装 Maya 教育版（现在是 2027），用 `tools/maya_export.py` 从实验室给的非 Ziva 版场景导出网格、landmark 权重和关节。
2. **产品不依赖 Maya**（[ADR-02](ADR-02.md) 不变）：Maya 只用于一次性迁移，`tools/verify.py` 也不需要它。
   - 2026-11-24 核实：[ADR-45](ADR-45.md) 第 3 条把 Blender 和 Maya 都列为实验室提出的宿主选项，倾向 Blender；产品现在仍不依赖 Maya（`src/`、`blender_addon/` 里没有 Maya 的导入）。
3. **自写场景坐标 OBJ**：OBJ 文件由我们的脚本直接写，不用 Maya 的 OBJ 插件。坐标就是场景坐标，所以 [ADR-16](ADR-16.md) 的第一步在导出时完成，[T-02](../archive/tasks/T-02.md) 只做换单位和转坐标轴，**不能再套一次变换**。
4. **Ziva 机器范围（已由 [ADR-24](../archive/decisions/ADR-24.md) 扩大，不再限一次）**：
   - 包括 Ziva 设置、Ziva 参考结果、运动（[12](../12-lab-export-checklist.md) 第二部分），以及无需解算的逐顶点权重表和连线（`ziva_maps.json`）、Ziva 给每个物体存的网格（`ziva_meshes/`，[12](../12-lab-export-checklist.md) 第 7 项）。
- **教育版红线**：教育版只能用于学习和研究，不能商用；**绝不在教育版 Maya 里保存实验室的 `.mb`**，否则文件会被打上教育版标记。脚本只读不存。

## 依据与边界

- **原因**：
  - 实验室反馈 Ziva 机器大约 4 个人轮流用，清单里只有一小部分真正需要 Ziva；
  - 导出脚本原来没运行过，现在能在本机反复运行和修改；
  - 导出变成仓库里能重复运行、带核对的工具，不是一次手工操作；
  - 文档原来的导出脚本用 Maya 的 OBJ 插件，按 Autodesk 公开的示例源码，它写的是场景坐标，而 [T-02](../archive/tasks/T-02.md) 又要求再套一次变换，会放大两次。自己写文件，坐标含义就由我们决定。
- **证据（2026-10-30）**：
  - `tools/maya_export.py` 40 秒内导出全部文件，自检通过；
  - `tools/check_lab_export.py` 不经过 Maya，直接从 `.mb` 读顶点，和导出文件逐点比较，5 个网格最大差别小于 0.0000001 个场景单位，新旧两个 `.mb` 都一样。
    - 这条证明顶点和顺序对；变换矩阵来自 Maya 自己的报告，它的独立检查是从 OBJ 量出的下颌尺寸 155.92；
  - 反向试验可以重复运行：`tools/check_lab_export.py --self-test`。调换两个嘴唇顶点，差别 62.35；真的多套一次变换，下颌 z 尺寸变成 372.16；删掉一半嘴唇的面，出现 128 条开口的边。三种都失败；
  - `tools/rehearse_ziva_export.py` 在普通 Maya 上排练 Ziva 脚本，结果写在 `data/ziva_rehearsal/rehearsal_report.json`。
- **放弃了**：全部请实验室操作；继续破解 `.mb` 的网格编码。

## 历史与修订

- **2026-10-30 原第 4 条方案**：最初仅 Ziva 设置、Ziva 参考结果和运动三项用 Ziva 机器，用 `tools/ziva_machine_export.py` 一次做完（[12](../12-lab-export-checklist.md) 第二部分）。
  - 两份 Ziva 结果来自**同一次解算**：脚本临时接一个网格到 `skinCluster7` 的输入上，AbcExport 一次写两个文件，不切换 `envelope`。这样省一次解算，[T-09](../archive/tasks/T-09.md) 的精确对比也不用依赖 Ziva 两次解算逐帧相同。
- **2026-11-03 更新**：第 4 条的 Ziva 机器清单加两项，都不需要解算：`ziva_maps.json` 和 `ziva_meshes/`（[12](../12-lab-export-checklist.md) 第 7 项）。
  - 原因：属性清单只收单值属性，读不出权重表（在普通 Maya 上实测）；6 块肌肉的网格只剩 Ziva 存的副本，离开 Ziva 就读不出面。
- **2026-11-09 更新**：第 4 条的范围扩大，Ziva 机器不再限一次，见 [ADR-24](../archive/decisions/ADR-24.md)。
- **2026-11-13 状态（已取回记录）**：
  - 第 4 条的三项都已取回（2026-11-12，[13](../13-explanations.md) [E-11](../explanations/E-11.md)）；
  - 现场做法和原第 4 条写的不同：运动是我们的一次性脚本（放在仓库外的数据文件夹 `scripts/`）照实验室的运动文件打的关键帧，钢琴界面的源码只用来定关键帧落在哪一帧，不是研究员在界面上按出来的；
  - IY、UW、T 三段脚本按现存文件播了 36、36、10 步，界面源码对从中性出发的过渡要 22 步，所以不一定是界面实际播的那一条（[E-14](../archive/explanations/E-14.md) 第 2 条）；
  - 取回的蒙皮前和蒙皮后逐帧对得上：同一帧的蒙皮前 + 权重 × 第（帧号 − 15）步的 landmark 位移和同一帧的蒙皮后最坏差 0.000016 mm（[E-15](../archive/explanations/E-15.md) 第 3 条）；实际做了什么见 [12](../12-lab-export-checklist.md) 第一部分。
- **2026-11-24 状态**：确认第 2 条产品不依赖 Maya 仍成立。

---

返回 [决策索引](../10-decisions.md)
