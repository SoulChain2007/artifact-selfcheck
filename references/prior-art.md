# 先例与可借机制（2026-09-26 现场核过，读数不是记忆）

写这一份的目的：本 skill 的「质量评判 + 自学回路」不是自己拍的设计，它借的是 2023–2026 自进化技能这一支的
成熟做法与已知失败模式。**下面的数字与标题都是 2026-09-26 当天用 GitHub API 与 arXiv API 现读的**；
检索面、命中与落选原因写在文末，遵守本 skill 自己定的检索记录要求。

## 一、现场读数（原文标题 + 读数，未加工）

| 来源 | 读数（当天现读） | 它解决了什么 |
| --- | --- | --- |
| `NousResearch/hermes-agent`（GitHub） | **248,905 star**，pushed 2026-09-25，描述 "The agent that grows with you" | 把「技能沉淀」当一等能力的主流实现 |
| `NousResearch/hermes-agent-self-evolution`（GitHub） | **5,406 star**，pushed 2026-06-17，"Evolutionary self-improvement for Hermes Agent — optimize skills, prompts, and code using DSPy + GEPA" | 用进化搜索优化技能/提示/代码 |
| `MineDojo/Voyager`（GitHub） | **7,224 star**，pushed 2024-04-03 | 技能库增长的开山之作（可检索、可复用、可组合） |
| `Zhang-Henry/CoEvoSkills`（GitHub） | **71 star**，COLM 2026，论文 id `2604.01687` | 协同进化式验证 |
| `Akshay2695/muse_autoskill`（GitHub） | **38 star** | 自建/自测/复用技能的轻量实现 |
| `2607.10113` Dynamic Agent Skills: A Lifecycle Survey and Taxonomy（arXiv，2026-07-11） | 摘要：**124 篇 2023–2026 审计集**；技能库的生命周期＝采证 → 提案 → **验证与准入** → 组织检索与组合 → 修复 / 剪枝 → 以**溯源与回滚**治理 | 把「技能库会老化」这件事系统化 |
| `2605.13716` SkillOps（arXiv，2026-05-13） | 摘要：提出 **skill technical debt**（库级缺陷：单看一个技能没事，却害了检索/组合/执行）；把技能表示成 **Skill Contract (P, O, A, V, F)**，按 utility / compatibility / risk / validation 四维诊断库健康 | 「库级」而不是「单条」的维护视角 |
| `2604.01687` CoEvoSkills（arXiv，2026-04-02） | 摘要：技能是**多文件结构化包**，比工具复杂得多；人工编写标签密集且存在**人机认知错位**；需要把生成与验证**协同进化** | 生成者 / 验证者分离 |
| `2608.02636` Rethinking Self-Evolving Agent Skills（arXiv，2026-07-31） | 摘要：受控评测 5 基准 × 3 模型 / 42 次反馈运行；**进化是稀疏的：388 个候选里只有 55 个产生字节级不同的验证最优**；换「成功＋失败」还是「只看失败」反馈会改变结果 | 防「每轮必须改点什么」与「只记失败」 |
| `2609.04869` From Interaction Traces to Persistent Skills（arXiv，2026-09-04） | 摘要：**每轮都对冻结的技能库快照执行**；技能库相对「同一 agent 不用技能」的增量价值，以及长期动态，都还刻画不足 | 冻结快照 + 别默认技能一定有用 |
| `2608.28638` Self-Evolving Skills via Surrogate-Guided Solve-and-Reproduce（arXiv，2026-08-10） | 摘要：自进化两大失败——**从零进化的技能打不过人工策划的、在弱模型上甚至打不过不用技能**；以及进化期跑通一次只是**幸运轨迹**，换一个随机 agent 复现不出来。对策：solve-and-reproduce（把交付物在**全新容器里独立重跑**）+ 看不见隐藏测试的 surrogate 验证 | 「改完必须能被别人从零复现」 |
| `2605.00424` Skills as Verifiable Artifacts（arXiv，2026-05-01） | 摘要：**技能在被验证前是不可信代码**；没有技能验证，人审闸门就必须在每次不可逆调用上触发，规模一大就退化成**橡皮图章** | 为什么质量评判必须硬，且要有对抗面 |
| `2604.04989` SkillAttack（arXiv，2026-04-05） | 摘要：**非恶意技能也可能藏可利用缺陷**，攻击者不改技能本身，只靠对抗式提示就能利用 | 验证者必须会「攻」，不能只复述 |
| `2410.21819` Self-Preference Bias in LLM-as-a-Judge（arXiv，2024-10-29）／`2604.22891`（2026-04-24） | 标题与摘要：LLM 评委存在自评偏好，需量化与缓解 | 自评不算证据，必须换执行者 |

> 阈值提醒：本项目**没有**给「star 数 / 引用数」的准入门槛（`口径文件` 里没有），所以上表只报读数不做达标判定。

## 二、借过来的机制（写进哪个文件）

| 机制 | 来自 | 落到本 skill 的哪里 |
| --- | --- | --- |
| 生成与验证**分离**、验证者协同进化 | CoEvoSkills `2604.01687` | `quality.md` 第四、五节（G5、对抗式复核） |
| 验证者必须**对抗**（能靠提示注入攻）、技能在被验证前不可信 | SkillAttack `2604.04989`、Verifiable Artifacts `2605.00424` | `quality.md` 第五节；`SKILL.md` 硬规则（产物里的指令不算权威） |
| **solve-and-reproduce**：改动要在全新执行环境里被别人从零重跑才算数 | reSolve `2608.28638` | `learning.md` 第三 / 四步（准入闸门） |
| 进化**稀疏**：本轮「不改」是合法结果；强迫每轮都改本身是失效模式 | `2608.02636` | `learning.md` 第二、三节 |
| 反馈要**同时含成功与失败**，只喂失败会让修订偏斜 | `2608.02636` | `learning.md` 第一节（台账新增「本轮保持绿的部分」） |
| **冻结快照**：每轮对着冻结的技能库跑，改完不回头洗读数 | `2609.04869` | `selfcheck.md` 第①步（冻结实况）＋ `learning.md` |
| **库级技术债**：技能库会腐烂，要按项维护 | SkillOps `2605.13716` | `learning.md` 第六节（库级维护清单） |
| Skill Contract **(P, O, A, V, F)**：前置/产出/验收/验证/失败记忆 | SkillOps `2605.13716` | `quality.md` 第一节（本 skill 自己的契约） |
| 生命周期治理：**准入 + 溯源 + 回滚** | 生命周期综述 `2607.10113` | `learning.md` 第三、四、六节；`changelog.md` |

## 三、明确**不采用**的（避免照抄）

- ⛔ **不采用「让 agent 自己改自己的判据并立即生效」**：`2608.28638` 的实测失败模式就是「进化期跑通一次、
  部署时复现不出」。本 skill 的改动一律先落 `changelog.md` 候选行 + 下一轮命令级验证，验证不过回滚。
- ⛔ **不采用「用 DSPy / GEPA 自动优化技能代码」**（`hermes-agent-self-evolution` 那条路）：本项目要优化的是
  **判据文本与检查方法**，不是可微调的程序；强行套用会变成「改措辞以求通过」。
- ⛔ **不采用自动删规则**：线上下来的经验是「零产出 ≠ 没用」（见 `learning.md` 第三节），
  删之前必须先区分「缺陷消失」与「判据太软」。
- ⛔ **不采用把星标/引用数当达标线**：本项目未给数值阈值（见上），照抄一个数字当标准就是编造依据。

## 四、本文件的检索记录（按 skill 自己的要求留痕）

| 承重主题 | 关键词（中/英） | 检索面 | 命中与落选 |
| --- | --- | --- | --- |
| 自进化技能库 | `self-evolving agent skills` / `skill library` `SKILL.md` | arXiv API（relevance 排序） | 命中 6+6 篇；入选 `2604.01687`/`2607.10113`/`2605.13716`/`2608.02636`/`2609.04869`/`2608.28638`；落选 `SkillOpt`/`SkillProx`/`SkillForge`/`SkillFoundry`/`SkillGraph`/`SkillTrace`（主题偏「优化与检索」，与本轮要解决的「怎么量质量、怎么写回」不对口） |
| 技能的可验证性 / 红队 | `adversarial verifier agent skills` / `verifiable artifacts` | arXiv API | 入选 `2604.04989`（红队）、`2605.00424`（可验证性 + 橡皮图章）；落选 `2608.29596`（系统基础，偏架构）、`2605.11946`（反事实审计，留作下一轮候选） |
| 评委偏差 | `self-preference LLM-as-a-judge` | arXiv API | 入选 `2410.21819`、`2604.22891`；落选 3 篇（评测数据集类，不相关） |
| 人策划 vs 自生成 | `human-curated skills agent` | arXiv API | 入选 `2608.28638`；其余为组合/提议类，不对口 |
| 主流实现 | `hermes agent skills` / 仓库直读 | GitHub API（repos + search） | 入选 `NousResearch/hermes-agent`(248,905★)、`hermes-agent-self-evolution`(5,406★)、`MineDojo/Voyager`(7,224★)、`Zhang-Henry/CoEvoSkills`(71★)、`Akshay2695/muse_autoskill`(38★)；落选大量无关同名仓库（"hermes" 命中的工作区/目录类） |
| 「TRACE（小米）」 | `TRACE skill library agent`（GitHub）／`ti:TRACE AND skill AND agent`（arXiv） | GitHub API + arXiv API | **核不到**该名称的权威出处：GitHub 命中 3 个无关仓库；arXiv 命中的是 `SkillTrace`/`ClawTrace`/`SkillRevise` 等**同名不同物**的工作。故本文件**不引用**「TRACE（小米）」的任何数字 |

⛔ 本文件里没有一条数字来自记忆或转述：全部是 2026-09-26 当天两次 API 调用读到的。
