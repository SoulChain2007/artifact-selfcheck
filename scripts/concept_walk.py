#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Inspect definition, learning and application chains for schema-compatible concepts."""
import argparse
import io
import json
import os
import random
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

# 概念类条目：法则 / 判据 / 轴 / 操作符 / 相态 / 边界 / 术语 / 卡类定义（换项目改这里）
CONCEPT_STRATA = ("L1", "L2")
CONCEPT_TYPES = ("law", "judge", "axis", "tagaxis", "operator", "phase", "layer", "scope",
                 "bound", "class", "rarity", "status", "keyword", "op", "func", "matrix",
                 "gate", "tier", "spec", "meta", "term", "concept", "lock", "attr", "check")
LEARN_TYPES = ("school", "edu", "prof", "profession", "career", "statute", "ideology", "rite",
               "custom", "promo", "festival", "doc", "lang", "book", "academy")


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


def refs(d, key):
    out = []
    for r in (d.get(key) or []):
        tid = r.get("id") if isinstance(r, dict) else r
        if tid:
            out.append(str(tid))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--seed", type=int, default=20260926)
    ap.add_argument("--id", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--include-mechanics", action="store_true",
                    help="把 cards/（游戏机制）里的概念也纳入采样；默认排除，因为『世界的人怎么理解它』"
                         "只对世界层概念成立 —— 机制槽位是给玩家看的规则，不是这个世界的人要理解的概念")
    a = ap.parse_args()
    E = load(a.root)
    if not E:
        sys.exit("读不到任何条目 —— 路径不对或生成器没跑，本检查不作数。")

    if a.id:
        if a.id not in E:
            sys.exit("找不到条目：%s" % a.id)
        sample = [a.id]
    else:
        pool = [i for i, d in E.items()
                if (str(d.get("stratum")) in CONCEPT_STRATA or str(d.get("type")) in CONCEPT_TYPES)
                and (a.include_mechanics or not str(d.get("_path", "")).startswith("cards/"))]
        if not pool:
            pool = list(E)
        random.seed(a.seed)
        sample = random.sample(pool, min(a.n, len(pool)))

    out, bad = [], 0
    for eid in sample:
        d = E[eid]
        # A 定义链：BFS 向上追依赖，看到达 L0 还是断/环
        path, seen, cur, hops = [], set(), eid, []
        reached_primitive = False
        looped = False
        depth = 0
        frontier = [eid]
        while frontier and depth < 12:
            nxt = []
            for x in frontier:
                for t in refs(E.get(x, {}), "depends_on"):
                    if t in seen:
                        continue
                    seen.add(t)
                    td = E.get(t)
                    if td is None:
                        hops.append({"to": t, "ok": False, "why": "目标条目不存在"})
                        continue
                    st = str(td.get("stratum") or "")
                    hops.append({"to": t, "name": td.get("name"), "stratum": st, "ok": True})
                    if st == "L0" or not refs(td, "depends_on"):
                        reached_primitive = True
                    else:
                        nxt.append(t)
            frontier = nxt
            depth += 1
        if not hops:
            hops.append({"to": None, "ok": False, "why": "该概念没有任何 depends_on（连不上更基础的概念）"})
        if not reached_primitive:
            looped = True

        # B 传授链：谁教它 —— 有 LEARN_TYPES 的条目引用它
        teachers = []
        for i, dd in E.items():
            if str(dd.get("type")) not in LEARN_TYPES:
                continue
            if str(dd.get("_path", "")).startswith("cards/"):
                continue
            if eid in refs(dd, "depends_on") or eid in refs(dd, "relates"):
                teachers.append({"id": i, "name": dd.get("name"), "type": dd.get("type")})

        # C 落地链：L3 实例用它
        uses = []
        for i, dd in E.items():
            if str(dd.get("stratum")) == "L3" and eid in (refs(dd, "depends_on") + refs(dd, "relates")):
                uses.append(i)

        rec = {"id": eid, "name": d.get("name"), "type": d.get("type"), "stratum": d.get("stratum"),
               "A_definition_chain": {"closed": reached_primitive and not looped, "hops": hops},
               "B_teaching_chain": {"closed": bool(teachers), "teachers": teachers[:5]},
               "C_instance_chain": {"closed": bool(uses), "instances": uses[:8],
                                    "count": len(uses)}}
        rec["ok"] = rec["A_definition_chain"]["closed"] and rec["B_teaching_chain"]["closed"] \
            and rec["C_instance_chain"]["closed"]
        if not rec["ok"]:
            bad += 1
        out.append(rec)

    if a.json:
        print(json.dumps({"root": a.root, "seed": a.seed, "sampled": len(sample),
                          "concepts_failing": bad, "results": out}, ensure_ascii=False, indent=2))
        return 0 if bad == 0 else 1

    print("══ 概念理解链验证 ══  抽 %d 个概念 · 种子 %d" % (len(sample), a.seed))
    for r in out:
        print("")
        print("  %s %s（%s / %s）→ %s" % (r["id"], r["name"], r["type"], r["stratum"],
                                          "三条链闭合" if r["ok"] else "有断链"))
        ch = r["A_definition_chain"]
        print("    [%s] A 定义链（向上追到原词）" % ("闭环" if ch["closed"] else "断"))
        for h in ch["hops"][:8]:
            print("        %s %-14s %s" % ("✅" if h["ok"] else "❌", str(h.get("to")),
                                           (h.get("name") or h.get("why") or "")))
        tb = r["B_teaching_chain"]
        print("    [%s] B 传授链（这个世界的人从哪儿学到它）%s"
              % ("闭环" if tb["closed"] else "断",
                 "" if tb["closed"] else "  ← 没有任何学府/职业/流派/法令教它"))
        for t in tb["teachers"]:
            print("        ✅ %s %s（%s）" % (t["id"], t["name"], t["type"]))
        ic = r["C_instance_chain"]
        print("    [%s] C 落地链（有具体实例用它）共 %d 个%s"
              % ("闭环" if ic["closed"] else "断", ic["count"],
                 ("：" + "、".join(ic["instances"][:4])) if ic["instances"] else ""))
    print("")
    print("⛔ %d 个概念有断链 —— 派返工件（补基础概念 / 补学习渠道 / 补实例）" % bad
          if bad else "✅ 抽中概念三条链都闭合")
    print("注：结论只对抽样框负责；写「抽 %d / 池若干，其余未查」。" % len(sample))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
