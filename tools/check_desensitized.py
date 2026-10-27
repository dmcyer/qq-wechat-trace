#!/usr/bin/env python3
"""提交前扫描：仓库文本里是否还有常见「未泛化」指纹。

用法（仓库根）:
    python tools/check_desensitized.py

退出码 0 = 未命中内置规则；1 = 有命中（打印文件:行）。

可选：脚本同目录的 pii_patterns.txt（每行一个正则，# 开头为注释）会追加扫描。
该文件已在 .gitignore，仅维护者本地使用——**含真实值的规则一律放那里，不要写进本文件**，
因为本文件会随仓库提交（公开时任何人可见）。

退出码 0 = 未命中规则；1 = 有命中（打印文件:行）。
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 内置：不含任何真实值的通用规则（可安全公开）
#
# ⚠️ 维护者约定：真实群名 / 群号 / 本机目录名等含真实值的规则，
#    一律写进同目录的 pii_patterns.txt（已 gitignore），不要加到本列表。
BUILTIN = [
    (r"D:[/\\]+files[/\\]", "本机 D:…/files/ 路径前缀"),
    (r"D:\\\\files\\\\", "config 里双写反斜杠的 D:\\\\files\\\\"),
    (r"qq_recover_\d+_v2", "旧脚本名 qq_recover_<数字>_v2"),
    (r"qq_export_\d+\.py", "旧脚本名 qq_export_<数字>.py"),
]

SKIP_DIR = {".git", "__pycache__", "node_modules", ".venv", "venv"}
# pii_patterns.txt 自身含真实值，扫描它必然自命中，故跳过
SKIP_FILE = {"check_desensitized.py", "pii_patterns.txt", "pii_patterns.example.txt"}
SCAN_EXT = {".md", ".py", ".ps1", ".mjs", ".json", ".txt", ".yml", ".yaml"}


def _iter_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext not in SCAN_EXT:
                continue
            if name in SKIP_FILE:
                continue
            yield os.path.join(dirpath, name)


def _load_extra():
    p = os.path.join(os.path.dirname(__file__), "pii_patterns.txt")
    if not os.path.isfile(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            out.append((line, "pii_patterns.txt"))
    return out


def main():
    extra = _load_extra()
    rules = [(re.compile(p), label) for p, label in BUILTIN]
    rules += [(re.compile(p), label) for p, label in extra]
    hits = []
    for path in _iter_files():
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    for rx, label in rules:
                        if rx.search(line):
                            rel = os.path.relpath(path, ROOT)
                            hits.append((rel, i, label, line.rstrip()[:120]))
                            break
        except OSError as e:
            print("skip %s: %s" % (path, e), file=sys.stderr)

    total = len(BUILTIN) + len(extra)
    if not hits:
        print("OK: 未命中脱敏规则（内置 %d 条 + 本地 pii_patterns.txt %d 条 = %d 条）。"
              % (len(BUILTIN), len(extra), total))
        return 0

    print("FAIL: %d 处命中（请泛化或加入误报例外后再提交）:\n" % len(hits))
    for rel, i, label, snippet in hits:
        print("  %s:%d  [%s]" % (rel, i, label))
        print("    %s" % snippet)
    return 1


if __name__ == "__main__":
    sys.exit(main())
