# ADR-22：几何单位和物理尺度分开

| 项目 | 内容 |
|---|---|
| **状态** | ✅ 已定（2026-11-09；k 的取值与标定已被 [ADR-31](ADR-31.md) 取代，FEBio 实现已被 [ADR-36](ADR-36.md) 取代） |
| **关联决策** | [ADR-31](ADR-31.md)、[ADR-36](ADR-36.md) |
| **关联任务** | [T-05](../archive/tasks/T-05.md)、[T-06a](../archive/tasks/T-06a.md) |
| **相关文档** | [04](../archive/prototype/04-v1-architecture.md) 第 5.1 节、[05](../05-ziva-to-febio.md) 第 2 节、[07](../07-validation.md) 第 3 节、[09](../09-roadmap-and-tasks.md)、[11](../11-risks-and-questions.md) |

## 当前生效结论

- **双量分离**：`scene.json` 的 `units` 里保留两个独立的量（[T-06a](../archive/tasks/T-06a.md) 实现）：
  - `mm_per_scene_unit`：几何换算，暂定 0.962；
  - `physics_length_scale`：无量纲的 k。求解器把模型当成几何尺寸的 **k 倍大**来算；几何和输出仍然是毫米。
- **现行 k 取值（已由 [ADR-31](ADR-31.md) 取代原条款）**：k = 0.67，由颅骨宽取 145 mm 得出。
- **现行 FEBio 实现（已由 [ADR-36](ADR-36.md) 取代原条款）**：节点坐标 × k，物理参数不缩放。

## 依据与边界

- **原因**：
  - 0.962 mm/单位是作者拿自己的下颌比出来、给控制器换算速度上限用的（论文附录 V）；
  - Ziva 求解时"眼里"的物理尺度由 `zSolver` 的缩放（100）等决定，当时不知道；
  - 重力下垂大约正比于"长度的平方 ÷ 刚度"，尺度差 10 倍，比任何材料参数的影响都大（量级估算，[07](../07-validation.md) 第 3 节有公式）；
  - 把几何单位和物理尺度混成一个数，错了就没法分开查。
- **影响**：
  - 改 [04](../archive/prototype/04-v1-architecture.md) 第 5.1 节、[05](../05-ziva-to-febio.md) 第 2 节、[07](../07-validation.md) 第 3 节；
  - 改 [09](../09-roadmap-and-tasks.md) 的 [T-05](../archive/tasks/T-05.md)、[T-06a](../archive/tasks/T-06a.md) 卡，以及 [11](../11-risks-and-questions.md) 的 Q3、A-09，新增 A-31。
- **放弃了**：只有一个换算系数；等 Ziva 的答复以后再设计。

## 历史与修订

- **2026-11-09 初版条款（部分已被取代）**：
  - 原设 `physics_length_scale` 默认 1.0，来源标"我们定的"；曾计划等 Ziva 属性清单和 Q3 的回答，拿到参考结果以后用 Ziva 第 0 到 14 帧的下垂量标定 k；
  - 原先写在这里的"密度乘 k²、重力除以 k"已放弃。
- **2026-11-24 状态**：k 的取值和标定已被 [ADR-31](ADR-31.md) 取代（k = 0.67，由颅骨宽取 145 mm 得出），"拿到参考结果以后用 Ziva 第 0 到 14 帧的下垂量标定 k"那句不再适用；k 在 FEBio 里的实现已被 [ADR-36](ADR-36.md) 取代。

---

返回 [决策索引](../10-decisions.md)
