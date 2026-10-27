#!/usr/bin/env python3
# 盐匹配：读每个 .db 文件头 16 字节（SQLCipher 盐），与扫描到的密钥配对
import os, json, sys
from trace_config import cfg

ROOT = cfg.wx_db_storage()
KEYS = os.path.join(cfg.keys_dir, 'wechat_keys.json')
if not os.path.exists(KEYS):
    sys.stderr.write('[中止] 找不到全量密钥文件：%s\n'
                     '  → 先跑 Step 2：python scripts/wx_mem_scan.py（微信必须保持运行，\n'
                     '    密钥只存在于进程内存里，关掉微信就扫不到了）\n' % KEYS)
    sys.exit(2)
if not os.path.isdir(ROOT):
    sys.stderr.write('[中止] 找不到微信 db_storage 目录：%s\n'
                     '  → 检查 config.json 的 wx_data_root / wx_account 是否指对\n' % ROOT)
    sys.exit(2)


data = json.load(open(KEYS, encoding='utf-8'))
keys = data['keys']
by_salt = {k['salt'].lower(): k for k in keys}

dbs = []
for dirpath, _, files in os.walk(ROOT):
    for f in files:
        if f.endswith('.db') and not f.endswith('-wal') and not f.endswith('-shm'):
            dbs.append(os.path.join(dirpath, f))

covered, missing = [], []
for p in sorted(dbs):
    try:
        with open(p, 'rb') as fh:
            head = fh.read(16)
        if len(head) < 16:
            missing.append((p, '文件太小'))
            continue
        salt = head.hex()
        if salt in by_salt:
            covered.append((p, by_salt[salt]['enc']))
        else:
            missing.append((p, salt))
    except Exception as e:
        missing.append((p, f'读取失败: {e}'))

print(f'=== 覆盖情况：{len(covered)}/{len(dbs)} 个库有密钥 ===')
for p, enc in covered:
    print(f'  [OK] {os.path.relpath(p, ROOT)}  key={enc[:16]}...')
print(f'\n=== 未覆盖 {len(missing)} 个（需要点开对应聊天后再扫）===')
for p, info in missing:
    print(f'  [--] {os.path.relpath(p, ROOT)}  salt={info if isinstance(info, str) and len(info) < 40 else info}')

out = {os.path.relpath(p, ROOT): {'key': enc, 'salt': bytes.fromhex(open(p, 'rb').read(16).hex()).hex()} for p, enc in covered}
with open(cfg.wx_keymap(), 'w', encoding='utf-8') as fp:
    json.dump(out, fp, ensure_ascii=False, indent=2)
print('\n映射表 -> db_key_map.json')
