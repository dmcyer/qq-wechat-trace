import sqlcipher3, datetime, re
from trace_config import cfg
P = cfg.qq_clear()
KEY = open(cfg.qq_key_file(), encoding='utf-8').read().strip()
LIST = None   # 名单改为直接从库里生成
EXPORTED = set(cfg.groups('qq'))
c = sqlcipher3.connect(P, isolation_level=None)
c.execute("PRAGMA cipher_page_size = 4096;")
c.execute("PRAGMA key = '%s';" % KEY)
c.execute("PRAGMA kdf_iter = 4000;")
c.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1;")
c.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;")


def ts(t):
    return (datetime.datetime.fromtimestamp(t, datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


# 会话名单：直接从 recent_contact_v3_table 生成（40021=群号, 40094=群名）
rows = c.execute('SELECT "40021","40094" FROM recent_contact_v3_table').fetchall()
sessions = [(str(a or ''), str(b or '').strip()) for a, b in rows]
sessions = [(u, n) for u, n in sessions if u and not u.startswith('===')]
groups = [(u, n) for u, n in sessions if re.fullmatch(r'\d+', u)]
privs = [(u, n) for u, n in sessions if not re.fullmatch(r'\d+', u)]
print('名单: 群 %d 个, 私聊 %d 个' % (len(groups), len(privs)), flush=True)

# 私聊表的 peer 列名
cols = [r[1] for r in c.execute('PRAGMA table_info(c2c_msg_table)')]
print('c2c_msg_table 列: %s' % cols[:14], flush=True)

res = []
for i, (u, n) in enumerate(groups):
    try:
        r = c.execute('SELECT count(*), min("40050"), max("40050") FROM group_msg_table WHERE "40027"=?',
                      (int(u),)).fetchone()
        res.append((int(u), n, r[0], r[1], r[2]))
    except Exception as e:
        res.append((int(u), n, -1, None, None))
    if i % 100 == 0:
        print('  群进度 %d/%d' % (i + 1, len(groups)), flush=True)

ok = [r for r in res if r[2] > 0]
ok.sort(key=lambda x: -x[2])
print('')
print('=' * 100)
print('有消息的群: %d / %d；其中已导出 %d 个，未导出 %d 个'
      % (len(ok), len(groups), sum(1 for r in ok if str(r[0]) in EXPORTED), sum(1 for r in ok if str(r[0]) not in EXPORTED)))
print('')
print('%-12s %-30s %10s  %-16s %-16s %s' % ('群号', '群名', '条数', '最早', '最晚', '已导出'))
print('-' * 100)
for g, n, cnt, mn, mx in ok[:40]:
    nm = n[:28] or '(无名)'
    print('%-12s %-30s %10d  %-16s %-16s %s' % (g, nm, cnt, ts(mn)[:10] if mn else '-', ts(mx)[:10] if mx else '-',
                                                'YES' if str(g) in EXPORTED else '** 未导出 **'))
print('-' * 100)
un = sum(r[2] for r in ok if str(r[0]) not in EXPORTED)
ex = sum(r[2] for r in ok if str(r[0]) in EXPORTED)
print('未导出群消息合计: %d 条   |  已导出群消息合计: %d 条' % (un, ex))
c.close()
