# 09 归档：已完成和取消的任务卡

这里是从 [09 路线图与任务](../09-roadmap-and-tasks.md) 整张搬过来的任务卡：已经完成的，和取消的。内容没有改写。还没做完的卡、里程碑和接下来的顺序在 09。

前四张（T-34、T-35、T-38、T-11）是完整的卡。后面二十张（T-00 到 T-30，和取消的 T-21）在搬来之前就已经压缩过：只留了结果、证据命令和事实现在记在哪里，做法和验收清单在 git 历史里。

---

### T-34 用实验室的真实运动和 Ziva 的材料重跑嘴唇，和 Ziva 逐帧比 ✅ 2026-11-13（结果在卡片末尾和 [13](../13-explanations.md) E-19）
- **目标**：骨头加嘴唇，用实验室的中性到 AA 运动和 Ziva 实测的材料、求解器设置跑一遍回放；和 Ziva 两次运行（整张脸、只留嘴唇）同一帧逐帧比，分两列报告毫米差；重力下垂和甩头同样并排；量我们每帧的耗时。
- **为什么**：原型机二第一版的 AA 是我们拟合的替身（ADR-42 退役），材料是我们定的临时值。Ziva 的结果和设置现在都有了（[13](../13-explanations.md) E-11），差多少第一次能直接量。已知的差距：重力下垂，全部 10,240 个顶点、第 14 帧对第 0 帧、平均对平均，Ziva 只留嘴唇 1.777 mm、我们的原型 0.093 mm，约 19 倍（E-14）；只留嘴唇的 Ziva 在第 14 帧还在下落，所以这不是两个停稳的数在比（第 4 步）。甩头 Ziva 2.7 mm、我们 0.094 mm，但 Ziva 那次是整张脸，我们只有嘴唇（第 5 步）。这张卡把差距量准，不调参数去凑（调参是 T-12）。训练的底是静止形状，由 T-31 用 145 份存档钉住；这张卡只管回放。
- **按照**：ADR-17（和 Ziva 的差只作参考，不设合格线）、ADR-42；[13](../13-explanations.md) E-15（这张卡靠的事实，开工前先读）；[07](../07-validation.md) 第 4.2 节（差别怎么算）；[04](../04-architecture.md) 第 5.2 节（运动格式）。
- **范围**：只有骨头加嘴唇。
- **输入**（都在仓库外的数据文件夹里，`.local/ziva_trip_pointer.json` 指向它）：
  - 实验室的运动：`job_251205-190350/251205-190358` 的 `combined_checkpoints.pkl`，22 步，下颌转 −5.16°，landmark 最多移动 12.1 mm；
  - Ziva 的参考：同一段 AA 的整张脸和只留嘴唇两次，蒙皮前、蒙皮后嘴唇，逐帧（D3）；同一晚的甩头（整张脸）。这些 Ziva 回放都是我们的脚本照实验室的运动文件打关键帧播的，不是研究员在钢琴界面上按出来的。整张脸是实验室真实的配置，是参照；只留嘴唇是我们做的敏感性实验，实验室自己不跑它，边界条件和我们的 FEBio 嘴唇不同（我们：上唇硬约束、下唇弹簧、两个合成的嘴角锚；Ziva：嘴唇连在被关掉的组织上，作用不知道），不是同口径的参照。两列都不是合格线（ADR-17）；哪一次的边界条件和物理尺度确认了，才能叫同口径；
  - Ziva 的设置：材料、求解器和粘连的实测值只列在 [03](../03-asset.md) 第 5 节的表里（来源 E-11），按那张表设。没有现成的命令把它们写进场景：`asrp import-asset` 写出 `scene.json` 以后，改软组织的材料参数（来源标 `lab_setting`）和 `solver` 里的 `substeps_per_frame`、`fps`、`gravity_mm_per_s2`（[04](../04-architecture.md) 第 5.1 节）。把这一步做成能重跑的脚本或导入选项，是这张卡的一部分；
  - 数据的样子（E-11）：每个导出文件夹里有 `session_report.json`、`motion.json`（逐帧的关节和骨头矩阵），每条数据流一个 `<id>.points.f32`（小端 float32，帧 × 顶点 × xyz，世界坐标，场景单位，Y 轴朝上；1 个场景单位 = 0.962 mm）、对应的 `.abc` 和静止形状 `.obj`；`lips_physics` 是蒙皮前的嘴唇，`lips_final` 是蒙皮后。文件夹：`ziva_reference/AA_lips_only_export_*`（只留嘴唇，也有 `lips_final`）、`ziva_reference/neutral_to_AA_export_*` 和 `ziva_reference/head_shake_export_*`（都是整张脸）、`ziva_reference/AA_round_trip_x10_export_*`、`ziva_static/`（属性、权重表、网格）、`lab_motions/results/<job>/<run>/combined_checkpoints.pkl`、`probes/keys_*.json`（逐帧实际打的关键帧）、`scripts/`。AA 参考共 47 帧：第 0 到 14 帧不动（重力沉降），第 15 到 36 帧是运动（22 步），第 37 到 46 帧停在最后的姿态；我们的运行也要带这 10 帧停留。Ziva 的"只留嘴唇"是在内存里把嘴唇以外的 40 个 zTissue 和 2 个 zCloth（共 42 个）设成 `enable=0` 得到的；嘴角连到这些被关掉的组织上的粘连当时起了什么作用，不知道（🔍）。
- **运动转换（取自 T-10）**：这张卡做 T-10 里它要的那一部分，即从中性出发的单段过渡：第 0 到 14 帧不动，文件里第 i 步（从 0 数）落在第 15 + i 帧（[03](../03-asset.md) 第 7 节）；下颌按文件里的俯仰增量绕世界 X 轴转（上机时就是这样把运动放进 Ziva 的，E-11）；300 个 landmark 的平移乘 `mm_per_scene_unit` 并转成 Z 轴朝上，只用 `asset/coords.py`。代码放在 `src/asrp_core/trajectory.py`，运动文件的读取器是我们的产品。T-10 剩下的部分（全部 84 个运动文件、带平移的运动、转轴随时间变的方块试验）留在 T-10。
- **做法**：
  1. 转换运动，先单独证明转换对，分两半：
     - **驱动（下颌）**，和嘴唇的点无关：第 0 到 46 帧每一帧，我们转换出、交给 FEBio 的下颌变换，和 Ziva 的 `motion.json` 里记录的 `jaw01` 世界矩阵比。先去掉基姿：Maya 的矩阵是行向量约定，世界轴下的转动是 inverse(M0) × Mf（M0 是第 0 帧，Mf 是第 f 帧）；它是绕世界 X 轴的带符号转动，第 0 到 15 帧在容差内是 0（第 15 帧实际是 −0.0000016°，不是严格的 0），第 36 帧是 −5.16416°，第 37 到 46 帧保持不变。比带符号的角度，不比大小；只比角度不够：每一帧比完整的相对矩阵（或者它对至少三个不共线的点的作用），并比枢轴（铰链上的点）。Maya 骨头的绝对矩阵带一个静态缩放（骨头有 2.54 的因子），所以绝对矩阵不能转置以后直接当刚体变换用：一律先对同一个物体的基姿取相对矩阵，再检查它是正交的；
     - **landmark**：每一帧 f，Ziva 同一帧的蒙皮前 + 权重 × 我们转换出的第（f − 15）步的 landmark 位移，应等于 Ziva 同一帧的蒙皮后（和 T-09 的那项核对相同，这次用我们的转换结果当 landmark 输入）。第 0 到 14 帧位移为零，第 37 到 46 帧用最后一步；整张脸和只留嘴唇两次都做。不拿第 14 帧的形状去叠后面帧的位移。这一项只证明 landmark 的转换对，证明不了下颌、枢轴和帧的保持；
     - 读实验室的 pickle 要用一个受限的读取器：只允许基本容器和 numpy 数组（见这张卡最后的"注意"）；
  2. 导入场景，把材料和求解器改成 Ziva 的值，场景里来源标 `lab_setting`。能设的：杨氏模量、泊松比、密度、每帧子步数、帧率。设不了或没对上的，逐项写进报告的"没对上的设置"清单：
     - 本构：Ziva 的 41 块组织是 `StVK`，抗压参数（compressionResistance）20000；我们是 `neo-Hookean`。只对齐杨氏模量和泊松比，受压时的反应仍然不同；
     - 积分器：Ziva 是 `BackwardEuler`；
     - 牛顿迭代上限；
     - 刚度阻尼：我们的场景只有质量阻尼（[05](../05-ziva-to-febio.md) 第 4 节）；
     - 粘连：我们上唇是 `hard`，其余是刚度 100 × E × h 的弹簧（N/mm）；Ziva 是刚度 1×10⁸ N/m³（= 0.1 N/mm³）的软约束，要乘一个面积才是弹簧刚度，怎么换算由 T-37 定；
     - 物理尺度：我们按 k = 0.67 算；Ziva 有自己的求解器变换，实验室场景里三轴缩放都是 100。厂商文档说放大这个变换会缩小组织在仿真里的物理尺度，教程说它的 locator 上有 1 m 的刻度。🔍 推断，没有在机器上核实：没有别的父级变换时，100 个 Maya 单位相当于求解器里的 1 米。这是第三种长度尺度，不是 0.962 mm/场景单位，也不是我们的 k（[05](../05-ziva-to-febio.md) 第 2 节，[03](../03-asset.md) 第 5 节）；
     - 重力：我们写 9810 mm/s²，Ziva 是 −9.8，它怎么换成世界里的位移没有量过（🔍）。
     下垂大致和"长度² × 密度 × 重力 / 刚度"成正比，所以物理尺度和重力可能是差距里最大的一项（🔍）。所以比较时两边各用自己的世界几何；物理尺度没对齐之前，差别只报差别，不解释原因（校准是 11 的 D18）。代码里的默认值不在这张卡改（T-37）；
  3. 跑中性到 AA 的回放，出两种状态（[13](../13-explanations.md) E-13）：② 蒙皮前（物理层）和 Ziva 同一帧的蒙皮前比；③ 最终形状（同一帧的物理形状 + 同一帧的 landmark 层）和 Ziva 同一帧的蒙皮后比。Ziva 两次运行各一列（整张脸、只留嘴唇），各按自己的真实帧；另附一张两边差别的清单：材料、物理尺度、碰撞、约束、锚的运动。每帧报最大、平均和 P95（95% 的顶点都小于的差）。合理性检查全绿不等于表面没问题：外部审计用实验室真实的 AA 运动跑过一次我们的产品（默认材料，真 FEBio），合理性检查 PASSED，但最终层第 21 帧有 8 张显示面翻转，最后一帧有 3 张翻转、108 条边短于静止长度的一半（引自审计，E-17；2026-11-13 我们用默认材料自己跑出了同一组数，E-19）。这些数在产品里只报告，不判；没有证明它们是自相交或看得见的缺陷，原因也没查。报告里列出有翻转面和短边的帧、它们在嘴唇上的位置，并用视图或和 Ziva 同顶点的对照解释它们，不把绿色的合理性一行说成"表面没问题"。和 Ziva 比不设统一的合格线（ADR-17）。"最后的姿态"要写帧号：第 36 帧（运动刚停）和第 46 帧（再停 10 帧）在物理层差 0.10 到 0.14 mm（E-15），报告里每个"最后的姿态"的数都写明是哪一帧。② 和 ③ 不和目标姿态比。① 训练时的形状不在这张卡里，它不跑物理，由 T-31 对实验室存下的训练结果验收。必须失败的对照（第 1 步的驱动检查要抓住前三个）：下颌转动的符号反了；下颌的运动错开一帧；第 37 到 46 帧下颌回到中性；landmark 的列错开一位；
  4. 重力下垂：两边用同一组顶点（全部 10,240 个）和同一个量（最大位移、平均位移、顺重力方向的平均），第 0 到 14 帧每一帧对第 0 帧逐帧比，不只比第 14 帧：只留嘴唇的 Ziva 在第 14 帧还没停稳（第 13 到 14 帧嘴唇还动了最大 0.365 mm，E-15 第 7 条），它第 14 帧的最大 5.39 mm、平均 1.78 mm、顺重力平均 1.72 mm（对第 0 帧）是下落途中的一张快照。整张脸同口径最大 1.2 mm、平均 0.29 mm，两次各一列。我们的原型同口径平均 0.093 mm，对只留嘴唇约 19 倍（E-14）；报告里写明这不是两个停稳的数在比，Ziva 停稳后下垂多少不知道（要一段更长的只有重力的运行，11 的 D17）。Ziva 的参考帧就是它的第 14 帧：不为了让我们自己的"组织停稳"检查通过把参考帧往后挪。原型机一另有一个 0.095 mm，是自由顶点第 10 到 14 帧顺重力的平均，口径不同，不拿来比；
  5. 甩头：运动用 `tools/head_shake_motion.py` 写的那条。Ziva 那次只移动了颅骨和下颌，另外 8 块骨头（上下牙等）没动，整张脸里粘在它们上面的组织会被扯住，所以 2.7 mm 不全是惯性晃动（[13](../13-explanations.md) E-15）。这一条说的是 Ziva 那一侧：我们的生成器不把没有粘连、没有碰撞的骨头写进 FEBio，原型里的牙齿只是显示，不影响我们的嘴唇。先统一量法：Ziva 的 2.7 mm 是全部 10,240 个显示顶点的最大值，我们的 `relative_to_head` 只用自由顶点；两边用同一个顶点掩码、基准帧第 14 帧、运动停在第 46 帧、同一个观测时窗。报嘴唇相对颅骨的最大位移和停下后的衰减，衰减分两个数："第一次低于 0.04 mm"（Ziva：停下后第 14 帧）和"一直低于 0.04 mm"（Ziva：停下后第 28 帧起；中间第 16 帧回弹到 0.077 mm）。我们原型的甩头停下后保持的帧数比 Ziva 那次（共 127 帧）少，时窗里没有一直低于门限时，报"时窗内没有达到"，不报帧号。这是跨范围的比较：我们只有嘴唇，Ziva 那次是整张脸，Ziva 没有只留嘴唇的甩头（[11](../11-risks-and-questions.md) D16）；报告里这一行标明"我们：只有嘴唇；Ziva：整张脸"。写明我们的数在时间步上没有收敛（T-33），只作并排；
  6. 速度：写明我们量的是求解器的耗时还是连写文件的整帧耗时，写明线程数和机器。两边不在同一台机器上，线程也不一样：我们的数是本机 FEBio 4 线程（默认，ADR-38；1、4、8、16 线程是 56.2、26.8、29.7、38.6 秒，4 线程最快）；Ziva 的数是实验室那台机器，16 个逻辑处理器，Maya 的线程数设的是 16，Ziva 求解器实际用了几个线程没有量（🔍）。所以速度并排是跨机器、跨线程数的，只能看量级。报告里两边各写：机器、逻辑处理器数、线程数。再加一栏网格规模：我们的计算点数和四面体数（现在 6,747 和 26,721，边长中位数 2.42 mm），Ziva 嘴唇的四面体尺寸（26.37 个场景单位，约 25 mm；实际个数没取回）。网格粗细差约 10 倍时比的不是求解器（[13](../13-explanations.md) E-18）。只和 Ziva 同口径的数比：Maya 求解器日志里只留嘴唇最后 46 行平均每步 0.0095 秒；整张脸当晚各次运行平均每步约 1.47 到 1.60 秒，有单步超过 3 秒（读日志的脚本取的是全局日志的最后几行，可能混进别的运行）；连写文件的导出是只留嘴唇每帧 1.03 秒、整张脸每帧 2.55 秒（E-15）。求解时间和导出时间不混用。写明 Ziva 的"一步"是什么（每帧 1 个子步）。
- **输出**：运动转换的代码和测试；`src/asrp_core/compare.py` 里的差别计算（T-11 在它上面接着做）；一份对比报告（JSON，只有数字，不含实验室的网格），内容是每帧的最大差、平均差和 P95（mm，物理层和最终形状分开）、逐帧的下垂、甩头、速度三张并排的表、没对上的设置清单。报告和结果页一起提交，位置由 T-36 定。
- **验收**（每条附真实命令和输出）：
  - 驱动：第 0 到 46 帧每一帧，交给 FEBio 的下颌带符号转角和 Ziva `motion.json` 里 `jaw01` 去掉基姿后的转角差小于 0.01°（第 0 到 15 帧在容差内是 0°，第 36 到 46 帧 −5.16416°）；每一帧的完整相对矩阵（或它对至少三个不共线的点的作用）一致，枢轴一致；转动的符号反了、错开一帧、第 37 到 46 帧回到中性、枢轴挪开，四个对照都必须失败；
  - landmark 转换：每一帧 f，Ziva 同一帧的蒙皮前 + 权重 × 转换后第（f − 15）步的 landmark 位移，和 Ziva 同一帧的蒙皮后最大差小于 0.01 mm，整张脸和只留嘴唇两次都过；把 landmark 列错开一位的对照组必须差 1 mm 以上；
  - 差别计算：Ziva 和它自己比，差为 0；人为平移 1 mm，平均差报告为 1 mm；
  - 逐帧差的表每一帧都有最大、平均、P95 三个数，帧数和 Ziva 参考的帧数相同；下垂表第 0 到 14 帧每一帧都有数；甩头表写明两边用的顶点掩码、基准帧（第 14 帧）、停止帧（第 46 帧）和观测时窗，有"第一次低于 0.04 mm"和"一直低于 0.04 mm"两个数（时窗内没有达到就写"时窗内没有达到"）；有翻转面和短边的帧和位置有一张表；逐帧差和下垂两张表有 Ziva 整张脸、只留嘴唇两列，甩头、速度表有我们和 Ziva 两列，没有空格；有两边差别的清单（材料、物理尺度、碰撞、约束、锚的运动）；每个"最后的姿态"的数写明第 36 帧还是第 46 帧；
  - 运行报告的溯源里，我们能设的值等于 Ziva 的值（杨氏模量、泊松比、密度、每帧子步数、帧率）；设不了的逐项列在报告里，至少有：本构（`StVK`、抗压参数 20000，对我们的 `neo-Hookean`）、积分器（`BackwardEuler`）、牛顿迭代上限、刚度阻尼、粘连刚度的单位（N/m³，要乘面积）、物理尺度（k 对 Ziva 的求解器变换）、重力；
  - 检查 a、b、b2、c、d 照常跑，结果照实报告，不通过也报告；全部通过时也列出翻转面和短边（只报告的那几项），和 Ziva 自己的数并排：用同一个算法数，Ziva 的物理层（蒙皮前）一个翻转面也没有；Ziva 的最终形状最多 4 个（第 20 帧）、最后一帧 3 个、短边 37 条（只留嘴唇 39 条）；实验室存下的 AA 训练结果 5 个、短边 121 条。翻转来自 landmark 层，Ziva 自己也有（[13](../13-explanations.md) E-17，`tests/test_lab_facts.py`）。这是 ADR-43 的参照线：我们的数明显多于 Ziva 时，报告里写明哪几帧、在嘴唇的什么位置、可能的原因；物理层和最终形状分开报；
  - `uv run python tools/verify.py` 通过。要仓库外数据的测试在没有数据时跳过，并在输出里写明跳过。
- **不做**：调参数去接近 Ziva（T-12）；其余 40 块组织（第二阶段）；改代码里的默认值（T-37）；Ziva 结果的回放包和热力图（T-11）；判断合格不合格（ADR-17）。
- **依赖**：T-09 ✅、T-28 ✅；仓库外的数据文件夹。
- **改动范围**：`src/asrp_core/trajectory.py`、`src/asrp_core/compare.py`、`tests/`。
- **规模**：中。
- **注意**：运动文件是 Python pickle，普通的加载会执行代码。这张卡加了受限的读取器（`trajectory.read_lab_motion`）：只允许基本容器和 numpy 数组，别的类型一律拒绝；只读实验室直接给的文件；转换成我们的 JSON 以后，产品不再读 pickle。
- **结果**（2026-11-13，细节和逐帧的表在 [13](../13-explanations.md) E-19，数字在 `data/preview/ziva_comparison.json`）：`src/asrp_core/trajectory.py` 加了只读数据的读取器 `read_lab_data` / `read_lab_motion` 和转换 `from_lab_motion`（读取器的第一版被独立审查做出了让它崩溃的文件，已改成解包时不让 numpy 参与的版本，有测试），命令是 `asrp convert-motion <运动文件> <scene.json> <输出> --starts-at-rest`；`asrp import-asset --tissue-settings lab` 把能设的设成 Ziva 的值；`src/asrp_core/compare.py` 是差别计算；`tools/ziva_comparison.py` 用产品自己的命令从导入跑到报告，T-37 每改一项默认值可以原样重跑。转换的证明（`tests/test_lab_motion.py`，要仓库外的数据）：下颌第 0 到 46 帧每一帧对 Ziva 的 `jaw01`，带符号的转角、完整的相对变换、下颌和下牙 32,034 个顶点的落点、枢轴，差都在 10⁻¹³ 量级，四个对照（符号反、晚一帧、停留段回中性、枢轴挪 1 mm）都失败；landmark 每一帧最大差 0.000016 mm，两次运行都是，两个对照都失败；另外真的改坏数据试了 12 种，全部被抓住。中性到 AA，物理层，全部 10,240 个顶点，第 36 帧：对整张脸平均 2.21、P95 4.91、最大 7.64 mm；对只留嘴唇平均 2.32、最大 7.10 mm；最终形状的差和物理层相同（两边叠的是同一个 landmark 层）。下垂第 14 帧对第 0 帧平均：我们 0.122、整张脸 0.293、只留嘴唇 1.777 mm（还在下落）。甩头同一量法：我们 0.121 mm，Ziva 2.731 mm（跨范围，我们的数在时间步上没有收敛）。表面：物理层两边都是 0 个翻转面；最终形状我们最多 8 个、Ziva 4 个，最后一帧两边是同样的 3 个面；短边我们 109 条、Ziva 37 条，量到这一片嘴唇的顶点在我们的物理层里移动得比 Ziva 的少，是什么造成的没有分开。五项合理性检查全过。报告的每张表有没有空格由 `tests/test_ziva_comparison_report.py` 查。**没做的**：没有调参数，没有改默认值；差距的原因没有查（物理尺度没对齐，D18）；速度只量了一次。这张卡留在这里没有归档，因为 T-36、T-37 还在引用它的步骤。

---

### T-35 在 Blender 里三步：打开资产、选运动、Run，在同一组物体上回放 ✅（2026-11-16；命令行下的检查通过，带窗口用鼠标从新开的 Blender 走了四遍，前三遍发现的问题修了，第四遍的截图在 [15](../15-prototype.md) 第 2.2 节；剩下的两条小问题写在卡片末尾）
- **目标**：不用命令行的研究员在 Blender 里做三步：打开资产，颅骨、下颌、牙齿、嘴唇出现在视口里；选一条运动；按 Run。算完以后结果在这些物体上播放，用 Blender 自己的时间轴。
- **为什么**：在 Maya 里用 Ziva，可以打开场景、播放、在视口里看结果（研究员在钢琴界面里实际看到什么没量过，🔍）。我们现在要在命令行里导入、运行，再把回放包加载进 Blender（[15](../15-prototype.md) 第 2 节）。下周给实验室看的就是这个用法。
- **范围**：骨头加嘴唇。不做钢琴界面（那是实验室的工具），不做其他组织，不做 Ziva 结果的回放（T-11）。
- **开工时的现状**（2026-11-13 以前，已被下面的结果取代）：面板有 Run、Results、Checks 三个小节（T-13）。资产小节（[06](../06-ui.md) 第 3.1 节）和运动下拉框还没做（06 的"设计里有、还没做"）。插件现有的回放构造默认显示物理层，而且新建物体（T-37 第 10 项），不能当成这张卡已经做了。
- **按照**：06 第 2、3.1、3.3、3.4 节；ADR-03（插件只管界面，计算在核心程序里）；面板上的文字是英文（06 开头）。
- **输入**：`data/lab_export/` 导入成的场景；运动：T-34 转换的中性到 AA，`tools/head_shake_motion.py` 的甩头。T-34 的转换没做完时，先用 `tools/placeholder_jaw_motion.py` 的代用张嘴开发。
- **输出**：插件里的资产小节和运动选择；回放加在资产里已有的物体上；`tools/check_panel.py` 里的新检查；06 第 3 节按做出来的样子改写。
- **验收**：
  - `tools/check_panel.py`（命令行下的 Blender，只在验证门的 full 级里跑）走一遍三步：打开资产后，场景里有颅骨、下颌、上牙、下牙、嘴唇五个网格物体；选运动并 Run，完成后被更新的是打开资产时的那五个物体（按物体身份查，不按个数查：删掉旧的再建同样多的新物体也要失败）；
  - 显示哪一层要点名：AA 默认显示最终形状（同一帧的物理 + landmark 层），甩头默认显示物理层。嘴唇在一个运动中间、landmark 层不为零的帧（AA 第 15 到 36 帧中选一帧，先确认那一帧的 landmark 层不为零）、第 36 帧和最后一帧的顶点，和运行文件夹里同一层的网格差小于 1×10⁻⁵ mm。这个差在 Blender 物体本地几何的毫米里量，和对应的网格缓存比，不用已经按物体缩放换成米的坐标。第 0 帧和第 14 帧两层相同，只查它们证明不了显示的是哪一层；
  - 骨头和嘴唇在同一帧：甩头查颅骨和下颌，AA 查下颌和下牙，上面每一帧的变换和运动文件一致；该不动的物体确实不动；嘴唇显示的是同一帧的结果；时间轴的帧数和帧率等于运动的；
  - 对照：故意把结果加到一个新建的物体上；AA 故意显示物理层；嘴唇比骨头晚一帧；甩头时颅骨不动。每个对照都要让上面对应的检查失败；
  - `tools/check_panel.py` 现有的回归检查留着，三步的流程不取代它们：取消一个真实的进程、关闭后没有子进程留下、运行中途重开文件、残缺的报告；
  - Checks 小节在五项都通过时，也列出只报告的翻转面和短边（哪几帧、多少个），不把绿色的合理性一行显示成"表面没问题"（外部审计在真实 AA 上量到全绿时最终层第 21 帧有 8 张翻转面，T-34 第 3 步）；
  - 三步里不需要输入任何文件路径，运动从列表里选；
  - 带窗口的 Blender 手动走一遍（`tools/panel_windowed_check.py`），记录看到的；
  - 插件里没有计算代码（06 第 6 节）。
- **不做**：钢琴界面；逐帧接着算（T-30）；其他组织。（开工时也不做 Ziva 结果的回放和物理设置小节，后来在第二轮里做了：Compare with Ziva 和只读的 Physics setup。）
- **已知的限制**：插件写的是 `render.fps = int(fps)`。实验室是 30 帧/秒，没有问题；不是整数的帧率会被截断。T-11 要么拒绝别的帧率，要么换算。
- **依赖**：T-13（面板的三个小节已有）；AA 那条运动要 T-34 的转换。
- **改动范围**：`blender_addon/`、`tools/check_panel.py`、`tools/panel_windowed_check.py`、`docs/06`；可能要动 `src/asrp_core/cli.py`（列出可用的运动）。
- **规模**：中。

- **结果**（2026-11-13）：面板有 Asset、Motion、Run 三个小节（`blender_addon/asrp_blender/asset.py` 和 `__init__.py`）。Open asset 用项目的 `data/lab_export` 调 `asrp import-asset`，建五个网格物体；运动列表来自 `asrp list-motions`（`src/asrp_core/motions.py`），列的是 `data/lab_export/trajectories/` 里的 `head_shake.json` 和 T-34 转出的 `neutral_to_AA.json`；Run 完成后结果放回这五个物体：嘴唇用网格缓存，骨头按运行文件夹里 `trajectory.json` 的逐帧变换打关键帧。有 landmark 层的运行默认显示最终形状，没有的显示物理层。插件里没有计算代码：骨头只播运动文件自己的驱动源，跟着派生驱动源的骨头会被拒绝。`tools/check_panel.py` 的三步检查（命令行下的 Blender，真实的 `asrp run`，真实的 AA 运动）：五个物体按身份（`session_uid`）查；甩头显示物理层，第 24、36、86 帧，AA 显示最终形状，第 25、36、46 帧，嘴唇在物体本地几何的毫米里和运行文件夹同一层的缓存差 0（门限 1×10⁻⁵ mm），检查前先确认中间那一帧两层差大于 0.05 mm；骨头在这些帧等于运动文件的变换，该不动的不动；时间轴的帧数和帧率等于运动的。四个对照都走同一个检查函数并被对应的检查抓住：甩头时颅骨不动（要求报的就是颅骨）、AA 显示成物理层、嘴唇比骨头晚一帧、结果放到新建的物体上。三个操作没有路径属性。原有的回归检查都留着。独立审查之后改了三处：运动文件夹里有一个不是文本的文件时列表不再整个失败、甩头对照要求点名颅骨、06 里的示例来源。**没做的、没验证的**：插件装进 Blender 自己的插件目录时要靠 `ASRP_PROJECT` 找项目，这种装法没验证；landmark 小点、在文本编辑器里打开导入报告、导入的进度条没有做，Open asset 时窗口会等几秒；清理子进程的回归检查把等待从约 1 秒放宽到约 9 秒（机器忙时 Windows 上结束进程树有延迟）；运行报告的 `surface_health` 只记最后一帧和最差的一帧，所以 Checks 小节只能说出这两帧的翻转面和短边。
- **带窗口用鼠标走一遍的发现**（2026-11-15，项目负责人要求；像使用者一样只用鼠标键盘，文档要求敲命令的地方照抄文档的命令；原型一、原型二各一遍。`tools/panel_windowed_check.py --three-steps` 也跑通了，但它是脚本替人按按钮，下面这些大多是它看不到的）：
  1. 仓库里没有现成的插件包，README 只写了命令行的装法。Blender 的 Edit > Preferences > Add-ons > Install from Disk 能装，但要先用命令行把包打出来；**已修一半**：README 的 "Install the Blender add-on" 现在写成一条打包命令加用鼠标装的步骤；包还是要用那一条命令打，仓库里仍没有现成的包；
  2. 装好以后按 Open asset，弹出 "ASRP project not found; set ASRP_PROJECT"：要设一个环境变量，Blender 里没有地方设，报错也不说设成什么。这一步把使用者挡在门外；**已修**：项目文件夹的偏好加面板上的 "Choose the ASRP project folder (once)" 和 Choose project folder 按钮（06 第 2 节），找不到项目时三步灰掉并写原因，不再出现这条报错；
  3. 装好、关掉再打开 Blender，插件前面的勾没了，ASRP 标签不见，要去 Preferences 里重新勾上（只见到一次，原因没有查清，🔍）；**没有重现，也没有找到插件这一边的原因**：用隔离的用户配置（`BLENDER_USER_RESOURCES` 指向临时文件夹）照 README 的办法打包、安装、勾上、退出再启动，勾还在，选的项目文件夹也在（`tools/check_panel.py` 的 case 12，每次验证都跑）；让 `register()` 抛错再存一次偏好，重新启动后勾仍在（面板不在，因为没注册上；改好以后又回来），所以 `register()` 出错不会把勾弄掉；项目找不到时 `register()` 不受影响（找项目是用到时才做的）。剩下的可能：Blender 退出时没有存偏好（"Auto-Save Preferences" 关着，或是别的 Blender 版本、别的配置文件夹，或用 `--factory-startup` 启动过），这些不是插件能控制的；面板上选项目文件夹时现在会立刻存一次偏好，勾也随之存下；
  4. Open asset 以后资产在启动场景的 2 米方块里面，完全看不见（当天已修：罩住资产的物体被隐藏，视角对准资产）；
  5. Run 完成以后视口不动，停在第 0 帧，面板上没有任何提示要去按时间轴的播放键；时间轴仍然显示 0 到 250 的范围，运动的 47 帧挤在最左边；**已修**：Run 完成后当前帧回到运动的第 0 帧，帧范围是运动的，每个时间轴 / 摄影表区域缩放到这个范围，自动开始播放，Run 小节有 Play / Pause 和 "Playing frame 0 to 46. Space bar pauses."（没有窗口的命令行检查只看得到当前帧、帧范围和播放请求；缩放和自动播放在带窗口的 Blender 里没见过）；
  6. 原型一没有界面入口：要先敲三条命令（导入、生成张嘴运动、运行），再用 Load result。加载以后视口是空的，要自己点 View > Frame Selected；看到的只有一块灰色的嘴唇，从背面看，没有颅骨和下颌；**已修**：原型一的张嘴 12 度是列表里的第一条 "Prototype 1: jaw opens 12 degrees (test motion)"（`data/lab_export/trajectories/jaw_open_12deg.json`，由 `tools/placeholder_jaw_motion.py` 写），默认选中，和另外两条一样在五个物体上带骨头播放；
  7. 甩头的 4.5 mm 在默认视角下只有几个像素（第 19 帧和第 0 帧相比，视口里约 5% 的像素不同），播放时几乎看不出来；
  8. 面板最上面是 Load result 和 Check backend，三步没有编号，新使用者不知道先点哪个；Load result 和 Load run folder 是两个意思相近的按钮；**已修**：三个小节标成 "1  Open the asset"、"2  Choose a motion"、"3  Run"，Load result、Check backend、Load run folder 和 Run other files 都挪进最下面收着的 "Advanced"；
  9. 运动列表显示的是文件名和内部用语（ours、lab_setting、landmarks），第二行在默认宽度下被截成 "neutral_to_AA: 47...etting, landmarks"；默认选中的是按字母排第一的甩头，不是实验室的运动；**已修**：列表每条是标题加一行较小的细节（"47 frames, 30 fps, lab motion"），"ours" 和 "lab_setting" 说成 "test motion" 和 "lab motion"，默认选第一条（原型一）；标题写在运动文件的 `title` 里（04 第 5.2 节）；
  10. Checks 里两行名字被截断（"(b) Hard attachments follow b…"），整节要往下滚才看得全，用语是内部的（Tet mesh valid、edges < 0.5x）；**名字已修**：名字最长 28 个字符，Checks 默认收着；"Tet mesh valid" 和 "edges < 0.5x" 的用语没有改；
  11. Load result 的文件窗口从"文档"文件夹开始，不是项目的 runs；右边有一个要手打的 version 文本框；
  12. 面板的 Open asset 用的是默认材料（15 kPa），T-34 的报告用的是 Ziva 的值（12 kPa），所以面板里的短边是 108 条、报告里是 109 条；面板上不写用的是哪一套。**已修**：Open asset 用 `--tissue-settings lab`，Asset 小节从导入的 `scene.json` 读出并写 "Material: 12 kPa, 0.4 (measured in Ziva)"。第 7 条（甩头看不清）这一包没动；第 11 条（Load result 的文件窗口）没动。
- **第二轮 A 部分**（R-01、R-02 剩下的部分，写法在 06 第 3.1、3.2 节）：
  - 一个 .blend 就是一个场景：存盘、另开一个 Blender 进程打开，面板认得资产和资产上的结果，结果照样能播、能切层、能换一条运动再 Run；场景文件夹或运行文件夹不在了，面板用一句话说清并仍可按 Open asset；File > New 回到空状态。Asset 小节写 "This .blend is the scene. Save it to keep the asset and the last result."；
  - R-01：第六个物体 "ASRP landmarks"（300 个 landmark，每个一个 1.6 mm 宽的小八面体，位置读 `scene.json` 的 `rest_positions_mm`，核心程序没改）、Show landmarks 复选框（默认开，有结果时自动隐藏并说明原因）、单位一行、导入报告几行和 Open import report 按钮；
  - R-02：Physics setup 小节（软组织、骨头、连接，来源用人话写，每行一个高亮按钮，Clear highlight，Check setup 跑 `asrp check`，最后一行写明只读）；
  - `tools/check_panel.py` 新增：case 13（真实存盘、另一个 Blender 进程重开、文件夹被搬走）、三步检查里的 landmark、单位、报告、Physics setup 行、高亮（结果不被打乱、Clear highlight 逐项还原）和 Check setup（好场景和一个连接没有顶点的场景）；每一项都在把对应的修复关掉以后看到它失败过。
- **第二轮，手走一遍以后的修正**：顶上那行 "Choose the ASRP project folder (once)" 被截断，改成两行短字，说明在主面板只写一次，三步各自灰掉；运动标题被截断，改成 "Prototype 1: jaw opens 12 deg"、"Prototype 2: neutral to AA"、"Prototype 2: head shake"（来源在下面一行写），标题最多 34 个字符，更长的 `trajectory.read` 拒绝；"On the asset:" 的运行名另起一行折行；Advanced 里写 "Project: <文件夹名>" 和 Change project folder；检查里每个小节画出来的每段字都量，超过 34 个字符就失败（把一行改回长文字时看到它失败）；运行完成后 Run 小节停在 "Complete" 加播放状态（检查里核对）。粗格子默认以后一次运行约 1 秒。
- **第二轮，第二次手走以后的修正**：第 1 步只留单选按钮、Open asset、"Open: …"、Show landmarks，其余收进默认收着的 "Asset details"，"Physics setup" 默认收着，运行文件夹挪到 Advanced，次要的行改成小字，打开资产并有结果时面板从顶到 Results 按钮约 620 像素（预算 650，检查里算，全部展开是 1372，所以检查会失败）；Run 按钮永远是第 3 步的第一行；没选项目文件夹时四面体那一行不写数；连接的刚度写 "(Ziva's stiffness, our area rule)"，左右嘴角两行用名字里不同的词分开；高亮改成嘴唇前面的一组小点（几何节点，跟着结果走，嘴唇自己的显示不动）；默认选中的运动是第一条来源标签为 `lab_setting` 的（现在是实验室的 AA），列表顺序不变；Run 在运行中、或刚结束 1 秒内再按被拒绝。视角跳变：插件里只有 Open asset 设视角，检查里每次 Run 前后核对每个 3D 视图的视图矩阵不变（没有发现插件移动视角；缩短面板以后按钮不再随结果移动）。
- **第二轮 B 部分**：
  - 四面体网格的选择（06 第 3.1 节）：Open asset 上面两个单选按钮，Coarse lattice 是默认（`--tetmesh data/tetmesh/lips_lattice.json --attachments ziva-soft`），Fine 和以前一样；一行说明随选择变，四面体数读网格文件；改选择不悄悄改任何东西，写 "Press Open asset again to use this mesh."；用粗格子时检查 (b) 显示 NOT RUN，不算失败；运行报告里的翻转面 warning 显示成 "Reported, not a check"；
  - Compare with Ziva（06 第 3.5 节）：参考文件夹存在插件偏好里，Compare 在后台跑 `asrp compare`，数字读 `compare_report.json`，Show Ziva's lips（第二个物体，灰蓝色，跟着显示的层），Show difference as colours（读 `.f32`，固定刻度 0 到 5 mm，帧变处理函数，取消勾选时还原）；
  - `tools/check_panel.py`：三个运动在默认的粗格子上从面板跑完并匹配各自的缓存；Fine 导入的场景和以前一样并能跑；对比部分在真实的 AA 导出上跑（数据在项目外，用 `tools/local_paths.py` 找；找不到时这一部分打印 NOT VERIFIED 和原因，不算通过）。
  - **没验证的**：带窗口时的样子（280 像素下有没有被截断的字、高亮的黄色在视口里是否一眼看得出、Open folder 和 Open import report 真的打开）；带着结果列表（Load result 等）的 .blend 存盘再打开。
  第 4 条当天修了，并且加进了检查：命令行下的三步检查原来在按 Open asset 之前先把场景里的网格（包括那个方块）删掉，所以看不到这个问题；现在它保留一个和启动场景一样的 2 米方块，要求打开资产后方块被隐藏而不是删除、旁边的物体不受影响，关掉修复时检查失败。
- **第三、四遍手走**（2026-11-15 到 16，装的是整批合起来的包，从新开的 Blender 只用鼠标）：第三遍在一屏里走完三步（粗格子默认，AA 算完自动播放、显示最终形状），Compare with Ziva 在面板上给出 "mean 1.88 mm, 95% 3.60 mm, max 5.09 mm"，差别着色和 Ziva 的嘴唇都出来；Ctrl+S 存盘、退出、另开 Blender 从最近文件打开，资产、第 36 帧的结果、选的运动和对比的数都在；在重开的场景上换原型一再 Run，结果被替换；甩头能跑。第三遍发现的三处当天修了，各加了检查并看到它在关掉修复时失败：
  1. Checks 里 "(b) Attachments follow bon…" 在 NOT RUN 旁边被截断：两行改名 "Hard attachments"、"Spring anchors"；
  2. 在已有资产的场景里再按 Open asset，新物体叫 "ASRP jaw.001" 之类（旧物体还占着名字时建的）：建完、删掉旧的以后改回原名；
  3. 再按 Open asset 以后 Run 小节仍写着上一份资产的 "Complete"：打开资产时清掉运行状态。
  另外 Open asset 的视角改成从正面看（项目负责人问"为什么不是正面图"），第四遍在正面视角下重拍了全部截图，包括细网格上的原型一。第二轮里视角跳到正面的现象，第三遍时发现鼠标停在我没放的位置、Blender 处在旋转视图的拖动里：是项目负责人同时在用鼠标，和我的点击撞上；插件里没有找到移动视角的代码，检查在每次 Run 前后核对视图矩阵不变。
- **剩下的**（不挡交付）：第 7 条，甩头 4.5 mm 在默认视角下几乎看不出来（结果页有放大的动图）；第 11 条，Advanced 里 Load result 的文件窗口从"文档"文件夹开始、有一个要手打的 version 框；"Tet mesh valid"、"edges < 0.5x" 的用语没有改；插件装进 Blender 时还要先用一条命令打包（安装包是 T-40）。

---

### T-38 一次性开发文件移出仓库 ✅（2026-11-15）
- **目标**：仓库里只留产品、产品的检查和资产管线；一次性的开发脚本、试验、为一页文档写的数字工具和它们的存档移出仓库。
- **为什么**：仓库装的是项目，不是开发过程（2026-11-13 定）。[13](../13-explanations.md) E-12 的分类：`tools/`、`spikes/`、`tests/`、`data/` 里有 35 个一次性的文件（PROCESS）。
- **做法**：
  1. 先处理被验证门或测试用到的试验文件：`spikes/s1_dynamic_jaw.py`（`tools/check_playback.py` 运行它，`tests/test_febio.py`、`tests/test_run.py` 导入它）、`spikes/s2_lips_febio.py`（`tests/test_tetmesh.py` 导入）、`spikes/s3_attachment.py`（`tests/test_s3_attachment.py`）。这三个是检查，搬进 `tests/` 或 `tools/`。`tests/test_surface_health.py` 导入的 `spikes/audit_aa_folds.py` 同样先把用到的部分搬走；
  2. 其余的按 E-12 的清单移到仓库外的开发归档（和上机脚本同一个数据文件夹）。git 历史里仍然有；
  3. 指向它们的地方跟着改：`pyproject.toml` 的 `pythonpath` 和 `per-file-ignores`；`src/` 里引用试验脚本路径的注释改成引用 ADR 或 13 的条目；README 和文档里的命令；
  4. 本机的路径不进仓库。**已做（2026-11-13）**：指针文件移到被 git 忽略的 `.local/`，位置由 `tools/local_paths.py` 从 `.local/` 或环境变量读，工具和测试里不再有写死的本机路径；验证门拦被跟踪的 `.local/` 文件，也拦任何写着本机文件夹的被跟踪文件（[08](../08-engineering-standards.md) 第 6 节）；
  5. **本机 AI 开发用的文件也是本机的，不进仓库**（2026-11-13 项目负责人定）：`AGENTS.md`、`CLAUDE.md`（如果有）和 `.claude/` 整个文件夹（现在被跟踪的是 `.claude/verify.json`）。做法：从 git 里取消跟踪，本机的文件留着不动、内容不改；加进 `.gitignore`；`tools/check_no_lab_files.py` 把它们列进"不许被跟踪"，同时去掉现在让 `AGENTS.md` 可以带本机路径的那条例外；`tests/test_docs_references.py` 不再把 `AGENTS.md` 当成仓库里的文档来查；[08](../08-engineering-standards.md) 第 6 节和别处提到 `.claude/verify.json` 的地方改成"每台机器自己的设置"，验证命令本身（`uv run python tools/verify.py --level auto`）写在文档里。本机的 Stop 钩子照旧读本机的 `.claude/verify.json`，不受影响。
- **验收**：
  - 一个列出 E-12 那 35 个路径的检查：`git ls-files` 里一个都不剩，剩一个就失败；
  - `git ls-files` 里没有 `AGENTS.md`、`CLAUDE.md` 和 `.claude/` 下的任何文件；故意把其中一个加回去，验证门必须失败；取消跟踪前后本机这些文件的内容逐字节相同；
  - 搬过去的三个检查仍在验证门里跑；
  - `git grep -n "spikes/"` 在 `src/` 里没有结果；
  - `uv run python tools/verify.py` 通过（含 `tests/test_docs_references.py`）。
- **不做**：改产品代码的行为；改 `AGENTS.md`、`CLAUDE.md` 的内容；改写 git 历史（旧提交里还留着的指针文件和这些 AI 开发文件2026-11-13 项目负责人定：现在不抹，等第一阶段做完或者整个产品做完时再说）。
- **依赖**：T-36（15 的数字工具和存档等结果页改完再移）；T-37 的第 7 项。
- **改动范围**：`tools/`、`spikes/`、`tests/`、`data/preview/`、`data/briefing/`、`pyproject.toml`、`.gitignore`、`README.md`、文档里的命令。
- **做了（2026-11-15）**：E-12 清单里的一次性文件移出了仓库（`tools/` 的 `rehearse_ziva_export.py`、`lip_attachments_preview.py`、`render_playback.py`、`briefing/`；`spikes/` 整个目录；`data/briefing/`、`data/lab_export/manual_maya_obj/`、`data/preview/` 里一次性脚本的输出和讲解页的图），存在仓库外的开发归档里，git 历史里仍有。三个检查和 `landmark_layer_check.py`（`tests/test_skinning.py` 要用它）搬进了 `tests/`：`tests/s1_dynamic_jaw.py`、`tests/s2_lips_febio.py`、`tests/s3_attachment.py`、`tests/landmark_layer_check.py`，`pyproject.toml` 的 `pythonpath` 只剩 `tools`。清单里有几条后来成了产品、留下：`tools/prototype_numbers.py`、`tests/test_prototype_page.py`、`tests/test_render_prototype.py`、`data/preview/prototype_*`（结果页 15 读它们；`prototype_run_report.json` 也在其中，`prototype_numbers.py` 读它）和 README 的动图。`AGENTS.md` 和 `.claude/verify.json` 已从 git 取消跟踪（本机文件内容不变，已核对哈希），`.gitignore` 加了 `AGENTS.md`、`CLAUDE.md`、`.claude/`，验证门拒绝它们被跟踪（`tests/test_no_lab_files.py`）。`tests/test_one_off_files_gone.py` 列出要移走的路径，剩一个就失败，也进 docs 级。`docs/15` 里那条命令已改成 `tests/landmark_layer_check.py`（存档随之重新生成）。
- **规模**：中。

---

### T-11 Ziva 参考导入和并排比较工具 ✅ 2026-11-15（命令、热力图数据、Ziva 回放包做完；Blender 面板的对比小节是 T-13 的）
- **目标**：`asrp compare`，实现 [07](../07-validation.md) 第 4.2 节的差别计算和报告、热力图数据，并把 Ziva 结果也做成回放包，让 Blender 能同时播放两边。差别计算的第一部分由 T-34 做（`src/asrp_core/compare.py`），这张卡在它上面做命令、热力图数据和 Ziva 的回放包。
- **注意**：Alembic 里的时间单位是秒。实验室场景是 30 帧/秒，读回时要按 30 帧/秒换算；按 24 帧/秒读，第 14 帧会读成第 17.5 帧。
- **输入**：我们这一侧的运行结果和回放包（T-06a ✅）；Ziva 一侧是取回的结果（数据在仓库外），做成同样格式的回放包。Ziva 的数据按流接收，每一路带：运行 id、流 id、真实帧、文件长度、运动覆盖到哪一帧、读回的结果（[13](../13-explanations.md) E-15 的导出状态表），不看导出的总状态。
- **点和连法是两件事**：Ziva 里嘴唇每一帧的三角形连法都变，顶点顺序不变（E-11）。所以"点一致"和"连法一致"分开写：比较的是按原顶点顺序的点；固定拓扑的回放包装不下逐帧变的连法，回放包用第一帧的连法，并写明这一点。
- **帧率**：插件现在写 `render.fps = int(fps)`，不是整数的帧率会被截断。这张卡要么拒绝 30 帧/秒以外的帧率，要么换算。
- **验收**：
  - 拿 Ziva 整张脸 AA 的蒙皮前和它自己比（第 0 到 46 帧，同一组 10,240 个顶点、同样的顶点编号），差别为 0；
  - 把同一份数据沿我们的 Z 轴（换算到毫米、Z 轴朝上以后）整体平移 1 mm，每一帧平均差别报告为 1 mm；顶点编号故意错开一位的对照必须报出大于 0 的差；
  - 物理段和最终形状分开报告；
  - Ziva 回放包在 Blender 里逐帧和 Alembic 原文件的点一致：第 0 到 46 帧每帧，按 30 帧/秒换算时间，同样的顶点编号，单位和坐标轴写明，最大差小于 1×10⁻⁴ mm。连法另报一条：写明回放包用的是哪一帧的连法，不说"和 Alembic 一致"；
  - 每一路 Ziva 数据在报告里有运行 id、流 id、真实帧、文件长度、运动覆盖和读回结果；只有前缀的流（Y 到第 33 帧，子步 4 的两次）不当完整运行用。
- **还要算两个指标**（ADR-25）：
  - 训练时的形状（静止形状 + landmark 位移，T-31 的 `final_shape(rest_model(...))`）到美术目标姿态的距离（目标姿态在源码仓库里，D9；用第 50 帧那组，[03](../03-asset.md) 第 13.7 节）。这是训练的残差：实验室存下的 AA 训练结果离目标，全部 10,240 个顶点平均 0.10 mm、最大 1.70 mm。回放的形状也可以报到目标的距离，说的是播出来的表情离想要的表情有多远（同一套拓扑、坐标、帧和顶点组）；它不是合格线、不是训练残差、不是材料误差：回放时物理把下唇带走，Ziva 自己的回放下唇也离目标约 11 mm（整张脸，下唇接下颌的 76 个顶点平均 11.64 mm；全部顶点平均 5.47、最大 14.50 mm，[13](../13-explanations.md) E-13）；
  - 物理段的下唇跟随比例：按 [07](../07-validation.md) 第 4.2 节的定义，一组顶点相对基准帧的位移对纯刚体预测（粘在下颌上跟着下颌走的位移）做带符号的最小二乘；基准帧写明；下颌没有动、分母为零时报"不适用"。Ziva、FEBio 各一个。Ziva 的蒙皮前下唇（接下颌的 76 个顶点）在 AA 里平均走 11.80 mm（整张脸，第 36 帧对第 0 帧，E-15）；只留嘴唇那次另报（第 36 帧对第 14 帧也是 11.80 mm，E-15），写明哪一次、哪一帧对哪一帧。
  验收：目标姿态网格和训练时的形状完全重合时距离为 0；下唇位移等于刚体预测时比例为 1，等于它的反向时为 −1；下颌不动时报"不适用"。
- **不做**：判断"合格 / 不合格"（ADR-17）。
- **依赖**：T-34（差别计算）。
- **改动范围**：`src/asrp_core/compare.py`、`ziva_export.py`、`ziva_compare.py`、`playback.py`（只加）、`cli.py`、`tests/`。
- **规模**：中。
- **做完的样子**（2026-11-15；命令的行为写在 [07](../07-validation.md) 第 4.2 节，文件格式在 [04](../04-architecture.md) 第 5.3、7 节）：
  - 面板要读的东西都在 `--out` 文件夹里，面板不用算：`compare_report.json`、`heatmap.json` + `heatmap_physics.f32` / `heatmap_final.f32`、`ziva_playback/`（插件的 Load Result 能直接加载）。
  - 取点方式：到目标姿态的距离看下颌最后动的那一帧（真实数据上是第 36 帧）；下唇跟随比例用场景里的 `lower_lip_on_jaw`（76 个顶点），物理层，基准帧报第 0 帧和第 14 帧；Ziva 一侧的下颌运动取自它自己的 `motion.json`。
  - Ziva 回放包在 Blender 里（`--background`）逐帧和 Alembic 原文件比：0 到 46 帧，30 帧/秒，最大差 1.6×10⁻⁵ mm；同一个检查把时间线设成 24 帧/秒，最大差 4.87 mm，所以这个检查抓得住帧率错（`tests/test_compare_blender.py`）。Alembic 里的物体带自己的变换（缩放 2.54、转轴），比较时取世界坐标。
  - 面板上的对比小节后来做了（T-35 第二轮 B，06 第 3.5 节）。没做：只有前缀的流和别的帧率不比，是拒绝，不是换算；"只留嘴唇"那次的比较没有单独验证（命令对它和整张脸一样处理，用哪一次由调用的人选）。

---

### T-00 基础设施 ✅
- **结果**：仓库和开发环境、`asrp doctor`、Blender 插件骨架、FEBio 动力学试验（S1，`tests/s1_dynamic_jaw.py`）、结果回放（`tools/check_playback.py`）、资产盘点工具、可移植的自动检查脚本 `tools/verify.py`。证据见各次提交。

---

### T-02 资产导入 ✅ 2026-11-10
- **结果**（2026-11-10）：`asrp import-asset <导出文件夹> <输出文件夹> [--mm-per-scene-unit 0.962] [--tetmesh 路径]`，代码在 `src/asrp_core/asset/`；换算只在 `asset/coords.py` 的 `to_mm_zup` 里，`tools/build_tetmesh.py`、`tools/blender_import_preview.py`、`tools/briefing/build.py`、`tests/s2_lips_febio.py` 都改成调用它。输出文件夹里有 `scene.json`、`meshes/`（五个网格，毫米、Z 轴朝上；`lips_tet.json` 是 `data/tetmesh/lips.json` 的原样拷贝）、`landmarks/`（T-09 起是换算好的 `skin_mm.json`）和 `import_report.json`（换算系数、坐标轴、网格、每个参数的来源、"缺了什么"、场景检查结果）。`uv run asrp import-asset data/lab_export <输出文件夹>` 打印的尺寸和 [03](../03-asset.md) 第 12 节的表一致，下颌前后 150.0 mm；`jaw01` 枢轴 (0.00, −121.71, −54.65) mm、转轴 (1, 0, 0)，带动下颌和下牙；结果 `import PASSED: scene check 0 errors, 1 warnings`（唯一的提醒是软组织没有连接；T-06a 把粘连写进场景后是 `0 warnings`）。导入前 `uv run python tools/check_lab_export.py data/lab_export "assets/w64 from v36 proxy delete done non ziva.mb"` 输出 `LAB EXPORT CHECK PASSED`（5 个网格最大差 0.0000000）。
- **事实在哪里**：单位、坐标轴、变换只套一次、导入时检查 `obj_coordinates` 是 `scene`、`jaw01` 铰链换算后的位置：[03](../03-asset.md) 第 10 节；`scene.json` 的内容和 `import_report.json`：[04](../04-architecture.md) 第 3、5.1 节；参数的来源标注：ADR-34；换算只有一份实现：05 坑 6；测试 `tests/test_asset.py`。

---

### T-03 导出嘴唇的四组粘连顶点集 ✅ 2026-11-11
- **结果**（2026-11-11）：`uv run python tools/lip_attachments.py --inventory data/asset_inventory.json` 输出四组顶点数 74、76、348、309，互不重叠，写入 `data/lab_export/lip_attachments.json`。位置核对（`tests/test_lip_attachments.py`，用真实 OBJ）：上唇组到颅骨的最近顶点距离中位数 3.28，到下颌 29.60；下唇组到下颌 3.28，到颅骨 29.10；两组重心 y 相差 34.03（数字和细节见 [03](../03-asset.md) 第 6 节）。导出文件里的 `inventory_sha256` 与清单的对应关系由同一个测试复核（本机有清单时运行）。上唇 74 个顶点用的默认权重 1.0，2026-11-12 在 Ziva 机器上证实（A-33，[13](../13-explanations.md) E-11）；文件里的说明文字还写着"待确认"，由 T-37 第 5 项改。
- **事实在哪里**：四组顶点和位置核对：[03](../03-asset.md) 第 6 节、ADR-32。读权重用 `tools/asset_report.py` 的 `read_attachments`，没有另写一份解析。

---

### T-04 嘴唇四面体化试验（S2） ✅ 2026-11-09
- **结果**（2026-11-06 初版，2026-11-09 复核定稿）：选定 fTetWild（ADR-20）。嘴唇网格自身穿插（05 坑 9），TetGen 不能用。fTetWild 每次结果不同（坑 12），所以网格用 `uv run python tools/build_tetmesh.py` 生成一次，提交在 `data/tetmesh/lips.json`，之后只读这个文件。定稿参数：包络 0.12 mm、边长 25.4 mm，6,747 个计算点；比较表见 ADR-20（`uv run python spikes/s2_tetmesh.py` 可重跑）；FEBio 重力沉降 `uv run python tests/s2_lips_febio.py smoke` 通过。初版的问题、下颌张开压力测试见 [13](../13-explanations.md) E-03。新问题：嘴角重叠部分和两个小孔是否和 Ziva 一致（11 的 Q11）。
- **事实在哪里**：工具选择和比较表：ADR-20；网格的数字和 FEBio 重力沉降：[05](../05-ziva-to-febio.md) 第 1 节 zTet 行；踩的坑：05 坑 9–15；为什么需要这一步、初版为什么不行：[13](../13-explanations.md) E-02、E-03；备选办法：T-20。

---

### T-05 场景描述格式定稿和校验器 ✅ 2026-11-10
- **结果**（2026-11-10）：格式 `asrp-scene/1`、`asrp-trajectory/1` 的字段写在 `src/asrp_core/scene.py`、`src/asrp_core/trajectory.py` 开头的格式说明里；命令 `asrp check <scene.json> [<trajectory.json>]`。S1 写成的示例在 `tests/fixtures/s1/`，由 `uv run python tests/fixtures/s1/build.py` 生成（测试每次重建并逐字节比较）。`uv run asrp check tests/fixtures/s1/scene.json tests/fixtures/s1/trajectory.json` 输出 `check PASSED: 0 errors, 0 warnings`。实现时定下、卡里没写死的两点（"帧数不一致"怎么查、粘连的两种类型）写在 04 第 5.1 节，已确认（ADR-34）。
- **事实在哪里**：场景描述和运动的内容：[04](../04-architecture.md) 第 5.1、5.2 节（含四面体网格引用的三项核对）；两种粘连类型、帧数怎么查等选择：ADR-34；运动按驱动源组织：ADR-21；单位规则：ADR-04、ADR-22。

---

### T-06a 生成器、粘连和回放（原型机） ✅ 2026-11-11 完成、评审后合并（PR #7、#8）
- **说明**：这张卡只留结果的要点和事实在哪里。现在的数字（默认 4 线程、五项检查）只在 [15](../15-prototype.md) 第 3 节。
- **目标**：scene + trajectory → FEBio 输入 → 物理段逐帧结果（含第 14 帧沉降后的形状）→ 嵌入显示网格 → 回放包，经 `asrp run` 跑通。这就是原型机（第 1 节）；第一版，缺的数据用标明来源的临时值。
- **结果**（2026-11-11）：原型机跑通，验收全部满足。三条命令：`uv run asrp import-asset data/lab_export <out>`（`import PASSED: scene check 0 errors, 0 warnings`）；`uv run python tools/placeholder_jaw_motion.py <out>/scene.json <out>/placeholder_jaw.json`（51 帧：第 0–14 帧不动，第 32 帧张开到 12°，第 50 帧合上；张开的方向按"下颌的中心往下走"从几何判断）；`uv run asrp run <out>/scene.json <out>/placeholder_jaw.json`。
  - **生成器**：k = 0.67；6,747 个计算点、26,721 个四面体；粘连的对应（上唇 `hard` 74 个顶点，下唇 `spring` 76 个，嘴角 348、309 个，共 1,428 根弹簧）和刚度的取法在 05 第 3 节。弹簧刚度按对数分档、每档取平均，每组的总刚度不变（下唇 184.68、左嘴角 845.64、右嘴角 750.87 N/mm，报告里 `binned_total_n_per_mm` 与分档前相同）；被截成 0 的重心坐标 34、37、206、176 个；冲突 0；整个显示网格到所用四面体最远 0.931 mm（上限 4.84 mm）；
  - **运行**：51 帧（含第 0 帧，FEBio 算 50 步），重试 0 次，用时见 15 第 3 节。当时的首次运行是单线程 44.8 秒（0.90 秒/帧）；
  - **检查**：五项（a)(b)(b2)(c)(d) 都通过，定义见 [07](../07-validation.md) 第 3 节，数字见 15 第 3 节。(c) 只能发现符号错或 100 倍的错；它的范围已在 T-22 里改成由模型估出（ADR-38 第 4 条）；
  - **复现**：同一份输入跑两次的比较标准见 ADR-38，单线程时回放文件逐位相同（05 坑 17）；
  - **Blender**：`blender --background --factory-startup --python tools/render_prototype.py -- <运行文件夹>` 用插件的 Load Result 加载回放包，第 0、14、32、50 帧和 `physics/display` 最大差不到 1×10⁻⁵ mm（float32，15 第 2 节），再画三张侧视图 `data/preview/prototype_rest.png`、`prototype_settled.png`、`prototype_open.png`；
  - **方块算例**（`uv run python -m pytest tests/test_generate.py -q`，39 个）：悬挂的杆末端下沉和 ρgL²/(2E) 差 0.22%（k = 1）、0.43%（k = 2）；拉伸的杆中段横向收缩 0.9525，neo-Hookean 单轴解 0.9535；k = 1 的 `.feb` 和不写 k 的逐字节相同；`hard` 区域逐帧跟随板 < 10⁻⁶ mm；弹簧刚度加大时和 `hard` 的最大差单调变小；最大距离保护、`hard` 赢 `spring`、两个刚体抢一个点报错、各项检查会失败的例子各有测试；
  - **真实嘴唇整条**：`ASRP_SLOW=1 uv run python -m pytest tests/test_prototype.py -q`（约 2 分钟：导入、代用运动、两次运行、逐位比较、运行报告、Blender 加载）；`tools/verify.py` 的 full 级会跑它。
- **事实在哪里**：k 的做法：05 第 2 节、ADR-36；粘连的对应、锚、实现细节表：05 第 3 节；材料：原型机用的是我们定的 15 kPa、泊松比 0.45，Ziva 是 12 kPa、0.4（[13](../13-explanations.md) E-11），改默认值是 T-37；运行文件夹：04 第 4 节；锚的格式：04 第 5.1 节末；合理性检查和"没运行"的含义：07 第 3 节、ADR-37；沉降形状：ADR-30；怎么重新跑、结果长什么样：[15](../15-prototype.md)。

---

### T-08 运行命令、运行文件夹和溯源 ✅ 2026-11-11（外壳；生成器由 T-06a 接入）
- **结果**（2026-11-11）：`uv run pytest tests/test_run.py -q` 通过；同一个 `.feb` 跑两次，解析出的每帧坐标最大差 1e-12 mm；把运行文件夹拷到别处只用它自己的文件重跑，最大差 1e-14 mm。非收敛报告出错帧号且没有结果文件；取消后 FEBio 进程确实结束。k 缩放的接口在 `run.Prepared.length_scale`：位置先除以 k（几何毫米）再写入 `physics/positions`（`.npy`，配 JSON 表头，T-25），k 记入溯源的 `parameters`（ADR-36）。
- **事实在哪里**：运行文件夹、溯源、出错处理、取消：[04](../04-architecture.md) 第 4、5.4、8、9 节；复现的标准：02 R-06、ADR-15、07 第 2 节；不比较 FEBio 日志：05 坑 8；线程：05 坑 17。

---

### T-09 landmark 变形层 ✅ 2026-11-12
- **结果**：`src/asrp_core/skinning.py`；导入时把蒙皮矩阵换算成毫米、Z 轴朝上，写成 `landmarks/skin_mm.json`（补上 M1 的缺口，ADR-34）；`trajectory.json` 的 `landmarks` 一节的读取和校验。
  - **和 Ziva 对过**：每一帧 f，Ziva 同一帧的蒙皮前嘴唇经 `skinning.deform` 叠加运动文件第（f − 15）步的 landmark 位移后，和 Ziva 同一帧的蒙皮后嘴唇比，47 帧、10,240 个顶点最大差 0.000016 mm（限 0.01 mm；整张脸和只留嘴唇两次都是，E-15 第 3 条）；把 landmark 列错开一位的对照组差 11.9 mm。数据在仓库外（[13](../13-explanations.md) E-11）；
  - **和实验室公式对过**：`uv run python tests/landmark_layer_check.py` 用实验室自己的绑定姿态和权重文件、按他们的公式算，300 个 landmark 全部移动，最大差 5.34×10⁻⁶ mm，对照（权重列错开一个 landmark）6.79 mm，施加的最大平移 16.1 mm（`data/preview/landmark_layer_check.json`）；
  - **测试**：换算 `tests/test_asset.py`（换算后每个 landmark 静止矩阵里的平移等于场景里它的静止位置）和 `tests/test_skinning.py`；landmark 不动时最终形状等于物理结果（`tests/test_skinning.py`、`tests/test_simulate.py`）；小例子和手算一致（`tests/test_skinning.py`）；`landmarks` 一节读回不变、缺字段和帧数对不上时报错（`tests/test_trajectory.py`）；场景不认识的 landmark 名字被 `asrp check` 拒绝（`tests/test_scene.py`）。
- **事实在哪里**：设计 [04](../04-architecture.md) 第 2 节、第 5.2 节（`landmarks` 一节）、ADR-08；选 physics only 或 final shape 加载在插件的加载函数里，面板归 T-13。

---

### T-15 代码检查工具（ruff） ✅ 2026-11-12
- **结果**：`ruff check`（规则 E、F、I、UP、B）是 `tools/verify.py` 的第一步；故意写一个未使用的导入，验证门会失败。
- **和原卡的偏差**（2026-11-12 决定）：**不限制行宽**（E501 忽略），也**不加** `ruff format --check`：现有代码按约 150 列写，全部重排会把真正的改动埋掉；等哪个文件下次要重写时再回头看。[08](../08-engineering-standards.md) 第 5 节第 8 条按此改。规则 B905（`zip()` 不带 `strict=`）整个仓库忽略，因为 54 处 `zip()` 全是把一起造出来的序列配对；`tools/maya_export.py`、`tools/rehearse_ziva_export.py`、`tools/ziva_machine_export.py` 三个脚本由 Maya 自带的 Python 运行，在 `pyproject.toml` 里各关了几条规则。具体清单只看 `pyproject.toml`。
- **事实在哪里**：规则和忽略项在 `pyproject.toml`；验证门的第一步在 `tools/verify.py`。

---

### T-17 软组织粘软组织试验（S4） ✅ 2026-11-16
- **结果**：FEBio 4.13 合成方块试验中，共用节点、有限刚度弹簧、tied-elastic 三种做法都对上理论（≤ 1%），2/4/8 块稳定；41 块直链里弹簧在第 8 步负体积失败。Ziva 那种有限刚度的软粘连在大规模下还没试；进核心归结构改动 A（对象模型）。
- **事实在哪里**：[13](../13-explanations.md) E-21。

---

### T-18 薄壳皮肤贴在实体上的试验（S5） ✅ 2026-11-16
- **结果**：FEBio 4.13 合成方块试验中，EAS 和 ANS 壳都对上理论，默认壳弯曲锁死；2026-11-17 复核发现 EAS 壳重启接着算崩溃，皮肤改用 ANS 壳。壳用 tied 接触连到组织，Ziva 粘连刚度的单位和 FEBio tied 一样；接触面法向朝外时 FEBio 只在日志里警告、照样正常结束，必须当失败处理；进核心归结构改动 A。
- **事实在哪里**：[13](../13-explanations.md) E-21、[05](../05-ziva-to-febio.md) 坑 21。

---

### T-19 扩展 Ziva 机器导出脚本 ✅ 2026-11-10
- **结果**（2026-11-10）：`tools/ziva_machine_export.py` 支持 [12](../12-lab-export-checklist.md) 第 2、4、5、7、8、9 项，分预检、静态资料、短跑、正式导出、同帧诊断、总收货六步，每次运行落在独立文件夹里。普通 Maya 上的排练通过：`mayapy tools/rehearse_ziva_export.py data/lab_export <输出目录>` 打印 `REHEARSAL PASSED: 37 checks, 0 failures`；`tests/test_ziva_capture.py` 12 个测试通过。2026-11-12 在真正的 Ziva（2.2.0-hotfix2）上跑通，现场改了一处：嘴唇每帧重新三角化，拓扑检查改成只看顶点数；缓存回放开着时求解器不走步，脚本的检查拦住了这次空跑（A-28，[13](../13-explanations.md) E-11）。
- **事实在哪里**：脚本的约束写在 `tools/ziva_machine_export.py` 开头；导出清单的各项：[12](../12-lab-export-checklist.md)。

---

### T-22 审计后的小修一批 ✅ 2026-11-11（PR #10）
- **结果**：九项 D1 到 D9 都做完（运动文件写自己的来源、场景写简化说明、沉降帧由运动文件说明、检查 (c) 的范围由模型估出、运行报告不再并排预算、派生驱动源取整个刚体运动的一部分、默认 4 线程、检查 (d) 和 `return_to_settled`、真实嘴唇进验证门）。`uv run python tools/verify.py` 通过，含真实嘴唇的运行。参考运行：五项检查全部通过，用时见 [15](../15-prototype.md) 第 3 节。
- **事实在哪里**：九项决定、原因和证据：ADR-38 第 1 到 9 条；运行报告的内容：[04](../04-architecture.md) 第 4 节；检查：[07](../07-validation.md) 第 3 节；线程：[05](../05-ziva-to-febio.md) 坑 17；数字和怎么重跑：[15](../15-prototype.md)；审计本身：[13](../13-explanations.md) E-08。

---

### T-23 方块上的主动收缩试验 ✅ 2026-11-16
- **结果**：FEBio 4.13 合成方块试验中，缩短量和手算一致，每帧激活和逐四面体方向都试过。实验室原本的用法里纤维从不激活（钢琴界面和训练都不碰），ADR-33 成立；进核心是在结构改动 A 之上往里加。
- **事实在哪里**：[13](../13-explanations.md) E-21。

---

### T-25 二进制结果和增量读进度 ✅ 2026-11-12（PR #10）
- **结果**：位置和显示网格存成 `.npy`（各配一个 JSON 表头，`asrp-positions/2`、`asrp-display/2`）；FEBio 把位置写进自己的文件 `positions.txt`，不再写进 `model.log`；进度只读日志新增的部分。原卡写的"运行文件夹小一个数量级以上"没有做到。
- **事实在哪里**：数字（文件夹大小、事后处理时间、前后逐字节对比）、没做到的原因和放弃的做法：ADR-38 第 10 条和它的证据；文件格式和运行文件夹：[04](../04-architecture.md) 第 4 节；运行文件夹里每个文件是什么：[15](../15-prototype.md) 第 2 节。

---

### T-27 中性到 AA：两种拼法，拟合 landmark 位移并运行 ✅ 2026-11-12，已退役（ADR-42）
- **做了什么**：landmark 位移由我们从实验室的 AA 目标形状拟合（`tools/aa_standin.py`），甲、乙两种拼法各跑一次完整的运行（物理加 landmark 层），五项检查都过。数字在 [15](../15-prototype.md) 第 8 节，由 `tools/prototype2_numbers.py` 从 `data/preview/` 的存档写出。
- **为什么退役**：实验室的真实运动已取回。乙被它推翻：landmark 层给接下颌的下唇顶点只加平均 1.06 mm、最大 3.23 mm，没有往回拉；甲的结构对（物理在先，landmark 偏移叠在上面），但数是我们拟合的（ADR-42）。真实运动由 T-34 做；工具、测试和存档在 T-37 第 7 项和 T-38 里删掉或移走。
- **留下的事实**：目标文件 `dataV22_phoneme_AA_for_d2.py` 里下颌和嘴唇的起始形状和我们的静止网格一致（差 10⁻⁹ 场景单位）；目标里下颌是绕 `jaw01` 的纯转动 5.74°；`skinCluster7` 的影响物正好是 300 个 `oor_*` landmark，不含 `jaw01`（`spikes/audit_skin_identity.py`，11 的 A-40）。推导和表格见 [13](../13-explanations.md) E-09、E-10。

---

### T-28 甩头：颅骨能动，求解器保留动态效果 ✅ 2026-11-12
- **结果**：
  - **方块**：物理阻尼写成 FEBio 的 mass damping 体载荷（为什么只有这一种，见 [05](../05-ziva-to-febio.md) 第 4 节）。无阻尼周期和理论差 +0.091%，衰减率差 −0.27%；两个对照都按要求不过（`uv run python spikes/t28_damped_cube.py`，`data/preview/t28_damped_cube.json`）。有弹簧时 `rhoi` = 1 也会吃掉振动，"没有数值阻尼"用 −2（05 坑 20）；
  - **代码**：头的驱动源 `head`、相对头的嘴角锚、阻尼和 `rhoi` 做成场景参数、运行报告的 `relative_to_head`（[04](../04-architecture.md) 第 4、5.1 节，ADR-41）。头不动时和以前逐字节相同（`data/preview/t28_head_shake_report.json` 的 `stage2_before_after`；另在提交 `0d04f3c` 和 `951abfa` 上手动核对过六个结果文件的 sha256）；
  - **甩头**：运动由 `tools/head_shake_motion.py` 照实验室脚本的关键帧写，帧间三次 Hermite。两个幅度都对，说的不是同一件事：实验室的关键帧是 ±5.0 个场景单位（4.81 mm），但关键帧落在四分之一圈的时刻，不在整帧上，所以按整帧取样后头最远走 4.64 个场景单位（4.46 mm）。Ziva 里同一段骨头按整帧也是左右各 4.64 个场景单位（E-11），和我们的取样一致；切线是我们对 Maya "auto" 切线的读法，逐帧的形状没有对过（🔍）。默认设置（`rhoi` 0、没有物理阻尼、每帧 1 步）87 帧跑完、五项检查都过：嘴唇相对头最大 0.094 mm（第 19 帧），甩头后最大 0.044 mm；什么都不动的对照 3.7×10⁻⁸ mm；
  - **没有收敛**：只改每帧步数，默认设置下甩头中的最大值是 0.094、0.040、0.078、0.142、0.327 mm（1、2、4、8、16 步），不单调（`spikes/audit_head_shake_timestep.py`，`data/preview/audit_head_shake_timestep.json`，[13](../13-explanations.md) E-10）。这些数不能用来下结论，原因由 T-33 查。Ziva 的同一段（整张脸，只移动了颅骨和下颌，另外 8 块骨头没动）：嘴唇相对颅骨最大 2.7 mm；停下后第 14 帧第一次低于 0.04 mm，第 16 帧回弹到 0.077 mm，第 28 帧起一直低于（E-15）；
  - **演示**：物理阻尼 C = 45/秒、`rhoi` 0.5（我们定的），最大 0.155 mm。只说明这组设置能跑完，不说明嘴唇真实的晃动有多大。
- **事实在哪里**：ADR-41；05 第 4 节、坑 19、20；小试验和时间步细分的推导：[13](../13-explanations.md) E-09、E-10。

---

### T-29 来回 10 次 ✅ 2026-11-12（用替身运动）
- **结果**：中性到 AA 再回中性来回 10 次（甲、乙各一次），检查 (d) 通过，`return_to_settled` 不随次数变大；数字在 [15](../15-prototype.md) 第 8.8 节（表由 `tools/prototype2_numbers.py` 生成）。替身运动随 ADR-42 退役，物理层回到起点的数仍然成立。
- **Ziva 的参考**（[13](../13-explanations.md) E-11、E-15）：我们的脚本照实验室的运动文件在 Ziva 里播了来回 10 次（整张脸）；每圈回到中性时对第 14 帧、全部顶点的最大值，蒙皮前的嘴唇离起点最大 0.049 mm，不累积；蒙皮后每圈多偏 0.52 mm，10 圈后 5.24 mm，因为去程和回程两个运动文件里的 landmark 偏移加起来不为零。🔍 这是按文件开环相加的结果；实验室界面在多段序列里还有一层按目标姿态的修正，没有复现（11 的 A-39、P-06）。

---

### T-30 逐帧接着算的试验 ✅ 2026-11-16
- **结果**：FEBio 4.13 合成方块试验中，FEBio 存档加重启文件，用事先不知道的运动接着算，接头处位移、速度、应力差都是 0；回到存档换一条路也通；进核心归结构改动 B（会话模型）。2026-11-17 复核扩展到 70 节点组合模型（2 块软组织 + 1 层皮肤壳 + 2 组有限刚度粘连，第 22 步存盘后再接着算 24 步）：ANS 壳全部 46 个时间点位置、速度、应力最大差为 0.0（输出精度内，信号非零），EAS 壳崩溃；目标规模与曲面、纤维、多线程等仍未试。
- **事实在哪里**：[13](../13-explanations.md) E-21、[05](../05-ziva-to-febio.md) 坑 21。

---

### T-21 更新新成员讲解页 ✖ 取消（2026-11-13）
- 讲解页（`data/briefing/asrp-briefing.html` 和 `tools/briefing/`）是给新成员的一次性介绍，不属于产品，随 T-38 移出仓库。现在的读者看 [01](../01-overview.md) 和 README。原卡列的过时点（粘连顶点数 733 应为 807、已完成的步骤还标"待开发"）在 git 历史里。
