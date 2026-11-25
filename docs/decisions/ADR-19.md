# ADR-19：私有仓库可以存放派生数据

| 项目 | 内容 |
|---|---|
| **状态** | ✅ 已定（2026-10-30，项目负责人定） |
| **关联决策** | [ADR-20](ADR-20.md) |
| **关联任务** | [T-02](../archive/tasks/T-02.md)、[T-03](../archive/tasks/T-03.md)、[T-04](../archive/tasks/T-04.md)、[T-06a](../archive/tasks/T-06a.md) |
| **相关文档** | [03](../03-asset.md) 第 11 节 |

## 当前生效结论

- **允许提交的派生数据**：仓库是私有的，所以我们导出和派生的文件、团队内部材料可以提交。现在提交的是：
  - `data/lab_export/`（网格、权重、关节）；
  - `data/preview/`（Blender 预览）；
  - `data/briefing/`（讲解页）；
  - `data/tetmesh/`（嘴唇四面体网格，它不能重新生成出同一个，见 [ADR-20](ADR-20.md)）。
- **绝不提交**：**实验室的原始 `.mb`、论文和演示视频仍然绝不提交。**
- **不提交的目录与中间文件**：`assets/`、`runs/`，以及体积大而且能重新生成的 `data/asset_inventory*.json`、`data/ziva_rehearsal/`。`.gitignore` 还会拦住任何位置的 `.mb`、`.ma`、`.pdf`、`.mp4`。
- **安全与许可注意**：
  - 这些派生文件含有完整的网格和权重，等于资产的另一种格式，因此仓库必须保持私有、只邀请项目成员，也不发到仓库以外的地方；
  - 资产的使用许可（Q6）还没有答复。如果实验室有限制，要把这些文件从 git 历史里清掉，光删除文件不够；
  - [T-03](../archive/tasks/T-03.md)、`tools/check_lab_export.py` 和重新构建讲解页仍然需要本地有 `.mb`。

## 依据与边界

- **原因**：[T-02](../archive/tasks/T-02.md)、[T-04](../archive/tasks/T-04.md)、[T-06a](../archive/tasks/T-06a.md) 要用导出数据，克隆下来就能开工，不用再单独传文件；讲解页和预览也跟着仓库走。

## 历史与修订

- **2026-10-30 取代**：取代 N-06 和 [03](../03-asset.md) 第 11 节里"派生数据不进仓库"的部分。
- **2026-11-24 状态**：上面列的 `data/briefing/` 已不在仓库里：它在提交 `059e38f`（[T-38](../archive/tasks/T-38.md)）里随一次性文件移出了仓库。现在提交的只剩 `data/lab_export/`、`data/preview/`、`data/tetmesh/`。

---

返回 [决策索引](../10-decisions.md)
