# 04 系统设计

给谁看：开发者。读完能知道软件分成哪几块、每块负责什么、数据怎么在它们之间流动、和实验室的代码在哪里分界；只看这份文档和自己的任务卡，就知道自己写的东西放在哪、要和谁对接。要什么写在 [02](02-requirements.md)，Ziva 到 FEBio 的对应写在 [05](05-ziva-to-febio.md)，做到哪了只看 [09](09-roadmap-and-tasks.md)。

## 1. 总体结构

```
┌──────────────────── Blender ────────────────────┐
│  ASRP 插件（只管界面）                           │
│  导入资产 · 检查设置 · 运行 · 回放 · 对比          │
└───────────────┬─────────────────────▲───────────┘
                │ 调用命令行，传文件夹路径 │ 读取结果文件
                ▼                     │
┌──────────── asrp_core（独立程序）─────┴──────────┐
│  资产导入 → 场景描述 → 四面体化 → 生成 FEBio 输入   │
│  → 调用 FEBio → 读结果 → landmark 变形层          │
│  → 回放包 · 对比报告 · 溯源记录                   │
└───────────────┬─────────────────────▲───────────┘
                │ .feb 输入文件          │ 日志和结果
                ▼                     │
            ┌────────── FEBio ──────────┐
            │  有限元求解（不改它的代码）  │
            └───────────────────────────┘

所有输入、中间文件、结果都落在一个"运行文件夹"里。
```

三条基本原则：

1. **Blender 只管界面。** 插件里不写任何计算逻辑。插件崩了或者以后换成别的界面，计算部分完全不受影响。
2. **核心程序不依赖 Blender。** 可以单独在命令行里运行，以后实验室的控制器也通过它来调用物理计算。
3. **模块之间只通过文件交换数据。** 每一步的输入、输出都能单独打开检查，出了问题能定位到具体哪一步。

## 2. 两段计算

最终的嘴唇形状由两段计算叠加而成，系统也按这两段来设计。依据是[资产分析](03-asset.md)第 4 节和实验室源码（ADR-29），并在 Ziva 里实测过：Ziva 的蒙皮前形状加上"权重 × landmark 平移"，还原出 Ziva 的蒙皮后形状，47 帧、10,240 个顶点里最大误差 0.000016 mm（[13](13-explanations.md) E-11）。

| 段 | 做什么 | 由谁算 | 输入 | 输出 |
|---|---|---|---|---|
| **物理段** | 下颌带动嘴唇，加上重力、惯性、组织之间的粘连 | FEBio | 场景描述 + 骨头的运动（landmark 不进物理，进物理的只有下颌这类骨头运动） | 每帧"只有物理"的嘴唇形状；其中**沉降后的形状**（由运动文件的 `settle_until_frame` 指定，实验室的运动和我们的代用运动都是第 14 帧）单独交出，它是控制器优化的起点（ADR-30）；每帧每块组织的应变能，只作诊断输出（ADR-33） |
| **landmark 段** | 300 个 landmark 的蒙皮变形叠加在物理结果上 | 我们自己的代码（纯几何，不需要 FEBio） | 物理段的结果 + landmark 运动 + 蒙皮权重 | 每帧最终的嘴唇形状 |

分成两段的好处：和 Ziva 对比时，可以先单独比较物理段。差异出在物理还是出在 landmark 层，一眼就能看出来。

landmark 段是物理之后的**可替换层**：先物理，后 landmark 蒙皮。这个顺序和实验室源码、论文 Algorithm 2 的第 12、13 步一致（先在物理模拟器开着的情况下把优化出的控制量作用到枢轴，再由 landmark 经 LBS 公式给出最终轨迹，ADR-29），也在 Ziva 场景里实测过（11 的 Q21，E-11）。以后若要加一个"landmark 进物理"的模式，只是多一种输入，不用重建（第二阶段，现在不做）。

## 3. 模块和职责

每个模块归哪张任务卡、做到哪了，只看 [09](09-roadmap-and-tasks.md)。

| 模块（代码位置） | 负责 | 不负责 |
|---|---|---|
| 环境检查 `asrp_core/doctor.py` | 找到 FEBio、Blender，检查路径和 Python 版本 | — |
| 资产导入 `asrp_core/asset/` | 把从 Maya 导出的网格、landmark 蒙皮和 Ziva 设置读进来，换算单位和坐标轴（全项目唯一的一份换算，`asset/coords.py`），生成场景描述和 `import_report.json`（换算系数、坐标轴、网格、每个参数的来源、"缺了什么"、场景检查结果）；把四组粘连、k 和材料写进场景（材料现在的默认值和 Ziva 实测值的差别见 [05](05-ziva-to-febio.md) 第 4 节）；把 landmark 蒙皮矩阵换算成毫米、Z 轴朝上、列向量，写成 `landmarks/skin_mm.json`（`asset/skin.py`，格式 `asrp-skin/1`，ADR-34） | 解析 .mb 的网格几何 |
| 场景描述 `asrp_core/scene.py` | 定义场景描述文件的格式，提供校验（缺什么、单位对不对） | 求解 |
| 运动 `asrp_core/trajectory.py` | 运动文件的格式和读写、铰链运动生成（代用运动）、`landmarks` 一节的校验和读成数组 | 转换实验室的运动文件（T-10 在同一个文件里加） |
| 四面体化 `asrp_core/tetmesh.py` | 把嘴唇的表面网格变成计算用的四面体网格，检查质量（连通、流形、亏格、上下唇分开、左右对称），写成 `data/tetmesh/` 下的文件，读回时校验哈希（为什么需要，见 [13](13-explanations.md) E-02） | 嵌入显示网格；运行时重新生成网格（只由 `tools/build_tetmesh.py` 显式生成，ADR-20） |
| FEBio 适配 `asrp_core/febio.py` | 调用 FEBio（默认 4 线程，可用 `--threads` 改，[05](05-ziva-to-febio.md) 坑 17，ADR-38；含结束整个进程树），读回结果 | 决定材料参数（参数从场景描述里来） |
| 生成器 `asrp_core/generate.py` | 场景描述 + 运动 → `.feb`：坐标 × k、重力反号、刚体（固定、给定、锚）、粘连的对应（05 第 3 节）、动力学设置；生成器报告 | 运行 FEBio；读结果 |
| 嵌入 `asrp_core/embed.py` | 显示网格跟着四面体网格动（zEmbedder 的替代）：每个显示顶点的四面体和重心坐标，粘连也用同一套 | — |
| 合理性检查 `asrp_core/plausibility.py` | [07](07-validation.md) 第 3 节的五项检查 (a)(b)(b2)(c)(d)；"没运行"（`passed` 为 `null`）不算失败，只有明确的 `false` 才算（ADR-37） | — |
| 场景运行 `asrp_core/simulate.py` | `asrp run <scene.json> <trajectory.json>`：生成器 → 运行外壳 → 嵌入、沉降后的形状、landmark 层（运动文件有 `landmarks` 一节时）、回放包、合理性检查、运行报告 | 运行文件夹的外壳（`run.py`） |
| 运行外壳 `asrp_core/run.py` | 一次运行 = 一个文件夹：拷入输入、启动 FEBio、进度（只读日志新增的部分）、取消、出错处理、读 FEBio 写的 `positions.txt`、把位置除以 k 后存成 `physics/positions.json` + `positions.npy`、写溯源；也能直接跑现成的 `.feb`（替身模式） | 生成 FEBio 输入（`simulate.py` 通过 `run.Prepared` 接入） |
| landmark 变形层 `asrp_core/skinning.py` | `deform(base, weights, translations)` = base + weights @ translations，运行用的就是这一个核；`deform_matrices` 是一般的矩阵形式，只用来证明换算和化简；`load` 读 `landmarks/skin_mm.json` | — |
| 训练接口 `asrp_core/final_shape.py` | `final_shape(下颌转动, landmark 位置)`：实验室训练环境每一步要的嘴唇形状，不经过 Maya（第 12.4 节）；基底取一次已完成的运行的沉降形状。下颌转动不改变基底：同一帧里转下颌，Ziva 不重新求解（11 的 Q20，E-11） | 推进物理；实验室的目标函数和梯度 |
| 回放包 `asrp_core/playback.py` | 把结果打包成 Blender 能直接播放的格式；有 landmark 层时多写一份最终形状的点缓存（5.3） | — |
| 对比 `asrp_core/compare.py` | 读入 Ziva 参考结果，计算误差，出报告和热力图数据（T-11；比什么和什么见 [07](07-validation.md) 第 4.2 节） | — |
| 溯源 `asrp_core/provenance.py` | 记录每次运行的输入指纹、软件版本、参数 | — |
| 命令行 `asrp_core/cli.py` | 把上面的功能包装成命令（见第 7 节） | — |
| Blender 插件 `blender_addon/asrp_blender/` | 界面（见 [06](06-ui.md)），调用命令行，加载结果；`session.py` 管子进程；面板上的文字是英文 | 任何计算 |

## 4. 运行文件夹

每次运行一个文件夹，放在 `runs/<运行编号>/` 下面，**里面的东西足以独立重现这次运行**：

```
runs/2026-11-03_neutral-to-AA_001/
  scene.json          场景描述（这次用到的全部设置）
  trajectory.json     这次的运动（每个驱动源每帧的刚体变换、landmark 每帧的平移）
  meshes/             用到的网格（毫米、Z 轴朝上），包括已落盘的四面体网格（只读，哈希记在 provenance.json）
  landmarks/          场景引用的 landmark 蒙皮 `skin_mm.json`（毫米、Z 轴朝上、列向量，`asrp-skin/1`；导入时换算好，原样拷进来）
  model.feb           生成的 FEBio 输入
  model.log           FEBio 日志（只有进度和提示，约 0.15 MB；节点位置不在这里）
  physics/            物理段结果（含沉降后的形状 settled_frame{n}；n 是运动文件的 settle_until_frame；只有运动文件写了 n ≥ 1、而且第 0 到 n 帧所有被用到的驱动源都停在静止位置时才写沉降形状，否则运行报告说明它不可用；每帧每块组织的应变能放在这里，格式在 T-26 定）
  final/              叠加 landmark 段之后的结果（`display.json` + `display.npy`；只有运动文件有 `landmarks` 一节时才有）
  playback.json       回放包（Blender 加载用）
  playback.pc2
  playback_final.pc2  最终形状的点缓存（同样只在有 landmark 层时才有）
  run_report.json     运行报告（键见下面"运行报告的内容"）
  compare/            和 Ziva 对比的报告（如果做了对比）
  provenance.json     溯源记录
```

`asrp run <scene.json> <trajectory.json>`（T-06a，`simulate.py`）现在写出：

1. 场景文件夹里场景引用的每个文件，按原来的相对路径拷进来（所以运行文件夹里的 `scene.json` 能直接再跑），运动改名为 `trajectory.json`；
2. `physics/positions.json` + `physics/positions.npy`：外壳写的，FEBio 的全部计算点，只有第 1 到 N−1 帧（坑 15）；
3. `physics/display.json` + `physics/display.npy`：显示网格每帧的位置，第 0 帧是静止姿态；
4. `physics/settled_frame{n}.json`（格式名 `asrp-settled/1`：`units`、`frame`、`time_s`、`tet_nodes`、`display`）和 `physics/settled_frame{n}.obj`（同一帧的显示网格，带面）。n 是运动文件的 `settle_until_frame`，实验室的运动和代用运动都是 n = 14；
5. 回放包：是显示网格本身（嘴唇 10,240 个顶点，不是四面体网格的表面，`node_ids` 为 null）；
6. 运动文件有 `landmarks` 一节时：`final/display.json` + `final/display.npy`（格式名 `asrp-display/2`，和 `physics/display.*` 相同，内容是物理结果加 `weights @ translations`）和 `playback_final.pc2`；`playback.json` 多一个可选键 `versions`（5.3）。没有这一节时这些都不存在，`playback.json`、`playback.pc2` 和 `physics/` 和以前逐字节相同，运行报告只多一个 `landmark_layer`（`applied` 为 `false`）；
7. `run_report.json`。

**运行报告的内容**（`run_report.json`，格式名 `asrp-run-report/1`，07 第 3 节），每个键写一次：

| 键 | 含义 |
|---|---|
| `run_id` | 这次运行的编号 |
| `status` | `complete`、`failed`、`cancelled` 三个值之一 |
| `frames` | 帧数 |
| `passed` | 整次运行是否通过 |
| `parameters` | 临时值和来源；运动那一行的来源取运动文件的 `source_tag`，没写记 `unstated` |
| `simplifications` | 场景 `simplifications` 里的说明，原样照抄；场景没写就是空列表（取代原来的 `attachments_not_built`） |
| `warnings` | 警告列表 |
| `generator` | 生成器报告 |
| `checks` | a、b、b2、c、d 五项，每项是 `name`、`passed`（`true`、`false` 或 `null`）、`message`、`numbers`；d 的数字是 `min_volume_ratio`、`min_volume_ratio_frame`、`max_volume_ratio`、`inverted_tets`、`frames_with_inverted_tets` |
| `not_run` | 没运行的检查的汇总（属于 `checks`） |
| `settled_shape` | `available`（骨头在沉降期间没动）、`frame`（n，没有沉降形状时为 `null`）；不可用时多一个 `reason`。可用时另有只报告的键：`tissue_step_max_mm`、`tissue_step_mean_mm`（四面体节点在第 n−1 到第 n 帧之间移动的最大、平均距离，几何 mm）、`tissue_step_frames`（`[n-1, n]`），以及 `tissue_settled`（这个最大距离是否小于 `tissue_settled_limit_mm` = 0.001 mm，和硬粘连的容差同一个数）。`tissue_settled` 不改变 `passed`，但训练接口（`final_shape.load`）默认不接受没停住的基底。n = 1 时比的是第 1 帧和静止姿态，量到的是整个重力下垂，所以总是"没停住"：一帧的沉降说明不了组织停没停 |
| `surface_health` | 只报告，不是检查（五项检查只看物理的四面体网格，这一项看研究员看到的表面）：显示表面的面和边相对静止形状（显示网格的第 0 帧）。`physics`（物理结果）和 `final`（叠上 landmark 层之后；没有 landmark 层时是 `null`）各有 `last`（最后一帧）和 `worst`（翻面最多的那一帧，并列时取边长超出一半到两倍范围最多的；多一个 `frame`）。每个里面：`flipped_faces`（法线与静止法线点积小于 0 的面数）、`edges_shorter_than_half`、`edges_longer_than_double`、`edge_ratio_min`、`edge_ratio_max`、`min_face_area_ratio`、`faces`、`edges`；另有 `note`。翻面不等于自交，穿插没有测 |
| `return_to_settled` | 只报告，`{frames, max_mm, mean_mm}`；没有这样的帧时 `frames` 是空列表 |
| `relative_to_head` | 只报告（T-28）：每帧自由显示顶点（没有粘连的）相对头的最大位移，减去参考帧的值。"头"是 `hard` 粘连所粘的那个刚体（实验室场景里是颅骨，头的驱动源动时它跟着动）；`hard` 粘连没有、或粘到两个以上刚体时相对世界。参考帧是沉降形状那一帧，没有沉降形状时是第 0 帧。键：`body`、`reference_frame`、`per_frame_max_mm`（每帧一个数）、`max_mm` 和 `frame`（只在参考帧之后找：参考帧之前的曲线是沉降本身）、`free_vertices` |
| `motion` | 任一显示顶点离静止位置最远的距离 `max_display_distance_mm` 和出现的帧 `frame` |
| `landmark_layer` | landmark 层有没有叠上：`applied`（`true` 或 `false`）。`true` 时另有 `landmarks_moved`（运动文件里有过非零平移的 landmark 个数）、`max_translation_mm`（最大的平移）、`max_final_minus_physics_mm`（最终形状离物理结果最远的距离）和 `frame`（它出现的帧）；`false` 时另有 `reason`。五项检查仍然只检查物理结果 |
| `spring_slip` | 每个弹簧组的 max\|u\|、δ、比值和是否超过 0.1 |
| `timing` | `generate_s`、`febio_s`、`febio_s_per_frame`、`post_s`；没有速度预算的键：耗时只报告，不和别的数并排（ADR-38 第 5 条） |
| `reason` | 见 `settled_shape`：沉降形状不可用时的原因 |

运行用的线程数记在溯源里（`febio_env`）。应变能的键在 T-26 定，`compare/` 的内容在 T-11 定。

**失败的运行不留结果**（ADR-37 第 4 条，T-25）：
1. FEBio 失败或取消，或整段没有全部算完，只写 `run_report.json`（检查 (a) 不通过），不写任何结果；
2. FEBio 跑完了但**我们自己的事后处理出错**（读位置、嵌入、写回放包、报告里有 NaN 等）：运行同样记为 `failed`，删掉 `physics/`、`final/`、`playback.json`、`playback.pc2`、`playback_final.pc2`，报告里去掉 `settled_shape`、`return_to_settled`、`spring_slip`、`motion`、`landmark_layer`、`relative_to_head`、`surface_health`，检查 (a) 不通过，原因写 `post-processing failed after FEBio finished: …`（路径已抹掉）。不会出现"看起来算完了"的运行；
3. 无论成功、失败还是取消，只删除 FEBio 写的 `positions.txt` 和 `model.xplt`（见下面）；别的名字的文件不碰。

生成器拒绝的场景（检查有错、显示顶点离四面体太远、一个点被两个刚体要走……）不建运行文件夹，`asrp run` 打印原因和 `run NOT STARTED`。

`runs/` 不进 git。`data/` 里提交的有 `lab_export/`、`preview/`、`briefing/`、`tetmesh/`（四面体网格是只读输入，ADR-19、ADR-20），其余不进。四面体网格是**显式生成一次、落盘并记哈希的输入**，运行时只读，不在运行中重新生成（fTetWild 同输入多次运行结果不同，见 ADR-20 和 [13](13-explanations.md) E-03）。需要分享某次运行时，把整个文件夹打包发送。

**位置和显示网格存成数组，日志不装坐标**（T-25，ADR-38 第 10 条）。生成的 `.feb` 让 FEBio 把节点位置写进自己的文件 `positions.txt`（和 `.feb` 同目录，每条记录是 `*Step`、`*Time`、`*Data  = positions`，然后每行 `id,x,y,z`，12 位有效数字），不再写进 `model.log`。整段算完后外壳读它、存成数组，再把它删掉（和 `model.xplt` 一样；失败和取消的运行也删；只删这个名字的文件，别的名字不碰）。两个结果各由一个小的 JSON 表头和一个 `.npy` 组成，数字在 `.npy` 里；表头里都有 `format`、`units`（`mm`）、`array`（`.npy` 的文件名）和 `shape`：

| 文件 | 格式名 | 内容 |
|---|---|---|
| `physics/positions.json` | `asrp-positions/2` | 表头另有 `times_s`（每帧的时间）、`node_ids`（FEBio 的节点编号） |
| `physics/positions.npy` | — | float64，帧 × 节点 × 3，几何毫米（已除以 k） |
| `physics/display.json` | `asrp-display/2` | 表头另有 `fps`、`frames`、`vertex_count`、`mesh`（显示网格的文件）、`note`；没有 `times_s` 和 `node_ids` |
| `physics/display.npy` | — | float64，帧 × 显示顶点 × 3 |
| `final/display.json` | `asrp-display/2` | 同 `physics/display.json`，`note` 写明是物理加 landmark 层；只有运动文件有 `landmarks` 一节时才有 |
| `final/display.npy` | — | float64，帧 × 显示顶点 × 3，几何毫米 |

沉降形状（`settled_frame{n}.json`，格式名 `asrp-settled/1`，和 `.obj`）、`playback.json`、`playback.pc2` 的格式没变，同一次运行的回放文件和以前逐字节相同。进度只读日志上次读过之后新增的部分，不再每次重读整个日志。运行外壳的 `provenance.json` 在 `outputs` 里同时列出每个结果的表头和数组。实测的大小和用时见 [10](10-decisions.md) ADR-38 第 10 条和 [15](15-prototype.md) 第 3 节。

替身模式（T-08）的运行文件夹只有 `model.feb`、`model.log`、`physics/positions.json` + `physics/positions.npy`（每帧每个节点的位置，几何毫米：已除以 k，ADR-36）、`provenance.json`，FEBio 的 `.xplt` 运行结束后删掉；替身 `.feb`（`asrp run --feb`）自己把位置记进日志，所以仍从 `model.log` 里读；失败和取消的运行没有 `physics/`；`provenance.json` 里不写任何本机绝对路径，输入按文件夹内的名字记哈希，所以整个文件夹复制到别处也能原样重跑。

## 5. 主要文件的内容

格式细节（字段名、类型）写在代码的格式说明里：`src/asrp_core/scene.py`、`src/asrp_core/trajectory.py` 开头（T-05 定稿），运行结果的格式在 `src/asrp_core/run.py`、`simulate.py` 开头。这里只规定**必须包含的信息**，并给出每个键的名字（格式名：`asrp-scene/1`、`asrp-trajectory/1`）。

两条通用规则：
- **大数组不内嵌。** 网格、四面体网格、landmark 蒙皮权重都是被引用的文件，`scene.json` 里只写路径和 sha256。场景文件因此能用眼睛读，文件被改过也一查哈希就知道。例外是粘连权重：它是稀疏列表，直接写在 `scene.json` 里；单个粘连超过一万项时再改成引用文件（ADR-34）。
- **四面体网格的引用要核对三件事，任何一项不符都是错误，并提示重新生成网格**：(1) 内容哈希；(2) 网格里记录的源表面 sha256 等于场景里该网格的原始 OBJ 的 sha256；(3) 网格里记录的 `mm_per_scene_unit` 等于场景的（`scene.py` 用 `tetmesh.load` 读时核对）。
- **校验结果分"错误"和"提醒"。** 错误是算不了或会算错（缺文件、哈希不符、连接没有有效顶点……），`asrp check` 失败；提醒是能算、但缺了要补的东西（比如软组织还没有任何连接），`asrp check` 照样通过，提醒要写进导入的检查报告。

### 5.1 场景描述 `scene.json`

| 部分 | 必须包含 |
|---|---|
| 单位 | 固定为 mm、N、MPa、s；记录每个网格原来的变换、从原始资产换算过来的系数和坐标轴转换（顺序见 [03](03-asset.md) 第 10 节）。**几何单位和物理尺度分开**（ADR-22）：`units.mm_per_scene_unit`（几何，0.962，**必填**）；`units.physics_length_scale`（无量纲 k，**可以不写**，不写时取 1.0 并把来源标成"我们定的"；第一阶段按真人大小取 0.67，由导入写进场景，T-06a 实现，ADR-31）：求解器把模型当成几何尺寸的 k 倍大来算，几何和输出仍是毫米；实现是 FEBio 里节点坐标 = 几何毫米 × k、物理参数不缩放、读回除以 k（[05](05-ziva-to-febio.md) 第 2 节，ADR-36） |
| 软组织 | 名字、网格文件、原始 OBJ 的文件名和 sha256、四面体网格文件及其内容哈希、材料（类型和参数）、每个参数的来源（实验室设置 / Ziva 默认值 / 我们定的） |
| 骨头 `bones` | 名字、网格文件、原始 OBJ 的文件名和 sha256、质量 `mass_t`（值可以是 `null`：未知，运动是固定或完全给定时用不到）、运动方式 `motion`：**`"fixed"`（固定）或 `"prescribed"`（给定）**（ADR-21）。给定时用 `driver` 写明**跟随哪个驱动源**，运动由 `trajectory.json` 里这个驱动源的每帧变换提供 |
| 驱动源 `drivers` | 名字（实验室资产里就是关节名，比如 `jaw01`），以及可选的铰链说明 `hinge`（`pivot_mm`、`axis`、`source`、`note`），用来生成代用运动和做检查。一个驱动源可以带动几块骨头：下颌和下牙都跟随 `jaw01`，和 Maya 里一个关节同时带动两块骨头一样（[03](03-asset.md) 第 4 节）。**派生驱动源**（T-06a 补充，见本节末的"嘴角的锚"）：可以不带自己的运动，写成"驱动源 X 的 factor 倍"，由 X 的整个刚体运动算出来；可选 `relative_to`（T-28）。**可选 `absent_means_rest`**（T-28，不能和 `blend` 同时有）：为 `true` 时运动文件可以不写这个驱动源，它就停在静止位置；跟着它的骨头这时按固定的骨头写进 FEBio，`.feb` 和以前逐字节相同。实验室场景里头的驱动源 `head` 带动颅骨和上牙，就是这样标的，所以只写 `jaw01` 的运动文件照旧能跑 |
| 连接 | 连接的两样东西、每个顶点的权重（稀疏列表 `[[顶点, 权重], ...]`）、刚度、类型。类型是 [05](05-ziva-to-febio.md) 第 3 节的两种做法：硬绑定（`hard`，没有刚度）或弹簧（`spring`，刚度 × 权重）。第一阶段：上唇 `hard`、下唇 `spring`、嘴角 `spring` 连到"锚"（05 第 3 节，ADR-32）；Ziva 里 140 个粘连全是软约束，差别见 05 第 4 节。粘连顶点怎么对应到计算点见 05 第 3 节。`to` 可以是骨头，也可以是下面的锚 |
| 锚 | 可选。名字，以及它跟随哪个驱动源（`anchors` 一节，见本节末）。锚是不显示、不参与碰撞、没有网格的刚体 |
| landmark `landmarks` | 可为 `null`。`names`、静止位置 `rest_positions_mm`、对嘴唇顶点的蒙皮权重 `weights`（被引用的文件 `landmarks/skin_mm.json`，格式 `asrp-skin/1`：`names`、`rest_world`、`bind_pre`、`geom`（列向量 4×4，毫米、Z 轴朝上，导入时换算，T-09）、稀疏的 `weights`、`source`（实验室导出文件的名字和原始文件的 sha256））、`note` |
| 求解设置 `solver` | `fps`、`substeps_per_frame`、`damping`、`gravity_mm_per_s2`（物理方向）、分析类型 `analysis`（动力学），可选的 `numerical_damping_rhoi`（T-28）。场景不记帧数：运动的帧率必须等于这里的帧率，帧数由 `trajectory.json` 给出。`damping` 是物理阻尼：FEBio "mass damping" 体载荷的 C（1/秒，f = −C ρ v），0 是没有（[05](05-ziva-to-febio.md) 第 4 节）。`numerical_damping_rhoi` 是 FEBio 的 `rhoi`：0 到 1，或 −2（Newmark，没有数值阻尼）；不写时取生成器的默认 0，场景写回时也不写。两个都进运行报告的 `parameters`，带来源 |
| 来源 `origin` | 从哪个资产文件、哪次导出生成的（`asset`、`export`、`tool`、`notes`） |
| 简化说明 `simplifications` | 可选。字符串列表（非空字符串），写"这个场景没建什么、简化了什么"，由导入器写（嘴唇场景三句：嘴周 6 块肌肉没建、9 处皮肤粘连没建、嘴角到颅骨和下颌的那串组织换成了嘴角的锚；原文见 `asset/lab.py`）；空就不写。运行报告照抄到它的 `simplifications`；场景没写，报告里就是空列表（ADR-38 第 2 条） |

**嘴角的锚（T-06a，05 第 3 节，ADR-32、ADR-36）。** 格式仍是 `asrp-scene/1`：只加了可选字段（`blend`、`anchors`，以及上表的 `simplifications`），旧文件原样可读，没有这些字段的场景写出来也和以前逐字节相同，所以不升版本号。

```
"drivers": [
  {"name": "jaw01", "hinge": {...}},                              # 有自己的运动（trajectory.json 里有）
  {"name": "lip_corner_blend", "hinge": null,                     # 派生：trajectory.json 里不写它
   "blend": {"of": "jaw01",                                       #   从哪个驱动源派生
             "factor": {"value": 0.5, "source": "ours", "note": "..."}}}   #   α，范围 [0, 1]
],
"anchors": [                                                      # 可选，缺省为空
  {"name": "lip_corner_anchor", "driver": "lip_corner_blend", "note": "..."}
]
```

- **派生驱动源 `blend`**：`of` 必须是另一个驱动源，也不能自己再是派生的（不连环）；`of` 不需要铰链。它的每帧变换 = `of` 那一帧整个刚体运动的 `factor` 倍：对 `of` 的变换 T 取 exp(factor·log T)（SE(3) 上；转动向量 w、θ = |w|，V = I + (1−cosθ)/θ²[w]× + (θ−sinθ)/θ³[w]×²，u = V⁻¹t，结果的转动是 exp(factor·w)，平移是 V(factor·w)·(factor·u)；θ < 10⁻⁸ 时 V = I）。α = 0 恒为单位变换（和颅骨重合），α = 1 等于 `of` 本身；`of` 是绕铰链的纯转动时，结果就是绕同一个铰链转 `factor` × 角度；`of` 是三个轴都转加平移的一般运动（实验室的下颌就是这样）时，转动和平移一起按比例缩，比例 a 的变换乘比例 b 的变换等于比例 a+b 的变换。相对静止转 π 或更多的帧不支持。**`relative_to`**（可选，T-28，一个驱动源的名字）：取 `of` 相对这个驱动源的运动的 `factor` 倍，T = T_rel · exp(factor · log(T_rel⁻¹ · T_of))；`relative_to` 不写时就是上面的公式，结果逐位不变；写了而它停在静止（运动文件没写它、它又标了 `absent_means_rest`）时也逐位等于上面的公式。它不能是派生的，不能等于 `of`，运动文件里要有它的运动（或者它标了 `absent_means_rest`），否则是错误。实验室场景里嘴角的锚是 `jaw01` 相对 `head` 的 α 倍：头不动时和以前一样，头和下颌一起平移时锚跟着头走。`blend` 和 `hinge` 不能同时有；`blend` 的驱动源 trajectory.json 里不用写运动，写了会被忽略（提醒）。ADR-38 第 6 条。
- **锚 `anchors`**：静止时和颅骨重合（静止位置 = 世界坐标原样，没有自己的位置字段），每帧的变换就是它跟随的那个驱动源（通常是派生的）的变换。没有网格、没有质量、不参与碰撞，所以不画、也没有源 OBJ。连接的 `to` 可以写锚的名字。锚的名字不能和骨头、软组织重名；`driver` 必须是场景里列出的驱动源。左右两个嘴角共用同一个锚（两边绕同一个铰链转同样的角度）。
- **连接的三样东西**不变：类型 `hard` / `spring`（`hard` 的 `stiffness.value` 必须是 `null`，`spring` 必须有数）、每个顶点的权重、目标（颅骨、下颌或锚）；`spring` 的基础刚度和其他参数一样带来源。
- **检查**（都是错误）：锚或派生驱动源指向不存在的驱动源；α 不在 [0, 1]；派生驱动源的 `of` 自己也是派生的；`spring` 没有刚度；`hard` 带了刚度。
- 生成器（T-06a 的 B2）把驱动源的运动解出来用 `asrp_core.scene.driver_motion(scene, trajectory)`：返回每个驱动源（含派生的）每帧的 4×4 变换。
- **名字规则**：软组织、骨头、锚、驱动源、连接的名字只能用 ASCII 字母、数字、`_`、`-`、`.`（名字会原样写进 FEBio 输入文件，别的字符如 `&` `<` 空格会破坏它），不符合就是错误；生成器写入时另外做 XML 转义作为第二道防线。派生驱动源只有被用到时才计算（被"给定"的骨头跟随，或被某个连接引用的锚跟随）；没被用到的、源驱动源在轨迹里没有运动的派生驱动源直接跳过。

### 5.2 运动 `trajectory.json`
- 每个驱动源，每一帧的 **4×4 刚体变换**（毫米、Z 轴朝上，包含平移和旋转，ADR-21；**列向量约定**，Maya 是行向量约定，转换时要转置，ADR-34），以驱动源的名字为键。跟随同一个驱动源的骨头都用这一份变换。骨头可平移也可旋转（论文 4.1.3），甩头实验里整个头在平移（4.4.6），只存关节角度表达不了；
- `landmarks` 一节：每个 landmark 每帧相对静止位置的**平移**（毫米、Z 轴朝上）。实验室的运动数据里 landmark 只有平移（[03](03-asset.md) 第 7 节），所以这一版不存旋转。键：`names`（各不相同的 landmark 名字列表，名字取自 `scene.json` 的 `landmarks.names`）和 `translations_mm`（每帧一项，每项对 `names` 里的每个 landmark 给一个 `[x, y, z]`）；运动文件里没写名字的 landmark 不动。一节可以不写（没有 landmark 运动时）。`trajectory.py` 读取时校验形状；`asrp check` 另外拒绝场景没有 landmark 却带了这一节、或写了场景里没有的名字；
- `fps`、`frames`（总帧数）、`source`（自由文字：实验室控制器的哪一次输出，或哪个生成器）、`drivers`（驱动源名字 → 每帧 4×4 变换）；
- 可选的 `source_tag`：`lab_setting`、`ziva_default`、`ours` 三个值之一（和场景参数的来源同一套），写别的值是错误。运行报告里运动那一行的来源取它，没写就记 `unstated`，不再从说明文字里猜；
- 可选的 `settle_until_frame`：整数 n（0 ≤ n < 帧数），只有重力的沉降的最后一帧；第 0 到 n 帧所有被用到的驱动源都必须停在静止位置（单位变换）。写了、n ≥ 1 而且满足，运行写 `physics/settled_frame{n}.*`，检查 (c) 用第 max(1, n−4) 到 n 帧（不含第 0 帧，它是静止姿态）；n = 0 时没有沉降可言，(c) 没运行、不写沉降形状；写了但驱动源在 n 帧之前就动了，(c) 没运行、不写沉降形状，并说明原因；**没写**，(c) 没运行、不写沉降形状，原因是"运动文件没说沉降到哪一帧"。两个键都不改变已有文件的有效性（ADR-38 第 1、3 条）。

正式的运动来自实验室的运动文件，经 T-10 转换（12.3）。铰链只在场景描述里作为驱动源的可选说明，用来生成测试用的代用运动（`tools/placeholder_jaw_motion.py`：51 帧，第 0–14 帧不动，第 32 帧张开到 12°，第 50 帧合上；张开的方向按"下颌的中心往下走"从几何判断）。代用运动也写成同样的每帧刚体变换，所以求解器只有一种输入形式；它在运动文件里写 `source_tag` 为 `ours`，`settle_until_frame` 为 14（5.2）。

### 5.3 回放包 `playback.json` + `playback.pc2`
已经实现，格式见 `src/asrp_core/playback.py` 开头的说明。表面网格以毫米存储，Blender 插件负责缩放显示。

运行有 landmark 层时（T-09），`playback.json` 多一个可选键 `versions`：`physics` 指向 `playback.pc2`，`final` 指向 `playback_final.pc2`；`cache` 始终是物理版本。没有 landmark 层时没有 `versions` 键，也没有第二份点缓存。插件加载时可选版本（`physics` 或 `final`）。

### 5.4 溯源 `provenance.json`
每个输入文件（包括四面体网格）的哈希值、asrp 版本和源码的 git 提交号（`software.asrp_source`：提交号，以及运行时有没有未提交的改动 `dirty`）、FEBio 版本、Python 版本、运行时间、运行命令、运行结果（成功或失败及原因）。

## 6. 物理后端接口

为了以后能换求解器、也为了把 Ziva 当作"参考后端"看待，物理计算被抽象成三件事：

1. **准备**：拿到场景描述，做好求解前的一切准备（读取已落盘的四面体网格、生成输入文件）；
2. **运行**：给定一段运动，计算每一帧；
3. **交结果**：按统一格式给出每帧每个顶点的位置。

FEBio 是第一个实现。Ziva 不在我们的软件里运行：它的结果在实验室的 Ziva 机器上导出（[13](13-explanations.md) E-11），按同样的"交结果"格式读入，用于对比（T-11）。

## 7. 命令行

| 命令 | 作用 | 对应需求 |
|---|---|---|
| `asrp doctor` | 检查环境 | — |
| `asrp import-asset <导出文件夹> <输出文件夹>` | 导入资产，生成场景描述和检查报告 | R-01 |
| `asrp check <scene.json> [<trajectory.json>]` | 检查场景设置；带上运动时，再查运动和场景对不对得上。有错误才失败，提醒照样通过 | R-02 |
| `asrp run <scene.json> <trajectory.json> [--threads N]` | 运行一次，生成运行文件夹；运行文件夹一建好就先打印 `run folder <路径>`（结束时再打一次）；之后打印生成器报告、max\|u\|÷δ、五项检查（a、b、b2、c、d）、一行 `landmarks`（叠上了：移动的个数、最大平移、最终形状离物理结果最远多少；没叠上：原因）和每帧用时，检查有不通过的就以 1 退出。`--threads N`：FEBio 的线程数，默认 4（取 N 和本机核数中小的），1 时回放文件逐位相同（ADR-38） | R-03、R-06 |
| `asrp run --feb <现成的 .feb> [--threads N]` | 替身模式：不生成输入，直接跑现成的 `.feb`，做运行文件夹、溯源、进度、取消、出错处理这层外壳 | R-03、R-06 |
| `asrp compare <运行文件夹> <Ziva 参考>` | 和 Ziva 对比（T-11） | R-05 |

Blender 插件的每个按钮都对应其中一条命令。界面能做的事，命令行都能做。

## 8. 一次运行的完整过程

1. 研究员在 Blender 里点 Run；
2. 插件把场景描述和运动的路径交给 `asrp run`，作为子进程在后台启动（一个线程读它的输出，Blender 的定时器每 0.25 秒取一次）；
3. 核心程序新建运行文件夹，复制输入，记录溯源；
4. 校验场景，有错立即停止并报告；
5. 读取已落盘的四面体网格，并把它的哈希记进溯源记录（四面体网格在运行之前显式生成一次，不在这里重新生成，ADR-20）；
6. 生成 `model.feb`，调用 FEBio；
7. 插件读 `asrp run` 打印的 `progress` 行（已完成的帧数 / 总帧数）并显示进度条；`run folder` 一行告诉它运行文件夹在哪（取消要用）；
8. FEBio 结束后检查是否"正常结束"，读出每帧结果；
9. 运动文件有 `landmarks` 一节时叠加 landmark 段；
10. 生成回放包；插件加载并在时间轴上播放。

## 9. 出错时怎么办

| 情况 | 系统的反应 |
|---|---|
| 场景设置有错（缺文件、单位不对、连接没有顶点） | 运行前就停下，用通俗的话说明是哪一项、怎么改 |
| FEBio 计算不收敛 | 停止，报告出错的帧号和 FEBio 的原始提示，**不显示任何结果** |
| FEBio 算完了，但我们自己的事后处理出错 | 运行记为失败，删掉 `physics/` 和回放包，不留任何结果，报告里写原因（第 4 节） |
| FEBio 找不到 | 提示安装或设置 `ASRP_FEBIO` |
| 研究员取消 | 停止 FEBio，运行文件夹标记为"已取消"。面板上点 Cancel 就是在运行文件夹里写 `cancel`；运行文件夹还不知道时，请求先记着，知道的那一刻就写；退出 Blender 或停用插件时，运行还在跑也同样取消，没有及时停下就结束整个进程树（时限见 [06](06-ui.md) 第 3.3 节） |
| 任何失败 | 运行文件夹保留，溯源记录写明失败原因，方便排查 |

**绝不在失败时显示上一次的旧结果。** 这是最容易误导研究的情况。面板的做法：开始新运行时，先把正在显示的结果全部隐藏（包括 Load result 加载的）；运行失败、没有开始或被取消时，什么都不加载。

报告的帧号是 FEBio 自己的时间步编号（从 1 数）；取消有两种方式，在运行文件夹里新建一个名为 `cancel` 的空文件，或在终端按 Ctrl-C，两种都会结束 FEBio 的整个进程树。

## 10. 规模和性能

| 网格 | 顶点数 |
|---|---|
| 嘴唇 | 10,240（显示用）；计算用的四面体网格会粗一些 |
| 下颌、颅骨、牙齿 | 7 千到 2.8 万，**只作为刚体**，不参与有限元计算，不影响速度 |

速度主要取决于嘴唇四面体网格的大小（6,747 个计算点、1,428 根弹簧）和每帧子步数。**我们现在的速度（用时、每帧用时、线程数）只记在 [15](15-prototype.md) 第 3 节**，这里不抄；速度预算和 Ziva 的实测速度见 [02](02-requirements.md) N-07。速度要求来自正向推进（回放，以及实验室界面的逐帧步进，T-30），不来自控制器训练：训练时不推进时间（ADR-30 及其修订）。事后处理（读结果、嵌入、写回放包）读的是数组，测量见 ADR-38 第 10 条的证据。

## 11. 已有代码和这份设计的对应

文件和目录的清单见 [README](README.md) 里的目录树；每个模块负责什么见本文第 3 节的表。两处都没有的，才写在这里：

- `spikes/` 和 `tools/mb_inventory.py`、`tools/asset_report.py`、`tools/lip_attachments.py`、`tools/maya_export.py` 是试验和资产分析、导出工具，**不是产品代码**，不要在它们上面直接扩展，结论写进 05、10。只用过一次的开发文件（比如上 Ziva 机器用的导出和排练脚本）按 T-38 移出仓库。

## 12. 和实验室代码的分界与对接

我们只顶替两样软件：**Ziva**（物理）和 **Maya**（摆关节、蒙皮、读网格、播放）。实验室的控制器代码和数据不归我们：landmark 往哪走由他们的控制器决定，landmark 怎么选、权重怎么绑是他们的数据。这一节写清楚线画在哪、他们的脚本对 Maya 和 Ziva 做的每一种操作由我们的什么顶替、两个对接的接口各收什么交什么。事实依据是实验室源码的调查（[03](03-asset.md) 第 13 节，下面只写节号，不重复行号）。

### 12.1 谁做什么

| 事情 | 现在谁做 | 换掉以后谁做 |
|---|---|---|
| 决定下颌转多少、每个 landmark 走到哪：控制器、目标函数（距离、应变能、Hill 肌肉功）、梯度用的 LBS 代理（03 第 13.3、13.4 节） | 实验室的 Python 代码 | **实验室，不变** |
| landmark 是哪 300 个点、对嘴唇顶点的权重、绑定姿态（03 第 13.7 节） | 实验室的数据（`.mb` 里的蒙皮，和源码仓库里的绑定数据） | **实验室，不变**；我们只读，不改、不重新生成 |
| 目标姿态（`dataV22_*`）和运动文件（D2） | 实验室的数据 | **实验室，不变** |
| 物理：重力沉降、下颌带动嘴唇、粘连、惯性 | Ziva | 我们：FEBio 加物理段（第 2 节） |
| 把下颌转到给定角度、把 landmark 放到给定位置、按权重算出最终的嘴唇形状 | Maya（关节和 `skinCluster`） | 我们：landmark 段（`skinning.py`，T-09） |
| 把最终的嘴唇顶点交给控制器 | Maya（读网格的世界坐标） | 我们：训练接口的返回值（12.4，T-31）；整段运行时是运行文件夹里的 `final/` |
| 推进时间、播放 | Maya 的时间轴 | 我们：`asrp run` 整段算完，Blender 里重放（[06](06-ui.md)） |
| 打开场景、选运动、运行、在视图里回放 | Maya 和 Ziva | 我们：Blender 插件（T-13；"打开资产、选运动、Run、回放"的流程是 T-35） |
| 钢琴式表情界面（按键触发音素、动作单元、表情） | 实验室在 Maya 里的面板 | **实验室，不变**。它改用 FEBio 时需要的"从上一帧接着算"由我们提供（T-30） |
| 把实验室的运动文件变成我们的运动文件 | 没有这一步 | 我们：T-10 的转换（12.3） |

**一条派生的规矩**：凡是"替实验室决定 landmark 往哪走"的代码，都不是产品。landmark 的位移一律来自实验室的运动文件，经 T-10 转换。中性到 AA 的正式结果也用实验室真实的下颌角度和 landmark 偏移（ADR-42）。

### 12.2 实验室脚本对 Maya 和 Ziva 做的每一种操作

最后一列写归哪张任务卡；做没做完只看 [09](09-roadmap-and-tasks.md)，这里不记。"不顶替"指第一阶段没有对应的东西。

| # | 实验室脚本做的事 | 出处（03） | 我们用什么顶替 | 任务卡 |
|---|---|---|---|---|
| 1 | 打开 `.mb` 场景，另存，`mayapy` 批处理 | 13.6 | 一次性导入成 `scene.json`（`asrp import-asset`）；每次运行一个运行文件夹；命令行本身就能批处理 | T-02 |
| 2 | 打开场景后逐帧走第 0 到 14 帧，让重力沉降 | 13.3、13.8 | 运动文件开头的静止帧（`settle_until_frame`）由物理段算；沉降后的形状单独写出（第 4 节的 `physics/settled_frame{n}.*`） | T-06a |
| 3 | 转下颌关节：训练时每一步给一个世界坐标轴下的**相对**转动（三个轴都转）；钢琴界面只转俯仰并打关键帧 | 13.2、13.3 | 整段运行：运动文件里驱动源 `jaw01` 每帧的刚体变换（5.2）；训练接口：下颌转动是输入之一（12.4） | T-06a（整段运行）、T-31 |
| 4 | 把每个 landmark 移到一个**绝对**的世界位置 | 13.3 | 整段运行：运动文件的 `landmarks` 一节（相对静止位置的平移，5.2）；训练接口：landmark 位置是输入之一（12.4） | T-09、T-31 |
| 5 | 读嘴唇网格全部顶点的世界坐标（物理加蒙皮之后的最终形状） | 13.2 | 整段运行：运行文件夹的 `final/`；训练接口：返回值 | T-09、T-31 |
| 6 | 查蒙皮权重 | 13.6 | 场景里 `landmarks` 引用的权重文件（来自实验室的导出，5.1） | T-02 |
| 7 | 向前推进一帧并等求解器算完（钢琴界面每按一次键） | 13.3 | 整段运行：整段算完再重放；从上一帧接着算是 T-30 | T-30 |
| 8 | 给关节打关键帧、播放时间轴 | 13.6 | 运动文件就是每帧的值；播放在 Blender 里 | T-05（运动文件）、T-13（面板） |
| 9 | 选中求解器（`cmds.ziva(s=True)`，返回值只用来打印） | 13.6 | 不需要 | — |
| 10 | 给求解器的起始帧和开关打关键帧或复位，让求解器从头再来 | 13.6 | 不需要：每次 `asrp run` 都从静止形状重新算起，进程之间不留状态 | — |
| 11 | 沉降那 15 帧临时把子步和牛顿迭代次数调低，之后恢复 | 13.6 | 没有对应：求解设置写在场景里，整段用同一套。Ziva 场景里实测的设置和我们的对照见 [05](05-ziva-to-febio.md) 第 4 节 | 不顶替 |
| 12 | 把肌肉纤维的激活设成 0 | 13.4 | 场景里没有纤维，物理段不做主动收缩（ADR-33） | — |
| 13 | 把碰撞关掉 | 13.6 | 场景里没有碰撞（Ziva 场景里碰撞检测也是关的，E-11） | — |
| 14 | 甩头：给下颌和颅骨的骨头网格的平移打关键帧 | 13.8 | 运动文件里颅骨和下颌各自的每帧刚体变换 | T-28 |
| 15 | 下牙和舌头的显示网格比下颌多转一点 | 13.2 | 没有顶替：只影响显示用的网格，不影响嘴唇 | 不顶替 |
| 16 | 界面读的显示代理网格（跟着 Ziva 网格的 blendShape）、渲染、拍屏 | 13.2、13.6 | Blender 里直接显示回放包；渲染用 Blender | T-13（回放）；渲染、拍屏不顶替 |
| 17 | 手指按压：手作为骨头做敲击，另在皮肤显示网格上做位置修正 | 13.8 | 这是实验室的实验，不归我们。物理层到第二阶段要能提供按给定运动走的刚体和皮肤层；显示网格上的修正是实验室的几何代码 | T-32（清单） |
| 18 | 两眼和额肌的 landmark 也按同样的方式移动（另外三组，各 300 个） | 13.2 | 第一阶段只有嘴唇这一组；其余三组随第二阶段的组织一起做 | T-32（清单） |
| 19 | 分析脚本读各个网格的顶点位置，自己算应变能、力、速度、体积 | 13.9 | 运行文件夹里每帧的顶点数组（第 4 节）；第一阶段只有嘴唇 | T-06a |

没有列进来的，就是实验室脚本没有对 Maya 或 Ziva 做的：脚本不创建组织、骨头、粘连、材料，也不设置任何物理参数（03 第 13.6 节），这些都在 `.mb` 里，由一次性的导入读进 `scene.json`。

### 12.3 回放接口：一整段运动（T-10）

实验室的控制器算完一段运动，存成运动文件；我们把它转成自己的运动文件，整段算完，在 Blender 里重放。

| | 内容 |
|---|---|
| 实验室交来的 | 运动文件（D2）：每帧一个向量，里面有嘴唇 300 个 landmark 相对起始位置的累计平移和下颌的欧拉角，还有两眼和额肌三组 landmark 的平移（第一阶段不用）。向量怎么分段、钢琴界面只用下颌的俯仰，都只写在 03 第 7 节和 T-10 卡。2026-11-12 从 Ziva 机器取回 97 个 `combined_checkpoints.pkl`，全部能用我们的读取器读通，每帧 3,603 个数（[13](13-explanations.md) E-11） |
| 转换（T-10） | 写成 `trajectory.json`（5.2）：驱动源 `jaw01` 每帧的 4×4 刚体变换；`landmarks` 一节是每个 landmark 每帧相对静止位置的平移。单位和坐标轴在这里换成毫米、Z 轴朝上，只用 `asset/coords.py` 那一份换算 |
| 我们算的 | `asrp run <scene.json> <trajectory.json>`：物理段算每帧"只有物理"的形状，landmark 段把平移按权重叠上去 |
| 我们交回的 | 运行文件夹：`physics/`（只有物理）、`final/`（最终形状）、回放包、运行报告和五项检查（第 4 节） |

### 12.4 训练接口：一步一问（T-31）

实验室的训练环境每一步做三件事：转下颌、摆 landmark、读网格（12.2 的第 3、4、5 行），中间不推进时间（03 第 13.3 节）。训练接口把这三件事合成一次函数调用，不经过 Maya：

```
final_shape(下颌转动, landmark 位置) -> 嘴唇顶点
```

| | 内容 |
|---|---|
| 约定 | **输入输出都用实验室一侧的约定**：场景单位、Y 轴朝上的世界坐标，和他们现在交给 Maya、从 Maya 读回的一样。换成毫米、Z 轴朝上只在函数内部的边界上做一次（`asset/coords.py`），调用的人不用知道 |
| 输入：下颌转动 | 下颌相对静止姿态的转动，一个 3×3 的旋转矩阵（世界坐标轴）。实验室每一步给 Maya 的是相对上一步的三个角（03 第 13.2 节）；三个轴的转动不能逐个角相加，而函数没有状态，所以把每一步的转动依次乘起来由调用的一侧做。每一步的三个角 Maya 按什么顺序合成，还没有核对（和 T-10 的欧拉角顺序是同一个问题） |
| 输入：landmark 位置 | 300 × 3 的数组，每个 landmark 的**绝对**世界位置，顺序是 `oor_01` 到 `oor_300` |
| 输出 | 10,240 × 3 的数组：嘴唇网格（`middleres_OrbicularisOris`）全部顶点的世界坐标，顶点顺序和实验室的网格相同 |
| 怎么算 | 基底形状 + 权重 ×（landmark 位置 − 静止位置）。基底是一次已完成的运行交出的**沉降后的形状**（ADR-30），不是静止形状 |
| 调用时不做的 | 不启动 FEBio，不依赖 Blender；函数没有状态，同样的输入永远给同样的输出 |
| 下颌转动的作用 | 同一帧里转下颌，Ziva 不重新求解（11 的 Q20：第 14 帧把 `jaw01` 转 2°，蒙皮前的嘴唇变化为 0，[13](13-explanations.md) E-11）。所以基底不随下颌变，下颌转动这个输入不改变嘴唇形状。代码里还留着"重新求解"的选项和相应的提示，删掉它们是 T-37 |

实验室梯度用的 LBS 代理（03 第 13.3 节）仍是他们的代码。它的公式是"绑定姿态 + 权重 × 平移"，和上面"怎么算"一行同形，只是基底不同（它用绑定姿态）；它读的权重文件和我们从 `.mb` 导出的权重是不是同一份，T-09 用实验室自己的绑定姿态和权重文件、按他们的公式算过一遍，和我们的结果逐点比（结果和范围见 09 的 T-09 卡）。
