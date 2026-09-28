#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""deep_audit.py — 深度四问：镜像一致性 / 反证边界 / 生活链可执行性 / 分母深度 / 抽样纪律

本轮（2026-09-26 第二轮"举一反三"，用户要求四条全做）由**透镜覆盖率矩阵**定位出的薄点：
  ① L3 内部一致 的深水区 —— **设定集 ↔ 机读镜像**（`content/rules/*.yaml`）逐字段对账：
     设定说 Tactic 的 allowed_ops 是这 20 个，游戏侧的表也必须是这 20 个；两个真相源一旦漂移，
     玩家看到的规则与设定就不是一回事了。
  ② L1 可证伪性 —— **反证/边界闭合**：每条法则/判据都该有"不许什么"的边界条目或反例；
     只有正面定义、没有任何边界 = 这条规则不可证伪，等于没立。
  ③ 可执行性/日常性 —— **一天的生活链**：吃、住、交易、纠纷、病、葬、计时，每一环都要有条目、
     且要落在具体国家/地区上；某环缺或悬空 ⇒ 这个世界"住不进去"。
  ④ L2 分母深度 —— 三套外部分母"整类未枚举=0"只说明**每类都有一个代币**；本问量**每类的厚度**，
     把 ≤2 条 designed 的类标为"代币覆盖"。
  ⑤ L6 抽样纪律 —— 报告是否按自己的抽样声明说话：出现"抽样 N/池 M"就打勾；
     出现"全库健康/全部通过"却没有抽样声明 ⇒ 判越界。

用法：
    python deep_audit.py --entries <产物根> [--mirror <镜像yaml>] [--reports <报告目录>]
                         [--report-glob "*.md"] [--last 6] [--json]
退出码：0 = 四问无发现；1 = 有发现（明细见输出）
"""
import argparse
import collections
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

try:
    import yaml
except ImportError:
    sys.exit("需要 PyYAML：用装了 pyyaml 的解释器运行")

# 落点字段按**实际字段名**给全（⛔ 首版只认 nation，导致"food 落国 0"的全量假阳性）
# ⛔ 第二次修正：五环的"世界内落点"字段各不相同（building→settlement、medicine→practitioner、
# rite→registry、verdict→arbiter…）。判据不是"必须有 nation"，而是"必须有一个可指认的落点字段"。
ANCHOR_FIELDS = ("nation", "element_nation", "region", "place", "places", "origin_nation", "nations",
                 "settlement", "practitioner", "arbiter", "registry", "city", "temple", "guild",
                 "used_by", "where", "location")
# 规则层条目（如市场层次/规则）本来就没有地理落点，不要求落点字段
NO_ANCHOR_NEEDED = ("market",)
# 只对 judge（判据）要求边界：law 是公理、bound/lock/constraint 自己就是边界
BOUNDARY_REQUIRED_TYPES = ("judge",)
BOUNDARY_TYPES = ("bound", "constraint", "lock", "verdict")
# 天然单例的类型（历法/生产链/大陆…）不按"厚度"判 —— 世界本来就只有一条
SINGLETON_TYPES = ("calendar", "chain", "continent", "eratech", "ledger", "meta", "leader",
                   "axis", "phase", "scope", "tier")
LIFE_SLOTS = {"吃": ("food", 3), "住": ("building", 3), "交易": ("market", 2),
              "纠纷": ("verdict", 3), "病": ("medicine", 3), "葬": ("rite", 3)}
MIRROR_KEYS = ("in_deck", "allowed_ops", "keyword_families", "consumable", "tradeable",
               "growable", "zone_whitelist", "min_requirement")


def load(root):
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
                d["_path"] = os.path.relpath(os.path.join(dp, fn), root).replace("\\", "/")
                E[str(d["id"])] = d
    return E


def refs(d):
    out = []
    for k in ("depends_on", "relates"):
        for r in (d.get(k) or []):
            t = r.get("id") if isinstance(r, dict) else r
            if t:
                out.append(str(t))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entries", required=True)
    ap.add_argument("--mirror", default="")
    ap.add_argument("--reports", default="")
    ap.add_argument("--report-glob", default="*.md")
    ap.add_argument("--last", type=int, default=6)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    E = load(a.entries)
    if not E:
        sys.exit("读不到条目 —— 路径不对或生成器没跑，本检查不作数。")
    findings = {}

    # ① 镜像一致性
    if a.mirror and os.path.isfile(a.mirror):
        mir = yaml.safe_load(io.open(a.mirror, encoding="utf-8")) or {}
        rows = mir.get("classes") or []
        byfn = {}
        for r in rows:
            if isinstance(r, dict) and r.get("function"):
                byfn[str(r["function"])] = r
        diffs = []
        matched = 0
        for i, d in E.items():
            f = d.get("fields") or {}
            fn = str(f.get("function_enum") or "")
            if not fn or fn not in byfn:
                continue
            matched += 1
            m = byfn[fn]
            for k in MIRROR_KEYS:
                if k not in m:
                    continue
                mv, sv = m[k], f.get(k)
                if isinstance(mv, list) and isinstance(sv, list):
                    if [str(x) for x in mv] != [str(x) for x in sv]:
                        diffs.append({"id": i, "function": fn, "key": k,
                                      "mirror": len(mv), "setting": len(sv),
                                      "mirror_only": sorted(set(map(str, mv)) - set(map(str, sv)))[:4],
                                      "setting_only": sorted(set(map(str, sv)) - set(map(str, mv)))[:4]})
                elif str(mv) != str(sv):
                    diffs.append({"id": i, "function": fn, "key": k, "mirror": str(mv), "setting": str(sv)})
        findings["mirror"] = {"mirror_file": os.path.basename(a.mirror), "matched": matched, "diffs": diffs}

    # ② 反证/边界闭合
    inbound = collections.defaultdict(list)
    for i, d in E.items():
        for t in refs(d):
            inbound[t].append((i, str(d.get("type"))))
    no_boundary = []
    for i, d in E.items():
        if str(d.get("type")) not in BOUNDARY_REQUIRED_TYPES:
            continue
        if not any(t in BOUNDARY_TYPES for _x, t in inbound.get(i, [])):
            no_boundary.append({"id": i, "type": d.get("type"), "name": d.get("name")})
    findings["no_boundary"] = no_boundary

    # ③ 一天的生活链
    life = []
    for label, (typ, need) in LIFE_SLOTS.items():
        es = [(i, d) for i, d in E.items() if str(d.get("type")) == typ and str(d.get("status")) == "designed"]
        if typ in NO_ANCHOR_NEEDED:
            anchored, need_anchor = len(es), False
        else:
            anchored = sum(1 for _i, d in es
                           if any((d.get("fields") or {}).get(k) for k in ANCHOR_FIELDS))
            need_anchor = True
        life.append({"slot": label, "type": typ, "count": len(es), "need": need,
                     "anchored_to_nation": anchored,
                     "ok": len(es) >= need and ((anchored * 2 >= len(es)) if (es and need_anchor) else bool(es))})
    findings["life_chain"] = life

    # ④ 分母深度：每类的厚度
    depth = collections.Counter(str(d.get("type")) for d in E.values() if str(d.get("status")) == "designed")
    thin = sorted([(t, n) for t, n in depth.items()
                   if n <= 2 and t not in SINGLETON_TYPES])
    findings["class_depth"] = {"total_types": len(depth), "token_types": len(thin),
                               "thin": [{"type": t, "designed": n} for t, n in thin]}

    # ⑤ 抽样纪律
    if a.reports and os.path.isdir(a.reports):
        rps = sorted(glob.glob(os.path.join(a.reports, a.report_glob)), key=os.path.getmtime)[-a.last:]
        rows = []
        for p in rps:
            t = io.open(p, encoding="utf-8", errors="replace").read()
            # 抽样声明：抽 N/池 M、抽样声明、**穷尽**（穷尽也是一种声明）都算；只认"写了覆盖面"
            has_sample = bool(re.search(r"抽\s*\d+\s*[/／]\s*池|抽样\s*(声明|[:：]|\d+)|池\s*\d+|穷尽|全量读数", t))
            overreach = bool(re.search(r"(全库健康|整库无问题|全部通过且无遗漏)", t)) and not has_sample
            rows.append({"report": os.path.basename(p)[:40], "sampling_stated": has_sample,
                         "overreach": overreach})
        findings["sampling_discipline"] = rows

    n = len(findings.get("mirror", {}).get("diffs", [])) + len(no_boundary) \
        + sum(1 for r in life if not r["ok"]) + len(thin) \
        + sum(1 for r in findings.get("sampling_discipline", []) if r["overreach"])
    if a.json:
        print(json.dumps({"entries": len(E), "findings": findings, "issue_count": n},
                         ensure_ascii=False, indent=2))
        return 0 if n == 0 else 1

    print("══ 深度四问 ══  条目 %d" % len(E))
    mi = findings.get("mirror")
    if mi:
        print("")
        print("① 设定集 ↔ 机读镜像（%s）：可比对 %d 个类，**漂移 %d 处**"
              % (mi["mirror_file"], mi["matched"], len(mi["diffs"])))
        for d in mi["diffs"][:6]:
            print("     ★ %s %s.%s：镜像=%s 设定=%s" % (d["id"], d["function"], d["key"],
                                                         d.get("mirror"), d.get("setting")))
    print("")
    print("② 反证/边界闭合：判据类（judge）条目 %d 个里 **%d 个没有任何边界/反例条目引用它**"
          "（law 是公理、bound 自身即边界，均已豁免）"
          % (len([1 for d in E.values() if str(d.get("type")) in BOUNDARY_REQUIRED_TYPES]), len(no_boundary)))
    for r in no_boundary[:6]:
        print("     ★ %s %s %s" % (r["id"], r["type"], r["name"]))
    print("")
    print("③ 一天的生活链（每环要有条目且≥半数落在具体国家）：")
    for r in life:
        print("     %s %-8s %-9s 条目 %2d/需 %d；落国 %d  %s"
              % ("✅" if r["ok"] else "❌", r["slot"], r["type"], r["count"], r["need"],
                 r["anchored_to_nation"], "" if r["ok"] else "← 这一环住不进去"))
    print("")
    cd = findings["class_depth"]
    print("④ 分母深度：共 %d 个类型；其中 **%d 个只有 ≤2 条 designed（代币覆盖）**：%s"
          % (cd["total_types"], cd["token_types"],
             "、".join("%s(%d)" % (x["type"], x["designed"]) for x in cd["thin"][:10])))
    sd = findings.get("sampling_discipline")
    if sd:
        print("")
        print("⑤ 抽样纪律（最近 %d 份报告）：" % len(sd))
        for r in sd:
            print("     [%s] %s  抽样声明=%s%s" % ("越界" if r["overreach"] else "ok",
                                                   r["report"], r["sampling_stated"],
                                                   "" if not r["overreach"] else "  ← 没声明抽样却说全库"))
    print("")
    print("发现合计 %d 项%s" % (n, "" if n else "（四问皆无发现）"))
    return 0 if n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
