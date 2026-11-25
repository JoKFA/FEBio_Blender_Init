# 2026-11-12 上机与本机导出详细记录（归档，原 12 第一部分）

> **归档说明**：本文件原样保存 2026-10-30 与 2026-11-12 已完成的 Maya / Ziva 导出详细日志。
> 现行待取数据与给实验室的问题见 [12-lab-export-checklist.md](../../12-lab-export-checklist.md)。

## 第一部分：已经做过的

### 1. 本机普通 Maya 导出（第 1、3 项）

输入是实验室提供的非 Ziva 版场景 `w64 from v36 proxy delete done non ziva.mb`。它删掉了全部 Ziva 节点，其余内容和原来的场景一样，普通 Maya 就能打开（[03](../../03-asset.md) 第 12 节）。

```bash
"C:\Program Files\Autodesk\Maya2027\bin\mayapy.exe" tools/maya_export.py "assets/w64 from v36 proxy delete done non ziva.mb" data/lab_export
uv run python tools/check_lab_export.py data/lab_export "assets/w64 from v36 proxy delete done non ziva.mb"
```

第一条约 40 秒，导出下面的文件，并自己核对顶点数、下颌尺寸 155.92、权重之和、控制点名单和蒙皮矩阵。第二条不经过 Maya，直接从 `.mb` 读顶点，和导出的文件逐点比较，并检查网格是否封闭；加 `--self-test` 会故意弄坏数据，确认这些检查真的会失败。

**核对的范围**：网格的顶点、顺序和面都核对过。权重和关节没有和 `.mb` 比较，只有 Maya 自检；landmark 层对 Ziva 的结果的对照（[13](../../13-explanations.md) E-11）是它们的独立检查。

| 输出（都在 `data/lab_export/`，已提交到私有仓库，ADR-19） | 内容 |
|---|---|
| `mesh_<网格名>.obj` | 五个网格的静止形状。**坐标已经是场景坐标**，导入时不能再套变换（ADR-18） |
| `context_skin_cloth_copy_v5_pull_back.obj` | 皮肤的静止形状，只用来显示嘴唇在脸上的位置，不参与计算 |
| `mesh_report.json` | 每个网格的顶点数、面数、尺寸和位置矩阵，以及下颌铰链的位置和朝向 |
| `skin_skinCluster7.json` | 300 个 landmark 对 10,240 个嘴唇顶点的权重，以及蒙皮公式要用的矩阵 |
| `joints.json` | `jaw01` 和 300 个 landmark 的静止位置 |
| `lip_attachments.json` | 嘴唇四组粘连的顶点集（T-03，`tools/lip_attachments.py` 生成） |
| `manual_maya_obj/` | 另一份手动导出（Maya 自带的 OBJ 导出，加一个 `.blend`）。只作参考，产品不读它：下巴、嘴唇、颅骨和上面的 OBJ 顶点一致（差别小于 0.000001 个场景单位），嘴唇有 2 个三角形的对角线不同；两只眼睛（各 8,064 个顶点）上面的导出里没有 |

### 10. 实验室源码仓库

源码仓库 `https://github.com/zhiyunrichardpeng/eugene-lab-fall26`（D10）。只读，不拷进本仓库（ADR-28）。内容和证据见 [03](../../03-asset.md) 第 13 节。

| 拿到了什么 | 在仓库里的位置 | 说明 |
|---|---|---|
| 目标姿态（D9） | `dataV22_*.py`（03 第 13.7 节） | 5 个网格在第 14 帧和第 50 帧（目标）的形状，世界坐标。来自完整场景。第 14 帧那一组（`…0`）就是静止形状，没有重力沉降；第 50 帧是控制器训练的目标形状：存下的 AA 训练结果按这个任务自己的嘴唇判据通过（9.018%，门限 10.020%；我们按实验室的公式自己算过，和两次外部审计相同，13 的 E-15 第 8 条），但不和目标逐点相同（全部顶点平均 0.10 mm、最大 1.70 mm）；目标是怎么做的不知道（🔍）；回放时不在它上面（03 第 13.7 节，13 的 E-13） |
| landmark 的绑定数据 | `automation/<组>_bind_pose.json`、`<组>_skin_weights.json`、`jaw_joint_pivots.json` | 四组 landmark 和下颌；嘴唇这组和我们导出的 `skin_skinCluster7.json` 是同一份东西的另一个出口 |
| 运动文件的格式 | 钢琴界面脚本 | 格式写在 03 第 7 节 |
| LBS 代理、Hill 模型、各实验的脚本 | 03 第 13.3、13.4、13.8 节 | 只作参考 |

仓库里没有的：生成粘连的脚本（11 的 Q18）、各实验的场景文件（Q19）。运动文件 `.pkl` 在 Ziva 机器上，见下。

### 2、4、5、7、8、9. 2026-11-12 的 Ziva 机器

项目负责人远程登录实验室的 Ziva 机器（Maya 2023.3.1，Ziva VFX 2.2.0-hotfix2），一趟取回第 2、4、5、7、8、9 项的主要部分。结果的数字在 [13](../../13-explanations.md) E-11，这里只写怎么做的。

**做法**：

1. **远程桌面**登录，不改实验室的任何文件。
2. **规则**：不改实验室的任何东西，只写进我们自己的临时文件夹，离开前删掉。
3. **没有用实验室的钢琴界面**，它是实验室自己的工具，运行时会往他们的文件夹里写日志。我们读了界面的源码，用自己的脚本照它的做法打关键帧：第 14 帧每个 landmark 的世界位置加上运动文件里每一步的偏移，从第 15 帧起逐帧打；下颌按俯仰增量绕世界 X 轴转。所以取回的 Ziva 回放都是我们的脚本播的，不是研究员在界面上按出来的；IY、UW、T 播的步数（36、36、10）和界面要求的 22 步不同（E-14 第 2 条）。
4. 运动文件 `combined_checkpoints.pkl` 直接从网络盘复制（第 5 项）；蒙皮前、后的嘴唇和各组织的逐帧形状用 `tools/ziva_machine_export.py` 采集并读回核对（第 4、8、9 项）；设置、权重表和 zGeo 网格（第 2、7 项）取自同一趟，各份是什么见数据文件夹里的 `README.md`。
5. **结果通过剪贴板带回**本机，再整理进数据文件夹。

**现场才知道的三件事**：

- Maya 会话开着缓存回放（Cached Playback）时，Ziva 求解器一步都不走，嘴唇和骨头网格都不动，也不报错。**整个会话里要先把它关掉**。导出脚本的检查会拦住这种空跑（报"物理形状在第 14 帧之后没有动"）。
- 场景里嘴唇的输出在 zEmbedder 之后还接了一个 polyTriangulate，三角形的连法**每一帧都变**，顶点编号和数量不变。所以导出脚本只检查顶点数，不检查面。
- 子步大于 1 很慢：子步 2 的那次导出 47 帧用了 2359 秒（约 39 分钟），外面一层批次用了 2493 秒（约 42 分钟），能做一次；子步 4 的两次没跑完。时间花在哪一段（每个子步多久、子步之间 Maya 重算多久）没有原始的事件日志，分不出来。要比较子步的影响时，用子步 2 对 1。

**取到的和没取到的**：取到的见 E-11 的清单；每次导出有哪些数据流、点数据真实到第几帧、有没有 `motion.json`、Alembic 读回，逐次列在 [13](../../13-explanations.md) E-15 的"各次导出的状态"表里，用之前先看那张表。Alembic 读回：当晚的接收报告对来回 10 次、Y、子步 4 的两次写的是"没有读回 / 0 路"，那说的是接收报告，不是文件；2026-11-13 外部审计用 Maya 的 API 独立读回了全部存下的 Alembic 流，14 次运行共 587 路，全部通过，最大差约 1.07×10⁻⁵ 个场景单位（E-17）。要点：子步 2 的那次写到第 46 帧，但只有第 0 到 36 帧在物理上可信；子步 4 的两次只有 2 帧和 5 帧，没有 `motion.json`，只是前缀，不能当完整运行用；Y 只到第 33 帧（它的报告写到第 46 帧，是错的），没有 `motion.json`；来回 10 次只导出了 2 路。"45 路"里也包括只留嘴唇那次被关掉的物体：那次 43 路身体流里有 42 路 47 帧完全不变，有数据流不等于这个物体参加了求解。zBuilder 的整套设置导出在这个场景上失败（Ziva 报 `Invalid simulation body; no shape found`），内容和已拿到的属性、权重表、网格重复，不需要重做。

**导出工具 `tools/ziva_machine_export.py`**：独立的单个文件，不需要安装 uv，也不联网、不加载 pickle、不自动打开或保存场景。要求 Maya 2022 或更新版本的 Python 3 模式，Ziva 已加载并能解算。不支持 Python 2。`tools/rehearse_ziva_export.py` 在普通 Maya 上用合成的替身排练它的采集和文件链路，不能验证 Ziva 节点本身。用法：

```python
path = "D:/ASRP/ziva_machine_export.py"
with open(path, encoding="utf-8") as f:
    source = f.read()
exec(compile(source, path, "exec"), {"__name__": "__main__", "__file__": path})
```

在 Script Editor 的 Python 页执行，出现面板后依次点 **1 Preflight**、**2 Rescue static data**、**3 Pilot current motion**、**4 Export full current motion**。不要为了赶时间截短正式运动，不要把 `require_simulation` 改成 False（那是排练开关）。回本机后用下面的命令检查拷回的文件夹（不初始化 Maya，只读文件；非零退出码或 `INCOMPLETE` 都不能认定收齐）：

```powershell
& "C:/Program Files/Autodesk/Maya2027/bin/mayapy.exe" tools/ziva_machine_export.py --collection <拷回的文件夹>
```

单个运动目录用 `--check <完整运行目录>`。

---
