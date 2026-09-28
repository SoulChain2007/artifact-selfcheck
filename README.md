# artifact-selfcheck

一个给 agent 用的交付前对账 skill。产物被说成「完成」的时候，它做三件事：先盘点盘上真有什么、再对文档里声称有什么；按主题去查权威资料，核一遍撑结论的来源；最后给这次检查本身打个可复算的分，拿分数回头改检查方法。

![version](https://img.shields.io/badge/version-2.6.1-blue)
![license](https://img.shields.io/badge/license-MIT-green)

## English

An agent skill for pre-delivery reconciliation. When a deliverable is declared "done" — a report, a spreadsheet, a web page, a code change, a dataset — it runs three passes:

1. **Self-check**: freeze what is actually on disk first, then read the claims. Six fixed lenses (claim vs reality, spec vs actual, internal consistency, reference integrity, verifiability, attention limits). Every claim needs a reproducible command run today.
2. **Sourcing review**: write topical queries instead of replaying a cached reference list; read live numbers (stars, citations, versions); quote the supporting sentence from each source.
3. **Scoring and self-learning**: score both passes with recomputable gates, and let the scores drive changes to the check method itself.

Cost scales by tier (`quick` / `partial` / `full`). For long-running tasks it anchors the original goal and re-checks early content against current criteria.

Caveat: the core method comes from ~68 real delivery batches in the maintainer's own projects. The general-purpose routing layer (tiers, task profiling, long-task anchors) has no external usage record yet — see [还没验证的部分](#还没验证的部分).

## 它解决什么问题

「完成」永远是被声称出来的。声称和实存之间有六种典型落差，这个 skill 逐条堵：

| 落差 | 样子 |
|---|---|
| 文档说做了，盘上没有 | 报告全绿，目标文件不存在 |
| 规格里有，产物里没有 | 分母从产物数，漏掉的东西永远进不了分母 |
| 同一事实两处说法不一 | 正文改了、元数据没跟上；改名后旧引用还在 |
| 引用悬空、孤儿、过期 | 指向已归档的路径，编号冲突 |
| 看着自洽，但没证据 | 没有命令、没有读数、没有时间戳 |
| 抽样被当成穷尽 | 只看了 5 个样本，报告写「全库健康」 |

## 三个动作

| 动作 | 内容 | 正文 |
|---|---|---|
| 产物自检 | 五步流程 + 判据生成器 + 随机抽样溯源 | [references/selfcheck.md](references/selfcheck.md) |
| 溯源复核 | 检索式模板、来源分层、支撑句摘录、反面证据 | [references/sourcing.md](references/sourcing.md) |
| 质量评判与自学 | 六条硬闸 + 十二个评分维度 + 元评审 + 回滚 | [references/quality.md](references/quality.md)、[references/learning.md](references/learning.md) |

只自检不查资料，会把「看着自洽的幻觉」判成通过；只查资料不查产物，会漏掉「资料没问题但东西没落盘」。质量评判是给前两个动作提供纠错来源的，没有它，跑多少轮都不会变好。

## 成本分三档

| 档 | 适用 | 经验消耗 |
|---|---|---|
| `quick` | 日常小产物：一份周报、一张表、一页网页、一次代码小改 | 约 10–20k tokens |
| `partial` | 一般交付 | 约 30–60k tokens |
| `full` | 跨多轮的大件、失败代价高的交付 | 约 80–150k+ tokens |

references 全量约 1,400 行，所以加载也按档位来：quick 只读任务画像节、分档定义和证据表里对应的那一行，full 才全量。查一份周报不该把整包读进来。

## 安装

把仓库整个目录放进 agent 框架的 skills 目录：

```bash
git clone https://github.com/SoulChain2007/artifact-selfcheck.git ~/.workbuddy/skills/artifact-selfcheck
# 其他框架同理，放各自的 skills 目录（~/.claude/skills/、~/.codex/skills/ 等）
```

如果同一个 skill 装了不止一份，改了一份要同步其余的，不然不同线路会按不同判据自检。

## 触发

说「自检一下」「复查」「对账」「有没有漏洞」，或者任何产物被说成「完成 / 已交付 / 闭环」。
纯问答、没确认的中间草稿、明确说「先别检查」时不触发。

触发后先做任务画像（四行）：产物类型、检查档位、承重结论、溯源主题词，从任务文本里当场提取。

## 跑一下自带测试

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tests/run_tests.ps1
```

```
PASS all-pass.grade = A
PASS gate-fail.grade = F          # 故意不过的用例，确认它真的会判 F
PASS gate-fail.hardFails = g4
PASS ledger.rows = 3
...
ALL TESTS PASSED
```

评分脚本可以单独跑，自评分是算出来的，不是手写的：

```powershell
powershell -File scripts/selfcheck_quality.ps1 -Mode score -Scores tests/fixtures/score_all_pass.json
```

```
grade=A percent=100 sa=5 sr=5
gates: g1=pass g2=pass g3=pass g4=pass g5=pass g6=pass
```

## 目录结构

```
artifact-selfcheck/
├── SKILL.md                 # 入口：触发、三个动作、成本预算、硬规则
├── references/
│   ├── selfcheck.md         # 五步流程、任务画像、判据生成器、按档位加载
│   ├── lenses.md            # 六条透镜的完整问句
│   ├── domains.md           # 分域证据表（代码/数据/文档/美术/音频/UI/关卡…）
│   ├── world-probes.md      # 设定集域的专用探针，其他域可跳过
│   ├── sourcing.md          # 溯源复核
│   ├── quality.md           # 硬闸、评分维度、三档定义、单会话降级
│   ├── scaling.md           # 规模换挡、灵敏度读数
│   ├── longtask.md          # 长任务：目标锚、漂移判定、回放复检
│   ├── iteration.md         # 规则预算、缺陷词表
│   ├── learning.md          # 反馈、元评审、版本与回滚
│   ├── prior-art.md         # 参考过的先例和当场读数
│   └── changelog.md         # 这个 skill 自己的版本史，每条改动带事故出处
├── scripts/                 # 9 个检查器（Python 3 标准库）+ 1 个评分脚本（PowerShell）
└── tests/                   # 自带断言，含一条故意判 F 的用例
```

## 设计原则

五条不变式，顺序不能颠倒：

1. 先落盘实况，再读主张。反过来做就是把文档的自称当事实，这是幻觉的第一来源。
2. 分母从规格里数，不从产物里数，且至少一份规格来自项目之外。
3. 每条断言配一条可复现的命令，命令的输出必须承载得住这个结论，载不住就标「未验证」。
4. 换域只换证据来源，不放松要求。
5. 收尾必须出返工件，只写报告不派活等于没发现。

六条透镜：声称↔实存、应有↔实有、内部一致、引用完整、可验证性、注意力限制。它们和领域无关，查代码和查美术用同一套，换的只是证据来源。

规则数量有上限：必答问题 9 条、透镜 6 条、硬规则 13 条，都到顶了。想加一条，得先合并或删掉一条——清单变长之后边际产出是负的（Haynes 2009, NEJM）。

## 这些规则是怎么来的

每条规则背后都有一次真实事故。维护者在自己的项目里逐批交付，攒出四个互不同源的失效族：

| 失效族 | 事故 | 对应的规则 |
|---|---|---|
| 证据载体承载不住结论 | 大读数都配了命令且全对，五个小计数全错；用 id 行哈希证「条目未动」，而变异体恰恰是「改字段、保 id」 | 命令的输出域必须覆盖结论涉及的字段 |
| 拿记忆当契约 | 凭印象写完成标记的命名约定，实现处的正则其实是另一套，8 个标记全部误判 | 规格必须从实现处读 |
| 证据在输出里，但没读完 | 一条命令输出 5 行，只读首行就断言「全库最大缺口」；把转述当原文引 | 读数要读完、引用要引原文 |
| 诊断工具自己没生效 | 验环境变量透传的写法在那个 shell 下根本不生效，得出的对比是无效证据 | 诊断命令先自证生效 |

改动台账在 [references/changelog.md](references/changelog.md)，每条记录触发的事故、改了哪处、下一轮拿什么验证。没有事故出处的改动不写进去。

## 还没验证的部分

按这个 skill 自己的规矩，没验证过的不能自称验证过：

- 三档路由、任务画像、长任务锚这些通用化部分，只过了结构校验和自带测试，没有外部使用记录。核心方法（六透镜、硬闸、溯源复核）有约 68 个真实批次的实战记录。
- 自评不算证据。full 档要求独立复核；单会话拿不到复核者时，评级上限 D 并显著标注，不许换个口吻自己扮演复核者。
- `chain_walk.py`、`concept_walk.py`、`deep_audit.py`、`struct_audit.py`、`anchor_and_support.py` 这五个脚本是为设定集类产物写的，算示例插件，其他领域可以跳过。
- 评分脚本和测试是 PowerShell，在 Windows 上验证过，Linux/macOS 没实测。Python 脚本只用标准库。
- 正文是中文。给非中文的执行模型用之前，先确认它的指令遵循能力。

## 参考过的先例

生成与验证分离、验证者要会对抗、改动要在全新环境复现、技能在被验证前按不可信内容处理——这些借自 2023–2026 年自进化技能一支的做法和已知失败模式。每项的当场读数和「明确不采用哪几条」在 [references/prior-art.md](references/prior-art.md)。

## 贡献

最有价值的贡献是一次真实的失败记录，不是新规则：拿它自检一个真实产物，把「它没抓到的问题」连同年份、命令、读数一起开 issue。能归进上面四个失效族，说明旧判据不够；归不进去，就是发现了第五族。

提 PR 加规则之前注意规则预算已经到顶：加一条得先合并或删一条。

## 版本

| 版本 | 日期 | 内容 |
|---|---|---|
| 2.6.1 | 2026-09-29 | 公开发行版：判据未动，改动全部是脱敏和发行包装 |
| 2.6.0 | 2026-09-29 | 按档位加载、单会话降级、成本预算、触发节流 |
| 2.5.0 | 2026-09-29 | 长任务模式：目标锚、漂移判定、回放复检 |
| 2.4.0 | 2026-09-29 | 从大件专用到所有任务可用：quick 档、任务画像 |
| 2.3.x | 2026-09-26 ~ 29 | 四个失效族逐个被事故抓出并收紧 |
| 2.0 ~ 2.2 | 2026-09-26 | 从一堆检查器变成一个 skill |

## 许可

[MIT](LICENSE)。
