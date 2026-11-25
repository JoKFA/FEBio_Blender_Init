# 08 开发规范

给谁看：所有参与开发的人（含 AI 开发会话）和审查者。
读完能知道：代码和文档放哪、环境与分支规矩、测试与验证门分级、什么叫“完成”，以及文档如何维护才不腐烂。
架构见 [architecture/README.md](architecture/README.md)，物理映射见 [05](05-ziva-to-febio.md)。
规范的目的只有一个：**几个人和多次会话接力开发时，代码不乱、结果可信、谁都能接手。**

## 1. 仓库结构与进仓边界

```text
asrp/
  src/asrp_core/        核心程序（计算、格式、CLI）。严禁 import bpy
  blender_addon/        Blender 插件（只管界面）。严禁第三方库
  tests/                自动化测试
  tools/                检查、分析、导出与渲染工具（非产品代码）
  docs/                 设计文档（本目录，唯一依据）
  assets/  runs/        实验室原始场景与运行结果 —— git 忽略
  data/                 lab_export/、preview/、tetmesh/ 提交私仓，其余忽略（ADR-19）
```

新功能按 [architecture/README.md](architecture/README.md) 第 2 节模块划分归位，不私建顶层目录。
**只放项目本身，不放开发过程**：一次性脚本放仓库外数据旁；工作计划写进 `docs/tasks/T-xx.md` 或 `docs/explanations/E-xx.md`，不单独进仓。

## 2. 开发环境

| 项 | 要求 | 说明 |
|---|---|---|
| 操作系统 / 路径 | Windows 11 · **路径只用英文字母和数字（纯 ASCII）** | 第一阶段优先 Windows；FEBio 可能打不开中文路径 |
| Python / 包管理 | `3.13`（匹配 Blender 5.2）· `uv` | `uv sync` 装依赖，`uv run ...` 运行；`asrp_query` 单独守 `3.9` 兼容线 |
| Blender / FEBio | Blender `5.2.x LTS` · FEBio `4.13.0` | FEBio 官网自行下载，**绝不入仓不转发**；路径找不到时设 `ASRP_FEBIO` |

环境就绪标准：运行 `uv run asrp doctor`，四项全部显示 `ok`。

## 3. 分支、合并与提交信息

- `main` **永远处于全量验证通过状态**，不允许直接推送或强制推送，一律从任务分支（如 `t-06-febio-scene`）开合并请求经至少一人审查后合并（私有仓 `JoKFA/FEBio_Blender_Init`，[ADR-14](decisions/ADR-14.md)、[T-16](tasks/T-16.md)）。
- 一个合并请求只做一个任务；非测试数据改动超过 ~400 行前先商量拆分。
- **提交信息**：首行说明**为什么改**，正文写背景、做法与真实证据，标注任务编号；用个人身份提交，**git 可见处绝不出现 AI 署名**；不提交密钥、个人数据、原始 `.mb`、论文、录像或 `runs/`。

## 4. 写代码的规矩

1. **核心不碰 Blender，插件不做计算**，违者退回。
2. **单位只在导入时换算一次**，之后全用毫米、牛顿、兆帕、秒（`mm、N、MPa、s`），变量名或注释写清单位（如 `stiffness_mpa`）。
3. **只做任务卡要求的事**；发现额外想法写进 [11](11-risks-and-questions.md) 或提给负责人。
4. **三次重复好过过早抽象**，出现第四次再提炼。
5. **错误信息说人话并给处理办法**；注释解释“为什么”和反直觉坑（如重力反号）。
6. **新增依赖须写明理由**并用 `uv add`；插件零第三方依赖。
7. **风格检查**：以 `ruff check`（规则 E、F、I、UP、B）为准，是 `verify.py` 第一步。例外：忽略 E501、不加 `ruff format --check`、全局忽略 B905；两个 Maya 脚本（`tools/maya_export.py`、`tools/ziva_machine_export.py`）在 `pyproject.toml` 里各关了两条规则（老式字符串格式化与一条风格规则），以 `pyproject.toml` 为准。

## 5. 测试与验证门分级

1. **测试必须真的能失败**：每个新行为配会失败的测试（修 bug 先写复现失败测试）；断言具体误差或数量，合并请求里写明“如果写错，哪个测试会失败”。
2. 测试数据用小合成例放 `tests/`，临时输出写临时目录；依赖仓库外实验室数据的测试在无数据机自动跳过并打印 `NOT VERIFIED`（发布前须在有数据机跑通）。
3. **实验室事实必须先有会失败的检查**：写进文档之前先在 `tests/test_lab_facts.py` 加断言，数字标清运行、顶点、帧与统计口径；有实验室原始结果时直接比对，不用别的实验拼（[E-15](archive/explanations/E-15.md)）。
4. **验证门（`uv run python tools/verify.py`）**：

| 级别 | 检查内容 | 耗时 | 适用时机 |
|---|---|---|---|
| `--level docs` | `ruff`、防误提交检查、文档引用/中英/结果页与验证门测试（**不跑 `test_lab_facts.py`**） | 10 秒 | 只改文档（改实验室数字须补跑 `core`） |
| `--level core` | 加上全部单元测试（不含真实嘴唇的慢测试） | 3 分钟 | 改代码或测试 |
| 不带参数（`full`） | 加上慢测试、`asrp doctor`、Blender manifest 校验与 `check_blender_addon.py` / `check_playback.py` / `check_panel.py` | 6 分钟以上 | **合并前唯一“能合并”定义**；改插件必跑 |
| `--level auto` | 按改动文件自动选级（供本机开发工具每轮调用，不能替代 `full`） | — | 迭代过程 |

5. **本机数据不进仓**：仓库外路径写在被忽略的 `.local/`（`ziva_trip_pointer.json`、`paths.json`）或环境变量 `ASRP_ZIVA_TRIP` / `ASRP_LAB_DATA`，由 `tools/local_paths.py` 读取；`tools/check_no_lab_files.py` 强制拦截 `.local/`、`AGENTS.md`、`CLAUDE.md`、`.claude/` 以及任何跟踪文本里出现本机绝对路径。

## 6. 什么叫“完成”与审查重点

同时满足全部六条才算完成（“测试全绿”本身不等于完成）：
- [ ] 任务卡每条验收标准达成并附**真实命令与真实输出**；
- [ ] 经**真实入口**在真实形状数据（含空值/缺字段）上运行通过；
- [ ] `uv run python tools/verify.py`（全量）退出码 0；
- [ ] 新行为有能失败的测试；
- [ ] 受影响文档按第 7 节同步更新；
- [ ] 至少一人审查通过（核范围、正确性、架构边界、单位坐标与文档；可用其他模型作第二意见，但合不由人定）。

## 7. 文档维护规矩（改文档前必查）

| 发生了什么 | 同步更新哪份文档 |
|---|---|
| 改动生效的参数、门限、默认值或环境版本 | [00 现行设定速查](00-current-settings.md) + 原权威设计页 |
| 做出或修订设计决定 | `docs/decisions/ADR-xx.md`（结论前置、历史沉底）+ [10](10-decisions.md)；被完全取代的旧 ADR 原样移入 `docs/archive/decisions/` |
| 发现架构或物理设计要改 | 先改 [architecture/](architecture/README.md) 或 [05](05-ziva-to-febio.md) 并审查，再改代码 |
| 完成试验或踩到新的 FEBio 坑 | [05-febio-pits.md](05-febio-pits.md)（补坑并加测试）+ [11](11-risks-and-questions.md) |
| 解决待决问题或定下不定项 | [11](11-risks-and-questions.md) 移出至 [archive/11-resolved-issues.md](archive/11-resolved-issues.md)，结论落回对应文档 |
| 新增、修改或完成任务卡 | 维护 `docs/tasks/T-xx.md` + [09](09-roadmap-and-tasks.md)；完成/取消/闭环的卡原样移入 `docs/archive/tasks/` |
| 新增设计解释或审计记录 | 长期解释建 `docs/explanations/E-xx.md`，审计/证据台账进 `docs/archive/explanations/E-xx.md`，同步 [13](13-explanations.md) 目录 |

**五条硬约束**：
1. **主线只写当前真相，历史原样进 `archive/`**：不删历史数据，也不让已交付原型或过程废话留在现行正文里。
2. **编号唯一不重用**：`ADR-`、`T-`、`E-`、`P-`、`D`、`A-`、`Q`、`R-`、`N-`、`坑 N` 全库只定义一次。
3. **代码出处写稳定符号，禁写裸行号**：写 `模块路径 + 符号/命令选项名`，绝不写 `generate.py:<行号>` 这类易漂移行号。
4. **短句分段、事实带限定语**：避免 200+ 字单行与超宽表格；每个实测数字写明是哪个命令或脚本得出的，并带口径与限定语（实测 / 只读源码 / 推断 / 单模型试验）。
5. **路径与署名卫生**：本机证据目录只记在 [E-23](archive/explanations/E-23.md)；文档和 git 可见处**不写 AI 模型或厂商名**（规则里提及被 git 忽略的字面配置文件名 `CLAUDE.md` / `.claude/` 属唯一例外）；改完必跑 `uv run python tools/verify.py --level docs`。

## 8. 数据安全、AI 会话协作与版本号

- **数据与哈希安全**：原始 `.mb`、论文、录像、实验室源码（只读用 `git show` 查，不拷不跑，[ADR-28](decisions/ADR-28.md)）、FEBio 安装包与 `runs/` 永不进仓；`data/` 与 `tests/fixtures/` 由 `.gitattributes` 设 `-text` 按字节检出，防 Windows `core.autocrlf=true` 改换行破坏哈希（验证：`git clone --config core.autocrlf=true` 后跑 `tests/test_scene.py`、`test_asset.py`、`test_tetmesh.py`、`test_trajectory.py` 全过）。
- **AI 开发会话协作**：一会话只领一张 `docs/tasks/T-xx.md`；先读 `docs/README.md` 指定的开发者起步 4 份，再**只读该卡点名的文档**；严禁擅改设计，发现问题立即停下汇报；交付真实命令输出、文件清单并走同等审查。
- **版本号**：`pyproject.toml`、`blender_addon/asrp_blender/blender_manifest.toml` 与 `src/asrp_core/__init__.py` **三处保持一致**；里程碑完成时按 `0.x` 递增并打 git 标签。
