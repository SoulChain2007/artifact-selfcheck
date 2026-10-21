#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""struct_audit.py — 结构审计五问：判据基础设施自检 / 跨条目矛盾 / 命名法 / 规模自洽 / 时序闭合

来源：把"用户找漏洞的元手法"机械化（2026-09-26）。用户每次都是从**一个具体提问角度**切进去的：
  · 换主体提问（"这个世界的人怎么拿到它 / 怎么理解它"）→ chain_walk / concept_walk
  · 沿边追问（"它的材料/下位有没有条目"）→ ref_closure
  · 反向追问（"谁依赖它"）→ ref_closure 的入度项
  · 量词置换（"有多少 / 占比多少"）→ ref_closure 的模板默认值项
  · **对本子自身提问**（"这套判据管不管得住自己"）→ 本脚本的 ①
本脚本补的五问，都是"换个角度问同一个库"：

  ① 判据基础设施自检 —— 自检台账用的 class 码是否都在**封闭词表**内；
     发明同义写法 ⇒ 跨轮的"同类 ≥2"统计永远失效（这是判据自身的漏洞）。
  ② 跨条目矛盾 —— 同一个实体（同名）在不同条目里被赋予**不同取值** ⇒ 双真相源。
  ③ 命名法一致性 —— 纯英文 slug 当名字 / 中英混用 ⇒ 命名体系漂移（世界里的人不会这么叫）。
  ④ 规模自洽 —— 设定文案里的数量级（"全球 ≈40 张"）与库内条目数对不上 ⇒ 数量漏缺。
  ⑤ 时序闭合 —— 状态字段（现存/失传/新创/在研）若从不出现"非现存"，说明时间维度没落地。

用法：
    python struct_audit.py --root <产物根> [--ledger <台账 jsonl>] [--vocab <词表文件>]
                           [--scale "S=40"] [--field-world-state world_state] [--json]
退出码：0 = 五问皆无发现；1 = 有发现（明细见输出）
"""
import argparse
import collections
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

CONSISTENCY_FIELDS = ("nation", "element_nation", "element", "rarity", "tier", "school", "class_ref")


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
                E[str(d["id"])] = d
    return E


def vocab_from_skill(skill_root):
    """从 skill 的 iteration.md 里读封闭词表（表里 `code` 形式）。"""
    p = os.path.join(skill_root, "references", "iteration.md")
    out = set()
    if os.path.isfile(p):
        txt = io.open(p, encoding="utf-8").read()
        out |= set(re.findall(r"`([a-z][a-z_]{3,})`", txt))
        out |= set(re.findall(r"\|\s*([a-z][a-z_]{3,})\s*\|", txt))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--ledger", default="")
    ap.add_argument("--vocab", default="")
    ap.add_argument("--skill-root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--scale", action="append", default=[],
                    help='设定里的数量级，形如 "S=40"（字段取值=数字）；与库内同字段取值的条目数比对')
    ap.add_argument("--field-world-state", default="world_state")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    E = load(a.root)
    if not E:
        sys.exit("读不到任何条目 —— 路径不对或生成器没跑，本检查不作数。")
    findings = {}

    # ① 判据基础设施：台账 class 是否都在封闭词表内
    if a.ledger and os.path.isfile(a.ledger):
        led = io.open(a.ledger, encoding="utf-8").read()
        used = set(re.findall(r'"class"\s*:\s*"([a-z_]+)"', led))
        vocab = set()
        if a.vocab and os.path.isfile(a.vocab):
            vocab = set(re.findall(r"`([a-z_]+)`", io.open(a.vocab, encoding="utf-8").read()))
        vocab |= vocab_from_skill(a.skill_root)
        outside = sorted(c for c in used if c and c not in vocab)
        findings["infra_vocab_drift"] = {"used": len(used), "outside_vocab": outside}

    # ② 跨条目矛盾：同名实体在不同条目里取值不同
    attr = collections.defaultdict(set)
    where = collections.defaultdict(list)
    for i, d in E.items():
        nm = str(d.get("name") or "")
        f = d.get("fields") or {}
        for k in CONSISTENCY_FIELDS:
            if nm and f.get(k) not in (None, ""):
                attr[(nm, k)].add(str(f[k]))
                where[(nm, k)].append(i)
    conflict = [{"name": k[0], "field": k[1], "values": sorted(v), "entries": where[k][:4]}
                for k, v in attr.items() if len(v) > 1]
    findings["cross_entry_conflict"] = conflict

    # ③ 命名法一致性
    slug = [i for i, d in E.items() if re.match(r"^[a-z0-9_]+$", str(d.get("name") or ""))]
    mixed = [i for i, d in E.items()
             if re.search(r"[A-Za-z]", str(d.get("name") or ""))
             and re.search(r"[\u4e00-\u9fff]", str(d.get("name") or ""))]
    findings["naming_drift"] = {"slug_names": slug, "mixed_names": mixed}

    # ④ 规模自洽
    scale = []
    for spec in a.scale:
        if "=" not in spec:
            continue
        fld, val = spec.split("=", 1)
        n = sum(1 for d in E.values() if str((d.get("fields") or {}).get(fld)) == val)
        try:
            want = int(val)
        except Exception:
            want = None
        scale.append({"field": fld, "value": val, "in_library": n, "claimed": want})
    findings["scale_mismatch"] = scale

    # ⑤ 时序闭合：状态字段的取值分布
    dist = collections.Counter()
    for d in E.values():
        v = (d.get("fields") or {}).get(a.field_world_state)
        if v:
            dist[str(v)[:16]] += 1
    findings["timeline_state"] = {"field": a.field_world_state, "distribution": dict(dist),
                                  "only_present": len(dist) <= 1}

    n_find = len(findings.get("infra_vocab_drift", {}).get("outside_vocab", [])) \
        + len(conflict) + len(slug) + len(mixed) + sum(1 for s in scale if s["claimed"] and s["in_library"] != s["claimed"])
    if a.json:
        print(json.dumps({"root": a.root, "entries": len(E), "findings": findings,
                          "issue_count": n_find}, ensure_ascii=False, indent=2))
        return 0 if n_find == 0 else 1

    print("══ 结构审计五问 ══  条目 %d" % len(E))
    iv = findings.get("infra_vocab_drift")
    if iv:
        print("")
        print("① 判据基础设施自检：台账用到 %d 个 class 码，其中 **%d 个不在封闭词表内**"
              % (iv["used"], len(iv["outside_vocab"])))
        for c in iv["outside_vocab"]:
            print("     ★ %s" % c)
    print("")
    print("② 跨条目矛盾：%d 处（同名实体在不同条目里取值不同）" % len(conflict))
    for c in conflict[:6]:
        print("     %s.%s -> %s   %s" % (c["name"], c["field"], " / ".join(c["values"]),
                                         "、".join(c["entries"])))
    print("")
    print("③ 命名法一致性：纯英文 slug 名 %d 条；中英混用 %d 条" % (len(slug), len(mixed)))
    if slug:
        print("     slug 例：%s" % "、".join(slug[:5]))
    if mixed:
        print("     混用例：%s" % "、".join(mixed[:5]))
    print("")
    print("④ 规模自洽：")
    for s in scale:
        flag = "✅" if (s["claimed"] and s["in_library"] == s["claimed"]) else "❌"
        print("     %s 字段 %s 取值 %s：库内 %d 条；设定声称 %s —— 差 %s"
              % (flag, s["field"], s["value"], s["in_library"], s["claimed"],
                 abs((s["in_library"] - s["claimed"])) if s["claimed"] else "?"))
    print("")
    ts = findings["timeline_state"]
    print("⑤ 时序闭合：字段 %s 取值分布 %s%s"
          % (ts["field"], ts["distribution"], "   ← 只有一种状态：时间维度没落地" if ts["only_present"] else ""))
    print("")
    print("发现合计 %d 项%s" % (n_find, "" if n_find else "（五问皆无发现）"))
    return 0 if n_find == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
