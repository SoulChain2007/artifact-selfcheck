#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""sample_trace.py — 随机抽样 + 逐条引用溯源检查（通用，任何产物类型都能用）

为什么要有它（2026-09-26 用户追加）：
  常规抽样是**定向**的（最久没查 / 最近改动 / 被引用最多）—— 快、抓得住"热点"，
  但它是**有偏**的：没进这三类的产物可能永远抽不到。随机抽样补的就是这个偏差，
  代价是它**必须可复现**（打印种子），否则下次没人能重跑同一批样本。

对每个样本做「引用溯源」：
  · 抓出工程前缀路径、docs/NN 编号、URL、连字符分段且数字结尾的 ID、
    `ref:` / `source:` / `authority:` / `见` 行；
  · **逐个尝试解析**：只搜 root、--also 和显式 --project-auto 范围；不隐式搜索父目录。
    ID/alias 从 id/alias/aliases 字段、文件名、ID 开头标题登记；普通提及不是定义。
    编号引用只搜这些根下的 docs；URL/authority 仅登记（不联网）；
  · 解析不了的 = **悬空引用**，逐条列出来（文件:行 + 引用原文）。

用法：
    python sample_trace.py <root>                     # 默认抽 5 个，种子 20260926
    python sample_trace.py <root> --n 8 --seed 42 --ext .yaml,.md
    python sample_trace.py <root> --json              # 机读（报告直接引用）
退出码：0 = CLEAN；1 = FIND（含协议标记）；2 = ERROR（含空池/不存在目录）
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
ID_RE = re.compile(r"(?<![\w-])[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*-\d+(?![\w-])")
AUTH_RE = re.compile(r"(?m)^\s*(?:-\s*)?(?:kind|ref|source|authority|出处|来源)\s*[:：]\s*\S+")


def sha12(path):
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def read_text(path):
    for enc in ("utf-8-sig", "gbk"):
        try:
            with io.open(path, encoding=enc) as fh:
                return fh.read()
        except UnicodeDecodeError:
            continue
    raise ValueError("无法解码文本：%s" % path)


def within_roots(path, roots):
    path = os.path.realpath(path)
    for root in roots:
        try:
            if os.path.commonpath([path, os.path.realpath(root)]) == os.path.realpath(root):
                return True
        except ValueError:
            continue
    return False


def collect_files(root, exts, excluded, sample_pool=False):
    def walk_error(error):
        raise error
    paths = []
    for directory, dirs, names in os.walk(root, onerror=walk_error):
        dirs[:] = sorted(d for d in dirs if d not in excluded and not os.path.islink(os.path.join(directory, d)))
        for name in sorted(names):
            if name.endswith(exts) and (not sample_pool or not name.startswith("_")):
                path = os.path.join(directory, name)
                if within_roots(path, [root]):
                    paths.append(path)
    return sorted(paths)


def index_ids(paths):
    """Index id/alias/aliases fields, filename IDs and ID-leading headings.

    Plain mentions never define IDs. IDs begin uppercase, use hyphen segments,
    end in digits. External aliases require an explicitly searched root.
    """
    definitions = set()
    for path in paths:
        definitions.update(ID_RE.findall(os.path.splitext(os.path.basename(path))[0].replace("_", " ")))
        text = read_text(path)
        if path.lower().endswith(".json"):
            try:
                payload = json.loads(text)
            except ValueError:
                payload = None  # Text tracing is not JSON schema validation.
            def visit(value):
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key.lower() in ("id", "alias", "aliases"):
                            values = child if isinstance(child, list) else [child]
                            for item in values:
                                if isinstance(item, str) and ID_RE.fullmatch(item):
                                    definitions.add(item)
                        visit(child)
                elif isinstance(value, list):
                    for item in value:
                        visit(item)
            visit(payload)
        alias_indent = None
        for line in text.splitlines():
            indent = len(line) - len(line.lstrip())
            if alias_indent is not None and line.strip() and indent <= alias_indent:
                alias_indent = None
            declaration = re.match(r'^\s*(?:-\s*)?["\']?(id|alias|aliases)["\']?\s*[:：]\s*(.*)', line, re.I)
            heading = re.match(r'^\s*#{1,6}\s+`?([A-Z][A-Za-z0-9-]*-\d+)(?![\w-])', line)
            value = declaration.group(2) if declaration else heading.group(1) if heading else ""
            if declaration and declaration.group(1).lower() == "aliases" and not value:
                alias_indent = indent
            elif alias_indent is not None and re.match(r'^\s*-\s*', line):
                value = line
            definitions.update(ID_RE.findall(value.split(" #", 1)[0]))
    return definitions


def resolve_path_ref(ref, roots):
    # ⛔ 判据 FAIL 时先看样本再调判据（skill 自己的纪律）：
    # 首版只搜了 root 与 root 的父目录，于是把「平级的主工程」里的
    # tools/、content/ 全判成悬空 —— 12 条全是假阳性。真正该搜的是
    # **该产物引用的那些工程根**（用 --also 传，或用 --project-auto 自动带上平级目录）。
    cands = []
    for r in roots:
        cands.append(os.path.join(r, ref.replace("/", os.sep)))
    for c in cands:
        if within_roots(c, roots) and os.path.isfile(c):
            return True
    return False


def resolve_num_ref(num, roots):
    # docs/NN 只搜索显式根下 docs；不拿其他目录中的同号文件冒充目标。
    for b in roots:
        if not os.path.isdir(b):
            continue
        for dirpath, _dirs, files in os.walk(os.path.join(b, "docs")):
            _dirs[:] = sorted(d for d in _dirs if not os.path.islink(os.path.join(dirpath, d)))
            for fn in files:
                if (re.match(r"^%s[_\-.]" % re.escape(num), fn) or ("_%s_" % num) in fn) and within_roots(os.path.join(dirpath, fn), roots):
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
    if a.n <= 0:
        raise ValueError("--n 必须大于 0")
    if not os.path.isdir(a.root):
        raise ValueError("root 不是目录：%s" % a.root)
    a.root = os.path.abspath(a.root)
    roots = [a.root]
    for extra in a.also:
        roots += [os.path.abspath(x.strip()) for x in re.split(r"[;；,]", extra) if x.strip()]
    for root in roots:
        if not os.path.isdir(root):
            raise ValueError("搜索根不是目录：%s" % root)
    if a.project_auto:
        parent = os.path.dirname(os.path.abspath(a.root))
        try:
            for d in sorted(os.listdir(parent)):
                p = os.path.join(parent, d)
                if os.path.isdir(p) and p != os.path.abspath(a.root):
                    roots.append(p)
        except OSError:
            raise
    roots = [r for r in dict.fromkeys(roots) if os.path.isdir(r)]
    exts = tuple(x.strip() for x in a.ext.split(",") if x.strip())
    if not exts:
        raise ValueError("--ext 不能为空")
    excl = tuple(x.strip() for x in a.exclude.split(",") if x.strip())
    files = collect_files(a.root, exts, excl, sample_pool=True)
    if not files:
        raise ValueError("没有可抽样的文件（检查 --ext / 路径）")
    definitions = index_ids(sorted(set(p for root in roots for p in collect_files(root, exts, excl))))
    k = min(a.n, len(files))
    sample = random.Random(a.seed).sample(files, k)

    out, dangling_total, no_ref = [], 0, 0
    for p in sorted(sample):
        txt = read_text(p)
        rel = os.path.relpath(p, a.root).replace("\\", "/")
        refs, dangling, unverified = [], [], 0
        for i, line in enumerate(txt.splitlines(), 1):
            for m in PATH_RE.finditer(line):
                refs.append(m.group(1))
                if not resolve_path_ref(m.group(1), roots):
                    dangling.append({"line": i, "kind": "path", "ref": m.group(1)})
            for m in NUMREF_RE.finditer(line):
                if any(p.start() <= m.start() < p.end() for pattern in (PATH_RE, URL_RE) for p in pattern.finditer(line)):
                    continue
                refs.append("docs/" + m.group(1))
                if not resolve_num_ref(m.group(1), roots):
                    dangling.append({"line": i, "kind": "docnum", "ref": "docs/" + m.group(1)})
            for m in URL_RE.finditer(line):
                refs.append(m.group(0))
                unverified += 1
            occupied = [m.span() for pattern in (PATH_RE, URL_RE) for m in pattern.finditer(line)]
            for m in ID_RE.finditer(line):
                if any(start <= m.start() < end for start, end in occupied):
                    continue
                refs.append(m.group(0))
                if m.group(0) not in definitions:
                    dangling.append({"line": i, "kind": "id", "ref": m.group(0)})
            for m in AUTH_RE.finditer(line):
                refs.append(m.group(0).strip())
                unverified += 1
        if not refs:
            no_ref += 1
        dangling_total += len(dangling)
        out.append({"file": rel, "bytes": os.path.getsize(p), "sha256_12": sha12(p),
                    "refs": len(refs), "unverified_refs": unverified, "dangling": dangling})

    result = {"selfcheck_protocol": 1, "status": "FIND" if dangling_total else "CLEAN",
              "scope": "仅抽样文件；只解析显式搜索根；URL/authority 仅登记未核验",
              "id_syntax": "大写字母起始、连字符分段、数字结尾，如 CARD-PRINT-999、WORLD-RULE-A-12345",
              "root": a.root, "roots_searched": roots, "seed": a.seed, "sampled": k, "pool": len(files),
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
          if dangling_total else "✅ 抽样内可检查引用无悬空；URL/authority 仅登记，未核验")
    print("搜索根：" + "; ".join(roots))
    print("注：随机抽样只对抽样框负责；结论写成「抽 %d / 池 %d，其余未查」。" % (k, len(files)))
    if dangling_total:
        print("ARTIFACT_SELFCHECK_FIND")
    return 0 if dangling_total == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        if "--json" in sys.argv:
            print(json.dumps({"selfcheck_protocol": 1, "status": "ERROR", "error": str(error)}, ensure_ascii=False))
        else:
            print("ERROR: %s" % error, file=sys.stderr)
        sys.exit(2)
