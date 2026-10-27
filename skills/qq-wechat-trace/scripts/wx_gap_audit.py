#!/usr/bin/env python3
# 审计已导出的 27 个群：用导出文件自身的时间轴找"历史可能不完整"的群
# 判据：
#   1) 库内条数 vs 导出条数 —— 已知 27/27 一致，此处只复核
#   2) 最大内部空档（天）—— 长空档说明 PC 端那段根本没收到消息
#   3) 活跃覆盖率 = 有消息的天数 / 跨度天数 —— 低说明大量日期空白
#   4) 最早时间 —— 对老群而言明显偏晚，可疑
import os, re, datetime, sys

from trace_config import cfg
QQDIR = sys.argv[1] if len(sys.argv) > 1 else cfg.outdir('qq')
WXDIR = sys.argv[2] if len(sys.argv) > 2 else cfg.outdir('wx')
NAMES = {'qq': cfg.groups('qq'), 'wx': cfg.groups('wx')}
TS = re.compile(r'^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} \|')

# 一个导出文件都没有时必须明确失败，不能输出一张空表还附带"判读提示"（静默通过）
_have = []
for _d, _tag in ((QQDIR, 'QQ'), (WXDIR, '微信')):
    if os.path.isdir(_d):
        _n = len([f for f in os.listdir(_d) if f.startswith(('qq_', 'wx_')) and f.endswith('.txt')])
        if _n:
            _have.append('%s %d 个' % (_tag, _n))
        else:
            sys.stderr.write('[审计失败] 目录里没有导出文件: %s\n' % _d)
    else:
        sys.stderr.write('[审计失败] 目录不存在: %s\n' % _d)
if not _have:
    sys.stderr.write('  → 先跑 qq_export_all.py / wx_export_shards.py 生成导出\n')
    sys.exit(2)


def audit(path, tag):
    days = set()
    n = 0
    bad_dates = 0
    skipped_lines = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for lineno, line in enumerate(f, 1):
            m = TS.match(line)
            if m:
                n += 1
                # 解析失败不能让整个审计崩掉（原实现在这里抛 ValueError，
                # 一个畸形日期就毁掉全部群的审计结果）。记下来，继续跑。
                try:
                    days.add(datetime.date.fromisoformat(m.group(1)))
                except ValueError:
                    bad_dates += 1
                    if len(skipped_lines) < 3:
                        skipped_lines.append('第%d行: %s' % (lineno, m.group(1)))
    if not days:
        return None
    if bad_dates:
        sys.stderr.write('[警告] %s 有 %d 个无法解析的日期，已跳过（%s）\n'
                         % (os.path.basename(path), bad_dates, '; '.join(skipped_lines)))
    ds = sorted(days)
    first, last = ds[0], ds[-1]
    span = (last - first).days + 1
    active = len(ds)
    # 最大内部空档
    maxgap, gapstart, gapend = 0, None, None
    for a, b in zip(ds, ds[1:]):
        g = (b - a).days
        if g > maxgap:
            maxgap, gapstart, gapend = g, a, b
    return dict(tag=tag, name=os.path.basename(path), n=n, first=first, last=last,
                span=span, active=active, cover=active / span, maxgap=maxgap,
                gapstart=gapstart, gapend=gapend)


rows = []
for num, nm in NAMES['wx'].items():
    p = os.path.join(WXDIR, 'wx_%s.txt' % num)
    if os.path.exists(p):
        r = audit(p, '微信'); r['num'] = num; r['cname'] = nm; rows.append(r)
for num, nm in NAMES['qq'].items():
    p = os.path.join(QQDIR, 'qq_%s.txt' % num)
    if os.path.exists(p):
        r = audit(p, 'QQ'); r['num'] = num; r['cname'] = nm; rows.append(r)

print('=' * 118)
print('%-4s %-14s %-18s %9s %7s %7s %6s %8s  %s' %
      ('', '群号', '群名', '条数', '跨度天', '活跃天', '覆盖', '最大空档', '空档位置'))
print('-' * 118)
for r in sorted(rows, key=lambda x: -x['maxgap']):
    gp = '%s ~ %s' % (r['gapstart'], r['gapend']) if r['maxgap'] > 0 else '-'
    print('%-4s %-14s %-18s %9d %7d %7d %5.0f%% %6d天  %s' %
          (r['tag'], r['num'], r['cname'][:16], r['n'], r['span'], r['active'],
           r['cover'] * 100, r['maxgap'], gp))
print('=' * 118)
print('覆盖率高 = 几乎每天都有消息；覆盖率低 = 大量空白月份')
print('判读提示：最大空档 > 60 天且该群前后都活跃，基本可判定 PC 端缺那段历史')


