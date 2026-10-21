#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""sampling_audit.py — L6 注意力层：报告"说的覆盖面"与"给的证据"是否匹配

补的是透镜矩阵最后一个薄点：L6 注意力限制。已有检查器只查"报告里有没有抽样声明"，
但**声明可以是空的** —— 写了"抽 5 / 池 1270"却一条样本读数都没给，读者无法验证它是真抽了，
还是抄了一个数字。所以本脚本把 L6 变成三条机器判据：

  ① **声明与证据对得上**：默认写了"抽 N"须有 N 个独立样本读数
     （每行一个样本标识〔路径或 ID〕+ 独立读数，重复标识只计一次），否则判 FIND。
     显式 --min-item-ratio < 1 仅为启发式容差；低于 N 条仍标 evidence_complete=false。
  ② **覆盖面声明**：抽样少于池子时，必须写出"只对抽样框负责 / 其余 M-N 未查"这类话，
     否则读者会把抽样结论当成全量结论。
  ③ **穷尽要说总量**：写"穷尽 / 全量读数"就必须给出池大小或条目总数；
     ⛔ 且**不许**在没有任何覆盖面声明时写"全库健康 / 整库无问题"（越界，判 FAIL）。

用法：
    python sampling_audit.py --reports <报告目录> [--glob "自检报告_第*批_*.md"] [--last 20]
                             [--json] [--min-item-ratio 1.0]
退出码：0 = CLEAN；1 = FIND（含协议标记）；2 = ERROR（运行/输入失败）
"""
import argparse
import glob
import io
import json
import math
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
TOTAL = re.compile(r"条目\s*(\d+)|共\s*(\d+)\s*[条个]")
NEGATED_EXHAUSTIVE = re.compile(r"(?:不|未|没有|无需|并非|不是|非)(?:做|作|进行|开展|完成|执行|采用|实施|"
                                r"提供|取得|达到|满足|作出|声称|计划|实现|宣称|检查|再|的|了|过|\s){0,4}$")
COVERAGE_DECL = re.compile(r"只对抽样框负责|其余\s*\d+\s*(?:个文件|份文件|文件|条目|条|个|项)?\s*未查|其余未查|未查其余")
OVERREACH = re.compile(r"全库健康|整库无问题|全部通过且无遗漏|全库无问题")
ITEM_HINT = re.compile(r"`([^`]+\.(?:yaml|yml|md|json|py|txt|csv|cs|ts|gd|html))`|"
                       r"(?<![\w-])([A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*-\d+)(?![\w-])")
# Readings must survive removal of the identifier. Its digits are not evidence.
READING = re.compile(r"(?:bytes?|refs?|resolved|unverified|count|lines?|items?|rows?|errors?|warnings?|"
                     r"字节|行数|条数|引用|悬空|读数|数量|错误|警告|分数|长度|得分)\s*[:：=]?\s*\d+(?:\.\d+)?"
                     r"|\d+(?:\.\d+)?\s*(?:B\b|KB\b|MB\b|字节|行|条|个|项|分|处)"
                     r"|\d+\s*/\s*[1-9]\d*"
                     r"|\b(?:PASS|FAIL|OK|CLEAN|FIND)\b|✅|✗|❌", re.I)


def evidence_samples(text):
    """One independent identity per row, counted once; no ID-digit readings.

    Compatible with historical ID/checkmark rows, backticked paths + units,
    labelled values, ratios, and Markdown tables with numeric reading cells.
    Unlabelled prose numbers (including list ordinals) are deliberately ignored.
    """
    samples = set()
    for line in text.splitlines():
        matches = list(ITEM_HINT.finditer(line))
        identities = {os.path.normcase(os.path.normpath(m.group(1).replace("/", os.sep))).replace("\\", "/") if m.group(1) else m.group(2)
                      for m in matches}
        if len(identities) != 1:
            continue
        remainder = ITEM_HINT.sub("", line)
        # A leading table ordinal is not a reading for the following sample.
        cells = line.split("|")
        identity_cell = next((index for index, cell in enumerate(cells) if ITEM_HINT.search(cell)), len(cells))
        table_number = "|" in line and any(re.fullmatch(r"\s*\*{0,2}\d+(?:\.\d+)?\*{0,2}\s*", cell)
                                              for cell in cells[identity_cell + 1:])
        if READING.search(remainder) or table_number:
            samples.update(identities)
    return sorted(samples)


def exhaustive_claim_lines(text):
    """Affirmative claim heuristic, not a general natural-language parser.

    Ordinary local negations such as 本轮不做全量读数 / 尚未穷尽 are excluded.
    The report should still use explicit count and coverage fields for clarity.
    """
    lines = []
    for line in text.splitlines():
        for match in EXHAUSTIVE.finditer(line):
            prefix = re.split(r"[，,。；;]", line[:match.start()])[-1]
            if not NEGATED_EXHAUSTIVE.search(prefix):
                lines.append(line)
                break
    return lines


def audit_report(path, min_ratio=1.0):
    if not 0 < min_ratio <= 1 or not math.isfinite(min_ratio):
        raise ValueError("min-item-ratio 必须在 (0, 1] 内")
    with io.open(path, encoding="utf-8-sig") as source:
        t = source.read()
    m = CLAIM_SAMPLE.search(t)
    claimed_n = int(m.group(1)) if m else None
    claimed_pool = int(m.group(2)) if m else None
    if claimed_n is None and CLAIM_N.search(t):
        claimed_n = int(CLAIM_N.search(t).group(1))
    if claimed_pool is None and CLAIM_POOL.search(t):
        claimed_pool = int(CLAIM_POOL.search(t).group(1))
    samples = evidence_samples(t)
    item_lines = len(samples)
    exhaustive_lines = exhaustive_claim_lines(t)
    exhaustive = bool(exhaustive_lines)
    has_cov = bool(COVERAGE_DECL.search(t))
    overreach = bool(OVERREACH.search(t)) and not has_cov

    issues = []
    evidence_required = None
    coverage_claims_consistent = True
    if overreach:
        issues.append("越界：写了「全库健康/整库无问题」却没有覆盖面声明")
    if claimed_n is not None:
        if claimed_n <= 0:
            issues.append("抽样数必须大于 0；空样本不能支持通过结论")
        if claimed_pool is None or claimed_pool <= 0:
            issues.append("抽样必须声明正数池大小")
        elif claimed_n > claimed_pool:
            issues.append("抽样数超过池大小")
        if claimed_n > 0 and claimed_pool is not None and claimed_pool >= claimed_n:
            evidence_required = claimed_n
        need = max(1, math.ceil(claimed_n * min_ratio))
        if item_lines < need:
            issues.append("声称抽 %d 条，但报告里只能数出 %d 条逐条读数（要 ≥%d）"
                          % (claimed_n, item_lines, need))
        if claimed_pool and claimed_n < claimed_pool and not has_cov:
            issues.append("抽样少于池子（%d/%d）却没写「只对抽样框负责 / 其余未查」" % (claimed_n, claimed_pool))
    # Exhaustive claims are checked independently: a smaller sample must never
    # hide a simultaneous promise of full coverage in the same report.
    if exhaustive:
        totals = {next(int(x) for x in match.groups() if x is not None)
                  for line in exhaustive_lines for match in TOTAL.finditer(line)}
        if len(totals) > 1:
            coverage_claims_consistent = False
            issues.append("穷尽声明中的总量互相矛盾")
        total = max(totals) if totals else claimed_pool
        if total is None:
            total_match = TOTAL.search(t)
            if total_match:
                total = next(int(x) for x in total_match.groups() if x is not None)
        if claimed_n is not None and not (claimed_n == claimed_pool == total and claimed_n > 0):
            coverage_claims_consistent = False
            issues.append("覆盖面声明矛盾：同时声称抽样与穷尽，但抽样数、池大小、穷尽总量不相等")
        if total is None or total <= 0:
            issues.append("写了「穷尽/全量」却没给总量（池大小或条目总数）")
        else:
            evidence_required = max(evidence_required or 0, total)
            if item_lines < max(1, math.ceil(total * min_ratio)):
                issues.append("穷尽声明缺少足够的独立样本读数：%d/%d" % (item_lines, total))
    elif claimed_n is None:
        issues.append("既没有抽样声明，也没有穷尽声明 —— 读不出本轮覆盖面")
    return {"report": os.path.basename(path), "claimed_n": claimed_n, "claimed_pool": claimed_pool,
            "item_lines": item_lines, "evidence_samples": samples,
            "evidence_required": evidence_required,
            "evidence_complete": coverage_claims_consistent and evidence_required is not None and item_lines >= evidence_required,
            "coverage_claims_consistent": coverage_claims_consistent,
            "min_item_ratio": min_ratio,
            "evidence_mode": "heuristic_tolerance" if min_ratio < 1 else "full_evidence",
            "coverage_declared": has_cov, "exhaustive": exhaustive,
            "issues": issues}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", required=True)
    ap.add_argument("--glob", default="自检报告_第*批_*.md")
    ap.add_argument("--last", type=int, default=20)
    # L6 requires N independent readings for a claim of N. The historical 0.8
    # default admitted 4/5; keeping it now requires explicit tolerance opt-in.
    ap.add_argument("--min-item-ratio", type=float, default=1.0,
                    help="默认 1.0：完整逐条证据；小于 1 仅为 heuristic/tolerance，不代表完整证据")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.last <= 0:
        raise ValueError("--last 必须大于 0")
    if not 0 < a.min_item_ratio <= 1 or not math.isfinite(a.min_item_ratio):
        raise ValueError("--min-item-ratio 必须在 (0, 1] 内")
    if not os.path.isdir(a.reports):
        raise ValueError("报告目录不存在：%s" % a.reports)
    rps = sorted(glob.glob(os.path.join(a.reports, a.glob)), key=os.path.getmtime)[-a.last:]
    if not rps:
        raise ValueError("没匹配到报告：%s / %s" % (a.reports, a.glob))
    rows = [audit_report(p, a.min_item_ratio) for p in rps]
    bad = [r for r in rows if r["issues"]]
    if a.json:
        print(json.dumps({"selfcheck_protocol": 1, "status": "FIND" if bad else "CLEAN",
                          "scope": "覆盖面语句采用局部语义启发式，排除常见否定表达；不保证解析所有自然语言叙述",
                          "min_item_ratio": a.min_item_ratio,
                          "evidence_mode": "heuristic_tolerance" if a.min_item_ratio < 1 else "full_evidence",
                          "evidence_complete": all(row["evidence_complete"] for row in rows),
                          "reports": len(rows), "failing": len(bad), "rows": rows},
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
        print("    evidence_complete=%s (%d/%s 个独立样本读数)" %
              (str(r["evidence_complete"]).lower(), r["item_lines"], r["evidence_required"]))
    if bad:
        print("")
        print("⛔ %d 份报告「说的覆盖面」与「给的证据」对不上：" % len(bad))
        for r in bad:
            for i in r["issues"]:
                print("   %s：%s" % (r["report"][:34], i))
    print("")
    print("判据：① 声明抽 N ⇒ 至少 ceil(N×%.2f) 个独立样本读数；② 抽样少于池子 ⇒ 必写「只对抽样框负责/其余未查」；"
          "③ 写穷尽 ⇒ 必给正数总量及读数；⛔ 无覆盖面声明却说「全库健康」= 越界。" % a.min_item_ratio)
    if a.min_item_ratio < 1:
        print("heuristic/tolerance 模式：通过容差阈值不等于 full evidence；完整性见 evidence_complete。")
    print("范围：覆盖面语句采用局部语义启发式，排除常见否定表达；复杂叙述请同时给明确计数与范围字段。")
    if bad:
        print("ARTIFACT_SELFCHECK_FIND")
    return 0 if not bad else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        if "--json" in sys.argv:
            print(json.dumps({"selfcheck_protocol": 1, "status": "ERROR", "error": str(error)}, ensure_ascii=False))
        else:
            print("ERROR: %s" % error, file=sys.stderr)
        sys.exit(2)
