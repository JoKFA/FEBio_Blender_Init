# 16 从 Maya 到 Blender 的完整流程

**一句话**：实验室的网格从 Maya 导出以后，**不经过 Blender**，由核心程序 `asrp_core` 直接读取、切成四面体、生成场景和运动、交给 FEBio 计算、叠加 landmark 层、打包成点缓存，最后才在 Blender 里播放。Blender 在这条流程里只是播放器和遥控器（ADR-03）。

这份文档把整条流程按顺序串起来，并列出每一步用到的命令和 `.py` 文件。每一步的设计细节在别的文档里，本文只做导航，链接见最后一节。

```
① Maya 导出 ─→ ② 四面体化 ─→ ③ 生成场景描述 ─→ ④ 准备运动 ─→ ⑤ 生成 model.feb ─→ ⑥ FEBio 计算
   （只做一次）    （只做一次）       scene.json       trajectory.json
                                                                                         │
⑪ Blender 播放 ←─ ⑩ 生成 PC2 回放包 ←─ ⑨ 合理性检查 ←─ ⑧ 叠加 landmark 蒙皮 ←─ ⑦ 读回结果、嵌入显示网格
                                                      （运动里有 landmark 才做）
```

- ① ② 已经做过，结果提交在 `data/` 里（ADR-19），平时从 ③ 开始；
- ⑤ 到 ⑩ 由一条命令 `asrp run` 一次做完；
- ⑪ 是唯一用到 Blender 的一步。

## 1. 一眼看全流程

| # | 步骤 | 命令 | 主要的 `.py` 文件 | 输入 → 输出 | 多久做一次 |
|---|---|---|---|---|---|
| ① | Maya 导出 | `"<Maya 安装目录>\bin\mayapy.exe" tools/maya_export.py <scene.mb> data/lab_export` | `tools/maya_export.py` | 实验室 `.mb` → `data/lab_export/` 的 OBJ、关节、landmark 权重 | 一次（ADR-18） |
| ② | 四面体化 | `uv run python tools/build_tetmesh.py` | `tools/build_tetmesh.py`、`src/asrp_core/tetmesh.py` | 嘴唇 OBJ → `data/tetmesh/lips.json` | 一次（ADR-20） |
| ③ | 生成场景描述 | `uv run asrp import-asset data/lab_export <场景文件夹>` | `src/asrp_core/asset/lab.py`、`asset/coords.py`、`asset/skin.py`、`scene.py` | `data/lab_export/` + `data/tetmesh/` → `scene.json` 等 | 每换一次资产或设置 |
| ④ | 准备运动 | 见第 5 节 | `src/asrp_core/trajectory.py` 和 `tools/` 下的运动脚本 | 场景 → `trajectory.json` | 每换一种动作 |
| ⑤ | 生成 `model.feb` | `uv run asrp run <scene.json> <trajectory.json>` | `src/asrp_core/generate.py` | `scene.json` + 运动里的骨头部分 → `model.feb` | 每次运行 |
| ⑥ | FEBio 计算 | 同上 | `src/asrp_core/run.py`、`febio.py` | `model.feb` → 每帧四面体节点的位置 | 每次运行 |
| ⑦ | 读回结果、嵌入显示网格 | 同上 | `src/asrp_core/run.py`、`embed.py` | 四面体结果 → 10,240 个嘴唇表面顶点的逐帧位置；沉降形状 | 每次运行 |
| ⑧ | 叠加 landmark 蒙皮 | 同上 | `src/asrp_core/skinning.py` | 物理结果 + landmark 位移 + 权重 → 最终形状 | 运动里有 landmark 时 |
| ⑨ | 合理性检查 | 同上 | `src/asrp_core/plausibility.py` | 结果 → 五项检查 | 每次运行 |
| ⑩ | 生成 PC2 回放包 | 同上 | `src/asrp_core/playback.py`、`provenance.py` | 结果 → `playback.json` + `playback.pc2`（有 ⑧ 时再加一份） | 每次运行 |
| ⑪ | Blender 播放 | 侧栏 ASRP > Load Result | `blender_addon/asrp_blender/__init__.py`、`session.py` | 回放包 → 时间轴上的动画 | 想看的时候 |

⑤ 到 ⑩ 的总调度是 `src/asrp_core/simulate.py`，命令行入口是 `src/asrp_core/cli.py`（`asrp` 这个命令由 `pyproject.toml` 的 `[project.scripts]` 生成）。

## 2. ① Maya 导出（只做一次）

**做什么**：用普通 Maya（不需要 Ziva）打开实验室的场景，把原型要用的东西导出成开放格式。Maya 只在这一步出现，产品本身从不需要 Maya（ADR-18）。

| 文件 | 作用 |
|---|---|
| `tools/maya_export.py` | 在 `mayapy` 里运行。导出 5 个网格（嘴唇、下颌、颅骨、上下牙）的静止形状，写成场景坐标的 OBJ；`joints.json`（下颌关节 `jaw01` 和 300 个 landmark）；`skin_skinCluster7.json`（landmark 对嘴唇的蒙皮权重）；`mesh_report.json` |
| `tools/check_lab_export.py` | 不用 Maya，直接读 `.mb` 里的顶点，和导出的 OBJ 逐点核对 |
| `tools/mb_inventory.py`、`tools/lip_attachments.py` | 不用 Maya 解析 `.mb`，读出嘴唇的四组粘连顶点，写成 `data/lab_export/lip_attachments.json`（T-03） |

**结果**：`data/lab_export/`，已提交。导出步骤和 Ziva 机器上的补充导出见 [12](12-lab-export-checklist.md)。

## 3. ② 四面体化（只做一次）

**做什么**：FEBio 只能在体积网格上计算，实验室给的嘴唇只是一层表面，要先填满四面体（为什么必须做，见 [13](13-explanations.md) E-02）。网格直接从嘴唇 OBJ 读取，**不经过 Blender**。

| 文件 | 作用 |
|---|---|
| `tools/build_tetmesh.py` | 入口：读嘴唇 OBJ，换算成毫米，调用 fTetWild，检查通过才写文件 |
| `src/asrp_core/tetmesh.py` | 四面体化、质量检查（没有压扁的四面体、上下唇分开、亏格正确），读取时校验哈希 |

**结果**：`data/tetmesh/lips.json`，已提交。fTetWild 同样的输入每次结果不同，所以只生成一次、提交，运行时只读不重算（ADR-20）。文件里记着嘴唇 OBJ 的 sha256；OBJ 的字节变了（比如行尾被转换），下一步就会报错（[08](08-engineering-standards.md) 第 10 节）。

## 4. ③ 生成场景描述 `scene.json`

**做什么**：把导出的资产换算成项目统一的单位和坐标轴（mm、Z 轴朝上），写成项目自己定义的场景描述，格式 `asrp-scene/1`。它回答"这个模型是什么"：软组织和材料、骨头跟着谁动、粘连、landmark、求解设置，以及每个参数的来源（实验室给的，还是我们定的临时值）。

| 文件 | 作用 |
|---|---|
| `src/asrp_core/cli.py` | `asrp import-asset` 的入口 |
| `src/asrp_core/asset/lab.py` | 主体：读 `data/lab_export/`，写 `scene.json`、换算后的网格、`import_report.json`（T-02） |
| `src/asrp_core/asset/coords.py` | 全项目唯一的一份单位和坐标轴换算（× 0.962，Y 朝上 → Z 朝上） |
| `src/asrp_core/asset/skin.py` | landmark 蒙皮权重换算成毫米、Z 朝上，写成 `landmarks/skin_mm.json` |
| `src/asrp_core/scene.py` | 场景描述的格式定义和校验；`uv run asrp check <scene.json>` 也用它（T-05） |

**结果**：场景文件夹里的 `scene.json`、`meshes/`、`landmarks/`、`import_report.json`。格式要包含哪些信息见 [04](04-architecture.md) 第 5.1 节，字段写法见 `scene.py` 开头的说明。

## 5. ④ 准备运动 `trajectory.json`

**做什么**：写出"这次怎么动"，格式 `asrp-trajectory/1`：每帧骨头驱动源的变换（下颌 `jaw01` 转多少、头平移多少），前几帧只受重力的沉降段，以及可选的每帧 300 个 landmark 的位移。同一个 `scene.json` 可以配不同的运动。

| 文件 | 作用 | 用在哪里 |
|---|---|---|
| `src/asrp_core/trajectory.py` | 运动文件的格式、读写、校验；铰链运动的生成（ADR-21） | 所有运动 |
| `tools/placeholder_jaw_motion.py` | 代用张嘴：下颌张到 12° 再合上，51 帧 | 原型机（[15](15-prototype.md) 第 2 节） |
| `tools/head_shake_motion.py` | 甩头，按实验室脚本的关键帧 | 原型机二（T-28） |
| `tools/aa_standin.py` | 中性到 AA：自己从目标形状拟合 landmark 位移，甲、乙两种拼法 | 原型机二（T-27、ADR-40） |

`aa_standin.py` 是临时替身：实验室真正的运动文件（D2）到了以后，由 T-10 的转换代替。格式要包含哪些信息见 [04](04-architecture.md) 第 5.2 节，字段写法见 `trajectory.py` 开头的说明。

## 6. ⑤–⑩ 一次运行：`asrp run`

```bash
uv run asrp run <scene.json> <trajectory.json>
```

`src/asrp_core/simulate.py` 按下面的顺序做完全部步骤，所有输入和结果都放进同一个运行文件夹（默认 `runs/<日期>_<名字>_<编号>/`，[04](04-architecture.md) 第 4 节）。

**⑤ 生成 `model.feb`**：`generate.py` 把场景和运动翻译成 FEBio 的输入：坐标乘 k（ADR-36）、重力反号（[05](05-ziva-to-febio.md) 坑 1）、刚体、粘连、动力学设置。**它只读运动里的骨头部分，landmark 那一节不进 FEBio。** 场景不合格时它拒绝生成，不建运行文件夹。

**⑥ FEBio 计算**：`run.py` 建运行文件夹、拷入输入、启动 FEBio、读进度、可以取消（T-08、T-25）；`febio.py` 负责真正调用 `febio4.exe`（默认 4 线程，ADR-38）。

**⑦ 读回结果、嵌入显示网格**：`run.py` 读回每帧四面体节点的位置并除以 k；`embed.py` 让实验室精细的嘴唇表面（10,240 个顶点）按重心坐标跟着四面体网格动。后面的步骤和播放用的都是这个表面。沉降段最后一帧（原型机是第 14 帧）的形状单独存一份，它是控制器优化的起点（ADR-30）。

**⑧ 叠加 landmark 蒙皮**：只在运动里有 `landmarks` 一节时才做。`skinning.py` 计算 最终形状 = 物理结果 + 权重 × landmark 位移。物理结果原样保留，最终形状另存一份。为什么放在物理之后：实验室的场景和源码就是先物理、后蒙皮（ADR-29，[04](04-architecture.md) 第 2 节）。

**⑨ 合理性检查**：`plausibility.py` 做五项检查（[07](07-validation.md) 第 3 节）：运动算完了没有、粘住的地方跟着骨头走没有、弹簧锚跟着刚体走没有、重力是不是往下拉、四面体有没有被压翻。任何一项不通过，命令以非 0 退出。

**⑩ 生成 PC2 回放包**：`playback.py` 写出 `playback.json`（表面网格和元数据）和 `playback.pc2`（每帧顶点坐标）；做了 ⑧ 时再加一份 `playback_final.pc2`。`provenance.py` 写溯源记录。PC2 格式和回放包见 [04](04-architecture.md) 第 5.3 节。

每条命令应该看到什么输出、用时多少，见 [15](15-prototype.md) 第 2 节。

## 7. ⑪ Blender 播放

**做什么**：插件按 `playback.json` 建出网格，挂一个 Mesh Cache 修改器读 PC2，按空格播放。Blender 不做任何计算。

| 文件 | 作用 |
|---|---|
| `blender_addon/asrp_blender/__init__.py` | 面板和按钮：Load Result（可以切换 physics 和 final 两个版本）、Checks（显示五项检查的结果） |
| `blender_addon/asrp_blender/session.py` | Run 按钮：在后台启动 `asrp run`，显示进度、可以取消 |
| `tools/render_prototype.py` | 可选：不开界面，加上颅骨和下颌渲染出图，并逐帧核对 Blender 里的嘴唇和 FEBio 的数字 |

插件的安装和使用见仓库根目录的 [README](../README.md) 和 [15](15-prototype.md) 第 2 节，面板设计见 [06](06-ui.md)。

## 8. 几个容易误会的地方

- **Blender 不在中间**：导出的 OBJ 由 `asrp_core` 直接读取。`tools/blender_import_preview.py` 会把网格导入 Blender，但它只生成 `data/preview/` 里的预览图，让人看一眼导出对不对，不在计算流程里。
- **不是所有输入都进 FEBio**：`scene.json` 和运动里的骨头部分经 `generate.py` 进 FEBio；landmark 位移和蒙皮权重不进，它们在 FEBio 算完之后才用到（⑧）。
- **`scene.json`、`trajectory.json` 是项目自己定义的格式**，不是 FEBio 的。项目自己的格式都以 `asrp-` 开头，比如 `asrp-scene/1`、`asrp-trajectory/1`、`asrp-playback/1`、`asrp-skin/1`。拆成中间文件，是为了同一个模型能配不同的运动，嵌入、检查、回放也能读它们，并且以后换求解器只需要重写 ⑤（[04](04-architecture.md) 第 6 节）。
- **四面体网格不是每次运行时生成的**：只由 `tools/build_tetmesh.py` 显式生成一次（ADR-20）。

## 9. 还没有的步骤

| 步骤 | 状态 | 任务 |
|---|---|---|
| 把实验室真实的运动文件转换成 `trajectory.json` | 等运动文件（D2） | T-10 |
| ⑫ 和 Ziva 的结果并排比较（`asrp_core/compare.py`） | 等 Ziva 的参考结果（D3） | T-11 |

## 10. 每一步的细节在哪里

| 想知道 | 看 |
|---|---|
| 系统分哪几块、每个模块负责什么、运行文件夹里有什么 | [04](04-architecture.md) 第 1、3、4 节 |
| `asrp run` 点下去以后的步骤（从插件的角度） | [04](04-architecture.md) 第 8 节 |
| `scene.json`、`trajectory.json`、回放包要包含什么 | [04](04-architecture.md) 第 5 节 |
| Ziva 的每样设置在新系统里怎么表达、踩过的坑 | [05](05-ziva-to-febio.md) |
| 怎么自己跑一遍、每条命令的输出 | [15](15-prototype.md) 第 2 节 |
| Maya 导出和 Ziva 机器上的导出 | [12](12-lab-export-checklist.md) |
| 为什么要四面体化 | [13](13-explanations.md) E-02、ADR-20 |
| 合理性检查查什么 | [07](07-validation.md) 第 3 节 |
