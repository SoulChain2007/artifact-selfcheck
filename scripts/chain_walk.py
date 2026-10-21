#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""chain_walk.py — 世界内可达性验证：随机抽条目 → 站在这个世界的人的角度写链 → 逐跳对账

用户 2026-09-26 追加的方法：
  随机抽一条世界条目，然后**假设自己是这个世界的人**，问「我要得到它/了解它，得走哪几条路」，
  每条路写成一条完整逻辑链（谁 → 去哪里 → 找谁 → 用什么 → 得到什么）。
  例：抽到一张武器卡 ⇒ ① 去某地区的某渠道购买；② 去击杀某异兽取某材料自己制作。
  然后**逐跳对账**：链上每个节点在产物里都得有对应条目、且可溯源；链断了或节点缺 = 内容漏缺。

为什么它比"字段齐全"更有用：字段齐全只说明条目**自己**写完了；可达性说明它**接进了世界**。
  一条无人能获得、无来源、无去处的条目，字段再全也是悬空的。

通用性：脚本本身不认识"卡牌"，只认三类证据——
  ① 条目自身属性里的实体名（材料/产地/工法…）② 这些名字能否解析到同名条目 ③ 获得链所需的**功能类型**是否存在
  （市场/价格/渠道/生产链/技术/流派…）。换项目时用 --type-map 换映射即可。

用法：
    python chain_walk.py --root <产物根> --n 2 --seed 20260926
    python chain_walk.py --root <产物根> --id CARD-PRINT-024      # 指定条目
    python chain_walk.py --root <产物根> --n 2 --json
退出码：0 = 抽样条目都有 ≥2 条闭环链；1 = 有断链/缺链（明细见输出）
"""
import argparse
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

# 默认映射（本项目＝设定集；换项目改这里或用 --type-map）
ACQUIRE_TYPES = ("print", "material", "food", "medicine", "item", "vehicle", "relic")
CHAIN_A_TYPES = ("market", "channel", "price")          # 购买链所需的功能类型
CHAIN_B_TYPES = ("beast", "flora", "material", "chain")  # 自制链所需：产出源 + 材料 + 生产链
TECH_TYPES = ("tech", "school", "prof", "profession", "craft")
NAME_FIELDS = ("materials", "core_yield", "medium", "ingredients", "made_of")
PLACE_FIELDS = ("nation", "element_nation", "region", "origin_nation")


def load(root):
    E = {}
    for dirpath, _dirs, files in os.walk(root):
        if "_schema" in dirpath or "__pycache__" in dirpath:
            continue
        for fn in files:
            if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                d = yaml.safe_load(io.open(p, encoding="utf-8"))
            except Exception:
                continue
            if isinstance(d, dict) and "id" in d:
                d["_path"] = os.path.relpath(p, root).replace("\\", "/")
                E[str(d["id"])] = d
    return E


def tokens(v):
    s = re.sub(r"[（(][^)）]*[)）]", "", str(v))
    return [t.strip(" 。.;；:：") for t in re.split(r"[+＋、,，/｜|\s]+", s) if t.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--id", default="")
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--seed", type=int, default=20260926)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not os.path.isdir(a.root):
        sys.exit("root 不是目录：%s" % a.root)
    E = load(a.root)
    if not E:
        sys.exit("读不到任何条目 —— 路径不对或生成器没跑，本检查不作数。")
    by_name = {}
    for i, d in E.items():
        if d.get("name"):
            by_name.setdefault(str(d["name"]), i)
    by_type = {}
    for i, d in E.items():
        by_type.setdefault(str(d.get("type")), []).append(i)

    def resolve(name):
        if name in by_name:
            return by_name[name]
        for n, i in by_name.items():          # 允许"霜王牙(基底)"这类包含式命中
            if name and (name in n or n in name):
                return i
        return None

    if a.id:
        sample = [a.id] if a.id in E else []
        if not sample:
            sys.exit("找不到条目：%s" % a.id)
    else:
        pool = [i for i in E if str(E[i].get("type")) in ACQUIRE_TYPES]
        if not pool:
            pool = list(E)
        random.seed(a.seed)
        sample = random.sample(pool, min(a.n, len(pool)))

    out, bad_total = [], 0
    for eid in sample:
        d = E[eid]
        f = d.get("fields") or {}
        rec = {"id": eid, "name": d.get("name"), "type": d.get("type"), "chains": []}

        # ── 链 A：向他人取得（购买/交易）—— 需要 产地 + 市场 + 价格 + 渠道
        hops = []
        place = None
        for k in PLACE_FIELDS:
            if f.get(k):
                place = tokens(f[k])[0]
                break
        hops.append({"hop": "产地", "look": place, "ok": bool(place and resolve(place)),
                     "entry": resolve(place) if place else None})
        for t in CHAIN_A_TYPES:
            ids = by_type.get(t, [])
            hops.append({"hop": t, "look": t, "ok": bool(ids), "entry": ids[0] if ids else None})
        rec["chains"].append({"name": "购买/交易链", "hops": hops,
                              "closed": all(h["ok"] for h in hops)})

        # ── 链 B：自己动手做 —— 材料（逐条）+ 产出源 + 生产链 + 工法
        hops_b = []
        mats = []
        for k in NAME_FIELDS:
            if f.get(k):
                mats += tokens(f[k])
        if mats:
            for m in mats:
                rid = resolve(m)
                hops_b.append({"hop": "材料", "look": m, "ok": bool(rid), "entry": rid})
        else:
            hops_b.append({"hop": "材料", "look": None, "ok": False, "entry": None})
        src = None
        for t in ("beast", "flora"):
            for i in by_type.get(t, []):
                fld = (E[i].get("fields") or {})
                for k in NAME_FIELDS:
                    if fld.get(k) and any(m in str(fld[k]) for m in mats):
                        src = i
                        break
                if src:
                    break
            if src:
                break
        hops_b.append({"hop": "产出源(异兽/植物)", "look": src, "ok": bool(src), "entry": src})
        for t in ("chain",):
            ids = by_type.get(t, [])
            hops_b.append({"hop": t, "look": t, "ok": bool(ids), "entry": ids[0] if ids else None})
        tech = None
        for t in TECH_TYPES:
            if by_type.get(t):
                tech = by_type[t][0]
                break
        hops_b.append({"hop": "工法/流派", "look": tech, "ok": bool(tech), "entry": tech})
        rec["chains"].append({"name": "自制链", "hops": hops_b,
                              "closed": all(h["ok"] for h in hops_b)})

        rec["closed_chains"] = sum(1 for c in rec["chains"] if c["closed"])
        rec["ok"] = rec["closed_chains"] >= 2
        if not rec["ok"]:
            bad_total += 1
        out.append(rec)

    if a.json:
        print(json.dumps({"root": a.root, "seed": a.seed, "sampled": len(sample),
                          "entries_with_lt2_closed_chains": bad_total, "results": out},
                         ensure_ascii=False, indent=2))
        return 0 if bad_total == 0 else 1

    print("══ 世界内可达性验证（站在这个世界的人的角度）══  抽 %d 条 · 种子 %d" % (len(sample), a.seed))
    for r in out:
        print("")
        print("  %s %s（%s）→ 闭环链 %d/2" % (r["id"], r["name"], r["type"], r["closed_chains"]))
        for c in r["chains"]:
            print("    [%s] %s" % ("闭环" if c["closed"] else "断链", c["name"]))
            for h in c["hops"]:
                print("        %s %-14s %-12s %s" % ("✅" if h["ok"] else "❌", h["hop"],
                                                     str(h["look"])[:12], h["entry"] or "（无条目）"))
    print("")
    print("⛔ %d 条抽中条目拿不到 2 条闭环链 —— 逐条派返工件（补市场/价格/产出源/工法）" % bad_total
          if bad_total else "✅ 抽中条目都有 ≥2 条闭环可达链")
    print("注：结论只对抽样框负责；写「抽 %d / 池若干，其余未查」。" % len(sample))
    return 0 if bad_total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
