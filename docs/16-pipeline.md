# 16 从 Maya 到 Blender 的完整流程

**一句话**：实验室的网格从 Maya 导出以后，**不经过 Blender**，由核心程序 `asrp_core` 直接读取、切成四面体、生成场景和运动、交给 FEBio 计算、叠加 landmark 层、打包成点缓存，最后在 Blender 里播放，并且可以和 Ziva 的结果并排比较。Blender 在这条流程里是播放器和遥控器：面板上的按钮只是调用 `asrp` 命令，计算从不在 Blender 里做（ADR-03）。

这份文档把整条流程按顺序串起来，并列出每一步用到的命令和 `.py` 文件（2026-11-16 的代码）。每一步的设计细节在别的文档里，本文只做导航，链接见最后一节。

```
① Maya 导出 ─→ ② 四面体化 ─→ ③ 生成场景描述 ─→ ④ 准备运动 ─→ ⑤ 生成 model.feb ─→ ⑥ FEBio 计算
   （只做一次）    （只做一次）       scene.json       trajectory.json
                                                                                         │
⑪ Blender 播放 ←─ ⑩ 生成 PC2 回放包 ←─ ⑨ 合理性检查 ←─ ⑧ 叠加 landmark 蒙皮 ←─ ⑦ 读回结果、嵌入显示网格
      │                                                （运动里有 landmark 才做）
      └─→ ⑫ 和 Ziva 对比（要 Ziva 机器上导出的参考结果）
```

- ① ② 已经做过，结果提交在 `data/` 里（ADR-19），平时从 ③ 开始；三条现成的运动也已提交（第 5 节）；
- ⑤ 到 ⑩ 由一条命令 `asrp run` 一次做完；
- 在 Blender 面板上，③ 到 ⑪ 是三个按钮：**Open asset**（③ 加读运动列表）、选运动、**Run**（⑤ 到 ⑩，结果直接播放）；⑫ 是 **Compare with Ziva**。

## 1. 一眼看全流程

| # | 步骤 | 命令（面板上的按钮） | 主要的 `.py` 文件 | 输入 → 输出 | 多久做一次 |
|---|---|---|---|---|---|
| ① | Maya 导出 | `"<Maya 安装目录>\bin\mayapy.exe" tools/maya_export.py <scene.mb> data/lab_export` | `tools/maya_export.py` | 实验室 `.mb` → `data/lab_export/` 的 OBJ、关节、landmark 权重 | 一次（ADR-18） |
| ② | 四面体化 | `uv run python tools/build_tetmesh.py [--method lattice]` | `tools/build_tetmesh.py`、`src/asrp_core/tetmesh.py` | 嘴唇 OBJ → `data/tetmesh/lips.json`（细网格）、`lips_lattice.json`（粗格子） | 一次（ADR-20、ADR-44） |
| ③ | 生成场景描述 | `uv run asrp import-asset data/lab_export <场景文件夹>`（**Open asset**） | `src/asrp_core/asset/lab.py`、`asset/coords.py`、`asset/skin.py`、`scene.py` | `data/lab_export/` + 一个四面体网格 → `scene.json` 等 | 每换一次资产、网格或设置 |
| ④ | 准备运动 | `uv run asrp convert-motion …`，或用现成的（选运动） | `src/asrp_core/trajectory.py`、`motions.py` | 实验室的运动文件 → `trajectory.json` | 每来一段新的运动 |
| ⑤ | 生成 `model.feb` | `uv run asrp run <scene.json> <trajectory.json>`（**Run**） | `src/asrp_core/generate.py` | `scene.json` + 运动里的骨头部分 → `model.feb` | 每次运行 |
| ⑥ | FEBio 计算 | 同上 | `src/asrp_core/run.py`、`febio.py` | `model.feb` → 每帧四面体节点的位置 | 每次运行 |
| ⑦ | 读回结果、嵌入显示网格 | 同上 | `src/asrp_core/run.py`、`embed.py` | 四面体结果 → 10,240 个嘴唇表面顶点的逐帧位置；沉降形状 | 每次运行 |
| ⑧ | 叠加 landmark 蒙皮 | 同上 | `src/asrp_core/skinning.py` | 物理结果 + landmark 位移 + 权重 → 最终形状 | 运动里有 landmark 时 |
| ⑨ | 合理性检查 | 同上 | `src/asrp_core/plausibility.py` | 结果 → 五项检查，外加只报告的翻转面和短边 | 每次运行 |
| ⑩ | 生成 PC2 回放包 | 同上 | `src/asrp_core/playback.py`、`provenance.py` | 结果 → `playback.json` + `playback.pc2`（有 ⑧ 时再加一份） | 每次运行 |
| ⑪ | Blender 播放 | 面板自动加载（或侧栏 Load Result） | `blender_addon/asrp_blender/__init__.py`、`asset.py`、`session.py` | 回放包 → 资产的五个物体在时间轴上动 | 每次运行后 |
| ⑫ | 和 Ziva 对比 | `uv run asrp compare <运行文件夹> <Ziva 导出文件夹> --out <输出文件夹>`（**Compare with Ziva**） | `src/asrp_core/ziva_compare.py`、`ziva_export.py`、`compare.py`；`blender_addon/asrp_blender/compare.py` | 我们的运行 + Ziva 的导出 → 对比报告、热力图数据、Ziva 嘴唇的回放包 | 想比的时候 |

⑤ 到 ⑩ 的总调度是 `src/asrp_core/simulate.py`，命令行入口是 `src/asrp_core/cli.py`（`asrp` 这个命令由 `pyproject.toml` 的 `[project.scripts]` 生成）。

## 2. ① Maya 导出（只做一次）

**做什么**：用普通 Maya（不需要 Ziva）打开实验室的场景，把原型要用的东西导出成开放格式。Maya 只在这一步出现，产品本身从不需要 Maya（ADR-18）。

| 文件 | 作用 |
|---|---|
| `tools/maya_export.py` | 在 `mayapy` 里运行。导出 5 个网格（嘴唇、下颌、颅骨、上下牙）的静止形状，写成场景坐标的 OBJ；`joints.json`（下颌关节 `jaw01` 和 300 个 landmark）；`skin_skinCluster7.json`（landmark 对嘴唇的蒙皮权重）；`mesh_report.json` |
| `tools/check_lab_export.py` | 不用 Maya，直接读 `.mb` 里的顶点，和导出的 OBJ 逐点核对 |
| `tools/mb_inventory.py`、`tools/lip_attachments.py` | 不用 Maya 解析 `.mb`，读出嘴唇的四组粘连顶点，写成 `data/lab_export/lip_attachments.json` |

**结果**：`data/lab_export/`，已提交。Ziva 机器上的导出（⑫ 要用的参考结果）是另一件事，见第 9 节。

## 3. ② 四面体化（只做一次）

**做什么**：FEBio 只能在体积网格上计算，实验室给的嘴唇只是一层表面，要先填满四面体（为什么必须做，见 [13](13-explanations.md) E-02）。网格直接从嘴唇 OBJ 读取，**不经过 Blender**。现在有两个网格，并存，按研究的需要选：

| 网格 | 命令 | 文件 | 特点 | 谁默认用它 |
|---|---|---|---|---|
| 细网格 | `uv run python tools/build_tetmesh.py` | `data/tetmesh/lips.json` | fTetWild 生成，约 26,700 个四面体；上下唇沿嘴缝分开，可以各自动（ADR-20） | 命令行的 `import-asset` |
| 粗格子 | `uv run python tools/build_tetmesh.py --method lattice` | `data/tetmesh/lips_lattice.json` | 规则立方格子，格边等于 Ziva 的四面体尺寸，126 个四面体；上下唇连成一块，和 Ziva 一样被下颌带着走；生成结果确定，算得快（ADR-44） | Blender 面板 |

两个都由 `src/asrp_core/tetmesh.py` 检查和读取，读取时校验内容哈希。**运行时从不重新生成**，只有显式运行 `tools/build_tetmesh.py` 才会改这两个文件。文件里记着嘴唇 OBJ 的 sha256；OBJ 的字节变了（比如行尾被转换），③ 就会报错。这时应该把 `data/` 按字节重新检出（[08](08-engineering-standards.md) 第 10 节，`.gitattributes`），不要重新生成网格。

## 4. ③ 生成场景描述 `scene.json`

**做什么**：把导出的资产换算成项目统一的单位和坐标轴（mm、Z 轴朝上），写成项目自己定义的场景描述，格式 `asrp-scene/1`。它回答"这个模型是什么"：软组织和材料、骨头跟着谁动、粘连、landmark、求解设置，以及每个参数的来源（实验室的设置，还是我们定的临时值）。

| 文件 | 作用 |
|---|---|
| `src/asrp_core/cli.py` | `asrp import-asset` 的入口和选项 |
| `src/asrp_core/asset/lab.py` | 主体：读 `data/lab_export/`，写 `scene.json`、换算后的网格、四面体网格的拷贝、`import_report.json` |
| `src/asrp_core/asset/coords.py` | 全项目唯一的一份单位和坐标轴换算（× 0.962，Y 朝上 → Z 朝上） |
| `src/asrp_core/asset/skin.py` | landmark 蒙皮权重换算成毫米、Z 朝上，写成 `landmarks/skin_mm.json` |
| `src/asrp_core/scene.py` | 场景描述的格式定义和校验；`uv run asrp check <scene.json>` 也用它 |

**常用选项**：

| 选项 | 默认 | 说明 |
|---|---|---|
| `--tetmesh` | `data/tetmesh/lips.json`（细网格） | 用粗格子就写 `--tetmesh data/tetmesh/lips_lattice.json` |
| `--tissue-settings` | `lab` | Ziva 里实测的材料（杨氏模量 12 kPa、泊松比 0.4、密度、子步数）；`ours` 是我们早先的值 |
| `--attachments` | `ours` | 上唇硬绑颅骨，其余用弹簧；`ziva-soft` 是四组都用按 Ziva 的软约束换算的弹簧，粗格子必须用它 |
| `--mm-per-scene-unit` | `0.962` | 长度换算 |

面板的 Open asset 就是在后台运行这条命令，用的是粗格子加 `--attachments ziva-soft`（选 Fine 时用细网格）。

**结果**：场景文件夹里的 `scene.json`、`meshes/`、`landmarks/`、`import_report.json`。格式要包含哪些信息见 [04](04-architecture.md) 第 5.1 节，字段写法见 `scene.py` 开头的说明。

## 5. ④ 准备运动 `trajectory.json`

**做什么**：写出"这次怎么动"，格式 `asrp-trajectory/1`：每帧骨头驱动源的变换（下颌 `jaw01` 转多少、头平移多少），前几帧只受重力的沉降段，可选的每帧 300 个 landmark 的位移，以及面板上显示的标题。同一个 `scene.json` 可以配不同的运动。

**三条现成的运动**，提交在 `data/lab_export/trajectories/`，面板的运动列表就是它们：

| 文件 | 是什么 | 怎么来的 |
|---|---|---|
| `neutral_to_AA.json` | 实验室真实的中性到 AA：下颌转 −5.16°，加 landmark 位移 | 实验室的运动文件经 `asrp convert-motion` 转换（T-34，ADR-42） |
| `jaw_open_12deg.json` | 原型机一的代用张嘴：下颌张到 12° 再合上 | `tools/placeholder_jaw_motion.py` |
| `head_shake.json` | 甩头，按实验室脚本的关键帧 | `tools/head_shake_motion.py` |

**新的运动**：实验室控制器的输出是 Python pickle 文件（`combined_checkpoints.pkl`），用一条命令转换，**不需要写新的代码**：

```bash
uv run asrp convert-motion <实验室的运动文件> <scene.json> <输出的 trajectory.json> --starts-at-rest --title "<面板上显示的名字>"
```

| 文件 | 作用 |
|---|---|
| `src/asrp_core/trajectory.py` | 运动文件的格式、读写、校验；铰链运动的生成；`read_lab_motion` 安全地读实验室的 pickle（只接受基本容器和数组，不执行文件里的代码），`from_lab_motion` 做转换 |
| `src/asrp_core/motions.py` | 列出一个导出文件夹里有哪些运动（`asrp list-motions`，面板的运动列表就用它） |
| `tools/placeholder_jaw_motion.py`、`tools/head_shake_motion.py` | 我们自己造的两条运动 |

`asrp set-motion-title <文件> "<标题>"` 可以改面板上显示的名字。现在的转换只处理"从中性出发的一段过渡"；实验室一般的运动文件怎么转，还在 T-10 里。格式要包含哪些信息见 [04](04-architecture.md) 第 5.2 节，字段写法见 `trajectory.py` 开头的说明。

## 6. ⑤–⑩ 一次运行：`asrp run`

```bash
uv run asrp run <scene.json> <trajectory.json>
```

`src/asrp_core/simulate.py` 按下面的顺序做完全部步骤，所有输入和结果都放进同一个运行文件夹（默认在 `runs/` 下，[04](04-architecture.md) 第 4 节）。面板上的 Run 就是在后台运行这条命令。

**⑤ 生成 `model.feb`**：`generate.py` 把场景和运动翻译成 FEBio 的输入：坐标乘 k（ADR-36）、重力反号（[05](05-ziva-to-febio.md) 坑 1）、刚体、粘连、动力学设置。**它只读运动里的骨头部分，landmark 那一节不进 FEBio。** 场景不合格时它拒绝生成，不建运行文件夹。

**⑥ FEBio 计算**：`run.py` 建运行文件夹、拷入输入、启动 FEBio、读进度、可以取消；`febio.py` 负责真正调用 `febio4.exe`（默认 4 线程，ADR-38）。

**⑦ 读回结果、嵌入显示网格**：`run.py` 读回每帧四面体节点的位置并除以 k；`embed.py` 让实验室精细的嘴唇表面（10,240 个顶点）按重心坐标跟着四面体网格动。后面的步骤和播放用的都是这个表面。沉降段最后一帧（第 14 帧）的形状单独存一份，它是控制器优化的起点（ADR-30）。

**⑧ 叠加 landmark 蒙皮**：只在运动里有 `landmarks` 一节时才做。`skinning.py` 计算 最终形状 = 物理结果 + 权重 × landmark 位移。物理结果原样保留，最终形状另存一份。为什么放在物理之后：实验室的场景和源码就是先物理、后蒙皮（ADR-29，[04](04-architecture.md) 第 2 节）。

**⑨ 合理性检查**：`plausibility.py` 做五项检查（[07](07-validation.md) 第 3 节）：运动算完了没有、硬粘住的地方跟着骨头走没有、弹簧锚跟着刚体走没有、重力是不是往下拉、四面体有没有被压翻。任何一项不通过，命令以非 0 退出。另外报告显示表面的翻转面和短边，和 Ziva 自己的数并排看，只报告、不判合格（ADR-43）。

**⑩ 生成 PC2 回放包**：`playback.py` 写出 `playback.json`（表面网格和元数据）和 `playback.pc2`（每帧顶点坐标）；做了 ⑧ 时再加一份最终形状的点缓存。`provenance.py` 写溯源记录。PC2 格式和回放包见 [04](04-architecture.md) 第 5.3 节。

## 7. ⑪ Blender 播放

**做什么**：资产的五个物体（颅骨、下颌、上牙、下牙、嘴唇）在 Open asset 时就建好了；Run 算完以后，嘴唇挂上一个 Mesh Cache 修改器读 PC2，骨头按 `trajectory.json` 每帧打关键帧，时间轴设成运动的帧数和帧率，按空格播放。再跑一次只替换修改器和关键帧，不换物体。Blender 不做任何计算。

| 文件 | 作用 |
|---|---|
| `blender_addon/asrp_blender/__init__.py` | 面板和按钮：三个步骤、Checks（五项检查和翻转面）、只读的 Physics setup、Load Result（手动加载一个运行文件夹，可以切换物理层和最终形状） |
| `blender_addon/asrp_blender/asset.py` | 三步的实现：Open asset 在后台运行 `asrp import-asset` 和 `asrp list-motions` 并建出物体；运行结束后把结果放到这些物体上 |
| `blender_addon/asrp_blender/session.py` | 在后台启动 `asrp run`（和 `asrp compare`），显示进度、可以取消 |
| `tools/render_prototype.py` | 可选：不开界面，把一次运行渲染成图，并逐帧核对 Blender 里的嘴唇和 FEBio 的数字 |

面板上每一步该看到什么、截图，见 [15](15-prototype.md) 第 2 节；插件的安装见仓库根目录的 [README](../README.md)；面板设计见 [06](06-ui.md)。

## 8. ⑫ 和 Ziva 对比

**做什么**：把我们一次运行的嘴唇，和 Ziva 同一段运动、同一帧的嘴唇逐个顶点比，物理层（蒙皮前）和最终形状（蒙皮后）分开报告，每帧给出平均、95%、最大三个数（[07](07-validation.md) 第 4.2 节）。和 Ziva 差多少只作参考，不设合格线（ADR-17）。

```bash
uv run asrp compare <我们的运行文件夹> <Ziva 的导出文件夹> --out <输出文件夹>
```

| 文件 | 作用 |
|---|---|
| `src/asrp_core/ziva_export.py` | 读 Ziva 的导出文件夹（每条数据流的点、静止形状、运动记录），按文件里真实有的帧取 |
| `src/asrp_core/compare.py` | 算两组形状的差：平均、95%、最大；只有数字，不判断 |
| `src/asrp_core/ziva_compare.py` | `asrp compare` 的主体：换算 Ziva 的坐标，逐帧比，写 `compare_report.json`、热力图数据（`heatmap_*.f32`）和 Ziva 嘴唇的回放包 |
| `blender_addon/asrp_blender/compare.py` | 面板的 Compare with Ziva：显示差别数字，把 Ziva 的嘴唇作为第二个物体放进来，按每个顶点的差上色 |
| `tools/ziva_comparison.py` | 整套对比一次做完（导入、转换运动、运行 AA 和甩头、和 Ziva 两次运行比），写一份数字报告（T-34） |
| `tools/render_comparison.py` | 结果页用的对比图和动图 |

**Ziva 的导出从哪来**：Ziva 机器上用 `tools/ziva_machine_export.py` 导出（[12](12-lab-export-checklist.md)，上机的结果见 [13](13-explanations.md) E-11）。这些是实验室的数据，**放在仓库外面**：`tools/lab_trip_manifest.py` 给带回来的文件建清单，本机的位置记在被 git 忽略的 `.local/` 里，代码通过 `tools/local_paths.py` 读取。`asrp compare` 的输出里有 Ziva 的形状，所以输出文件夹也必须在仓库外，或放在 git 不收的 `runs/` 下。

**现在的数字**（中性到 AA，第 36 帧，物理层，对 Ziva 整张脸）：粗格子平均 1.88 mm、最大 5.12 mm（[01](01-overview.md)；细节见 [13](13-explanations.md) E-19 和 [15](15-prototype.md)）。

## 9. 几个容易误会的地方

- **Blender 不在中间**：导出的 OBJ 由 `asrp_core` 直接读取。面板上的按钮也只是调用 `asrp` 命令。`tools/blender_import_preview.py` 会把网格导入 Blender，但它只生成预览图，让人看一眼导出对不对，不在计算流程里。
- **不是所有输入都进 FEBio**：`scene.json` 和运动里的骨头部分经 `generate.py` 进 FEBio；landmark 位移和蒙皮权重不进，它们在 FEBio 算完之后才用到（⑧）。
- **`scene.json`、`trajectory.json` 是项目自己定义的格式**，不是 FEBio 的。项目自己的格式都以 `asrp-` 开头，比如 `asrp-scene/1`、`asrp-trajectory/1`、`asrp-playback/1`、`asrp-skin/1`。拆成中间文件，是为了同一个模型能配不同的运动，嵌入、检查、回放也能读它们，并且以后换求解器只需要重写 ⑤（[04](04-architecture.md) 第 6 节）。
- **四面体网格不是每次运行时生成的**：两个网格都只由 `tools/build_tetmesh.py` 显式生成一次（ADR-20、ADR-44）。
- **新的运动不需要新的代码**：实验室的运动文件用 `asrp convert-motion` 转换；只有我们自己造的代用运动才各有一个脚本。
- **训练线和回放线是两条路**：本文讲的是回放线，即物理逐帧算、再叠 landmark。实验室训练控制器时要的是另一件事：每一步给出"静止形状 + landmark 位移"的嘴唇，不跑 FEBio。这个接口是 `src/asrp_core/final_shape.py`（T-31，[13](13-explanations.md) E-13）。

## 10. 还没做完的

| 什么 | 状态 | 任务 |
|---|---|---|
| 实验室一般的运动文件怎么转换（现在只处理从中性出发的一段过渡） | 运动文件已取回，单段过渡已做 | T-10 |
| 物理尺度和重力对齐 Ziva：我们的重力下垂比 Ziva 小得多 | 没开始，要再上一次 Ziva 机器校准 | T-41 |
| 让代码的默认值跟上实测的事实 | 部分完成 | T-37 |
| 在 Blender 里照 Ziva 的流程自己搭场景（标骨头和软组织、建四面体、看见粘连） | 没开始 | T-39 |

## 11. 每一步的细节在哪里

| 想知道 | 看 |
|---|---|
| 系统分哪几块、每个模块负责什么、运行文件夹里有什么 | [04](04-architecture.md) 第 1、3、4 节 |
| `asrp run` 点下去以后的步骤（从插件的角度） | [04](04-architecture.md) 第 8 节 |
| `scene.json`、`trajectory.json`、回放包要包含什么 | [04](04-architecture.md) 第 5 节 |
| Ziva 的每样设置在新系统里怎么表达、踩过的坑 | [05](05-ziva-to-febio.md) |
| 面板上怎么操作、每一步应该看到什么、命令行的做法 | [15](15-prototype.md) 第 2 节 |
| 和 Ziva 差多少、为什么 | [15](15-prototype.md)、[13](13-explanations.md) E-19 |
| Maya 导出和 Ziva 机器上的导出 | [12](12-lab-export-checklist.md) |
| 为什么要四面体化、为什么有两个网格 | [13](13-explanations.md) E-02、ADR-20、ADR-44 |
| 合理性检查查什么 | [07](07-validation.md) 第 3 节 |
