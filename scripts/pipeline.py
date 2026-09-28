#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pipeline.py — 自检流水：一条命令按顺序跑完全部检查器，汇总成一张表

为什么要有它（2026-09-26 用户「接着做」）：
  此前 9 个检查器各自能跑，但**没有人在每一轮里按顺序全跑一遍** —— 判据再多，
  没人跑就等于不存在。本脚本是"自检的执行入口"：
    · 按配置顺序调用每个检查器，收集**退出码 / 末行读数 / 耗时**；
    · 把三类结果分开报，⛔ 不把"有发现"当"跑失败"：
        CLEAN  = 退出码 0（这轮没发现）
        FIND   = 退出码 1（跑赢了，但有发现 ⇒ 这是待办清单，不是崩溃）
        ERROR  = 退出码 ≥2 或抛异常（检查器本身坏了 —— 这才是要立刻修的）
    · 输出一行汇总，**可直接抄进报告**：`自检流水：通过 k/N（有发现 f，错误 e）`
    · `--stamp <path>` 写一份 JSON 运行留痕（谁在什么时候跑了什么、各是什么结果）

配置（JSON；示例见 config/pipeline.json）：
{
  "root": "<产物根>", "projectRoot": "<工程根>", "ledger": "<台账 jsonl>",
  "docs": "<被引文档根>", "mirror": "<镜像 yaml>", "reports": "<报告目录>",
  "seed": 40,
  "checks": [ { "name": "...", "script": "<脚本路径>", "args": ["--root", "{root}"] }, ... ]
}
占位符：{root} {projectRoot} {ledger} {docs} {mirror} {reports} {seed} {skill}

用法：
    python pipeline.py --config <json> [--stamp <json>] [--json] [--timeout 600]
退出码：0 = 全部 CLEAN 或仅有 FIND（有分工清单）；1 = 有 ERROR（检查器坏了）或配置读不到
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# skill 自身目录：本脚本可能被复制到项目里跑（例如被复制到项目自建的 tools/ 目录下），
# 那时 dirname(dirname(__file__)) 会是项目的 tools/ 而不是 skill —— 所以**优先用配置里的
# "skill" 键**，没有才回退到自身路径。实测踩过：复制后 7 个检查器全报"脚本不存在"。
SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def expand(v, ctx):
    s = str(v)
    for k, val in ctx.items():
        s = s.replace("{%s}" % k, str(val))
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--stamp", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()
    if not os.path.isfile(a.config):
        sys.exit("找不到流水配置：%s" % a.config)
    cfg = json.loads(io.open(a.config, encoding="utf-8").read())
    ctx = dict(cfg)
    ctx["skill"] = str(cfg.get("skill") or SKILL)
    ctx.setdefault("seed", 40)
    checks = cfg.get("checks") or []
    if not checks:
        sys.exit("配置里没有 checks —— 空流水等于没跑，不作数。")

    rows = []
    for c in checks:
        name = str(c.get("name") or os.path.basename(str(c.get("script"))))
        script = expand(c.get("script", ""), ctx)
        if not os.path.isfile(script):
            alt = os.path.join(SKILL, "scripts", os.path.basename(str(c.get("script", ""))))
            script = alt if os.path.isfile(alt) else script
        args = [expand(x, ctx) for x in (c.get("args") or [])]
        t0 = time.time()
        rc, out, err = None, "", ""
        if not os.path.isfile(script):
            rc, err = 127, "脚本不存在：%s" % script
        else:
            try:
                p = subprocess.run([sys.executable, script] + args,
                                   capture_output=True, timeout=a.timeout)
                rc = p.returncode
                out = (p.stdout or b"").decode("utf-8", "replace")
                err = (p.stderr or b"").decode("utf-8", "replace")
            except Exception as e:
                rc, err = 126, str(e)
        dt = round(time.time() - t0, 1)
        verdict = "CLEAN" if rc == 0 else ("FIND" if rc == 1 else "ERROR")
        tail = ""
        for ln in reversed([x for x in out.splitlines() if x.strip()]):
            tail = ln.strip()
            break
        if verdict == "ERROR":
            tail = (err.strip().splitlines() or [""])[-1][:100] or tail
        rows.append({"name": name, "script": os.path.basename(script), "rc": rc,
                     "verdict": verdict, "seconds": dt, "tail": tail[:120]})

    clean = sum(1 for r in rows if r["verdict"] == "CLEAN")
    find = sum(1 for r in rows if r["verdict"] == "FIND")
    error = sum(1 for r in rows if r["verdict"] == "ERROR")
    summary = "自检流水：通过 %d/%d（有发现 %d，错误 %d）" % (clean, len(rows), find, error)
    result = {"config": a.config, "checks": len(rows), "clean": clean, "findings": find,
              "errors": error, "summary": summary, "rows": rows,
              "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if a.stamp:
        try:
            with io.open(a.stamp, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            print("stamp 写入失败：%s" % e)

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if error else 0

    print("══ 自检流水 ══  检查器 %d 个（配置：%s）" % (len(rows), os.path.basename(a.config)))
    print("")
    print("  %-24s %-8s %-7s %-6s %s" % ("检查器", "脚本", "结果", "秒", "末行读数"))
    for r in rows:
        print("  %-24s %-8s %-7s %-6s %s" % (r["name"][:24], r["script"][:8], r["verdict"],
                                             r["seconds"], r["tail"][:64]))
    print("")
    print(summary)
    print("含义：CLEAN 这轮没发现；**FIND 是待办清单（不是崩溃）**；ERROR 才是检查器坏了，必须立刻修。")
    if error:
        print("")
        print("⛔ 有 %d 个检查器报错：" % error)
        for r in rows:
            if r["verdict"] == "ERROR":
                print("   %s：%s" % (r["name"], r["tail"]))
    return 1 if error else 0


if __name__ == "__main__":
    sys.exit(main())
