#!/usr/bin/env python3
# 微信密钥内存扫描器：扫 Weixin.exe 进程内存，抓 WCDB 缓存的裸密钥
# 模式（来自 wechat-decrypt-export 文档）：x'<64hex_enc_key><32hex_salt>'
# 同时兼容 ASCII 与 UTF-16LE 两种存储形态
import ctypes, re, sys, json, os
from trace_config import cfg

P_VM_READ = 0x0010
P_QUERY_LIMITED = 0x1000
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
RW = 0x02 | 0x04 | 0x08 | 0x20 | 0x40 | 0x80

k32 = ctypes.windll.kernel32

class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64),
                ("AllocationProtect", ctypes.c_uint32), ("pad1", ctypes.c_uint32),
                ("RegionSize", ctypes.c_uint64), ("State", ctypes.c_uint32),
                ("Protect", ctypes.c_uint32), ("Type", ctypes.c_uint32), ("pad2", ctypes.c_uint32)]

# ASCII: x'<64hex><32hex>'
RE_A = re.compile(rb"x'([0-9a-fA-F]{64})([0-9a-fA-F]{32})'")
# UTF-16LE: x \0 ' \0 <hex with \0 interleaved> ' \0
RE_U = re.compile(rb"(?:x\x00'\x00(?:[0-9a-fA-F]\x00){96}'\x00)")

def decode_utf16(m: bytes) -> str:
    return m.decode('utf-16le', errors='ignore')

def scan_pid(pid, out):
    h = k32.OpenProcess(P_VM_READ | P_QUERY_LIMITED, False, pid)
    if not h:
        print(f"pid {pid}: OpenProcess failed err={ctypes.get_last_error()}", file=sys.stderr)
        return 0
    addr = 0
    mbi = MBI()
    total = 0
    CHUNK = 4 * 1024 * 1024
    try:
        while addr < 0x7FFFFFFFFFFF:
            if k32.VirtualQueryEx(h, ctypes.c_uint64(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:
                break
            base, size, state, protect = mbi.BaseAddress, mbi.RegionSize, mbi.State, mbi.Protect
            if (state == MEM_COMMIT and protect != PAGE_NOACCESS and not (protect & PAGE_GUARD)
                    and (protect & RW) and 0 < size <= 200 * 1024 * 1024):
                off = 0
                while off < size:
                    n = min(CHUNK, size - off)
                    buf = ctypes.create_string_buffer(n)
                    got = ctypes.c_size_t(0)
                    if k32.ReadProcessMemory(h, ctypes.c_uint64(base + off), buf, n, ctypes.byref(got)) and got.value:
                        data = buf.raw[:got.value]
                        total += got.value
                        for m in RE_A.finditer(data):
                            out.add(('A', m.group(1).decode(), m.group(2).decode()))
                        for m in RE_U.finditer(data):
                            s = decode_utf16(m.group())
                            mm = re.match(r"x'([0-9a-fA-F]{64})([0-9a-fA-F]{32})'", s)
                            if mm:
                                out.add(('U', mm.group(1), mm.group(2)))
                    off += n
            nxt = base + size
            if nxt <= addr:
                break
            addr = nxt
    finally:
        k32.CloseHandle(h)
    return total

# 找 Weixin.exe 进程
import subprocess
def weixin_pids():
    pids = []
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Weixin.exe', '/FO', 'CSV', '/NH'],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith('INFO:'):
            continue
        parts = [p.strip('"') for p in line.split('","')]
        if parts and parts[0].lower() == 'weixin.exe':
            try: pids.append(int(parts[1]))
            except Exception: pass
    return pids

def main():
    pids = weixin_pids()
    print('Weixin pids:', pids, flush=True)
    if not pids:
        # 微信没开时不能说"扫不到就完了"——密钥是**持久**的，扫过一次就存在
        # wechat_keys.json 里，之后导数据根本不需要再扫（关着微信照样能解库）。
        # 所以要分清「本来就扫过」和「一次都没扫过」，给不同的下一步。
        keys_json = os.path.join(cfg.keys_dir, 'wechat_keys.json')
        keymap = os.path.join(cfg.keys_dir, 'wx_db_key_map.json')
        if os.path.exists(keys_json) and os.path.exists(keymap):
            try:
                n = json.load(open(keys_json, encoding='utf-8')).get('count', '?')
            except Exception:
                n = '?'
            sys.stderr.write(
                '[中止] 微信未运行，无法扫描内存。\n'
                '  → 但你已经扫过了（%s 里有 %s 个密钥，密钥映射也在），\n'
                '    **不需要重扫**，直接接着跑后面的导出步骤即可。\n'
                '    只有以下情况才需要重扫：换了微信账号 / 密钥映射缺了某个库 / 密钥文件丢了。\n'
                % (keys_json, n))
        else:
            sys.stderr.write(
                '[中止] 微信未运行，扫不到密钥。\n'
                '  → 密钥只存在于 Weixin.exe 的进程内存里，所以**必须先把微信开起来**：\n'
                '     1) 启动微信并保持登录（建议在微信里点开要导的那个群，\n'
                '        没点开过的库密钥不会加载进内存）\n'
                '     2) 重跑本脚本\n'
                '     3) 扫完之后就可以关掉微信了，后续导出只用已保存的密钥文件\n')
        sys.exit(2)
    out = set()
    for pid in pids:
        t = scan_pid(pid, out)
        print(f'pid {pid}: scanned {t/1048576:.0f} MB, keys so far: {len(out)}', flush=True)
    keys = [{'enc': k, 'salt': s, 'enc_utf16': (f == 'U')} for f, k, s in sorted(out)]
    with open(os.path.join(cfg.keys_dir, 'wechat_keys.json'), 'w', encoding='utf-8') as fp:
        json.dump({'count': len(keys), 'keys': keys}, fp, ensure_ascii=False, indent=2)
    print(f'共找到 {len(keys)} 个密钥 -> wechat_keys.json', flush=True)

if __name__ == '__main__':
    main()
