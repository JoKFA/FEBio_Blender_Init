# 12 实验室导出清单

这份清单可以直接发给实验室。它列出原型需要、但从 `.mb` 文件里读不出来的东西，每一项都写了**为什么需要**和**怎么在 Maya 里导出**。所有操作都在实验室现有的 Maya 2023 + Ziva 环境里完成。

> **优先级**：
> - **第 1 项（网格）最先给**：没有它，我们跑不了第一次完整的计算；
> - **第 4 项（Ziva 参考结果）必须在 Ziva 许可到期前完成**，过期就再也做不出来了。它**不用等任何决定**，用你们平时研究用的场景直接导出即可；
> - 其余各项可以分批给。

> **关于脚本**：下面的 Python 脚本是按 Maya 的标准命令写的，**我们没有 Maya 环境，还没实际运行过**。如果报错，请把报错信息发给我们，或者按文字说明手动操作。

导出的文件请打包，通过实验室认可的方式发送。我们收到后放在不进代码仓库的 `data/lab_export/` 目录，不外传。

| 本清单 | 对应 [11](11-risks-and-questions.md) 里的编号 |
|---|---|
| 第 1 项 | D7 |
| 第 2 项 | D6、Q4 |
| 第 3 项 | D7 |
| 第 4 项 | D3 |
| 第 5 项 | D2 |
| 第 6 项 | Q1、Q2、Q3、Q5–Q9、D4 |

---

## 1. 五个网格的静止形状 □

- **需要**：`middleres_OrbicularisOris`（嘴唇）、`middleres_Jaw`、`middleres_skull`、`middleres_TeethUp`、`middleres_TeethDown`。
- **为什么**：`.mb` 文件里网格的"面"（哪些点连成面）是不公开的编码，我们读不出来，所以需要开放格式的网格来建计算模型。
- **注意**：直接选中网格导出，导出的是**已经被 Ziva 和 landmark 变形过的形状**，不对。我们需要的是**静止形状**，也就是每个网格名字以 `ShapeOrig` 结尾的那份中间网格，它是 Ziva 和蒙皮的输入。
- **怎么导**：在 Script Editor 的 Python 标签里运行：

```python
import json, os
import maya.cmds as cmds

OUT = r"D:\asrp_export"   # 改成你们的导出目录
MESHES = ["middleres_OrbicularisOris", "middleres_Jaw", "middleres_skull",
          "middleres_TeethUp", "middleres_TeethDown"]

cmds.loadPlugin("objExport", quiet=True)   # OBJ 导出插件
if not os.path.isdir(OUT):
    os.makedirs(OUT)
report = {}
for name in MESHES:
    orig = name + "ShapeOrig"                         # 静止形状
    rest = cmds.createNode("transform", name=name + "_REST")
    shape = cmds.createNode("mesh", name=name + "_RESTShape", parent=rest)
    cmds.connectAttr(orig + ".outMesh", shape + ".inMesh")
    world = cmds.xform(name, query=True, matrix=True, worldSpace=True)
    cmds.xform(rest, matrix=world, worldSpace=True)   # 放到和原网格相同的位置
    cmds.select(rest, replace=True)
    cmds.file(os.path.join(OUT, "mesh_%s.obj" % name), force=True, exportSelected=True,
              type="OBJexport", options="groups=0;ptgroups=0;materials=0;smoothing=0;normals=0")
    report[name] = {"vertices": cmds.polyEvaluate(shape, vertex=True), "world_matrix": world}
    cmds.delete(rest)
with open(os.path.join(OUT, "mesh_report.json"), "w") as f:
    json.dump(report, f, indent=2)
print(report)
```

- **请核对**：脚本最后会打印每个网格的顶点数。我们从 `.mb` 文件里读到的是：嘴唇 10,240、下颌 7,426、颅骨 28,414、上牙 24,608、下牙 24,608。如果不一致，请告诉我们。
- **输出**：5 个 `mesh_<网格名>.obj`，以及 `mesh_report.json`（顶点数和每个网格在场景里的位置矩阵）。

## 2. Ziva 的完整设置 □

- **需要**：所有 Ziva 设置的**全部属性值**，包括没改过的默认值。
- **为什么**：`.mb` 只存了改过的值。文件里所有材料都没有存数值，说明很可能都是默认值，但默认值是多少，文件里没有。
- **怎么导**（两步都请做）：
  1. **属性清单**：运行下面的脚本，把每个 Ziva 设置的每个属性都写进一个文件，这样默认值也一定会包括在内：

```python
import json, os
import maya.cmds as cmds

OUT = r"D:\asrp_export"
TYPES = ["zSolverTransform", "zSolver", "zTissue", "zBone", "zTet", "zMaterial",
         "zAttachment", "zEmbedder", "zFiber", "zCloth"]
if not os.path.isdir(OUT):
    os.makedirs(OUT)
dump = {}
for t in TYPES:
    try:
        nodes = cmds.ls(type=t) or []
    except RuntimeError:
        nodes = []
    for node in nodes:
        values = {}
        for attr in cmds.listAttr(node, scalar=True) or []:
            plug = node + "." + attr
            try:
                values[attr] = cmds.getAttr(plug)
                if cmds.getAttr(plug, type=True) == "enum":   # e.g. attachment mode: also keep the label
                    values[attr + "__label"] = cmds.getAttr(plug, asString=True)
            except Exception as exc:
                values[attr] = "unreadable: %s" % exc
        dump[node] = {"type": t, "attributes": values}
with open(os.path.join(OUT, "ziva_attributes.json"), "w") as f:
    json.dump(dump, f, indent=1, default=str)
print(len(dump), "Ziva nodes written")
```

  2. **zBuilder 导出**：用 Ziva 自带的 zBuilder 把整套设置存成文件，大致如下（以你们 Ziva 版本的文档为准）：

```python
import zBuilder.builders.ziva as zva
z = zva.Ziva()
z.retrieve_from_scene()
z.write(r"D:\asrp_export\ziva_setup.zBuilder")
```

- **另外请截图**：`zSolver1` 和 `zMaterial1` 的属性面板（Attribute Editor），方便核对。

## 3. landmark 的蒙皮权重 □

- **需要**：`skinCluster7`（300 个 `oor_` 关节带动嘴唇）的全部权重。
- **为什么**：最终的嘴唇形状 = 物理结果 + landmark 变形，这一层要用这些权重。
- **怎么导**：

```python
import os
import maya.cmds as cmds
OUT = r"D:\asrp_export"
if not os.path.isdir(OUT):
    os.makedirs(OUT)
cmds.deformerWeights("skinCluster7_weights.xml", export=True, deformer="skinCluster7", path=OUT)
```

  也可以在菜单里操作：选中嘴唇网格，`Deform > Export Weights`。

## 4. Ziva 参考结果（许可到期前必须完成，不用等任何决定） □

- **需要**：选一条运动（建议"中性 → AA"，下颌动作明显），导出嘴唇网格**每一帧**的形状，**导两次**：
  - **4a 最终形状**：正常播放后导出 `middleres_OrbicularisOris`；
  - **4b 只有物理**：把 `skinCluster7` 的 `envelope` 设为 0，也就是关掉 landmark 变形，再重新算一遍并导出。
- **为什么**：我们会把它和 FEBio 的结果在 Blender 里并排播放，请你们的研究员评审新结果能不能用于继续研究。我们不要求和 Ziva 逐点一致，所以它不是"标准答案"，而是"以前的样子"。分两次导出，可以把物理部分和 landmark 部分分开看；landmark 那一层用的是同一个公式，还能精确核对。
- **怎么导**：
  1. 打开你们**平时研究用的场景**，加载这条运动；
  2. **每次导出前先清空 Ziva 的缓存，从第 0 帧开始按顺序播放到最后一帧**（Ziva 只能一帧一帧往前算）；
  3. 选中嘴唇网格，`Cache > Alembic Cache > Export Selection to Alembic`，帧范围**从第 0 帧到运动结束**（包括第 0 到 14 帧的重力沉降），勾选 **World Space**；
  4. 4a 和 4b 用**完全相同的帧范围**。
- **文件名**：`ziva_<运动名>_final.abc`、`ziva_<运动名>_physics.abc`。
- **请一并告诉我们**：用的场景文件名和版本、Maya 和 Ziva 的版本。如果用的场景和这次给我们的 `v36 dev_proxy_jaw_oor V3` 不是同一个，请说明区别。

## 5. 这条运动本身 □

- **需要**：第 4 项用到的那条运动的原始数据，也就是 Facial Expression Automator 从网络盘读进来的那份文件，以及一句话说明它的格式。
- **为什么**：我们要用同一条运动驱动 FEBio。
- **另外请导出**：播放这条运动时，`jaw01` 和 300 个 `oor_` 关节每一帧的变换。用 FBX 导出这些关节（勾选 Bake Animation），或者导出 Alembic。

## 6. 几个简短的问题 □

请直接回答，一两句话就行：

1. **单位和尺寸**：论文附录 V 说 1 个单位约 0.962 毫米，我们核对过，下颌在场景坐标下的尺寸正好是论文里的 155.92。但这样换算下来，颅骨左右约 217 毫米，比一般成年人大 1.5 倍左右。请确认：(a) 1 个场景单位到底等于多少毫米；(b) 模型是不是有意做得比真人大；(c) 骨骼和嘴唇网格都带 2.54 倍的缩放，这是从英寸换算过来的吗；(d) Ziva 求解器（`zSolver1`）的缩放 100 代表什么。
2. **坐标轴**：场景是 Y 轴朝上吗？
3. **landmark**：landmark 只是在 Ziva 算完之后做蒙皮变形，不参与物理计算，对吗？
4. **参与计算的组织**：这个代理场景里，Ziva 实际在计算哪些组织？网格被删掉的那些组织还在算吗？
5. **原型范围**：[11](11-risks-and-questions.md) 的 P-01 里，你们倾向哪个方案？方案 A 的"按区域挂到骨头上"你们能接受吗？
6. **期限**：Ziva 许可哪天到期？
7. **评审重点**：我们不打算用"和 Ziva 差几毫米"当合格线，而是请研究员把两边结果并排看，回答几个问题：嘴唇跟着下颌动得自然吗？有没有抖动、鼓包、塌陷？重力下垂可信吗？叠加 landmark 以后表情还认得出来吗？和 Ziva 差别大的地方能接受吗？你们觉得还要看什么？
8. **使用许可**：这份资产可以用于本项目吗？有没有使用限制？
9. **控制器怎么用物理**：控制器优化的时候，是每试一次都要让 Ziva 算一遍，还是先把物理算好、只优化 landmark？这决定了新的物理计算要多快才够用。
