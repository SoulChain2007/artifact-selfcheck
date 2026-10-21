# artifact-selfcheck

**3.0.2 · 完整版 · MIT 免费开源**

给 AI Agent 使用的交付前自检技能：把用户需求、实际文件、完成声称和运行证据逐项对账，明确漏项与未验证项。
保留 quick / partial / full 三档、六透镜、评分、自学候选及回滚机制。没有付费门槛；模型或工具费用由各自服务提供方决定。

## 使用

将本目录放在宿主的 skills 目录下，保持 `SKILL.md` 位于 `artifact-selfcheck/` 根目录。

| 宿主 | 本次已发现的本机安装位置 |
| --- | --- |
| Codex | `%USERPROFILE%\.codex\skills\artifact-selfcheck` |
| WorkBuddy 国内版 | `%USERPROFILE%\.workbuddy\skills\artifact-selfcheck` |
| WorkBuddy 国际版 | `%USERPROFILE%\.workbuddy-ai\skills\artifact-selfcheck` |

不同安装方式可能使用其他目录；这些位置不代表所有版本宿主的统一规范。安装后开启新会话，确认加载的版本。

提示示例：`用 artifact-selfcheck 检查这次交付，先核需求与实物，再运行适用检查，明确未验证项。`

| 档位 | 范围 |
| --- | --- |
| quick | 本轮局部变更，反查通过断言，写明边界 |
| partial | 指定分区及相邻依赖，验证缺陷样本检出能力 |
| full | 在明确声明的需求分母上完整验收，验证真实入口与跨模块链路 |

按风险与交付承诺定档。方法按需加载；外部承重结论才需溯源。独立复核缺失如实降级，不伪造复核者。
完整执行合同见 [SKILL.md](SKILL.md)、[评分合同](references/quality.md) 与 [版本记录](references/changelog.md)。

## 验证与打包

需要实际可执行的 Python 3；评分脚本需要 PowerShell。部分世界设定 YAML 探针另外需要 PyYAML，不适用时跳过并说明。

```powershell
python -m unittest discover -s tests -p "test_*.py"
powershell -NoProfile -File tests/run_tests.ps1
python scripts/release.py verify --root .
python scripts/release.py build --root . --output ../artifact-selfcheck-3.0.2-skillhub.zip
```

ZIP 根目录直接包含 `SKILL.md`，便于手动提交 SkillHub。生成后可用安装脚本同步本机三端并把原 ZIP 复制到桌面：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_windows.ps1 -Archive ../artifact-selfcheck-3.0.2-skillhub.zip
```

安装器先验证归档内文件清单和 SHA256，再备份旧目录并安装，最后复核每个文件。缺失、内容漂移或多余文件会拒绝安装。
安装结果只证明目录内容；宿主实际加载与执行仍需新会话确认。安装不会更新宿主的插件缓存。

## 边界与贡献

本技能不是通用正确性证明，也不保证发现所有缺陷。公开包不包含私人项目的原始历史审计记录，以明确标注的迁移摘要说明旧版本边界。
3.0.2 的测试覆盖发行完整性、评分与 CLI 合同，不替未运行的领域检查或宿主 UI 签验收。
Quick 独立3.0.1是另一份精简发行包，本版不沿用其包名或许可标记。

欢迎提交真实失败样例：需求、最小产物、命令、输出和漏检内容。请勿上传密钥、客户资料或私人项目数据。

## English

A free, MIT-licensed pre-delivery reconciliation skill for AI agents. It checks claims against artifacts and requirements, validates evidence, and records limits. Includes all three risk-based modes, scoring, scoped learning and rollback. Tests validate specific contracts, not universal effectiveness.

## License

[MIT](LICENSE).
