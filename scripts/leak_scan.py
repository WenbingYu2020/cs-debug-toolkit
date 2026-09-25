#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发版前公开内容扫描（源码树版）。

与 `build_*.ps1` 的「包内泄漏检测」互补：构建脚本只扫**分发包**，而公开仓库还包含
`docs/`、`tests/`、`*.md` 等**不入包但会进仓库**的文件——本脚本扫整棵待推送源码树，
避免客户名 / 真实 ID / 个人路径 / AK 随源码泄露。

用法:
  python scripts/leak_scan.py                        # 扫 git 跟踪文件（默认，最贴近"即将公开"的内容）
  python scripts/leak_scan.py --all                  # 扫工作区所有文件（含未跟踪，会命中 temp/ 等本地产物）
  python scripts/leak_scan.py --dirs docs skill      # 只扫指定目录
  python scripts/leak_scan.py --config <patterns.json> [--ext .md,.py,.json]
  python scripts/leak_scan.py --quiet                # 只输出结论

退出码: 0 = 干净；1 = 有命中；2 = 配置缺失。
配置：默认读脚本同目录 `leak_patterns.json`（gitignore），缺失时回退 `leak_patterns.example.json`。
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_EXT = [".py", ".ps1", ".js", ".md", ".json", ".html", ".txt", ".yml", ".yaml"]
SKIP_DIRS = {".git", "__pycache__", "node_modules", "dist", ".venv", "venv", ".pytest_cache"}


def load_config(path):
    for cand in ([path] if path else []) + [
        os.path.join(HERE, "leak_patterns.json"),
        os.path.join(HERE, "leak_patterns.example.json"),
    ]:
        if cand and os.path.exists(cand):
            with io.open(cand, encoding="utf-8") as f:
                cfg = json.load(f)
            return cand, cfg.get("patterns", []), cfg.get("extensions", DEFAULT_EXT)
    return None, [], DEFAULT_EXT


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=os.getcwd())
        if out.returncode == 0 and out.stdout.strip():
            return [p for p in out.stdout.splitlines() if p.strip()]
    except Exception:
        pass
    return None


def walk_files(dirs):
    files = []
    for root_dir in dirs:
        for root, subdirs, names in os.walk(root_dir):
            subdirs[:] = [d for d in subdirs if d not in SKIP_DIRS]
            for n in names:
                files.append(os.path.join(root, n))
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="扫工作区所有文件（含未跟踪）")
    ap.add_argument("--dirs", nargs="*", default=None, help="只扫指定目录/文件")
    ap.add_argument("--config", default=None, help="泄漏模式配置 JSON")
    ap.add_argument("--ext", default=None, help="覆盖扩展名过滤，逗号分隔")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cfg_path, patterns, exts = load_config(args.config)
    if args.ext:
        exts = [e if e.startswith(".") else "." + e for e in args.ext.split(",")]
    if not patterns:
        print("配置缺失：找不到 leak_patterns.json / leak_patterns.example.json", file=sys.stderr)
        return 2
    rx = re.compile("|".join(patterns))
    exts = [e.lower() for e in exts]

    if args.dirs:
        files = walk_files(args.dirs)
    elif args.all:
        files = walk_files(["."])
    else:
        files = tracked_files() or walk_files(["."])

    hits, scanned = [], 0
    for path in files:
        if os.path.splitext(path)[1].lower() not in exts:
            continue
        if os.path.basename(path) in ("leak_patterns.json", "leak_patterns.example.json"):
            continue
        try:
            with io.open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except (IOError, UnicodeDecodeError):
            continue
        scanned += 1
        for idx, line in enumerate(lines, 1):
            if rx.search(line):
                hits.append((path, idx, line.strip()[:160]))

    if hits and not args.quiet:
        print("⚠ 疑似泄漏（%d 处）：" % len(hits))
        for path, idx, text in hits:
            print("  %s:%d  %s" % (path, idx, text))
    print("扫描 %d 个文件（配置：%s）→ %s" % (
        scanned, os.path.basename(cfg_path or "?"), "命中 %d 处" % len(hits) if hits else "干净 ✅"))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
