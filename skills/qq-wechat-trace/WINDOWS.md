# Windows 平台注意事项

本项目只在 **Windows 上的 QQNT + 微信 PC 4.x** 实测过。这份文档收集 Windows 特有的坑，
**其中第 1 条是实测踩过的，且报错信息完全指不到真正原因**。

---

## 1. ⚠️ PowerShell 5.1 写文件会带 BOM，密钥直接失效（2026-09-24 实测）

```
EF BB BF 4D 7E 57 ...
↑↑↑↑↑↑↑ BOM
```

**现象**：解密时报 `hmac check failed` / `file is not a database` / `invalid key`，
而密钥肉眼看着一模一样。

**根因**：Windows 自带的 **PowerShell 5.1** 的 `Out-File -Encoding utf8` 写的是
**带 BOM 的 UTF-8**。而 Python 的 `.read().strip()` 只去空白，**去不掉 BOM**：

```python
open(path, encoding='utf-8').read().strip()   # len=17，首字符是 '﻿'
```

于是 `PRAGMA key` 收到的是 `'﻿<你的密钥前 6 位>...'`（**17** 字节，比正确的 16 多一个），
SQLCipher 自然拒认。
PowerShell 7 的 `Out-File -Encoding utf8` **不带 BOM**，所以同一个命令在两个版本行为不同。

**怎么避免**：

| 做法 | 命令 |
|---|---|
| 用 PowerShell 7 | `'密钥' \| Out-File -FilePath keys\QQ_DB_KEY_<号>.txt -Encoding utf8` |
| PS 5.1 指定无 BOM | `Out-File -FilePath ... -Encoding utf8NoBOM` |
| 让 Python 写（最稳） | `python -c "open(p,'w',encoding='utf-8').write(k)"` |

**兜底**：`trace_config.py` 已对密钥做 `lstrip('﻿')`，但你不经 `cfg` 直接读文件时仍会中招。

---

## 2. 权限与进程

| 事项 | 说明 |
|---|---|
| **QQ / 微信必须完全退出** | 备份/剥头时源库被独占锁，否则报 `file is being used by another process` |
| **优雅退出 vs 强杀** | `taskkill /F` 会留下 `-wal`/`-shm` 且不 checkpoint；正常点 × 退出更干净 |
| **`-wal`/`-shm` 必须一起备** | WAL 里可能有未合并的写入；只拷 `.db` 会丢最近的数据 |
| **读微信内存通常要管理员** | `wx_mem_scan.py` 用 `OpenProcess(PROCESS_VM_READ)`；报 `拒绝访问 0x5` 就用管理员权限重跑 |
| **杀毒软件误报** | `fetch_qq_key.ps1` 会附加调试器、`wx_mem_scan.py` 扫进程内存，都可能被杀软拦；需加白名单 |

## 3. 文件与路径

| 事项 | 说明 |
|---|---|
| **robocopy 别用于微信 db_storage** | `nt_data` 有 24 万个小文件，逐文件拷贝慢一个数量级（20 分钟才 9GB）；**用 `tar -cf`**（3GB 实测 3.2 秒，且天然含 wal/shm） |
| **robocopy 用于 QQ 单库没问题** | `robocopy <src> <dst> nt_msg.db nt_msg.db-*.material /Z /R:2 /W:5`，`/Z` 是可续传模式 |
| **Windows 的 `tar` 是 bsdtar** | 不是 GNU tar。`-tf` / `-xf` / `-cf` 通用，但 `--zstd`、`--delete` 等 GNU 专有选项不一定有 |
| **绝对不要原地打开活库** | `nt_msg.db` 前 1024 字节是 `QQ_NT DB` 头，必须先剥到副本；且以读写模式打开活库可能触发 checkpoint **修改源文件** |
| **长路径** | `<QQ_DATA_ROOT>\<QQ号>\nt_qq\nt_db\...` 已接近 260 字符上限；脚本里若拼更长路径可能报 `路径太长` |
| **磁盘空间** | 剥头副本 ≈ 原库大小（QQ 约 23 GB），导前确认目标盘有余量 |

## 4. 编码与控制台

| 事项 | 说明 |
|---|---|
| **控制台别打印非 GBK 字符** | `✔`、emoji 会让 GBK 代码页崩输出。本项目脚本只用 ASCII+中文，安全；你自己加 print 时注意 |
| **长任务设 UTF-8** | `$env:PYTHONIOENCODING="utf-8"`，避免管道重定向时编码错乱 |
| **Node 读写文件** | `wx_fix_zstd.mjs` 用 `fs.readFileSync(src,'utf8')` / `writeFileSync(...,'utf8')`，Node 的 utf8 **不带 BOM**，与 PS 5.1 行为不同 |
| **.ps1 脚本本身带 BOM** | 本仓库的 `scripts/fetch_qq_key.ps1` 以 **UTF-8 带 BOM** 保存——PS 5.1 需要 BOM 才知道这是 UTF-8，否则按 GBK 读，脚本里的中文提示会乱码（不影响功能，但会误导人） |

## 5. 运行时版本

| 依赖 | Windows 上要注意 |
|---|---|
| **Python** | 3.13 或 3.14。`sqlcipher3` 是编译型 wheel，**版本必须与 Python 匹配**（cp314 的 wheel 装不到 3.13 上） |
| **Node** | **≥ 23.8** 才有 `zlib.zstdDecompressSync`。低于此版本微信 zstd 一步跑不了，见 `DEPENDENCIES.md` §Removing-Node |
| **PowerShell** | **5.1 就够**（`fetch_qq_key.ps1` 自称兼容 5.0 与 7.0），但要注意第 1 条的 BOM 差异 |
| **执行策略** | 跑 ps1 可能被 ExecutionPolicy 拦：`powershell -ExecutionPolicy Bypass -File scripts\fetch_qq_key.ps1` |
| **网络** | `scripts/fetch_qq_key.ps1` 需要联网拉上游脚本；脚本内置 4 个镜像地址自动回退（见《国内网络环境手册》§4）；全不通时用 `-LocalPath` 指定本地副本 |

---

## 出问题时的排查顺序

```
1. 报 "file is being used by another process"     → QQ/微信没退干净（§2）
2. 报 "hmac check failed" / "invalid key"         → 先查密钥文件有没有 BOM（§1）
3. 报 "database disk image is malformed"           → 截断文件/损坏页；看 qq_recover_by_rowid.py
4. 报 "unrecognized token"                       → PRAGMA key 用了单引号，改双引号
5. 微信导出条数只有预期 1/5                       → 只读了一个分片，用 wx_export_shards.py（§3）
6. 微信正文是 b"(\xb5/... 乱码                    → 没跑 zstd 解码（Node ≥23.8）
7. 备份奇慢                                    → 在对微信 db_storage 用 robocopy，改 tar（§3）
```

