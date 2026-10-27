# -*- coding: utf-8 -*-
"""修复结果对账 v2：逐行比对原始文件与修复文件。
与 v1 的区别：压缩行的判定同时覆盖 b'...' 和 b"..." 两种 Python repr 引号形式，
否则双引号形式的残留会被漏检。"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from trace_config import cfg
SRC = cfg.outdir('wx')
DST = SRC + '_decoded'

# 没有可对账的文件时必须明确失败——不能让它打印"无问题"蒙混过去（静默通过比报错更危险）
_src_files = [f for f in os.listdir(SRC) if f.endswith('.txt')] if os.path.isdir(SRC) else []
if not _src_files:
    sys.stderr.write('[对账失败] 导出目录里没有 txt: %s\n' % SRC)
    sys.stderr.write('  → 先跑 wx_export_shards.py 生成导出，再跑本脚本\n')
    sys.exit(2)
if not os.path.isdir(DST):
    sys.stderr.write('[对账失败] 找不到修复版目录: %s\n' % DST)
    sys.stderr.write('  → 先跑 node wx_fix_zstd.mjs 生成解码版\n')
    sys.exit(2)

# zstd 帧魔数 28 b5 2f fd 在 repr 里一定以 \xb5/\xfd 形式出现
MARK = "\\xb5/\\xfd"


def is_compressed(line):
    return ("\\xfd" in line) and (": b'" in line or ': b"' in line)


print(f"{'文件':<26}{'原行数':>8}{'新行数':>8}{'改动行':>8}{'残留压缩':>10}{'其他改动':>10}")
tot = [0, 0, 0, 0, 0]
problems = []

for name in sorted(f for f in os.listdir(SRC) if f.endswith('.txt')):
    with open(os.path.join(SRC, name), encoding='utf-8', errors='replace') as f:
        a = f.read().split('\n')
    dpath = os.path.join(DST, name)
    if not os.path.exists(dpath):
        problems.append(f"{name}: 修复文件缺失")
        continue
    with open(dpath, encoding='utf-8', errors='replace') as f:
        b = f.read().split('\n')

    # 修复文件应比原文件多 1 行（元信息块里的「修复说明」）
    if len(b) != len(a) + 1:
        problems.append(f"{name}: 行数 {len(a)} -> {len(b)}，预期 +1")

    changed = 0
    residual = 0
    other = 0
    bi = 0
    for ai, line in enumerate(a):
        bl = b[bi] if bi < len(b) else None
        if bl is not None and line != bl:
            if bl.startswith('修复说明:'):
                bi += 1
                bl = b[bi] if bi < len(b) else None
        if bl != line:
            changed += 1
            if is_compressed(line):
                if is_compressed(bl or ''):
                    residual += 1
            else:
                other += 1
                if other <= 2:
                    problems.append(f"{name} 行{ai + 1} 非压缩行被改动:\n    原: {line[:110]}\n    新: {(bl or '')[:110]}")
        bi += 1

    remain = sum(1 for l in b if MARK in l)
    residual = max(residual, remain)
    print(f"{name:<26}{len(a):>8}{len(b):>8}{changed:>8}{residual:>10}{other:>10}")
    tot[0] += len(a); tot[1] += len(b); tot[2] += changed
    tot[3] += residual; tot[4] += other

print('-' * 70)
print(f"{'合计':<26}{tot[0]:>8}{tot[1]:>8}{tot[2]:>8}{tot[3]:>10}{tot[4]:>10}")

print('\n【判定】')
print(f"  残留压缩串: {tot[3]}  {'OK 全部清干净' if tot[3] == 0 else 'FAIL 仍有残留'}")
print(f"  非压缩行被误改: {tot[4]}  {'OK 未误伤' if tot[4] == 0 else 'FAIL 有误伤'}")
if problems:
    print('\n【问题明细】')
    for p in problems:
        print('  ' + p)
else:
    print('  行数全部为 原+1，无其他问题')

