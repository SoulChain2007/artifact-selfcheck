#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""anchor_and_support.py — 锚点级引用解析 + 来源支撑性抽检（判据按类型分档）

本轮"举一反三"的两个新缺口（2026-09-26，由**透镜覆盖率矩阵**定位到 L5 可验证性最薄后设计）：

  A 锚点级引用解析 —— 引用写成 `docs/54 §1.15` 时，**文件解析得到 ≠ 那一节还在**。
    文档重构/改编号之后，编号能命中、节号却已经飞了；旧的检查（sample_trace）只看文件能不能解析。
    实测：某项目 1793 条带 §锚点的引用里 **7 处锚点在目标文件里找不到**（全指向 docs/79 §3.7）。

  B 来源支撑性抽检 —— "来源存在" ≠ "来源支撑我的这句话"（skill sourcing.md 第四步的判据）。
    做法：抽 N 条带 authority 的条目，看**条目名是否真出现在被引文件里**。
    ⛔ **判据必须按类型分档**：抽象条目（`Seal vs Monster`、`情感原点 vs 阈值`）本来就不会以名字出现，
    拿名字判它就是误报 —— 实测某项目抽 40 条命中 19/40，其中未命中的多属抽象类，
    所以本脚本把它们**分开报**，抽象类只作"需人工判读"，不判生效。

外部依据（准入台账已登记）：
  · CitePrism（arXiv 2605.16000）："Citation context…all affect whether a reference appropriately
    supports a local claim." ⇒ B 的判据方向有先例
  · VeriCite（arXiv 2510.11394）：行内引用核验可减少幻觉、便于人工复核
  · 锚点类检查：未命中先例 ⇒ 自创，标 weak

用法：
    python anchor_and_support.py --entries <产物根> --docs <文档根> [--n 40] [--seed S] [--json]
退出码：0 = 无悬空锚点且具名类支撑率达阈值；1 = 有（明细见输出）
"""
import argparse
import collections
import glob
import io
import json
import os
import random
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import yaml
except ImportError:
    sys.exit("需要 PyYAML：用装了 pyyaml 的解释器运行")

# 具名实体类型：这些条目的 name 应该真的出现在被引文档里
NAMED_TYPES = ("print", "named", "protagonist", "region", "continent", "landmark", "beast",
               "flora", "material", "food", "medicine", "item", "vehicle", "faction",
               "nation", "school", "building", "route", "rift", "pool")


def load_entries(root):
    E = {}
    for dp, _d, fs in os.walk(root):
        if "_schema" in dp or "__pycache__" in dp:
            continue
        for fn in fs:
            if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
                continue
            try:
                d = yaml.safe_load(io.open(os.path.join(dp, fn), encoding="utf-8"))
            except Exception:
                continue
            if isinstance(d, dict) and "id" in d:
                E[str(d["id"])] = d
    return E


def load_docs(root):
    out = {}
    for p in glob.glob(os.path.join(root, "**", "*.md"), recursive=True):
        m = re.match(r"(\d{1,3})[_\-.]", os.path.basename(p))
        if m:
            out[int(m.group(1))] = p
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entries", required=True, help="产物根（条目 yaml）")
    ap.add_argument("--docs", required=True, help="被引文档根（docs/，按 编号_ 命名）")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=20260926)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    E = load_entries(a.entries)
    docs = load_docs(a.docs)
    if not E:
        sys.exit("读不到条目 —— 路径不对或生成器没跑，本检查不作数。")
    if not docs:
        sys.exit("读不到被引文档（按 编号_ 命名）—— 检查 --docs。")

    # ── A 锚点级引用解析 ─────────────────────────────────────
    anch_tot, dangling, cache = 0, [], {}
    for i, d in E.items():
        for au in (d.get("authority") or []):
            ref = str((au or {}).get("ref") or "")
            m = re.match(r"docs/(\d{1,3})\s*§\s*([0-9]+(?:\.[0-9]+)*)", ref)
            if not m:
                continue
            anch_tot += 1
            num, sec = int(m.group(1)), m.group(2)
            p = docs.get(num)
            if not p:
                dangling.append({"id": i, "ref": ref, "why": "docs/%d 不存在" % num})
                continue
            if p not in cache:
                cache[p] = io.open(p, encoding="utf-8", errors="replace").read()
            txt = cache[p]
            if not re.search(r"(?m)^#{1,6}\s*" + re.escape(sec) + r"(\D|$)", txt) and sec not in txt:
                dangling.append({"id": i, "ref": ref, "why": "节 §%s 不在该文件里" % sec})

    # ── B 来源支撑性抽检（按类型分档）────────────────────────
    random.seed(a.seed)
    pool = [i for i, d in E.items() if d.get("authority")]
    sample = random.sample(pool, min(a.n, len(pool))) if pool else []
    stat = collections.defaultdict(lambda: {"n": 0, "hit": 0, "miss": []})
    for i in sample:
        d = E[i]
        t = "具名" if str(d.get("type")) in NAMED_TYPES else "抽象"
        nm = str(d.get("name") or "")
        hit = False
        for au in (d.get("authority") or []):
            m = re.match(r"docs/(\d{1,3})", str((au or {}).get("ref") or ""))
            if m and int(m.group(1)) in docs:
                p = docs[int(m.group(1))]
                if p not in cache:
                    cache[p] = io.open(p, encoding="utf-8", errors="replace").read()
                if nm and nm in cache[p]:
                    hit = True
        stat[t]["n"] += 1
        if hit:
            stat[t]["hit"] += 1
        elif len(stat[t]["miss"]) < 8:
            stat[t]["miss"].append("%s/%s" % (i, nm))

    named = stat.get("具名", {"n": 0, "hit": 0})
    named_rate = (named["hit"] / float(named["n"])) if named["n"] else 1.0
    result = {"entries": len(E), "docs": len(docs),
              "anchor_refs": anch_tot, "anchor_dangling": dangling,
              "support": {k: {"n": v["n"], "hit": v["hit"], "miss": v["miss"]} for k, v in stat.items()},
              "named_support_rate": round(named_rate, 3)}
    bad = len(dangling) > 0 or named_rate < 0.6
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not bad else 1

    print("══ 锚点级引用解析 + 来源支撑性抽检 ══  条目 %d · 文档 %d" % (len(E), len(docs)))
    print("")
    print("A 锚点级引用：带 §锚点的引用 %d 条，**悬空锚点 %d 处**" % (anch_tot, len(dangling)))
    for x in dangling[:10]:
        print("     ★ %s -> %s（%s）" % (x["id"], x["ref"], x["why"]))
    print("")
    print("B 来源支撑性（抽 %d 条，按类型分档）" % len(sample))
    for k in ("具名", "抽象"):
        s = stat.get(k)
        if not s:
            continue
        rate = (s["hit"] / float(s["n"])) if s["n"] else 0
        note = "" if k == "具名" else "   ← 抽象条目名字本就不该出现，只作人工判读、不判生效"
        print("     %s：%d/%d 命中（%.0f%%）%s" % (k, s["hit"], s["n"], rate * 100, note))
        for m in s["miss"][:4]:
            print("        · %s" % m)
    print("")
    print("判据：悬空锚点必须为 0；**具名类**支撑率 ≥60%（抽象类不作判据）。")
    print("⛔ 有悬空锚点或无支撑" if bad else "✅ 锚点全部解析、具名类支撑率达标")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
