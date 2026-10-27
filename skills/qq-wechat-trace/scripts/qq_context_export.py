#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按人导出：某 QQ 号在指定群的全部发言 + 前后 N 条上下文，重叠自动合并。

用法：
    # 先定位人在哪个群
    python scripts/qq_locate_person.py <目标QQ号>

    # 再导出发言 + 上下文
    python scripts/qq_context_export.py --group <群号> --uin <目标QQ号> --ctx 5

    # 输出到指定文件
    python scripts/qq_context_export.py --group <群号> --uin <目标QQ号> \
        --ctx 5 --out work/x.txt

为什么需要这个脚本（chatlog-keeper 没有的能力）：
  chatlog-keeper 是**整会话导出**。想要「某人的全部发言」只能自己从全量里筛，
  而一旦加上上下文，连续发言会让同一批上下文被重复打印 N 遍。
  本脚本用**区间合并**解决：
      每条发言 -> [i-ctx, i+ctx]
      重叠或相邻的区间合并为一段
      每段只输出一次，段内该人的发言用 ▶ 标出
  实测 224 条发言 / ctx=5：逐条展开 2464 条 -> 合并后 995 条（省 1469 条重复）。

依赖：已剥头的 QQ 库（scripts/qq_strip_header.py 产出，路径见 cfg.qq_clear()）
"""
import argparse
import datetime
import os
import re
import sys

import sqlcipher3

from trace_config import cfg

TZ = datetime.timezone(datetime.timedelta(hours=8))

# ---------------------------------------------------------------------------
# QQ 消息体字段（2026-10 实测确认）
#   40800 / 40900 都是 protobuf，不是纯文本
#   45101 = 正文文本
#   47602 = 元素类型
# ---------------------------------------------------------------------------
F_BODY = '40800'
F_BODY2 = '40900'
TEXT_FIELD = 45101
CONTAINER_FIELDS = (40800, 40900, 40801, 47423)


def parse_pb(buf):
    """极小 protobuf 解析器，返回 [(field_no, wire_type, value)]。遇错即停。"""
    out = []
    i, n = 0, len(buf)
    while i < n:
        key = 0
        shift = 0
        while i < n:
            b = buf[i]
            i += 1
            key |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
            if shift > 63:
                return out
        fn, wt = key >> 3, key & 7
        if fn == 0:
            return out
        if wt == 0:
            v = 0
            shift = 0
            while i < n:
                b = buf[i]
                i += 1
                v |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
                if shift > 63:
                    return out
            out.append((fn, wt, v))
        elif wt == 2:
            ln = 0
            shift = 0
            while i < n:
                b = buf[i]
                i += 1
                ln |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
                if shift > 63:
                    return out
            if i + ln > n:
                return out
            out.append((fn, wt, buf[i:i + ln]))
            i += ln
        elif wt == 5:
            i += 4
        elif wt == 1:
            i += 8
        else:
            return out
    return out


def _is_garbage_text(s):
    """判断一段解码结果是否是元数据/二进制噪声。"""
    if not s or not s.strip():
        return True
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', s):
        return True
    if re.search(r'u_[A-Za-z0-9_\-]{15,}', s):        # qq 内部 uid
        return True
    if re.fullmatch(r'[\d\s]+', s):
        return True
    cjk = len(re.findall(r'[\u4e00-\u9fff]', s))
    weird = len(re.findall(r'[\u0080-\u02ff\u0370-\u052f\u0590-\u08ff]', s))
    if weird > cjk and weird > 2:
        return True
    if not re.sub(r'[\s\d\W_]', '', s):
        return True
    return False


def _scrub(text):
    """清理长度前缀被误当 UTF-8 解码后产生的残字。

    这是最坑的一处：protobuf 长度前缀字节可能落在
    拉丁扩展 / 希腊 / 西里尔 / 阿拉伯 / 亚美尼亚 / 藏文 / 希伯来 区段，
    解码后变成看似文字的残字（实测见过 ݽպj、ª、ڔ、ཐ、պj）。
    这些区段在中文聊天里几乎不出现，整片删除。
    """
    if not text:
        return ''
    t = re.sub(r'u_[A-Za-z0-9_\-]{15,}', ' ', text)
    t = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', ' ', t)
    t = re.sub(
        r'[\u0080-\u02ff\u0370-\u052f\u0530-\u058f\u0590-\u08ff'
        r'\u0f00-\u0fff\ufb50-\ufdff\ufe70-\ufeff\ufff0-\uffff]', '', t)
    t = re.sub(r'[ \t]{2,}', ' ', t).strip()
    if len(re.sub(r'[\s\W_]', '', t)) < 2:
        return ''
    return t


def extract_text(*blobs):
    """从 40800 / 40900 里抽正文。

    ★ 关键两条（都是踩坑换来的）：
      1. 引用回复消息里，40800 会夹带被引用消息的完整元数据（uid、群号、
         二进制长度前缀）。不递归+不过滤，正文里会混进大量乱码。
      2. 40900 也是 protobuf，不能直接 .decode()。有些消息 40800 只有元数据，
         正文全在 40900 里（实测某条 224 条发言里有 3 条如此）。
    """
    for blob in blobs:
        if not blob:
            continue
        parts = []

        def walk(b, depth=0):
            if depth > 6:
                return
            for fn, wt, v in parse_pb(b):
                if wt != 2:
                    continue
                if fn == TEXT_FIELD:
                    try:
                        s = v.decode('utf-8')
                    except Exception:
                        continue
                    if not _is_garbage_text(s):
                        parts.append(s)
                elif fn in CONTAINER_FIELDS:
                    walk(v, depth + 1)

        walk(bytes(blob))
        if parts:
            return _scrub(''.join(parts))
    return ''


def fetch_group_rows(con, group):
    """取某群全部消息，**坏页容错**。

    QQ 库里有些群的数据页已损坏，直接 `WHERE 40027=?` 会抛
    `database disk image is malformed`（实测：某个高活跃群的库就是这样）。
    正确姿势是 Step 1 走索引拿 rowid 列表，Step 2 按 rowid 逐行点读，
    坏行跳过并计数——不能因为几页坏了就整群读不出来。
    """
    IDX = 'group_msg_table_idx40027_40003'
    cols = ('rowid', '"40050"', '"40033"', '"40090"', '"40093"',
            '"%s"' % F_BODY, '"%s"' % F_BODY2)
    sel = ', '.join(cols)

    # ---- 先试直读（快，且大多数群没坏页）----
    try:
        return con.execute(
            'SELECT %s FROM group_msg_table WHERE "40027" = ? '
            'ORDER BY "40050" ASC, rowid ASC' % sel, (group,)).fetchall(), 0
    except Exception as e:
        if 'malformed' not in str(e).lower():
            raise
        print('  ⚠ 该群有坏页（malformed），改用「索引定位 rowid + 逐行点读」…')

    # ---- 走索引取 rowid ----
    try:
        rid_list = [r[0] for r in con.execute(
            'SELECT rowid FROM group_msg_table INDEXED BY %s '
            'WHERE "40027" = ? ORDER BY rowid' % IDX, (group,))]
    except Exception as e:
        raise SystemExit(
            '❌ 该群索引也读不了（%s）。\n'
            '  → 用 scripts/qq_recover_by_rowid.py %s 抢救' % (e, group))

    print('  索引定位到 %d 条，开始逐行点读（坏行会跳过）…' % len(rid_list))

    rows, bad = [], 0
    for i, rid in enumerate(rid_list, 1):
        try:
            r = con.execute(
                'SELECT %s FROM group_msg_table WHERE rowid = ?' % sel, (rid,)).fetchone()
            if r:
                rows.append(r)
        except Exception:
            bad += 1
        if i % 2000 == 0:
            print('    进度 %d/%d，已读到 %d 条，坏行 %d'
                  % (i, len(rid_list), len(rows), bad), flush=True)

    print('  点读完成：成功 %d 条，坏行跳过 %d 条' % (len(rows), bad))
    # 按时间排序（rowid 顺序近似时间序，但坏页跳过后仍重排一次更稳）
    rows.sort(key=lambda r: (r[1] or 0, r[0]))
    return rows, bad


def open_clear_db():
    db = cfg.qq_clear()
    if not os.path.exists(db):
        raise SystemExit(
            '剥头库不存在：%s\n'
            '  → 先跑 python scripts/qq_strip_header.py' % db)
    key = cfg.qq_key()
    con = sqlcipher3.connect(db, isolation_level=None)
    con.execute('PRAGMA cipher_page_size = 4096;')
    con.execute('PRAGMA key = "%s";' % key)
    con.execute('PRAGMA kdf_iter = 4000;')
    con.execute('PRAGMA cipher_hmac_algorithm = HMAC_SHA1;')
    con.execute('PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;')
    return con


def bj(ts):
    try:
        return datetime.datetime.fromtimestamp(int(ts), TZ).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return '?'


def main():
    ap = argparse.ArgumentParser(description='按人导出某群发言 + 上下文（重叠合并）')
    ap.add_argument('--group', required=True, help='群号（40027）')
    ap.add_argument('--uin', required=True, help='目标 QQ 号（40033）')
    ap.add_argument('--ctx', type=int, default=5, help='前后各几条上下文，默认 5')
    ap.add_argument('--out', help='输出文件；缺省写到 cfg.home 下')
    ap.add_argument('--max-gap', type=int, default=0,
                    help='相邻区间间隔 <= 此值时也合并，默认 0（仅合并重叠/相接）')
    ap.add_argument('--limit', type=int, default=0,
                    help='只处理前 N 条发言（按时间升序），0 = 全部')
    ap.add_argument('--force', action='store_true',
                    help='跳过输出规模检查，强制全量导出')
    args = ap.parse_args()

    group = int(args.group)
    uin = str(args.uin).strip()

    con = open_clear_db()
    try:
        rows, bad_rows = fetch_group_rows(con, group)
    finally:
        con.close()

    if not rows:
        print('❌ 群 %s 没有消息（群号对吗？）' % group)
        return 1

    print('群 %s 消息总数: %d%s'
          % (group, len(rows), ('（坏页跳过 %d 条）' % bad_rows) if bad_rows else ''))

    msgs = []
    blank = 0
    for rid, ts, sender, nick, card, b1, b2 in rows:
        txt = extract_text(b1, b2)
        if not txt:
            txt = '［图片/表情/非文本］'
            blank += 1
        msgs.append({
            'rid': rid, 'ts': ts,
            'uin': str(sender) if sender is not None else '',
            'name': (card or nick or '').strip() or ('QQ%s' % sender),
            'text': txt.replace('\n', ' ⏎ '),
        })

    hits = [i for i, m in enumerate(msgs) if m['uin'] == uin]
    print('目标 %s 发言: %d 条   非文本: %d 条' % (uin, len(hits), blank))
    if not hits:
        print('❌ 该群内没有此人的发言')
        return 1

    if args.limit and args.limit > 0 and len(hits) > args.limit:
        print('  按 --limit %d 截断（原 %d 条）' % (args.limit, len(hits)))
        hits = hits[:args.limit]

    # ---- 区间合并：这是「不重复计算」的核心 ----
    spans = []
    for i in hits:
        lo = max(0, i - args.ctx)
        hi = min(len(msgs) - 1, i + args.ctx)
        if spans and lo <= spans[-1][1] + 1 + args.max_gap:
            spans[-1] = (spans[-1][0], max(spans[-1][1], hi))
        else:
            spans.append((lo, hi))

    merged = sum(b - a + 1 for a, b in spans)
    naive = len(hits) * (2 * args.ctx + 1)
    print('上下文区间 %d 段：逐条展开 %d 条 -> 合并后 %d 条（省 %d 条重复）'
          % (len(spans), naive, merged, max(0, naive - merged)))

    # 规模保护：发言极多的活跃用户，上下文会撑出几十 MB。
    # 实测某个高活跃群里一人 66116 条发言 / ctx=4 -> 16.7 MB / 17 万行。
    if merged > 20000 and not args.force:
        print()
        print('⚠ 输出规模较大：%d 条（预计 %.1f MB）' % (merged, merged * 0.0001))
        print('  建议先缩小范围：')
        print('    --ctx 2            只留前后各 2 条')
        print('    --limit 500        只导前 500 条发言（时间升序）')
        print('    --force            确实要全量，跳过本检查')
        return 2

    if not args.out:
        outdir = cfg.outdir('qq')
        args.out = os.path.join(outdir, 'person_%s_group_%s_ctx%d.txt'
                                % (uin, group, args.ctx))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    hit_set = set(hits)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write('=== 群 %s 中 QQ %s 的发言 + 上下文 ===\n' % (group, uin))
        f.write('=== 消息总数 %d，目标发言 %d 条，上下文前后各 %d 条 ===\n'
                % (len(msgs), len(hits), args.ctx))
        f.write('=== 上下文区间 %d 段（重叠已合并，不重复输出）===\n' % len(spans))
        f.write('=== 时区 UTC+08:00   ▶ = 目标发言 ===\n\n')
        for si, (a, b) in enumerate(spans, 1):
            f.write('---------- 片段 %d/%d：%s ~ %s ----------\n'
                    % (si, len(spans), bj(msgs[a]['ts']), bj(msgs[b]['ts'])))
            for i in range(a, b + 1):
                m = msgs[i]
                mk = '▶' if i in hit_set else ' '
                f.write('%s [%s] %s: %s\n' % (mk, bj(m['ts']), m['name'], m['text']))
            f.write('\n')

    # ---- 自检：条数对不上就是有 bug ----
    body = open(args.out, encoding='utf-8').read()
    n_mark = body.count('\n▶')
    n_lines = sum(1 for ln in body.split('\n')
                  if re.match(r'^[▶ ] \[\d{4}-\d{2}-\d{2} ', ln))
    ok = (n_mark == len(hits) and n_lines == merged)
    print()
    print('核对: ▶ %d/%d  |  行 %d/%d  -> %s'
          % (n_mark, len(hits), n_lines, merged, 'PASS' if ok else '★FAIL'))
    print('输出: %s' % args.out)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
