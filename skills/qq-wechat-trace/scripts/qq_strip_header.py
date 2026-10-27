import os, shutil, sys, time
from trace_config import cfg
SRC = cfg.qq_db()
DST = cfg.qq_clear()
HDR = 1024
# 安全闸：DST 绝不能等于 SRC，也绝不能落在源库所在目录**或其任意子目录**里。
# 否则下面那句 os.remove(DST) 有可能删到活库——源数据没有备份，删了就没了。
_src_abs = os.path.abspath(SRC)
_dst_abs = os.path.abspath(DST)
_src_dir = os.path.dirname(_src_abs)
if _dst_abs == _src_abs:
    sys.stderr.write('[中止] 剥头目标与源库是同一个文件：%s\n' % DST)
    sys.exit(2)
if _dst_abs == _src_dir or _dst_abs.startswith(_src_dir + os.sep):
    sys.stderr.write('[中止] 剥头目标落在源库所在目录（或其子目录）内，拒绝写入：\n'
                     '  源库目录: %s\n  剥头目标: %s\n'
                     '  → 请把 config.json 的 home 指到别的盘/目录，不要把临时副本放回源库旁边。\n'
                     % (_src_dir, DST))
    sys.exit(2)
if not os.path.exists(SRC):
    sys.stderr.write('[中止] 找不到 QQ 源库：%s\n'
                     '  → 检查 config.json 的 qq_data_root / qq_uin 是否指对了盘和账号\n'
                     '  → 若 QQ 正在运行，源库可能被独占锁；先完全退出 QQ\n' % SRC)
    sys.exit(2)

if os.path.exists(DST):
    print('目标已存在，先删: %s (%.1f GB)' % (DST, os.path.getsize(DST) / 1073741824.0))
    os.remove(DST)
t0 = time.time()
with open(SRC, 'rb') as fi, open(DST, 'wb') as fo:
    fi.seek(HDR)
    shutil.copyfileobj(fi, fo, length=16 * 1024 * 1024)
sz = os.path.getsize(DST)
print('剥头完成: %s' % DST)
print('  源 %.2f GB -> 目标 %.2f GB (应恰好差 1024 字节)' % (os.path.getsize(SRC) / 1073741824.0, sz / 1073741824.0))
print('  差值 = %d 字节' % (os.path.getsize(SRC) - sz))
print('  耗时 %.0f 秒' % (time.time() - t0))
