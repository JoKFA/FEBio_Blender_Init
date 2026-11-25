# ADR-01：物理计算用 FEBio

| 项目 | 内容 |
|---|---|
| **状态** | ✅ 已定（2026-10-27；由 [ADR-26](../archive/decisions/ADR-26.md) 补充复核关，2026-11-16 关已过；2026-11-24 核实速度要求仍开着） |
| **关联决策** | [ADR-26](../archive/decisions/ADR-26.md) |
| **关联任务** | [T-17](../archive/tasks/T-17.md)、[T-18](../archive/tasks/T-18.md)、[T-23](../archive/tasks/T-23.md)、[T-30](../archive/tasks/T-30.md)（已过关）；[T-24](../tasks/T-24.md)（未运行） |
| **相关说明** | [13](../13-explanations.md) 的 [E-21](../archive/explanations/E-21.md) |

## 当前生效结论

- **物理求解器选型**：用 FEBio 替换 Ziva。以后如果需要第二个求解器做交叉验证，首选 ArtiSynth。
- **FEBio 保留**：第二阶段投入之前的复核关已于 2026-11-16 过关，不触发换求解器（见 [E-21](../archive/explanations/E-21.md)）。
  - 过关依据为四个方块试验单项可行：[T-17](../archive/tasks/T-17.md)、[T-18](../archive/tasks/T-18.md)、[T-23](../archive/tasks/T-23.md)、[T-30](../archive/tasks/T-30.md)。
- **未闭项边界**：[T-24](../tasks/T-24.md) 没有运行（[09](../09-roadmap-and-tasks.md) 里仍是 🟢）。过关只说明每项能力单项可行，不说明够快；速度要求仍开着，见 [ADR-26](../archive/decisions/ADR-26.md) 的状态行。
- **许可限制**：官方安装包的许可只允许单机安装和内部使用，不允许再分发（已读安装附带的许可协议）。

## 依据与边界

- **原因**：FEBio 专为生物力学开发，有已发表的验证；源码开源（MIT 许可），每一步计算都能检查；输入输出都是文件，适合独立运行；自带刚体、动力学和多种软组织材料。
- **放弃了**：
  - AdonisFX、Houdini Otis（闭源，没有生物力学方面的有效性声明，本质上和 Ziva 是同一类工具）；
  - SOFA、PolyFEM（在 Windows 上安装风险高）；
  - 自己写有限元（验证工作量太大）。

## 历史与修订

- **2026-11-09 补充**：第二阶段要的软组织互相粘连和薄壳皮肤还没有试验，定在第二阶段投入之前用 [T-17](../archive/tasks/T-17.md)、[T-18](../archive/tasks/T-18.md) 复核，见 [ADR-26](../archive/decisions/ADR-26.md)（2026-11-11 起关卡从 M3 之前移到第二阶段投入之前）。
- **2026-11-16 状态**：关已过，四个方块试验单项可行，不触发换求解器，FEBio 保留（[13](../13-explanations.md) [E-21](../archive/explanations/E-21.md)）。
- **2026-11-24 核实**：上述四个方块试验都是 ✅ 2026-11-16（原归档，现为 [T-17](../archive/tasks/T-17.md)、[T-18](../archive/tasks/T-18.md)、[T-23](../archive/tasks/T-23.md)、[T-30](../archive/tasks/T-30.md)）；[T-24](../tasks/T-24.md) 没有运行，速度要求仍开着。

---

返回 [决策索引](../10-decisions.md)
