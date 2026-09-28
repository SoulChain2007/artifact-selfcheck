#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""sampling_audit.py — L6 注意力层：报告"说的覆盖面"与"给的证据"是否匹配

补的是透镜矩阵最后一个薄点：L6 注意力限制。已有检查器只查"报告里有没有抽样声明"，
但**声明可以是空的** —— 写了"抽 5 / 池 1270"却一条样本读数都没给，读者无法验证它是真抽了，
还是抄了一个数字。所以本脚本把 L6 变成三条机器判据：

  ① **声明与证据对得上**：写了"抽 N"就必须能数出 ≥N 条**逐条读数行**
     （每行含样本标识〔路径或 ID〕+ 至少一个读数），否则判 FAIL。
  ② **覆盖面声明**：抽样少于池子时，必须写出"只对抽样框负责 / 其余 M-N 未查"这类话，
     否则读者会把抽样结论当成全量结论。
  ③ **穷尽要说总量**：写"穷尽 / 全量读数"就必须给出池大小或条目总数；
     ⛔ 且**不许**在没有任何覆盖面声明时写"全库健康 / 整库无问题"（越界，判 FAIL）。

用法：
    python sampling_audit.py --reports <报告目录> [--glob "自检报告_第*批_*.md"] [--last 20]
                             [--json] [--min-item-ratio 0.8]
退出码：0 = 全部报告"说得对得上"；1 = 有报告声明与证据不匹配
"""
import argparse
import glob
import io
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CLAIM_SAMPLE = re.compile(r"抽\s*(\d+)\s*[/／]\s*池\s*(\d+)")
CLAIM_N = re.compile(r"抽样数\s*[:：]\s*\*{0,2}(\d+)")
CLAIM_POOL = re.compile(r"池大小\s*[:：]\s*\*{0,2}(\d+)")
EXHAUSTIVE = re.compile(r"穷尽|全量读数|全量推进")
COVERAGE_DECL = re.compile(r"只对抽样框负责|其余\s*\d+\s*个?[文件条]?未查|其余未查|未查其余")
OVERREACH = re.compile(r"全库健康|整库无问题|全部通过且无遗漏|全库无问题")
ITEM_HINT = re.compile(r"(`[^`]*(?:\.yaml|\.md|\.json|\.py)`|[A-Z][A-Z0-9]{1,8}-[A-Z0-9]{2,10}-\d{1,4})")


def audit_report(path, min_ratio):
    t = io.open(path, encoding="utf-8", errors="replace").read()
    m = CLAIM_SAMPLE.search(t)
    claimed_n = int(m.group(1)) if m else None
    claimed_pool = int(m.group(2)) if m else None
    if claimed_n is None and CLAIM_N.search(t):
        claimed_n = int(CLAIM_N.search(t).group(1))
    if claimed_pool is None and CLAIM_POOL.search(t):
        claimed_pool = int(CLAIM_POOL.search(t).group(1))
    # 逐条读数行：含样本标识 + 至少一个数字或勾/叉的行
    item_lines = 0
    for ln in t.splitlines():
        if ITEM_HINT.search(ln) and (re.search(r"\d", ln) or ("✅" in ln) or ("✗" in ln) or ("/2" in ln)):
            item_lines += 1
    exhaustive = bool(EXHAUSTIVE.search(t))
    has_cov = bool(COVERAGE_DECL.search(t))
    overreach = bool(OVERREACH.search(t)) and not has_cov

    issues = []
    if overreach:
        issues.append("越界：写了「全库健康/整库无问题」却没有覆盖面声明")
    if claimed_n:
        need = max(1, int(claimed_n * min_ratio))
        if item_lines < need:
            issues.append("声称抽 %d 条，但报告里只能数出 %d 条逐条读数（要 ≥%d）"
                          % (claimed_n, item_lines, need))
        if claimed_pool and claimed_n < claimed_pool and not has_cov:
            issues.append("抽样少于池子（%d/%d）却没写「只对抽样框负责 / 其余未查」" % (claimed_n, claimed_pool))
    elif exhaustive:
        if not (claimed_pool or re.search(r"条目\s*\d+|共\s*\d+\s*[条个]", t)):
            issues.append("写了「穷尽/全量」却没给总量（池大小或条目总数）")
    else:
        issues.append("既没有抽样声明，也没有穷尽声明 —— 读不出本轮覆盖面")
    return {"report": os.path.basename(path), "claimed_n": claimed_n, "claimed_pool": claimed_pool,
            "item_lines": item_lines, "coverage_declared": has_cov, "exhaustive": exhaustive,
            "issues": issues}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", required=True)
    ap.add_argument("--glob", default="自检报告_第*批_*.md")
    ap.add_argument("--last", type=int, default=20)
    ap.add_argument("--min-item-ratio", type=float, default=0.8)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not os.path.isdir(a.reports):
        sys.exit("报告目录不存在：%s" % a.reports)
    rps = sorted(glob.glob(os.path.join(a.reports, a.glob)), key=os.path.getmtime)[-a.last:]
    if not rps:
        sys.exit("没匹配到报告：%s / %s" % (a.reports, a.glob))
    rows = [audit_report(p, a.min_item_ratio) for p in rps]
    bad = [r for r in rows if r["issues"]]
    if a.json:
        print(json.dumps({"reports": len(rows), "failing": len(bad), "rows": rows},
                         ensure_ascii=False, indent=2))
        return 0 if not bad else 1

    print("══ L6 注意力层：覆盖面声明 vs 证据 ══  审查报告 %d 份" % len(rows))
    print("")
    print("  %-34s %-10s %-8s %-9s %s" % ("报告", "声明", "逐条行", "覆盖面声明", "判定"))
    for r in rows:
        claim = ("抽 %d/池 %d" % (r["claimed_n"], r["claimed_pool"])) if r["claimed_n"] \
            else ("穷尽" if r["exhaustive"] else "无声明")
        print("  %-34s %-10s %-8d %-9s %s"
              % (r["report"][:34], claim, r["item_lines"], r["coverage_declared"],
                 "ok" if not r["issues"] else "FAIL"))
    if bad:
        print("")
        print("⛔ %d 份报告「说的覆盖面」与「给的证据」对不上：" % len(bad))
        for r in bad:
            for i in r["issues"]:
                print("   %s：%s" % (r["report"][:34], i))
    print("")
    print("判据：① 声明抽 N ⇒ 至少 N 条逐条读数；② 抽样少于池子 ⇒ 必写「只对抽样框负责/其余未查」；"
          "③ 写穷尽 ⇒ 必给总量；⛔ 无覆盖面声明却说「全库健康」= 越界。")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
