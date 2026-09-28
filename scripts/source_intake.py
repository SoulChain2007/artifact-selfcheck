#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""source_intake.py — 外部方法准入闸门自检：查网学来的东西，不许"全学"

用户 2026-09-26 口径：
  「skill 查网方法呢，你怎么没用，怎么 skill 还能只用一半呢……查网得到的东西如果全都学了容易被污染，
   所以需要针对这方面也自检。」

为什么必须有这道闸（有论文背书）：BadSkill（arXiv 2604.09378）—— 第三方 skill 可以"看起来无害"，
把恶意行为藏在随附的模型/文本里，这是**供应链风险**；AutoWorldBuilder（arXiv 2607.09403）也把
"缺乏自动化质量保证"列为世界构建的三大挑战之一。⇒ **外部学到的东西默认不可信，必须过闸。**

本脚本检查一份「外来方法登记台账」（JSONL，一行一次准入），每行必须齐：
  source        来源标题 + 年份 + 作者/机构 或 仓库全名
  surface       检索面（arXiv / GitHub / 官方文档 / DOI…）
  reading       当场读数（引用数 / star / 版本号）；读不到要写 "N/A + 原因"
  quote         支撑句摘录（≤2 行原文）—— 回答"哪一部分支持我这句"
  counter       反面检索记录 —— 搜过"它的失败/局限"了吗？结果是什么
  target        学来后用在哪（文件:节）
  verdict       adopt / weak / reject（reject 也要留）
  detector      准入后**由哪个检查器检出**（不许引入"检测不到"的判据）

判据：缺 quote / 缺 counter / verdict=adopt 但 detector 为空 ⇒ FAIL。
用法：
    python source_intake.py --ledger <source_intake.jsonl> [--json]
退出码：0 = 全部合规；1 = 有不合规行（明细见输出）
"""
import argparse
import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REQUIRED = ("source", "surface", "reading", "quote", "counter", "target", "verdict", "detector")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not os.path.isfile(a.ledger):
        sys.exit("找不到准入台账：%s（本轮若未经查网就新增判据，那是「只用一半」，先补台账）" % a.ledger)
    rows, bad, missing_field = [], [], []
    for ln in io.open(a.ledger, encoding="utf-8").read().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        try:
            r = json.loads(ln)
        except Exception:
            bad.append({"line": ln[:60], "why": "非 JSON"})
            continue
        rows.append(r)
        for k in REQUIRED:
            if not str(r.get(k, "")).strip():
                bad.append({"source": r.get("source", "?"), "why": "缺字段 %s" % k})
        if str(r.get("verdict", "")).lower() == "adopt" and not str(r.get("detector", "")).strip():
            bad.append({"source": r.get("source", "?"), "why": "verdict=adopt 但没有 detector（学进来的判据必须能被检出）"})
        if str(r.get("quote", "")).strip() in ("-", "无", "N/A"):
            bad.append({"source": r.get("source", "?"), "why": "支撑句摘录为空 —— 说不出「哪一部分支持我这句话」就不算核过"})
        if str(r.get("counter", "")).strip() in ("", "-", "无"):
            bad.append({"source": r.get("source", "?"), "why": "没有反面检索记录（只搜支持自己的证据 = 确认偏差）"})

    if a.json:
        print(json.dumps({"ledger": a.ledger, "rows": len(rows), "violations": bad,
                          "adopted": sum(1 for r in rows if str(r.get("verdict", "")).lower() == "adopt"),
                          "rejected": sum(1 for r in rows if str(r.get("verdict", "")).lower() == "reject")},
                         ensure_ascii=False, indent=2))
        return 0 if not bad else 1

    print("══ 外部方法准入闸门 ══  台账 %s · 登记 %d 行" % (a.ledger, len(rows)))
    adopt = [r for r in rows if str(r.get("verdict", "")).lower() == "adopt"]
    weak = [r for r in rows if str(r.get("verdict", "")).lower() == "weak"]
    rej = [r for r in rows if str(r.get("verdict", "")).lower() == "reject"]
    print("")
    for r in rows:
        print("  [%s] %s" % (str(r.get("verdict", "?")).upper(), str(r.get("source"))[:60]))
        print("        读数：%s ｜ 用在：%s ｜ 检出器：%s"
              % (str(r.get("reading"))[:40], str(r.get("target"))[:40], str(r.get("detector"))[:40] or "（无）"))
        print("        支撑句：%s" % str(r.get("quote"))[:70])
        print("        反面检索：%s" % str(r.get("counter"))[:70])
    print("")
    print("采纳 %d / 弱依据 %d / 拒收 %d" % (len(adopt), len(weak), len(rej)))
    if bad:
        print("")
        print("⛔ %d 项不合规 —— 修完才能把外部方法写进 skill（这就是「防污染」的执行点）：" % len(bad))
        for b in bad:
            print("   %s：%s" % (b.get("source", b.get("line", "?")), b["why"]))
        return 1
    print("✅ 准入台账全部合规（每条都有来源/读数/支撑句/反面检索/落点/检出器）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
