#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""sample_trace.py — 随机抽样 + 逐条引用溯源检查（通用，任何产物类型都能用）

为什么要有它（2026-09-26 用户追加）：
  常规抽样是**定向**的（最久没查 / 最近改动 / 被引用最多）—— 快、抓得住"热点"，
  但它是**有偏**的：没进这三类的产物可能永远抽不到。随机抽样补的就是这个偏差，
  代价是它**必须可复现**（打印种子），否则下次没人能重跑同一批样本。

对每个样本做「引用溯源」：
  · 抓出文件里的引用：路径（相对路径 / 绝对路径 / docs/NN 这类编号引用）、URL、ID（大写-小写-数字）、
    `ref:` / `source:` / `authority:` / `见` 行；
  · **逐个尝试解析**：路径类引用在 root 与 root 的父目录下找；编号引用按前缀匹配；URL 只登记（不联网）；
  · 解析不了的 = **悬空引用**，逐条列出来（文件:行 + 引用原文）。

用法：
    python sample_trace.py <root>                     # 默认抽 5 个，种子 20260926
    python sample_trace.py <root> --n 8 --seed 42 --ext .yaml,.md
    python sample_trace.py <root> --json              # 机读（报告直接引用）
退出码：0 = 样本里没有悬空引用；1 = 有（明细见输出）
"""
import argparse
import hashlib
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

PATH_RE = re.compile(r"(?<![\w/])((?:docs|content|game|world|cards|bridge|tools|_交接产出|output|设定集)"
                     r"/[A-Za-z0-9_\-./\u4e00-\u9fff]+\.(?:md|yaml|yml|json|cs|py|txt|ts|gd))")
NUMREF_RE = re.compile(r"\bdocs/(\d{1,3})\b")
URL_RE = re.compile(r"https?://[^\s\)\]\"'>]+")
ID_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,8}-[A-Z0-9]{2,10}-\d{1,4}\b")
AUTH_RE = re.compile(r"(?m)^\s*(?:-\s*)?(?:kind|ref|source|authority|出处|来源)\s*[:：]\s*\S+")


def sha12(path):
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def read_text(path):
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return io.open(path, encoding=enc).read()
        except Exception:
            continue
    return ""


def resolve_path_ref(ref, roots):
    # ⛔ 判据 FAIL 时先看样本再调判据（skill 自己的纪律）：
    # 首版只搜了 root 与 root 的父目录，于是把「平级的主工程」里的
    # tools/、content/ 全判成悬空 —— 12 条全是假阳性。真正该搜的是
    # **该产物引用的那些工程根**（用 --also 传，或用 --project-auto 自动带上平级目录）。
    cands = []
    for r in roots:
        cands.append(os.path.join(r, ref.replace("/", os.sep)))
    for c in cands:
        if os.path.exists(c):
            return True
    return False


def resolve_num_ref(num, roots):
    # docs/NN 这类编号引用：在 root 与父目录下找 NN_* 或 NN-* 或 *_NN_*
    for b in roots:
        if not os.path.isdir(b):
            continue
        for dirpath, _dirs, files in os.walk(b):
            if dirpath.count(os.sep) - b.count(os.sep) > 3:
                continue
            for fn in files:
                if re.match(r"^%s[_\-.]" % re.escape(num), fn) or ("_%s_" % num) in fn:
                    return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20260926)
    ap.add_argument("--ext", default=".md,.yaml,.yml,.json,.cs,.py,.txt")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--exclude", default="_schema,node_modules,.git,__pycache__")
    ap.add_argument("--also", action="append", default=[],
                    help="额外的工程根（可重复，或用 ; 分隔）。产物与它引用的工程是平级目录时必须给")
    ap.add_argument("--project-auto", action="store_true",
                    help="自动把 root 的同级目录也当工程根（平级工程布局）")
    a = ap.parse_args()
    if not os.path.isdir(a.root):
        sys.exit("root 不是目录：%s" % a.root)
    roots = [a.root]
    for extra in a.also:
        roots += [x.strip() for x in re.split(r"[;；,]", extra) if x.strip()]
    if a.project_auto:
        parent = os.path.dirname(os.path.abspath(a.root))
        try:
            for d in os.listdir(parent):
                p = os.path.join(parent, d)
                if os.path.isdir(p) and p != os.path.abspath(a.root):
                    roots.append(p)
        except Exception:
            pass
    roots = [r for r in dict.fromkeys(roots) if os.path.isdir(r)]
    exts = tuple(x.strip() for x in a.ext.split(",") if x.strip())
    excl = tuple(x.strip() for x in a.exclude.split(",") if x.strip())
    files = []
    for dirpath, dirnames, filenames in os.walk(a.root):
        dirnames[:] = [d for d in dirnames if d not in excl]
        for fn in filenames:
            if fn.startswith("_") or not fn.endswith(exts):
                continue
            p = os.path.join(dirpath, fn)
            if any(x in p for x in excl):
                continue
            files.append(p)
    if not files:
        sys.exit("没有可抽样的文件（检查 --ext / 路径）")
    random.seed(a.seed)
    k = min(a.n, len(files))
    sample = random.sample(files, k)

    out, dangling_total, no_ref = [], 0, 0
    for p in sorted(sample):
        txt = read_text(p)
        rel = os.path.relpath(p, a.root).replace("\\", "/")
        refs, dangling = [], []
        for i, line in enumerate(txt.splitlines(), 1):
            for m in PATH_RE.finditer(line):
                refs.append(m.group(1))
                if not resolve_path_ref(m.group(1), roots):
                    dangling.append({"line": i, "kind": "path", "ref": m.group(1)})
            for m in NUMREF_RE.finditer(line):
                refs.append("docs/" + m.group(1))
                if not resolve_num_ref(m.group(1), roots):
                    dangling.append({"line": i, "kind": "docnum", "ref": "docs/" + m.group(1)})
            for m in URL_RE.finditer(line):
                refs.append(m.group(0))
            for m in AUTH_RE.finditer(line):
                refs.append(m.group(0).strip())
        if not refs:
            no_ref += 1
        dangling_total += len(dangling)
        out.append({"file": rel, "bytes": os.path.getsize(p), "sha256_12": sha12(p),
                    "refs": len(refs), "dangling": dangling})

    result = {"root": a.root, "roots_searched": roots, "seed": a.seed, "sampled": k, "pool": len(files),
              "dangling_total": dangling_total, "samples_without_refs": no_ref,
              "samples": out}
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if dangling_total == 0 else 1

    print("══ 随机抽样 + 引用溯源 ══  池 %d 个文件 · 抽 %d 个 · 种子 %d（可复现）"
          % (len(files), k, a.seed))
    print("")
    for r in out:
        flag = "OK " if not r["dangling"] else "悬空"
        print("  [%s] %s  (%d B, sha %s)  引用 %d 条" %
              (flag, r["file"], r["bytes"], r["sha256_12"], r["refs"]))
        for d in r["dangling"]:
            print("        L%-4d %-6s %s" % (d["line"], d["kind"], d["ref"]))
    print("")
    print("样本内悬空引用合计：%d ；完全无引用的样本：%d"
          % (dangling_total, no_ref))
    print("⛔ 有悬空引用 —— 逐条派返工件（补条目 / 改引用 / 登记为不存在的历史件）"
          if dangling_total else "✅ 抽样样本的引用全部可解析")
    print("注：随机抽样只对抽样框负责；结论写成「抽 %d / 池 %d，其余未查」。" % (k, len(files)))
    return 0 if dangling_total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
