#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从活库复制微信分片副本（含 wal/shm），供 wx_survey_all.py / wx_export_shards.py 使用。

为什么需要这个脚本：仓库里一直没有它。手册只写了「手工 tar 抽取」或「手动拷贝」，
于是用户 clone 后跑到微信这一步必然卡住——分片目录是空的，表现为
`各分片 Msg 表数: {}`、`有消息表的群: 0 个`，看起来像"密钥错了"，
实际只是**副本还没建**。

用法：
    python scripts/wx_copy_shards.py            # 复制全部分片 + contact
    python scripts/wx_copy_shards.py 0 1 2      # 只复制指定分片（抓单群时更快）

关于一致性：微信若正在运行，拷到的是可能处于中间状态的库（撕裂）。
这不影响源库安全，只影响"能看到多少条"——重跑一次即可。
要完全一致就先退出微信（但那样就没法用 wx_mem_scan.py 扫内存密钥了，
所以推荐顺序是：先扫密钥 → 再退微信 → 再拷分片）。
"""
import os
import shutil
import sys
import time

from trace_config import cfg

SHARD_COUNT = 7


def copy_with_sidecars(src, dst_dir):
    """复制一个库及其 -wal / -shm。返回 (文件名, 总字节数)；源不存在返回 None。"""
    if not os.path.exists(src):
        return None
    os.makedirs(dst_dir, exist_ok=True)
    total = 0
    for suffix in ('', '-wal', '-shm'):
        s = src + suffix
        if not os.path.exists(s):
            continue
        d = os.path.join(dst_dir, os.path.basename(s))
        shutil.copy2(s, d)
        total += os.path.getsize(d)
    return os.path.basename(src), total


def main():
    want = set(sys.argv[1:])
    root = cfg.wx_db_storage()
    if not os.path.isdir(root):
        sys.stderr.write('[中止] 找不到微信 db_storage：%s\n'
                         '  → 检查 config.json 的 wx_data_root / wx_account 是否指对\n' % root)
        sys.exit(2)

    t0 = time.time()
    copied = 0

    for i in range(SHARD_COUNT):
        if want and str(i) not in want:
            continue
        src = os.path.join(root, 'message', 'message_%d.db' % i)
        # 目标结构必须和脚本里读的路径一致：<shard_dir>/<account>/db_storage/message/
        dst = os.path.join(cfg.wx_shard_dir(i), cfg.wx_account, 'db_storage', 'message')
        r = copy_with_sidecars(src, dst)
        if r is None:
            print('message_%d.db  源不存在，跳过' % i)
            continue
        copied += 1
        print('message_%d.db  %7.1f MB -> %s' % (i, r[1] / 1048576.0, dst))

    # contact 库（导出时用来把 real_sender_id 映射成昵称）
    src = os.path.join(root, 'contact', 'contact.db')
    dst = os.path.join(cfg.wx_shard_dir(0), cfg.wx_account, 'db_storage', 'contact')
    r = copy_with_sidecars(src, dst)
    if r:
        print('contact.db     %7.1f MB -> %s' % (r[1] / 1048576.0, dst))
    else:
        print('contact.db     源不存在（昵称映射会缺失，导出仍能跑）')

    print('\n完成：%d 个分片，耗时 %.1fs' % (copied, time.time() - t0))
    if copied == 0:
        sys.stderr.write('[警告] 一个分片都没复制到，后面几步会读到空表\n')
        sys.exit(2)


if __name__ == '__main__':
    main()
