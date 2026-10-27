#!/usr/bin/env python3
# 损坏群恢复导出：索引枚举 rowid -> 分批点读 -> 失败才二分定位坏行
# 为什么不能按 40003 分批扫：该群只有极少数行（实测 2 行）的表数据页损坏，
#   但任何 ORDER BY "40003" 的批量语句一碰到坏行就整条中止 -> 旧工具整块跳过 5136 个序号，
#   白白丢掉 1625 条完好消息。
# 本法只依赖「索引可枚举 rowid」+「坏行可按 rowid 单独跳过」，与损坏位置无关。
import sqlcipher3, datetime, time, json, os, sys
from trace_config import cfg

CLEAR = cfg.qq_clear()
KEY = open(cfg.qq_key_file(), encoding='utf-8').read().strip()
STATE = os.path.join(cfg.home, 'qq_export_state.json')
OUTDIR = cfg.outdir('qq')
# 群号属于个人信息，不做默认值；必须显式传入
if len(sys.argv) < 2:
    sys.stderr.write('用法: python qq_recover_by_rowid.py <群号>\n')
    sys.exit(2)
G = sys.argv[1]
COLS = '"40001","40003","40033","40050","40090","40093","40800"'
BATCH = 200


def ts_to_bj(t):
    return (datetime.datetime.fromtimestamp(t, datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')


def log(m):
    print('[' + ts_to_bj(int(time.time())) + '] ' + m, flush=True)


def rv(b, i):
    v, s = 0, 0
    while True:
        x = b[i]; i += 1
        v |= (x & 0x7F) << s
        if not (x & 0x80): break
        s += 7
    return v, i


def wire(b):
    i = 0
    while i < len(b):
        try:
            tag, i = rv(b, i)
            fn, wt = tag >> 3, tag & 7
            if wt == 0:
                v, i = rv(b, i); yield fn, 0, v
            elif wt == 2:
                ln, i = rv(b, i)
                yield fn, 2, b[i:i + ln]; i += ln
            elif wt == 5: yield fn, 5, b[i:i + 4]
            elif wt == 1: yield fn, 1, b[i:i + 8]
            else: return
        except Exception:
            return


TYPE_NAMES = {1: '文本', 2: '图片', 3: '文件', 4: '语音', 5: '视频', 6: '表情', 7: '回复', 8: '灰条',
              9: '红包', 10: 'Ark卡片', 11: '商城表情', 14: 'Markdown', 16: '合并转发', 17: '按钮', 21: '通话'}


def parse_content(b):
    ctype, text, face = None, '', ''
    for fn, wt, v in wire(b):
        if fn == 45002 and wt == 0: ctype = v
        elif fn == 45101 and wt == 2:
            try: text = v.decode('utf-8')
            except Exception: text = v.decode('utf-8', 'replace')
        elif fn == 47602 and wt == 2:
            try: face = v.decode('utf-8')
            except Exception: pass
    return ctype, text, face


def parse_msgbody(blob):
    if not blob: return ''
    parts = []
    for fn, wt, v in wire(blob):
        if fn == 40800 and wt == 2:
            ctype, text, face = parse_content(v)
            if ctype == 1 and text: parts.append(text)
            elif ctype == 6: parts.append(face or '[表情]')
            elif ctype == 11 and text: parts.append(text)
            elif ctype == 14 and text: parts.append(text)
            elif ctype in TYPE_NAMES: parts.append('[' + TYPE_NAMES[ctype] + ']')
            elif text: parts.append(text)
    return ' '.join(p for p in parts if p)


c = sqlcipher3.connect(CLEAR, isolation_level=None)
c.execute("PRAGMA cipher_page_size = 4096;")
c.execute("PRAGMA key = '%s';" % KEY)
c.execute("PRAGMA kdf_iter = 4000;")
c.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1;")
c.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;")
gid = int(G)
t0 = time.time()

# 1) 索引枚举全部 (rowid, 40003)，不碰表数据页
pairs = c.execute('SELECT rowid, "40003" FROM group_msg_table WHERE "40027"=?', (gid,)).fetchall()
log('索引枚举到 %d 行' % len(pairs))

parsed = []
nonText = 0
unreadable = []


def read_rows(rowids):
    """返回可读的行；不可读的 rowid 记入 unreadable"""
    global nonText
    if not rowids:
        return
    try:
        q = 'SELECT %s FROM group_msg_table WHERE rowid IN (%s)' % (COLS, ','.join('?' * len(rowids)))
        for r in c.execute(q, rowids).fetchall():
            ts = r[3]
            if ts is None: continue
            text = parse_msgbody(r[6])
            if not text:
                nonText += 1; continue
            parsed.append((ts, r[0], r[4] or r[5] or '?', text))
        return
    except Exception:
        pass
    if len(rowids) == 1:
        unreadable.append(rowids[0])
        return
    mid = len(rowids) // 2
    read_rows(rowids[:mid])
    read_rows(rowids[mid:])


rowids = [p[0] for p in pairs]
for i in range(0, len(rowids), BATCH):
    read_rows(rowids[i:i + BATCH])
    if (i // BATCH) % 200 == 0:
        log('  已处理 %d/%d，得文本 %d 条，不可读 %d，耗时 %.0fs'
            % (min(i + BATCH, len(rowids)), len(rowids), len(parsed), len(unreadable), time.time() - t0))

parsed.sort(key=lambda x: (x[0], x[1]))
log('读取完成：文本 %d 条，非文本 %d 条，真正不可读 %d 行' % (len(parsed), nonText, len(unreadable)))

state = {}
try: state = json.load(open(STATE, encoding='utf-8'))
except Exception: pass
info = state.get(G, {})
head = [
    '=== 导出元信息 ===',
    '群号: ' + G,
    '群名: ' + info.get('name', '?'),
    '人数: ' + str(info.get('members', '?')),
    '导出时间: ' + ts_to_bj(int(time.time())) + ' (北京时间 UTC+8)',
    '本批条数: ' + str(len(parsed)) + ' (本地活库全量，损坏行已按 rowid 逐个跳过)',
    '来源: 本地离线数据库 nt_msg_live_clear.db（活库剥头副本，非 API，无风控风险）',
    '最早时间: ' + (ts_to_bj(parsed[0][0]) + ' (北京)' if parsed else '?'),
    '最晚时间: ' + (ts_to_bj(parsed[-1][0]) + ' (北京)' if parsed else '?'),
    '时间跨度: ' + ('%.2f 天' % ((parsed[-1][0] - parsed[0][0]) / 86400) if parsed else '?'),
    '损坏情况: 全群 %d 行中，真正无法读取 %d 行；其余全部恢复（旧跳过式导出会多丢约 1600 条）'
    % (len(pairs), len(unreadable)),
    '不可读rowid: ' + (json.dumps(unreadable) if unreadable else '无'),
    '非文本消息: ' + str(nonText) + ' 条(无文本内容，未计入)',
    '时间说明: 所有时间均为北京时间(UTC+8)；第一批API导出文件为UTC，注意区分',
    '换行说明: 消息内含换行处以 ⏎ 标记',
    '媒体说明: 非文本消息以 [图片]/[语音]/[视频] 等标记保留时间线',
    '=== 正文 ===',
]
f = os.path.join(OUTDIR, 'qq_' + G + '.txt')
if os.path.exists(f):
    bak = f + '.bak-before-recovery'
    if os.path.exists(bak):
        os.remove(bak)
    os.rename(f, bak)
    log('覆盖前的版本已留底: ' + bak)
with open(f, 'w', encoding='utf-8') as fp:
    fp.write('\n'.join(head) + '\n')
    for ts, msgid, nick, text in parsed:
        fp.write(ts_to_bj(ts) + ' | ' + nick + ': ' + text.replace('\r', '').replace('\n', ' ⏎ ') + '\n')
log('[OK] %s: %d 条，耗时 %.0fs -> %s' % (G, len(parsed), time.time() - t0, f))
c.close()

