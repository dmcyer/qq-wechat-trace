import sqlcipher3, json, os, time
from trace_config import cfg
B = cfg.keys_dir
KEYMAP = json.load(open(cfg.wx_keymap(), encoding="utf-8"))
WORKDIRS = {0: "new_00", 1: "new_10", 2: "new_2", 3: "new_3", 4: "new_4", 5: "new_5", 6: "new_6"}
for i in sorted(WORKDIRS):
    rel = "message\\message_%d.db" % i
    p = os.path.join(cfg.wx_shard_dir(i), cfg.wx_account, 'db_storage', 'message', 'message_%d.db' % i)
    if not os.path.exists(p):
        print("message_%d.db  副本不存在，跳过" % i)
        continue
    # 取密钥要放在存在性检查之后：原来写在前面，分片不在映射里时直接 KeyError 崩溃，
    # 上面那个"跳过"分支永远保护不到它
    info = KEYMAP.get(rel)
    if not info:
        print("message_%d.db  不在密钥映射里，跳过" % i)
        continue
    t0 = time.time()
    c = sqlcipher3.connect(p, isolation_level=None)
    c.execute("PRAGMA cipher_page_size = 4096;")
    c.execute('PRAGMA key = "%s";' % ("x'%s%s'" % (info["key"], info["salt"])))
    rows = c.execute("PRAGMA integrity_check").fetchall()
    bad = [r[0] for r in rows if r[0] != 'ok']
    print("message_%d.db  %7.1f MB  integrity_check=%s  (%.0fs)"
          % (i, os.path.getsize(p) / 1048576.0, ("!!! %d 处问题" % len(bad)) if bad else "ok", time.time() - t0), flush=True)
    if bad:
        for b in bad[:10]:
            print("    " + b)
    c.close()
print("全部完成")
