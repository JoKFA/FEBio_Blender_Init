# 17 系统论文大纲（草稿，待讨论）

**状态**：草稿，2026-11-24 起草，**还没有和项目负责人、实验室讨论过**。这里的方向、贡献点和投稿安排都只是提议，不是决定；讨论以后定下来的事记进 [10](10-decisions.md)，要问实验室的记进 [11](11-risks-and-questions.md)。

**保密**：实验室的论文还在审稿中，本文只写我们自己的工作和项目文档里已有的数字，不引用实验室论文的内容。这份大纲在私有仓库里，不发到仓库以外的地方。

## 1. 这篇论文是什么

**类型**：系统论文。重点是三件事：**替换流程**、**验证方法**、**实测发现**。算法本身（有限元用 FEBio、蒙皮用线性蒙皮、四面体用 fTetWild 或规则格子）不是新的，新的是"怎样把一个闭源、已停售的商业物理层，从一个正在使用的研究控制器下面换掉，并且能证明换得对"。

**一句话论点**（草稿）：研究用的面部控制器可以脱离闭源的商业软组织求解器继续工作；通过逐层的精确验证，替换带来的全部差别可以被归结到唯一被替换的物理层，再在没有真值的情况下，用原求解器作为参照（而不是靶子）来度量它。

**能说和不能说**（照 [07 归档](archive/prototype/07-v1-validation-history.md) 第 7 节，论文的主张不能越过这条线）：

| 能说 | 不能说 |
|---|---|
| 用开源的 FEBio 替代 Ziva 做物理计算，实验室的控制器照常工作 | 重现了 Ziva 的结果 |
| 和 Ziva 的差别是多少 mm（写明口径：哪一次 Ziva 运行、物理层还是最终形状、哪些帧、哪些顶点） | 生物力学上是准确的 |
| 除物理层以外的每一层都和原系统逐位一致（有证据） | 比 Ziva 更准确 |

"经实验室研究员评审可用于后续研究"这一句，要等评审做过才能写（第 6 节）。

## 2. 贡献点（候选）

按证据的强弱排序。每一条都写了现在的证据在哪里、还缺什么。

| # | 贡献 | 证据（已有） | 还缺 |
|---|---|---|---|
| C1 | **求解器替换的分层验证方法**：先证明物理层以外的每一层（运动转换、landmark 层、训练接口）和原系统逐位一致，差别就只能来自物理层；再用原求解器作参照、不设合格线（ADR-17）；加上参照线（ADR-43）和每项检查的反例对照 | 运动转换：下颌逐帧和 Ziva 记录的 `jaw01` 一致（验收线 0.01°）；landmark 层：Ziva 的蒙皮前 + 权重 × 转换出的位移 = Ziva 的蒙皮后（验收线 0.01 mm），整张脸和只留嘴唇两次都过（T-34）；训练接口复现实验室存下的 145 份训练结果，最坏差 0.000007 mm（ADR-42 的补充，T-31）；每项检查都有故意做错的对照组 | 把这些整理成一套可以推广的步骤；说明它适用于哪些"换求解器"的场景 |
| C2 | **离散化的拓扑本身就是建模选择**：网格是否把嘴缝"焊住"，决定上唇会不会被下颌带走 | 同一段实验室的 AA：上唇中部被带动，细网格 0.22 mm、粗格子 5.51 mm、Ziva 4.80 mm；和 Ziva 整张脸第 36 帧平均差，细网格 2.28 mm、粗格子 1.88 mm（ADR-44，[13](13-explanations.md) E-20） | 格子位置的敏感性已有一组（平移半格，ADR-44）；还缺网格加密的系统对照，以及"这个效应在 Ziva 里来自它的粗网格"的直接证据 |
| C3 | **训练线和回放线的分离**：控制器训练时用"静止形状 + landmark 位移"，回放时才是"物理逐帧算 + landmark 叠加"，两者的嘴唇差别很大 | 下唇在目标形状里只走 1.24 mm，回放的最终形状里走 12.79 mm（整张脸，第 36 帧对第 0 帧，ADR-42，[13](13-explanations.md) E-13）；不经过宿主软件的训练接口 `final_shape`（T-31） | 需要实验室确认这个描述符合他们的流程（11 的 Q20、Q21 一类问题） |
| C4 | **商业求解器里隐藏的尺度参数**：重力下垂我们比 Ziva 小得多，怀疑来自 Ziva 求解器变换带来的第三种长度尺度 | T-34 开工时测得：全部顶点第 14 帧平均下垂，Ziva 只留嘴唇 1.777 mm、我们 0.093 mm | **还没查清**（T-41）。查清以前不能当贡献写，只能写在局限里 |
| C5 | **可复现的工程做法** | 运行文件夹加溯源；提交并校验哈希的四面体网格（ADR-20、ADR-44）；1 线程逐位相同、多线程误差在 1×10⁻⁹ mm 以内（ADR-38）；读实验室 pickle 的安全读取器；踩过的坑（[05 踩坑记录](05-febio-pits.md)，比如 FEBio 的重力符号和手册相反） | 作为支撑写在方法和附录里，不单独当主贡献 |

## 3. 形式化（问题的数学写法）

把实验室的流程和我们的替换写成几个算子的组合。符号是草稿，写论文时再统一。

- 控制器输出：每帧骨头驱动 $D(t)$（下颌、头的刚体变换）和 landmark 位移 $\Delta L(t)$；
- 物理层：

$$P(t) = \mathcal{E}\big(\Phi_{\mathrm{FEM}}(S,\ D(0..t))\big)$$

  $S$ 是场景描述（网格、材料、粘连、求解设置），$\Phi_{\mathrm{FEM}}$ 是动力学有限元求解，$\mathcal{E}$ 是嵌入（四面体节点到显示顶点的重心插值）；

- 回放的最终形状：$X_{\mathrm{play}}(t) = P(t) + W\,\Delta L(t)$，$W$ 是 landmark 的蒙皮权重（先物理、后蒙皮，ADR-29）；
- 训练时的形状：$X_{\mathrm{train}} = X_{\mathrm{rest}} + W\,\Delta L$，不跑物理（ADR-30、[13](13-explanations.md) E-13）；
- **验证的分解**（C1 的核心）：如果 $D$、$\Delta L$、$W$ 和原系统逐位一致，那么

$$X_{\mathrm{play}}^{\mathrm{ours}}(t) - X_{\mathrm{play}}^{\mathrm{Ziva}}(t) = P^{\mathrm{ours}}(t) - P^{\mathrm{Ziva}}(t)$$

  整体的差别全部来自被替换的物理层。差别按帧报平均、P95、最大（[07](07-validation.md) 第 4.2 节），只作参照（ADR-17）。

## 4. 论文结构

| 节 | 内容 | 材料从哪来 |
|---|---|---|
| 1 引言 | 闭源商业软组织求解器停售，研究用的控制器被绑在它上面；需要开源、可复现的替代；列出贡献 C1–C3 | [01](01-overview.md)、ADR-01、ADR-17 |
| 2 相关工作 | 基于解剖的面部仿真；生物力学有限元平台（FEBio、ArtiSynth、SOFA）；嵌入式仿真网格；线性蒙皮控制层；图形学和仿真里的可复现性 | 待查文献 |
| 3 问题形式化 | 第 3 节的公式；训练线和回放线；替换要满足的条件 | [04 归档](archive/prototype/04-v1-architecture.md) 第 2 节、[13](13-explanations.md) E-13 |
| 4 方法 | 4.1 资产和坐标：全流程唯一一次单位和坐标轴换算，物理尺度 k（ADR-36）<br>4.2 离散化：贴合表面的细网格和规则格子，嵌入，网格外顶点的外推（ADR-20、ADR-44）<br>4.3 粘连映射：硬绑定、弹簧、锚点；Ziva 软约束换算成弹簧刚度（[05](05-ziva-to-febio.md) 第 3 节）<br>4.4 生成 FEBio 模型：刚体驱动、动力学设置、踩过的坑<br>4.5 landmark 层和训练接口<br>4.6 和宿主无关的架构：核心程序独立运行，靠文件交换数据，Blender 只是界面（ADR-03、ADR-45） | [16](16-pipeline.md)、[04 归档](archive/prototype/04-v1-architecture.md)、[05](05-ziva-to-febio.md) |
| 5 验证方案 | 逐层精确验证；五项合理性检查；和原求解器的差别指标；参照线（翻转面和短边，ADR-43）；反例对照；确定性 | [07](07-validation.md)、T-34 卡 |
| 6 实验 | 实验室真实的中性到 AA；张嘴 12°；甩头；重力下垂；细网格对粗格子；对 Ziva 的两次运行（整张脸、只留嘴唇）；速度（写明机器和线程数） | [13](13-explanations.md) E-19、E-20，[15](15-prototype.md) |
| 7 讨论 | 离散化拓扑作为建模选择；隐藏的尺度参数；能说和不能说的结论；局限：只有嘴唇一块组织、没有接触、下垂差距、甩头的时间步收敛（T-33）、本构不同（Ziva 的 StVK 对我们的 neo-Hookean） | ADR-44、T-41、[13](13-explanations.md) E-21 |
| 8 结论和开放 | 代码开放（受授权限制的部分除外，第 6 节） | — |

## 5. 图表计划

| 图表 | 说明 | 现在有没有 |
|---|---|---|
| 图 1 | 替换前后的管线对照：控制器不变，物理层从 Ziva 换成 FEBio | 要画 |
| 图 2 | 逐层验证的示意：哪几层逐位一致、差别落在哪一层 | 要画 |
| 图 3 | 中性到 AA 的正面动图截帧：粗格子、细网格、Ziva 整张脸 | 有（[15](15-prototype.md) 的动图），要确认资产授权（第 6 节） |
| 图 4 | 逐帧差别曲线：物理层和最终形状，对 Ziva 两次运行 | 数字在 E-19，要画 |
| 图 5 | 上唇被带动的距离：细网格、粗格子、Ziva（C2） | 数字在 ADR-44，要画 |
| 表 1 | Ziva 的设置和我们的设置，能对齐的和对不上的 | T-34 卡里的清单 |
| 表 2 | 每项验证：检查什么、验收线、实测结果、反例对照 | T-34 卡、[07](07-validation.md) |
| 表 3 | 速度：两边的机器、线程数、每帧耗时 | E-19、ADR-44（写明机器当时有别的任务） |

## 6. 投稿前要先解决的问题

有几条可能直接决定能不能投，要先和项目负责人、实验室商量。

| 问题 | 为什么关键 | 谁来定 |
|---|---|---|
| **实验室的论文还在审稿中** | 我们的工作建立在他们的控制器上，动机和背景都要引用它。投稿时间、作者署名、怎么引用，要和实验室商量 | 项目负责人和实验室 |
| **资产可能是商业授权的模型**（11 的 Q6，还没答复） | 论文里的图和数据都来自这个头模。授权不允许的话，要么取得许可，要么换一个开放的头部模型重跑 | 实验室 |
| **和 Ziva 的对比能不能公开发表** | 要查 Ziva 的许可条款里有没有限制公开基准测试（还没查） | 项目负责人 |
| **实验室研究员的评审还没做** | 按 [07](07-validation.md)，这是验收的根本标准；没有它，引言和结论里的"可用于研究"不能写 | 实验室 |
| **下垂差距还没查清**（T-41） | 是最大的一项已知差距，审稿人一定会问 | 我们 |
| **甩头的时间步还没收敛**（T-33） | 影响甩头实验能不能进论文 | 我们 |
| **只有嘴唇一块组织** | 审稿人很可能会问"整张脸呢"。ADR-45 的地基工作（多块组织、皮肤、接着算，[13](13-explanations.md) E-21 的两处结构改动）做完以后，论文会扎实得多 | 项目负责人定顺序 |

## 7. 投稿去向（候选，没有核实过各自的要求）

- **系统或方法论文**：图形学或仿真方向的期刊，或生物力学计算方法方向的期刊。具体去哪里，要看讨论后定下的重点：偏图形学写法就突出 C2（离散化），偏生物力学就突出 C1（验证方法）；
- **软件论文**（可以先投）：介绍开源工具和验证方法，篇幅短，不依赖实验室论文先发表，但仍然要解决资产授权的问题。

## 8. 要和项目负责人讨论的问题

1. 投系统论文还是先投软件论文，还是两篇都做？
2. 贡献点里 C1、C2、C3 作为主线，合适吗？C4 要不要等 T-41 有结论再决定？
3. 作者署名和投稿时间，怎么和实验室商量？
4. 资产授权（Q6）和 Ziva 对比能否发表，谁去确认？
5. 论文要不要等地基工作（ADR-45）完成、至少加上第二块组织以后再投？

## 9. 参考文献（候选）

按论文的章节分组，编号只在本文里用。**这是候选清单，不是定稿**：写作时再按目标期刊的格式整理，没用上的删掉，缺的补上。

标记：**✔** 表示 2026-11-24 已在网上核对过作者、出处和 DOI（核对用的页面附在条目后）；**○** 表示按记忆列出，作者和题目应该没错，但卷期、页码还要在写作前核对。

### 9.1 背景：Ziva 停售、实验室的工作（第 1 节引言）

- [R1] **实验室的论文**（审稿中）。题目、作者、引用方式要等实验室同意后再定（第 6 节第 1 条）；在那之前不写进任何对外的稿子。
- [R2] ✔ Unity. *An update about Ziva*. 2024-04-02（宣布停止销售和支持 Ziva 系列产品）. [unity.com/blog/news/update-about-ziva](https://unity.com/blog/news/update-about-ziva)

### 9.2 基于解剖的面部仿真（第 2 节相关工作）

- [R3] ○ Lee Y., Terzopoulos D., Waters K. Realistic modeling for facial animation. *SIGGRAPH 1995*, 55–62.
- [R4] ○ Sifakis E., Neverov I., Fedkiw R. Automatic determination of facial muscle activations from sparse motion capture marker data. *ACM Transactions on Graphics* 24(3), 2005, 417–425.
- [R5] ○ Teran J., Sifakis E., Irving G., Fedkiw R. Robust quasistatic finite elements and flesh simulation. *SCA 2005*, 181–190.
- [R6] ✔ Cong M., Bao M., E J. L., Bhat K. S., Fedkiw R. Fully automatic generation of anatomical face simulation models. *SCA 2015*, 175–183. doi:10.1145/2786784.2786786（[researchr](https://researchr.org/publication/CongBEBF15/bibtex)）
- [R7] ○ Ichim A.-E., Kadleček P., Kavan L., Pauly M. Phace: Physics-based face modeling and animation. *ACM Transactions on Graphics* 36(4), 2017.
- [R8] ○ Bao M., Cong M., Grabli S., Fedkiw R. High-quality face capture using anatomical muscles. *CVPR 2019*, 10802–10811.
- [R9] ✔ Yang L., Zoss G., Chandran P., Gotardo P., Gross M., Solenthaler B., Sifakis E., Bradley D. An implicit physical face model driven by expression and style. *SIGGRAPH Asia 2023*. doi:10.1145/3610548.3618156（[arXiv:2401.15414](https://arxiv.org/abs/2401.15414v1)）
- [R10] ○ Park H., Grama Srinivasan S., Cong M., Kim D., Kim B., Swartz J., Museth K., Sifakis E. Near-realtime facial animation by deep 3D simulation super-resolution. *ACM Transactions on Graphics* 43(4), 2024.
- [R11] ○ Kim T., Eberle D. Dynamic deformables: Implementation and production practicalities. *SIGGRAPH 2020 Courses*.（生产环境里的软组织仿真，可用来说明 Ziva 这一类工具的做法）

### 9.3 生物力学的有限元平台和面部、口腔模型（第 2 节）

- [R12] ○ Maas S. A., Ellis B. J., Ateshian G. A., Weiss J. A. FEBio: Finite elements for biomechanics. *Journal of Biomechanical Engineering* 134(1), 2012, 011005.
- [R13] ✔ Maas S. A., Ateshian G. A., Weiss J. A. FEBio: History and advances. *Annual Review of Biomedical Engineering* 19, 2017, 279–299. doi:10.1146/annurev-bioeng-071516-044738（[PMC6141040](https://pmc.ncbi.nlm.nih.gov/articles/PMC6141040)）
- [R14] ○ Lloyd J. E., Stavness I., Fels S. ArtiSynth: A fast interactive biomechanical modeling toolkit combining multibody and finite element simulation. In Payan Y. (ed.), *Soft Tissue Biomechanical Modeling for Computer Assisted Surgery*, Springer, 2012, 355–394.
- [R15] ○ Faure F., Duriez C., Delingette H., et al. SOFA: A multi-model framework for interactive physical simulation. 同上书, 2012, 283–321.
- [R16] ✔ Stavness I., Lloyd J. E., Payan Y., Fels S. Coupled hard–soft tissue simulation with contact and constraints applied to jaw–tongue–hyoid dynamics. *International Journal for Numerical Methods in Biomedical Engineering* 27(3), 2011, 367–390. doi:10.1002/cnm.1423（[HAL](https://hal.archives-ouvertes.fr/hal-00599050)）
- [R17] ✔ Barbarino G. G., Jabareen M., Trzewik J., Nkengne A., Stamatas G., Mazza E. Development and validation of a three-dimensional finite element model of the face. *Journal of Biomechanical Engineering* 131(4), 2009. doi:10.1115/1.3049857（[sciencegate](https://next.sciencegate.app/document/10.1115/1.3049857)；作者列表的后三位按记忆补，写作前再核对）

### 9.4 离散化：四面体网格、规则格子、嵌入（第 4.2 节，C2）

- [R18] ○ Si H. TetGen, a Delaunay-based quality tetrahedral mesh generator. *ACM Transactions on Mathematical Software* 41(2), 2015, Article 11.（FEBio Studio 用它，遇到自相交的嘴唇网格会停下，[05](05-ziva-to-febio.md) 坑 9）
- [R19] ○ Hu Y., Zhou Q., Gao X., Jacobson A., Zorin D., Panozzo D. Tetrahedral meshing in the wild. *ACM Transactions on Graphics* 37(4), 2018.
- [R20] ○ Hu Y., Schneider T., Wang B., Zorin D., Panozzo D. Fast tetrahedral meshing in the wild. *ACM Transactions on Graphics* 39(4), 2020.（fTetWild，细网格用它，ADR-20）
- [R21] ○ Molino N., Bridson R., Teran J., Fedkiw R. A crystalline, red green strategy for meshing highly deformable objects with tetrahedra. *12th International Meshing Roundtable*, 2003, 103–114.
- [R22] ○ Labelle F., Shewchuk J. R. Isosurface stuffing: Fast tetrahedral meshes with good dihedral angles. *ACM Transactions on Graphics* 26(3), 2007.
- [R23] ○ Kuhn H. W. Some combinatorial lemmas in topology. *IBM Journal of Research and Development* 4(5), 1960, 518–524.（每个立方格切成 6 个四面体的切法，S1 和粗格子都用它）
- [R24] ✔ Nesme M., Kry P. G., Jeřábková L., Faure F. Preserving topology and elasticity for embedded deformable models. *ACM Transactions on Graphics* 28(3), 2009（SIGGRAPH 2009）. doi:10.1145/1531326.1531358（[项目页](https://www.cs.mcgill.ca/~cg/projects/composite)）。**和 C2 最相关**：粗的嵌入网格会把"靠得很近但力学上分开"的部分连在一起，这正是上下唇在粗格子里被焊住的现象

### 9.5 蒙皮控制层（第 3、4.5 节）

- [R25] ○ Magnenat-Thalmann N., Laperrière R., Thalmann D. Joint-dependent local deformations for hand animation and object grasping. *Graphics Interface 1988*, 26–33.（线性蒙皮）
- [R26] ○ Lewis J. P., Cordner M., Fong N. Pose space deformation: A unified approach to shape interpolation and skeleton-driven deformation. *SIGGRAPH 2000*, 165–172.
- [R27] ○ Lewis J. P., Anjyo K., Rhee T., Zhang M., Pighin F., Deng Z. Practice and theory of blendshape facial models. *Eurographics 2014 State of the Art Reports*.

### 9.6 材料模型（第 4、7 节：neo-Hookean 对 StVK）

- [R28] ○ Bonet J., Wood R. D. *Nonlinear Continuum Mechanics for Finite Element Analysis*. 2nd ed., Cambridge University Press, 2008.

### 9.7 验证、确认和报告规范（第 5 节，C1）

- [R29] ○ Anderson A. E., Ellis B. J., Weiss J. A. Verification, validation and sensitivity studies in computational biomechanics. *Computer Methods in Biomechanics and Biomedical Engineering* 10(3), 2007, 171–184.
- [R30] ✔ Henninger H. B., Reese S. P., Anderson A. E., Weiss J. A. Validation of computational models in biomechanics. *Proceedings of the IMechE, Part H: Journal of Engineering in Medicine* 224(7), 2010, 801–812.（[PMC2941217](https://pmc.ncbi.nlm.nih.gov/articles/PMC2941217)）
- [R31] ✔ Erdemir A., Guess T. M., Halloran J., Tadepalli S. C., Morrison T. M. Considerations for reporting finite element analysis studies in biomechanics. *Journal of Biomechanics* 45(4), 2012, 625–633. doi:10.1016/j.jbiomech.2011.11.038（[PMC3278509](https://pmc.ncbi.nlm.nih.gov/articles/PMC3278509)）。论文的方法和附录可以按它的报告条目逐项写
- [R32] ○ ASME V&V 40-2018. *Assessing Credibility of Computational Modeling through Verification and Validation: Application to Medical Devices*. ASME, 2018.（是否引用要看投稿方向；我们不做医疗器械，只借它"可信度要和用途相称"的思路）

### 9.8 可复现性（第 4.6、5 节，C5）

- [R33] ○ Peng R. D. Reproducible research in computational science. *Science* 334(6060), 2011, 1226–1227.

### 9.9 软件（按各自要求的方式引用）

- [R34] FEBio 4 和 FEBio Studio：按官网要求引用 R12、R13，并写明版本（本项目用 4.13）。
- [R35] Blender：按官方建议的软件引用方式，写明版本（本项目用 5.2）。
- [R36] fTetWild 的 Python 包 `pytetwild`：引用 R20，并写明包的版本（本项目用 0.2.x，ADR-20）。

### 9.10 还要找的

- 图形学或仿真里"替换求解器后怎么证明结果对"的先例：比如游戏、影视流程里换物理引擎的报告，或者"差分测试"一类方法。现在手上没有，C1 的相关工作要靠它撑；
- 嘴唇或口周区域的生物力学模型（比如 ArtiSynth 的面部和口腔模型）；
- Ziva 的技术说明：没有公开论文，只能引用厂商文档；要先确认能不能引、怎么引（第 6 节第 3 条）。
