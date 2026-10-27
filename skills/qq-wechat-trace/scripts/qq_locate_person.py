#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 QQ 号定位：这个人在哪些群发过言？群名是什么？

用法：
    python scripts/qq_locate_person.py <目标QQ号>
    python scripts/qq_locate_person.py <目标QQ号> --ai-only

为什么需要这个脚本（别人的工具没有这个能力）：
  * chatlog-keeper 能整库导出、能查会话列表，但**没有「输入一个 QQ 号，
    告诉你在哪些群」的入口**。要自己拼三条映射：
        profile_info_v6.1002 (QQ号) -> 1000 (uid)
        group_member3.1000  (uid)  -> 60001 (群号)
        group_detail_info_ver1.60001 -> 60007 (群名)
  * 本脚本把这三步封装起来，并额外给出「该号在这些群的发言条数」。

★ 只用 aux 库（group_info.db / profile_info.db），**不碰 24GB 的 nt_msg.db**。
  两个 aux 库都带 1024 字节 NTQQ 头，SQLCipher 无法直接吸收，
  所以复制到临时目录去头后再读（不动原库）。
"""
import argparse
import os
import shutil
import sys
import tempfile

import sqlcipher3

from trace_config import cfg

HDR = 1024
AUX = {
    'group': 'group_info.db',
    'profile': 'profile_info.db',
}


def open_aux(which):
    """复制指定 aux 库到临时目录、去掉 1024 头，返回只读连接。

    返回 (connection, temp_path)；调用方负责 close + 删除 temp_path。
    """
    src = os.path.join(cfg.qq_db_dir(), AUX[which])
    if not os.path.exists(src):
        raise SystemExit('找不到 %s：%s' % (AUX[which], src))

    tmpdir = tempfile.mkdtemp(prefix='qqt_aux_')
    dst = os.path.join(tmpdir, AUX[which])
    with open(src, 'rb') as fi:
        fi.seek(HDR)
        with open(dst, 'wb') as fo:
            shutil.copyfileobj(fi, fo, 1024 * 1024)

    key = cfg.qq_key()
    con = sqlcipher3.connect(dst)
    con.execute('PRAGMA cipher_page_size = 4096;')
    con.execute('PRAGMA key = "%s";' % key)
    con.execute('PRAGMA kdf_iter = 4000;')
    con.execute('PRAGMA cipher_hmac_algorithm = HMAC_SHA1;')
    con.execute('PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;')
    return con, tmpdir


def main():
    ap = argparse.ArgumentParser(description='按 QQ 号定位其所在的群')
    ap.add_argument('uin', help='目标 QQ 号')
    ap.add_argument('--ai-only', action='store_true', help='只显示群名含 ai 的')
    ap.add_argument('--with-count', action='store_true',
                    help='同时统计该号在各群的发言条数（需读 nt_msg.db，较慢）')
    args = ap.parse_args()

    target = str(args.uin).strip()

    # ---- 1. QQ 号 -> uid / 昵称 ----
    con, tmp = open_aux('profile')
    try:
        cols = [r[1] for r in con.execute('PRAGMA table_info(profile_info_v6)')]
        if not cols:
            raise SystemExit('profile_info_v6 表不存在')
        row = con.execute(
            'SELECT "1002","1000","20002","20003" FROM profile_info_v6 '
            'WHERE "1002" = ? LIMIT 1', (target,)).fetchone()
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)

    if not row:
        print('❌ 本机库里没有 QQ 号 %s 的资料' % target)
        print('   可能：不在你的好友/群成员范围内，或从未与你同群')
        return 1

    qq_no, uid, nick, _ = row
    print('QQ 号  : %s' % qq_no)
    print('昵称   : %s' % (nick or '(空)'))
    print('uid    : %s' % uid)
    print()

    # ---- 2. uid -> 群号 -> 群名 ----
    con, tmp = open_aux('group')
    try:
        gids = [r[0] for r in con.execute(
            'SELECT "60001" FROM group_member3 WHERE "1000" = ?', (uid,))]
        name_map = {g: (n or '').strip() for g, n in con.execute(
            'SELECT "60001","60007" FROM group_detail_info_ver1')}
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)

    if not gids:
        print('未在任何群成员表里找到该 uid')
        return 1

    items = [(g, name_map.get(g, '(无群名)')) for g in gids]
    if args.ai_only:
        items = [(g, n) for g, n in items if 'ai' in n.lower()]

    print('=== 所在群: %d 个 ===' % len(items))
    for g, n in items:
        print('  %-14s %s' % (g, n))

    # ---- 3. 可选：统计发言条数 ----
    if args.with_count:
        print()
        print('=== 各群发言条数 ===')
        db = cfg.qq_clear()
        if not os.path.exists(db):
            print('  ⚠ 剥头库不存在，跳过计数：%s' % db)
            print('  → 先跑 python scripts/qq_strip_header.py')
            return 0
        key = cfg.qq_key()
        c2 = sqlcipher3.connect(db, isolation_level=None)
        c2.execute('PRAGMA cipher_page_size = 4096;')
        c2.execute('PRAGMA key = "%s";' % key)
        c2.execute('PRAGMA kdf_iter = 4000;')
        c2.execute('PRAGMA cipher_hmac_algorithm = HMAC_SHA1;')
        c2.execute('PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;')
        for g, n in items:
            try:
                cnt = c2.execute(
                    'SELECT count(*) FROM group_msg_table '
                    'WHERE "40027" = ? AND "40033" = ?', (g, target)).fetchone()[0]
            except Exception:
                cnt = -1
            if cnt:
                print('  %-14s %-40s %d 条' % (g, n[:38], cnt))
        c2.close()

    return 0


if __name__ == '__main__':
    sys.exit(main())
