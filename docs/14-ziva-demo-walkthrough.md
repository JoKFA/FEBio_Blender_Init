# 14 实验室演示的 Ziva 操作流程（2026-11-10 会议录像）

**一段话**：2026-11-10 的 Zoom 会议里，研究员 Zhiyun (Richard) Peng 在 Ziva 机器上演示了 Maya 2023.3.1 + Ziva 的操作：打开场景、给骨头和软组织加上或去掉 Ziva 物理、渲染几帧看重力下坠、用"钢琴界面"（Facial Expression Automator）做 AA 音。录像只有 19 分 30 秒。**没有演示**：读 zSolver、zMaterial、zAttachment 的数值，清 Ziva 缓存，加载 `.pkl` 运动文件，甩头。所以第 3 节的数值表很短，对 [11](11-risks-and-questions.md) 的 5 个问题基本没有回答。

**材料位置（不进 git）**：`E:\Codebase\3D模拟\ziva-demo-2026-11-10\`，里面有完整转写稿 `transcript.txt`、5 张缩略总览 `sheet_*.jpg`、80 张抽帧 `frames/`、本文引用的全分辨率关键帧 `key_frames/`。视频原件在 `C:\Users\User\Downloads\GMT20261110-235156_Recording_2160x1350.mp4`，没有移动。

**怎么读本文的标记**：时间点是视频 mm:ss；来源"画面"或"语音"；把握：高 / 中 / 低 / 不确定。转写质量：前 12 分钟和 14 分钟之后基本可信，**约 12:00 到 13:00 是语音识别失败**（一串重复的"2"），那一段只信画面。语音里的专有名词（Ziva、Solver、LBS、FEBio）有错字，下面已按画面和上下文改过。说话人没有标，换人时只能从摄像头小窗判断。

---

## 1. 操作流程（照着做）

| # | 做什么 | 时间点 | 来源 | 把握 |
|---|---|---|---|---|
| 1 | 通过远程桌面进入 Ziva 机器。进去时上一位同学的 Maya 还开着（`g10-10 rest pose 1200 landmarks v9.mb`，标题带 `*`，未保存） | 0:08–0:23 | 语音+画面 | 高 |
| 2 | **别人留下没关的东西，先帮他保存再关**。研究员存到 `C:\Users\zpa18\Desktop\daiwik\` | 0:20–0:54 | 语音+画面（保存对话框 0:23，资源管理器 0:27） | 高 |
| 3 | 从任务栏启动 Maya（启动界面写 Autodesk Maya 2023），在 Recent 里点场景，或点 Open 在对话框里选 | 1:00–1:43 | 画面 | 高 |
| 4 | 第一个打开的是简化演示场景 `v36 dev_proxy_jaw_oor V3 more aggressive delete done.mb`，目录 `C:\keyLabLocal_D\c99-maya-ziva-workshop\different pose as rest pose\`。研究员口头叫它"Ziva project … rest pose，带 Ziva 的简化模型" | 1:06–2:14 | 语音+画面（标题栏 2:14） | 高 |
| 5 | 场景载入后，他**先把 Ziva 的 playback 关掉**。他的说法：打开它，Ziva 会在后台把全部 50 帧一次算出来，所以慢，他一般关掉 | 2:02–2:25 | 语音 | 中（"playback"具体是哪个按钮、哪个界面，画面没拍清） |
| 6 | 看场景：一层是皮肤 surface mesh，一层是头骨，层（Layer Editor）里点 V 就能隐藏 | 2:28–2:49 | 语音+画面 | 高 |
| 7 | **去掉物理**：选中网格，点 Ziva 菜单里的 `Remove tissue or bone`，它就变回纯几何网格 | 2:56–3:07 | 语音 | 高（菜单项名语音说出） |
| 8 | **加骨头物理**：选中网格，Ziva 菜单里点 `bone`，它就有重力、刚体性质，能被别的组织粘连（attach） | 3:14–3:40 | 语音+画面（3:14、3:29 骨头网格呈绿色线框） | 高 |
| 9 | **加软组织物理**：同样的方式点 `tissue`（肌肉）。4:58 画面是 Ziva 菜单展开、嘴唇网格选中成绿色 | 4:53–4:58 | 语音+画面 | 中 |
| 10 | 点完加物理就会在后台算前几帧（他说"算了三帧"），"solver 已经打开了"；从第 1 帧开始算重力和周围组织的拉力 | 3:49–4:13 | 语音 | 中 |
| 11 | 这个简化场景**算崩了**：研究员说他把肌肉剪得太多，只剩几块，"不是好例子" | 4:16–4:29 | 语音 | 高 |
| 12 | 换一个**完整场景**：File → Open，在同一目录里选 `neutral 260825 v15 made the teeth MESH.mb`（对话框里同目录有几十个版本文件）。他说这个"可以渲染" | 4:33–5:11 | 语音+画面（打开对话框 5:02，标题栏 6:32 起） | 高 |
| 13 | 这个场景就是"0–50 帧"。他说：你们的 FEBio 相当于点了 playback，后台算好，再在 Blender 里回放 | 5:12–5:34 | 语音 | 高 |
| 14 | 渲染一帧看结果：Render Settings（渲染器 Arnold，渲染层 masterLayer）设单帧、很小的图（160 × 121，画面上 "Image size: 160 x 121"）；Render Sequence 里相机选 `muscle_closeup`；点 `Render Sequence` | 6:07–6:50 | 语音+画面 | 高 |
| 15 | 渲染连续帧：Frame Range 设 0 到 2，再开 playback，第 2 帧嘴唇会往下掉，但没掉很多，因为骨头拖着它 | 7:00–8:07 | 语音+画面 | 中 |
| 16 | 找渲染出来的图：用 Everything 搜文件名（`test_new_neutral_V14`），10 张这样的图连起来就是动画 | 7:43–8:24 | 语音+画面 | 高 |
| 17 | 在时间轴上拖动，直接看肌肉往下掉 | 10:00–10:13 | 语音+画面 | 高 |
| 18 | **钢琴界面的启动**：在 VS Code 里打开 `h99-UI-mayascipt-V1.py`（仓库路径 `a3-stochastic-V1 > b99-frame1to4-get-b1to3 > d4 interactive interface of animation`），文件开头的注释写着：先在 Maya 里打开场景，再在 Maya 的 Script Editor 里执行 `commandPort -name "localhost:7001" -sourceType "mel";`，打通 VS Code 和 Maya 的通道，然后从 VS Code 把界面代码送进 Maya | 12:17–12:43 | 画面（注释原文 12:40）；语音那段识别失败 | 高（画面）／低（语音） |
| 19 | 清理环境，然后按一个快捷键，"钢琴界面就出现了"：窗口标题 `Facial Expression Automator`，初始显示 `Current Pose: Neutral \| Frame: 14` | 12:55–13:31 | 语音（13:04）+画面（13:01、13:31 缩略图） | 中（快捷键语音识别失败，"shift"后面的内容不知道） |
| 20 | 选 `Phoneme AA (pot)`，界面调用"已经算好的路径"，"5000 步压缩成 50 步"，每步自己推进、算出下一步 | 13:06–13:35 | 语音 | 中（"code one"很可能是 combined checkpoints，推断） |
| 21 | 渲染到第 20 步就停（不用看满 36 步）：landmark 拖着嘴唇往下拉，下巴也在转，这就是音素 AA。完整的 AA 要 36 步 | 15:22–16:16 | 语音 | 高 |
| 22 | 键盘模式（钢琴式）：展开 `Keyboard Mode (piano-style)`，勾 `Enable keyboard mode`，按键盘上的键切换表情，可以同时按多个键（低音加高音，"又做表情又说话"）。第一次用前点 `Precompute All Keyboard Transitions (Fix First-Time Lag)` | 14:26–14:47 | 语音+画面（14:46） | 高 |
| 23 | **回到初始**：界面上的按钮叫 `Reset to Neutral (Reopen Rest Pose)`，字面意思是重新打开静止姿态的场景 | 14:46 | 画面 | 高（按钮字）／中（实际做法） |
| 24 | 研究员答应：可以把我们的脚本放到这台机器上运行取数据；建议在**共享文件夹**里新建一个 project（名字以 `b5` 开头，没听清），资产放进去，大家共享 | 16:43–17:12 | 语音 | 高 |

结果怎么看、怎么存：演示里只看了视口和渲染出来的 PNG（`test_new_neutral_V14*.png`，Windows 最近文件里记录的位置是 `C:\Users\zpa18\AppData\Roaming\...`，真正的输出目录是实验室结果目录下的 `maya_render_output_hub` 之类，**没读清**，7:52 画面）。**没有演示导出顶点或存缓存。**

---

## 2. 读到的设置和数值

| 项 | 值 | 时间点 | 来源 | 把握 |
|---|---|---|---|---|
| Maya 版本 | **Autodesk Maya 2023.3.1**（标题栏）。Python 3 | 0:23 起 | 画面 | 高 |
| Ziva 版本 | **没读到**。菜单栏有 `Ziva`、`Ziva Tools`、`Ziva Transfer`，工具架有 `Ziva` 标签页 | 12:55 | 画面 | 高（菜单名）／Ziva 版本：未知 |
| 其他插件可见 | Arnold、MASH、TURTLE、XGen、Motion Graphics | 12:55 | 画面 | 高 |
| 登录用户 | Maya 右上角 `Zhiyun Peng`；Windows 用户目录 `zpa18` | 0:23、7:52 | 画面 | 高 |
| 机器日期时间 | 2026-11-10 约 16:52 到 17:08 | 全程 | 画面（任务栏） | 高 |
| 演示场景 1 | `C:\keyLabLocal_D\c99-maya-ziva-workshop\different pose as rest pose\v36 dev_proxy_jaw_oor V3 more aggressive delete done.mb` | 2:14 | 画面 | 高 |
| 演示场景 2（完整） | 同目录 `neutral 260825 v15 made the teeth MESH.mb` | 6:32 | 画面 | 高 |
| 钢琴界面注释里的场景 | `C:\keyLabLocal_D\c99-maya-ziva-workshop\experiment_files\g10-10 rest pose 1200 landmarks …`（后面被截断，应是 v9.mb） | 12:40 | 画面 | 高（前半）／中（后半） |
| 大纲里的节点 | `middleres_skull`、`middleres_Jaw`、`middleres_Node`、`middleres_OrbicularisOculi`、`middleres_OrbicularisOris`、`middleres_TeethDown`、`middleres_TeethUp`、`zSolver1`、`head`、`jack01_MODEL`、`jack01_c_mouth01_world`，以及三组相机和 Omni 灯 | 4:33、5:02 | 画面 | 高 |
| 图层 | `skin_ziva`、`skin_render`、`the_hand`、`ziva_mesh_muscles`、`back_eye_hider_board`、`three_point_lightV1`、`muscle_view_mode`、`skin_view_mode` | 12:55 | 画面 | 高 |
| 帧率 | **30 fps**（时间轴右下） | 12:55、14:46 | 画面 | 高 |
| 时间轴 | 动画范围 0 到 50（语音："0–50 帧"）；播放范围随操作变（演示时 0–20，AA 运行后 1–36）；AA 运行后显示 `Current Pose: phoneme AA \| Frame: 36` | 5:12、12:55、14:46 | 语音+画面 | 高 |
| 重力沉降 | 前面留"缓冲期"，运动从第 15 帧开始；钢琴界面起始显示 Frame 14 | 11:07–11:28、13:31 | 语音+画面 | 高（语音）／中（Frame 14，缩略图） |
| 每帧求解耗时 | Script Editor 里每行 `ziva 2026-11-10 17:05:54.302 INFO\| Timestep completed; stepped to frame …`，相邻行间隔约 **2.3–2.5 秒**（最后一间隔 5 秒）；状态栏一行写着 `stepped to frame 36.0; wall clock time 1.519s` | 14:46 | 画面 | 中（帧号被截断；这是演示机配置，实际质量设置不详） |
| 渲染设置 | Arnold Renderer，图 160 × 121，相机 `muscle_closeup` | 6:32、12:55 | 画面 | 高 |
| 钢琴界面的按键 | 见第 1 节第 22 步；键位：`[f] Frown [b] Brow [q] Squint`；`[0] Neu [s] Smile [m] Mouth [c] Cheek [p] Pucker [1] Happy [2] Sad [3] Surpr`；`[n] N [a] AA [i] IY [t] T [e] EH [u] UW [v] V [y] Y` | 14:46 | 画面 | 高 |
| 相机按钮 | Front、L 3/4、R 3/4、Mouth、Frame、Orbit UP/DOWN/LEFT/RIGHT | 14:46 | 画面 | 高 |
| **没读到** | 重力、缩放、子步、牛顿迭代、zMaterial（杨氏模量、泊松比、密度）、粘连刚度、zCloth、Ziva 许可到期日、zSolver 属性面板（Attribute Editor 全程没展开） | — | — | 没出现 |

---

## 3. 研究员口头说的要点

- **别人没关的 Maya 先帮存再关**（0:48–0:54）。
- **加骨头、加软组织、去物理**是三个 Ziva 菜单项，对应 `bone`、`tissue`、`Remove tissue or bone`（2:56–4:58）。加完物理，Ziva 在后台立刻开始算，慢，所以他平时关掉 playback（2:02–2:25，3:49–4:13）。
- **简化场景会崩**（4:16–4:29）：把肌肉删到只剩几块，Ziva 的解算失败。**对我们的影响**：`v36 … more aggressive delete done.mb` 这个代理场景不一定能解算，参考结果要在完整场景里做（12 里写的"完整场景"就是他演示的 `neutral 260825 v15 made the teeth MESH.mb`，见第 5 节）。
- 他把我们的 FEBio 流程类比成"点 playback，后台算好，Blender 里回放"（5:12–5:34、10:39–10:51）。
- 运动前 0–14 帧是沉降缓冲，第 15 帧起 landmark 才开始动（11:07–11:28）。
- 钢琴界面的运动是已经算好的 36 个检查点，"5000 步压缩成 50 步"，界面逐步推进，每一步重新算（13:23–13:35，16:14）。
- 钢琴界面大部分代码是 LLM 写的，他们只给提示词和技术（14:54–14:57）。
- 另一位美国博士生在做这个过程的加速，暂时不需要合作（13:38–14:11）。
- 文件和代码都在共有资产里，代码已经整理过，拉下来就能跑（16:21–16:40）。
- 我们可以把脚本放到这台机器上运行取数据；放在共享文件夹新建的 project 里（16:43–17:12）。
- 对原型机和速度的期望（17:28–18:11，说话人不确定，镜头在换人）：原型机下周二前能出；原型机只需要一个动作跑通整条管线、物理层面没问题；不需要和 Ziva 对得很齐，因为我们是有限元、比简化的 Ziva 模型更精确；和医院 MRI 数据对得上更重要。
- **对"三步管线"的说法**（8:43–9:47）：提问方复述的顺序是 ①landmark 运动学位移 ②LBS ③Ziva 物理；研究员只纠正了 LBS 的全称（"Linear Blend Shape"，应是线性蒙皮）。**这个顺序和我们读出来的（物理在前、landmark 蒙皮叠在物理结果上，[03](03-asset.md) 第 4 节）相反**，但这是对话里的口头复述，不是研究员的明确陈述，记为"不确定"，要再问。

---

## 4. 和现有假设的对照

| 假设 | 来源 | 结论 | 证据 |
|---|---|---|---|
| Maya 2022 以上、Python 3 | 12 第二部分 | **证实**：Maya 是 2023.3.1 | 画面 0:23 |
| 节点名 `middleres_OrbicularisOris` | 脚本 `LIPS` | **证实**（大纲里有）。在两个演示场景里都出现 | 画面 4:33、5:02 |
| `skinCluster7`、`jaw01` | 脚本 | **没涉及**：大纲只看了顶层，没展开关节 | — |
| 30 帧/秒 | 12、03 第 5 节 | **证实** | 画面 12:55 |
| 从第 0 帧开始，0–14 帧沉降，运动从第 15 帧 | 12、03 | **证实**（语音）；时间轴动画范围从 0 | 语音 11:07–11:28，画面 12:55 |
| 运动是打在时间轴上的关键帧 | 12 | **没涉及**：界面逐步推进，日志是 `stepped to frame N`，但有没有关键帧画面没拍到。下面第 5 节要在现场确认 | 画面 14:46 |
| 钢琴界面加载运动、读 `combined_checkpoints.pkl` | 03 第 7 节 | **没涉及**：选 `Phoneme AA` 就开始，没有文件对话框；语音"调用算好的路径"，只是推断就是它 | 语音 13:18 |
| 甩头是给骨头网格打平移关键帧 | 03 第 13.8 节 | **没涉及** | — |
| 清 Ziva 缓存、重置回到起始帧 | 12 B 节 | **部分涉及**：研究员关的是 Ziva 的 playback；重置的按钮是 `Reset to Neutral (Reopen Rest Pose)`，字面是重新打开场景。没见到"缓存"这个词 | 语音 2:02、画面 14:46 |
| 研究场景是"完整场景" | 12 | **具体化**：完整可算的场景是 `neutral 260825 v15 made the teeth MESH.mb`；v36 代理会算崩 | 语音 4:16、5:01 |
| Ziva 机器上的 Maya 能跑自己的脚本 | 12 | **证实**：研究员明确说可以 | 语音 16:43–16:58 |
| 物理在前、landmark 蒙皮在后 | 03 第 4 节 | **口头复述与之相反，但不是研究员的明确陈述**，不改，要再问 | 语音 8:43–9:47 |
| 求解器参数（缩放 100、子步、牛顿迭代等） | 03 第 5 节 | **没涉及** | — |
| 材料数值、粘连刚度 | 03 第 5、6 节 | **没涉及** | — |
| 11 的 Q17（下唇算两遍） | 11 | **没涉及** | — |
| 11 的 Q18（粘连怎么生成） | 11 | **没涉及** | — |
| 11 的 Q19（烧伤改了什么） | 11 | **没涉及** | — |
| 11 的 Q5（许可到期日） | 11 | **没涉及** | — |
| 11 的 Q12（原型机范围和速度） | 11 | **部分回答**：见第 3 节最后几条（说话人不确定） | 语音 17:28–18:11 |

---

## 5. 因此要改的地方

**这次只新增了本文，没有改 03、11、12、脚本。**下面是该改的清单，下一步照着改。

**脚本 `tools/ziva_machine_export.py`**（不改代码，只列）：

1. 帧范围：`first`、`last` 默认"用时间轴"。演示里播放范围会被钢琴界面改成 1–36（动画范围是 0–50）。请把 `first=0` 明确写进 SETTINGS，或让预检打印用的是动画范围还是播放范围，并在 `last` 超出播放范围时报警。
2. 每帧耗时：把 `estimated_seconds_per_frame` 的预期放在 2.5 左右（演示机每帧约 1.5 到 2.5 秒）。AA 完整 36 步约 1.5 到 2 分钟，不是瓶颈；但每帧的耗时会随渲染质量和 playback 设置变。
3. 预检的 `Ziva 版本` 要打印出来（视频里读不到）。
4. 对完整场景才解算：预检遇到 `middleres_*` 节点太少、`zSolver1` 求解后无输出时，提示"这可能是简化代理场景"。

**导出清单 [12](12-lab-export-checklist.md)**：

1. "去之前"的场景名，写成 `C:\keyLabLocal_D\c99-maya-ziva-workshop\different pose as rest pose\neutral 260825 v15 made the teeth MESH.mb`，并说明 v36 代理会算崩（链到本文）。
2. 研究员的 Ziva playback 开关是什么，要在第 B 节"禁用/清空缓存"里换成他实际用的步骤。
3. "重置"一栏写钢琴界面按钮名 `Reset to Neutral (Reopen Rest Pose)`。
4. 进机器时先看有没有别人没关的场景，先保存再关；不要覆盖对方文件。
5. 脚本放进共享文件夹的新 project 下（路径名要再问）。

**文档 [03](03-asset.md) 第 5 节**：视频里没读到求解器、材料数值，不填。**第 4 节的顺序**见第 3 节最后一条，等研究员确认后再改。

**问题清单 [11](11-risks-and-questions.md)**：Q17、Q18、Q19、Q5 无回答，保持开着。Q12 可以记"研究员说原型机只要整条管线跑通、不必和 Ziva 对齐"（时间点 17:28–18:11，说话人不确定）；是否关掉要等确认说话人。

---

## 6. 没看清、要再问的

1. 钢琴界面的启动快捷键（12:00–13:00 语音失败，画面里快捷键没拍到）。
2. 运动文件（`combined_checkpoints.pkl`）在哪个目录或网络盘；钢琴界面选 AA 时读的是哪个路径。
3. Ziva 版本；zSolver、zMaterial、zAttachment 的数值（Attribute Editor 没打开）。
4. "playback"是 Ziva 的哪个开关，关掉等于清缓存吗。
5. 运动是打关键帧还是由界面逐帧推进；AA 的完整帧数（演示只看到第 36 帧，和 03 说的"从第 15 帧起 36 个检查点，到第 50 帧"差 14 帧，没解释）。
6. 物理和 landmark 蒙皮的先后顺序（第 3 节最后一条）。
7. 共享文件夹的确切路径：画面里只有 `OneDrive > physically based facial model > Eugene-lab-summer26`，下面有几个子文件夹，名字没读清；要新建的 project 名以 `b5` 开头，没听清。
8. 渲染输出目录的全名。
9. 说话人：17:28–18:11 那段是谁说的，要翻录像摄像头确认。
10. Q17、Q18、Q19、Q5：录像里没有答案，仍需直接问。
