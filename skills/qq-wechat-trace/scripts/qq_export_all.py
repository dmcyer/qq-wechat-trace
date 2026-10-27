#!/usr/bin/env python3
# QQ 全量导出 v2：按群走 40027 索引（群号=40027），不再全表扫描
import sqlcipher3, datetime, time, json, os
from trace_config import cfg

CLEAR = cfg.qq_clear()
KEY = open(cfg.qq_key_file(), encoding='utf-8').read().strip()
STATE = os.path.join(cfg.home, 'qq_export_state.json')
OUTDIR = cfg.outdir('qq')

TARGETS = list(cfg.groups('qq').keys())   # 群名单来自 config.json（属个人信息，不入库）

def ts_to_bj(t):
    return (datetime.datetime.fromtimestamp(t, datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')

def log(msg):
    print('[' + ts_to_bj(int(time.time())) + '] ' + msg, flush=True)

# ---------- protobuf ----------
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
                ln, i = rv(b, i); yield fn, 2, b[i:i+ln]; i += ln
            elif wt == 5: yield fn, 5, b[i:i+4]; i += 4
            elif wt == 1: yield fn, 1, b[i:i+8]; i += 8
            else: return
        except Exception:
            return

TYPE_NAMES = {1:'文本',2:'图片',3:'文件',4:'语音',5:'视频',6:'表情',7:'回复',8:'灰条',9:'红包',
              10:'Ark卡片',11:'商城表情',14:'Markdown',16:'合并转发',17:'按钮',21:'通话'}

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

def connect():
    c = sqlcipher3.connect(CLEAR, isolation_level=None)
    c.execute("PRAGMA cipher_page_size = 4096;")
    c.execute("PRAGMA key = '%s';" % KEY)
    c.execute("PRAGMA kdf_iter = 4000;")
    c.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1;")
    c.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;")
    return c

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    state = {}
    try: state = json.load(open(STATE, encoding='utf-8'))
    except Exception: pass
    con = connect()

    for g in TARGETS:
        t0 = time.time()
        info = state.get(g, {})
        try:
            rows = con.execute(
                'SELECT "40001","40033","40050","40090","40093","40800" FROM group_msg_table WHERE "40027"=? ORDER BY "40003" ASC',
                (int(g),)).fetchall()
        except Exception as e:
            log('!! %s 索引查询失败: %s（该群数据页可能损坏，跳过）' % (g, str(e)[:80]))
            continue

        parsed = []
        nonText = 0
        for r in rows:
            ts = r[2]
            if ts is None: continue
            text = parse_msgbody(r[5])
            if not text: nonText += 1; continue
            parsed.append((ts, r[0], r[3] or r[4] or '?', text))
        parsed.sort(key=lambda x: (x[0], x[1]))

        name = info.get('name', '?')
        members = info.get('members', '?')
        head = [
            '=== 导出元信息 ===',
            '群号: ' + g,
            '群名: ' + name,
            '人数: ' + str(members),
            '导出时间: ' + ts_to_bj(int(time.time())) + ' (北京时间 UTC+8)',
            '本批条数: ' + str(len(parsed)) + ' (本地库全量，含媒体标记消息)',
            '来源: 本地离线数据库 nt_msg_clear.db（非 API 拉取，无腾讯风控风险）',
        ]
        if parsed:
            first, lastm = parsed[0], parsed[-1]
            head += [
                '最早时间: ' + ts_to_bj(first[0]) + ' (北京)',
                '最晚时间: ' + ts_to_bj(lastm[0]) + ' (北京)',
                '时间跨度: ' + ('%.2f' % ((lastm[0] - first[0]) / 86400)) + ' 天',
                '最早 msgid: ' + str(first[1]),
                '最晚 msgid: ' + str(lastm[1]),
            ]
        head += [
            '非文本消息: ' + str(nonText) + ' 条(无文本内容，未计入)',
            '时间说明: 所有时间均为北京时间(UTC+8)；第一批API导出文件为UTC，注意区分',
            '换行说明: 消息内含换行处以 ⏎ 标记',
            '媒体说明: 非文本消息以 [图片]/[语音]/[视频] 等标记保留时间线',
            '=== 正文 ==='
        ]
        f = os.path.join(OUTDIR, 'qq_' + g + '.txt')
        with open(f, 'w', encoding='utf-8') as fp:
            fp.write('\n'.join(head) + '\n')
            for ts, msgid, nick, text in parsed:
                fp.write(ts_to_bj(ts) + ' | ' + nick + ': ' + text.replace('\r', '').replace('\n', ' ⏎ ') + '\n')
        log('[OK] %s %s: %d 条 (非文本 %d)，耗时 %.0fs -> %s' % (g, name[:20], len(parsed), nonText, time.time() - t0, f))

    log('全部完成')
    con.close()

if __name__ == '__main__':
    main()


