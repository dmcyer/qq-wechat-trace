import sqlcipher3, json, hashlib, os, datetime, sys
from trace_config import cfg
B = cfg.keys_dir
KEYMAP = json.load(open(cfg.wx_keymap(), encoding="utf-8"))
SHARD_COUNT = 7  # 分片库数量，需与 wx_copy_shards.py 保持一致
EXPORTED = set(cfg.groups('wx'))


def openc(i):
    rel = "message\\message_%d.db" % i
    # 先确认文件存在再取密钥（原顺序会让"跳过"分支不可达）
    p = os.path.join(cfg.wx_shard_dir(i), cfg.wx_account, 'db_storage', 'message', 'message_%d.db' % i)
    if not os.path.exists(p):
        return None
    info = KEYMAP.get(rel)
    if not info:
        return None
    c = sqlcipher3.connect(p, isolation_level=None)
    c.execute("PRAGMA cipher_page_size = 4096;")
    c.execute('PRAGMA key = "%s";' % ("x'%s%s'" % (info["key"], info["salt"])))
    return c


def ts(t):
    return (datetime.datetime.fromtimestamp(t, datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


# 群名
nick = {}
cdir = os.path.join(cfg.wx_db_storage(), 'contact', 'contact.db')
if not os.path.exists(cdir):
    sys.stderr.write('[中止] 找不到 contact 库：%s\n'
                     '  → 检查 config.json 的 wx_data_root / wx_account 是否指对\n' % cdir)
    sys.exit(2)
ci = KEYMAP.get("contact\\contact.db")
if not ci:
    sys.stderr.write('[中止] 密钥映射里没有 contact\\contact.db\n'
                     '  → 先跑 Step 2：python scripts/wx_mem_scan.py 重新生成密钥\n')
    sys.exit(2)
cc = sqlcipher3.connect(cdir, isolation_level=None)
cc.execute("PRAGMA cipher_page_size = 4096;")
cc.execute('PRAGMA key = "%s";' % ("x'%s%s'" % (ci["key"], ci["salt"])))
for u, n in cc.execute("SELECT username, nick_name FROM contact WHERE username LIKE '%@chatroom'"):
    nick[u] = n or ""
cc.close()

# 群名单直接从 contact 表生成（原来读外部文件 wx_all_rooms.txt，
# 那是本地中间产物、不随仓库走，公开版跑到这里必然 FileNotFoundError。
# contact 表里本来就有全部 @chatroom，没必要依赖外部文件。）
rooms = list(nick.keys())
print("微信群总数: %d（其中有名字的 %d）" % (len(rooms), sum(1 for r in rooms if nick.get(r))), flush=True)

# 每个库里有哪些 Msg_ 表
tabs = {}
for i in range(SHARD_COUNT):
    c = openc(i)
    if not c:
        continue
    tabs[i] = set(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"))
    c.close()
print("各分片 Msg 表数: %s" % {i: len(tabs[i]) for i in tabs}, flush=True)

found, missing = [], []
for r in rooms:
    h = "Msg_" + hashlib.md5(r.encode()).hexdigest()
    dbs = [i for i in tabs if h in tabs[i]]
    if not dbs:
        missing.append(r)
        continue
    tot, txt, mn, mx = 0, 0, None, None
    for i in dbs:
        c = openc(i)
        t, x, a, b = c.execute('SELECT count(*), sum(CASE WHEN local_type=1 THEN 1 ELSE 0 END), '
                               'min(create_time), max(create_time) FROM "%s"' % h).fetchone()
        tot += t or 0; txt += x or 0
        if a: mn = a if mn is None else min(mn, a)
        if b: mx = b if mx is None else max(mx, b)
        c.close()
    found.append((r, tot, txt, mn, mx, len(dbs)))

found.sort(key=lambda x: -x[1])
print("")
print("=" * 96)
print("有消息表的群: %d 个 / 无消息表(未加载过): %d 个" % (len(found), len(missing)))
print("")
print("%-16s %-22s %9s %9s %8s  %-16s %s" % ("群号", "群名", "全类型", "文本", "分片数", "最早", "是否已导出"))
print("-" * 96)
for r, tot, txt, mn, mx, nd in found[:45]:
    num = r.split("@")[0]
    nm = nick.get(r, "")[:20] or "(无名)"
    flag = "YES" if num in EXPORTED else "** 未导出 **"
    print("%-16s %-22s %9d %9d %8d  %-16s %s" % (num, nm, tot, txt, nd, ts(mn)[:10] if mn else "-", flag))
print("-" * 96)
print("有消息表但未导出的群: %d 个" % sum(1 for f in found if f[0].split('@')[0] not in EXPORTED))
print("无消息表的群: %d 个（本机微信从未加载过这些会话，需在微信里点开）" % len(missing))
