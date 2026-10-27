import sqlcipher3, datetime, os, json, sys
from trace_config import cfg
DB = cfg.qq_clear()
KEY = open(cfg.qq_key_file(), encoding='utf-8').read().strip()
OUT = cfg.outdir('qq')
GROUPS = [(g,) for g in cfg.groups('qq')]
con = sqlcipher3.connect(DB, isolation_level=None)
con.execute("PRAGMA cipher_page_size = 4096;")
con.execute("PRAGMA key = '%s';" % KEY)
con.execute("PRAGMA kdf_iter = 4000;")
con.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1;")
con.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;")

# 没有配置任何群时必须明确失败，不能输出空表还退出 0（静默通过）
if not GROUPS:
    sys.stderr.write('[对账失败] config.json 的 groups.qq 是空的\n')
    sys.stderr.write('  → 把要核对的群号填进 config.json，例如 [["<群号>", "<群名>"]]\n')
    sys.exit(2)
print("")


def ts(t):
    return (datetime.datetime.fromtimestamp(t, datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def exported_count(g):
    p = os.path.join(OUT, "qq_%s.txt" % g)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        for line in f:
            if line.startswith("本批条数:"):
                return int(line.split("条数:")[1].split("(")[0].strip())
            if line.startswith("最早时间:"):
                return "最早=" + line.split("最早时间:")[1].split("(北京)")[0].strip()
    return None


for (g,) in GROUPS:
    line = "%-12s " % g
    try:
        n, mn, mx, nulls = con.execute(
            'SELECT count(*), min("40050"), max("40050"), sum(CASE WHEN "40050" IS NULL THEN 1 ELSE 0 END) FROM group_msg_table WHERE "40027"=?',
            (int(g),)).fetchone()
        line += "行数=%-8d 空时间戳=%-6d 最早=%s 最晚=%s" % (n, nulls or 0, ts(mn) if mn else "-", ts(mx) if mx else "-")
    except Exception as e:
        line += "索引查询失败: %s" % str(e)[:50]
    ec = exported_count(g)
    line += "   | 导出文件: %s" % (ec if ec is not None else "无")
    print(line)
con.close()

