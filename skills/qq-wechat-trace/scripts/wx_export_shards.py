#!/usr/bin/env python3
# 微信群文本消息全量导出 v2 —— 合并全部分片库（修正"首次命中即锁定"的漏数据 bug）
# 用法: python wx_export_shards.py <群号> [群号 ...]
# 数据源: 从 09-23 快照抽出的各分片副本（含 wal/shm），只读，不碰活库
import sqlcipher3, json, os, sys, hashlib, datetime, time, re
from trace_config import cfg

B = cfg.keys_dir
KEYMAP = json.load(open(cfg.wx_keymap(), encoding="utf-8"))
OUTDIR = cfg.outdir("wx")
WORKDIRS = {0: "new_00", 1: "new_10", 2: "new_2", 3: "new_3", 4: "new_4", 5: "new_5", 6: "new_6"}
SHARDS = list(WORKDIRS.keys())

TYPE_NAMES = {1: '文本', 3: '图片', 34: '语音', 43: '视频', 47: '表情', 48: '位置', 49: '链接/文件', 42: '名片',
              50: '通话', 10000: '系统提示', 244813135921: '复合类型A', 21474836529: '复合类型B'}
PREFIX = re.compile(r'^([A-Za-z0-9_\-@\.]{1,64}):[ \t]*\r?\n(.*)$', re.S)


def ts(t):
    return (datetime.datetime.fromtimestamp(t, datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')


def log(m):
    print('[' + ts(int(time.time())) + '] ' + m, flush=True)


def db_path(i):
    p = os.path.join(cfg.wx_shard_dir(i), cfg.wx_account, 'db_storage', 'message', 'message_%d.db' % i)
    return p if os.path.exists(p) else None


def openc(i):
    rel = "message\\message_%d.db" % i
    # 顺序很重要：先查文件存在，再取密钥（映射里没有的分片应跳过，不该 KeyError）
    p = db_path(i)
    if not p:
        return None
    info = KEYMAP.get(rel)
    if not info:
        print('  message_%d.db 不在密钥映射里，跳过' % i)
        return None
    c = sqlcipher3.connect(p, isolation_level=None)
    c.execute("PRAGMA cipher_page_size = 4096;")
    c.execute('PRAGMA key = "%s";' % ("x'%s%s'" % (info["key"], info["salt"])))
    return c


def load_contacts():
    nick, wx2nick = {}, {}
    cdir = os.path.join(cfg.wx_db_storage(), 'contact', 'contact.db')
    import sys as _sys
    if not os.path.exists(cdir):
        _sys.stderr.write('[中止] 找不到 contact 库：%s\n'
                          '  → 先把 contact.db 副本准备好（见手册 ④）\n' % cdir)
        _sys.exit(2)
    info = KEYMAP.get("contact\\contact.db")
    if not info:
        _sys.stderr.write('[中止] 密钥映射里没有 contact\\contact.db\n'
                          '  → 先跑 Step 2：python wx_mem_scan.py 重新生成密钥\n')
        _sys.exit(2)
    c = sqlcipher3.connect(cdir, isolation_level=None)
    c.execute("PRAGMA cipher_page_size = 4096;")
    c.execute('PRAGMA key = "%s";' % ("x'%s%s'" % (info["key"], info["salt"])))
    for r in c.execute('SELECT id, username, alias, nick_name FROM contact'):
        nick[r[0]] = (r[1], r[3] or r[1])
        if r[3]:
            wx2nick[r[1]] = r[3]
            if r[2]:
                wx2nick[r[2]] = r[3]
    c.close()
    return nick, wx2nick


nick, wx2nick = load_contacts()
log('contact 昵称映射: %d 条' % len(nick))
os.makedirs(OUTDIR, exist_ok=True)
ROOMS = {a: a + '@chatroom' for a in sys.argv[1:]}
H = {q: 'Msg_' + hashlib.md5((q + '@chatroom').encode()).hexdigest() for q in ROOMS}

for q, room in ROOMS.items():
    h = H[q]
    rows = []
    type_counter = {}
    used_shards = []
    for i in SHARDS:
        c = openc(i)
        if not c:
            continue
        ex = c.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?", (h,)).fetchone()[0]
        if not ex:
            c.close()
            continue
        for t, n in c.execute('SELECT local_type, COUNT(*) FROM "%s" GROUP BY local_type' % h).fetchall():
            type_counter[t] = type_counter.get(t, 0) + n
        # 逐行取（只取文本 + 时间），用 rowid 分页避免一次全读
        cur = c.execute('SELECT create_time, local_id, real_sender_id, message_content FROM "%s" '
                        'WHERE local_type=1 ORDER BY create_time, local_id' % h)
        n0 = 0
        for ct, lid, sid, content in cur:
            if content is None:
                continue
            rows.append((ct, lid, sid, str(content)))
            n0 += 1
        c.close()
        used_shards.append('message_%d.db:%d' % (i, n0))
    rows.sort(key=lambda x: (x[0], x[1]))
    senders = {}
    n_pref = 0
    lines = []
    for ct, lid, sid, content in rows:
        m = PREFIX.match(content)
        if m:
            n_pref += 1
            sender = wx2nick.get(m.group(1), m.group(1))
            text = m.group(2)
        else:
            s = nick.get(sid)
            sender = (s[1] if s else ('uid%d' % sid)) + '(?)'
            text = content
        senders[sender] = senders.get(sender, 0) + 1
        lines.append(ts(ct) + ' | ' + sender + ': ' + text.replace('\r', '').replace('\n', ' ⏎ '))
    type_str = ', '.join('%s:%d' % (TYPE_NAMES.get(t, str(t)), n) for t, n in
                         sorted(type_counter.items(), key=lambda x: -x[1]) if t != 1)
    top = ', '.join('%s(%d)' % (k, v) for k, v in sorted(senders.items(), key=lambda x: -x[1])[:5])
    head = [
        '=== 导出元信息 ===',
        '群号: ' + room,
        '导出时间: ' + ts(int(time.time())) + ' (北京时间 UTC+8)',
        '文本消息数: ' + str(len(lines)),
        '来源: 本地离线快照（wx_db_backup_<日期>_db_storage.tar 或 wx_copy_shards 副本；非 API）',
        '最早时间: ' + (ts(rows[0][0]) + ' (北京)' if rows else '?'),
        '最晚时间: ' + (ts(rows[-1][0]) + ' (北京)' if rows else '?'),
        '时间跨度: ' + ('%.2f 天' % ((rows[-1][0] - rows[0][0]) / 86400) if rows else '?'),
        '分片来源: ' + (' + '.join(used_shards) if used_shards else '无'),
        '发送者来源: 内容内置wxid前缀(%d条) / real_sender_id映射(%d条,带(?)标记)' % (n_pref, len(lines) - n_pref),
        '非文本消息: ' + (type_str if type_str else '无'),
        '活跃发送者Top5: ' + (top if top else '?'),
        '发送者说明: 昵称取自 contact 表（微信全局昵称，群名片可能不同）；(?)为无前缀消息按id推测',
        '时间说明: 北京时间(UTC+8)；换行以 ⏎ 标记',
        '=== 正文 ===',
    ]
    f = os.path.join(OUTDIR, 'wx_' + q + '.txt')
    with open(f, 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(head) + '\n')
        fp.write('\n'.join(lines) + '\n')
    log('[OK] %s 文本 %d 条, 时间 %s ~ %s, 分片 %s, 文件 %.1f KB' % (
        q, len(lines), ts(rows[0][0]) if rows else '?', ts(rows[-1][0]) if rows else '?',
        '+'.join(used_shards), os.path.getsize(f) / 1024.0))
log('全部完成 -> ' + OUTDIR)
