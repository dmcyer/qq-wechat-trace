---
name: qq-wechat-trace
description: >-
  Export and archive the user's own QQ NT chat history from local encrypted
  databases on Windows (CLI scripts only). QQ: key setup, header stripping,
  SQLCipher read on copies, per-group export, per-person lookup, merged
  context export, corrupted-page recovery by rowid. Optional WeChat PC 4.x
  helpers (multi-shard merge, zstd decode, gap audit) when the user explicitly
  asks; local data only, no upload.
whenToUse: >-
  Use when the user wants to export or archive their own QQ NT chat history on
  Windows. Primary triggers: "导出QQ聊天记录", "QQ NT导出", "损坏QQ群", "rowid恢复",
  "某人在哪个群", "按人导出QQ", "带上下文", "qq export", "person export".
  WeChat only if the user names WeChat: "微信分片导出", "微信zstd", "wx export".
  Operate only on authorized local data on the user's machine.
metadata:
  license: MIT
  version: 0.2.0
  platform: windows
  requires: python>=3.13, node>=23.8, sqlcipher3==0.6.2
  upstream: QQBackup/qq-win-db-key (Non-Commercial Open Source License v1, fetched at runtime)
---

# qq-wechat-trace

**用法**：`<qq|wx> [full | recover <群号> | gaps | keys | deps | person <QQ号> [群号]]>`

**SCOPE**: This skill drives the `scripts/` CLI to read the user's local QQ NT
(and optionally WeChat PC) message stores through header-stripped **copies** only,
export plain text under `home`, and audit gaps when asked. It does NOT modify
live databases in place, does NOT log into accounts on its own, does NOT upload
data, and does NOT export media binaries.

所有真实身份信息（QQ号、微信号、绝对路径、群号群名、密钥）都只在 `config.json` 里，
该文件已列入 `.gitignore`。脚本一律 `from trace_config import cfg`，不写死个人路径。

---

## Steps

### Step 0 — Verify the toolchain

Run `python scripts/trace_config.py` (it prints the effective config, paths only,
never key contents). Then check the four runtime dependencies:

| 依赖 | 最低版本 | 用途 | 检查命令 |
|---|---|---|---|
| Python + `sqlcipher3` | 3.13 或 3.14 | QQ/微信解密与导出 | `python -c "import sqlcipher3"` |
| **Node** | **≥ 23.8** | 仅微信 zstd 解码 | `node -e "console.log(!!require('zlib').zstdDecompressSync)"` |
| `tar` (bsdtar) | Windows 10 1803+ 自带 | 抽微信分片副本 | `tar --version` |
| `robocopy` | Windows 自带 | 备份 QQ 活库 | `where robocopy` |
| PowerShell | **5.1 即可**（7.x 也行） | 提 QQ 密钥 | `$PSVersionTable.PSVersion` |

If `sqlcipher3` is missing: `pip install sqlcipher3==0.6.2` — but **do not install
anything without the user's confirmation**. If Node < 23.8, the WeChat zstd step
cannot run — see `DEPENDENCIES.md` §Removing-Node for the pure-Python fallback.

Then check the Windows-specific traps in `WINDOWS.md` — most importantly: **if the
key file was written by Windows PowerShell 5.1 it almost certainly starts with a
UTF-8 BOM**, which `.strip()` does not remove and which makes SQLCipher reject an
otherwise-correct key with a misleading `hmac check failed`.

### Step 1 — Verify configuration

Confirm `config.json` exists and every required key holds a real value —
**without echoing any value back into the conversation**:

- `qq_uin`, `wx_account`, `qq_data_root`, `wx_data_root` must all be present and
  must NOT still be `<占位符>`.
- A bare "key exists" check is not enough: a fresh copy of `config.example.json`
  has every key but with placeholder values. `trace_config` already rejects
  placeholders by raising `ConfigError` — surface that message verbatim.
- The key files themselves (`keys/QQ_DB_KEY_<QQ号>.txt`, `keys/wx_db_key_map.json`)
  must exist. Report **paths only**. Never print, repeat, or paste the key value.
- Never invent a key. If missing, tell the user how to obtain it (Step 2).

### Step 2 — Obtain keys (the only step that needs the human)

| 平台 | 方式 | 需要交互？ |
|---|---|---|
| **QQ** | `powershell -ExecutionPolicy Bypass -File scripts/fetch_qq_key.ps1` → 自动拉起 QQ，用户登录一次 → 打印 16 位密钥 → 存入 `keys/QQ_DB_KEY_<QQ号>.txt` | **是，必须前台** |
| **微信** | 微信保持运行 → `python scripts/wx_mem_scan.py` → 扫进程内存拿 `x'<64hex><32hex盐>'` → 写入 `keys/wx_db_key_map.json` | 否（但微信必须在跑） |

Rules:
- **One key file per account.** Never overwrite `QQ_DB_KEY_<uin>.txt` for a
  different uin — the key is sticky per (account, machine); overwriting means
  re-logging into the old account to re-extract.
- QQ keys are sticky across restarts for QQNT (unlike legacy PCQQ, which
  re-issues per login). If a key stops working, it means password change or
  client reinstall — re-run the ps1.
- WeChat keys need the target chat opened once (WCDB lazy-loads). If a shard
  reports "未覆盖", ask the user to open a chat that uses it, then re-scan.

### Step 3 — Detect the mode from the argument

`<qq|wx>` selects the platform; the optional verb selects the task:

- *(none)* → **full export** of every group in `config.json` → `groups[platform]`.
- `recover <群号>` → single group via the rowid-recovery path (for groups whose
  index range hits corrupted pages, e.g. the classic `malformed` failure).
- `gaps` → run the history-gap audit over existing exports (no DB access).
- `keys` → print which key files exist (paths only) and whether they parse.
- `deps` → print the Step 0 table with pass/fail.

### Step 4 — Build the command

Every script reads its paths from `trace_config`, so commands stay short:

```bash
# QQ：先剥头复制（绝不原地改活库），再导出
python scripts/qq_strip_header.py          # 活库 -> work/nt_msg_clear_<uin>.db
python scripts/qq_export_all.py            # 全群，走 40027 索引

# QQ：单群损坏抢险（索引坏了就用 rowid 逐行读）
python scripts/qq_recover_by_rowid.py <群号>

# 微信：抽分片副本 -> 合并导出 -> zstd 解码 -> 对账
python scripts/wx_export_shards.py <群号...>     # 自动合并 message_0..6
node   scripts/wx_fix_zstd.mjs                 # 解码 + 剥发送者前缀 + 生成 _senders.tsv
python scripts/wx_verify_fix.py                # 对账：改动行/残留/误伤 必须为 0/0/0

# 洞检测（纯读导出文件）
python scripts/wx_gap_audit.py [qq导出目录] [wx导出目录]

# QQ：按人定位 + 按人导出上下文（见 Step 4b）
python scripts/qq_locate_person.py <QQ号>              # 这个人在哪些群？
python scripts/qq_locate_person.py <QQ号> --ai-only     # 只看群名含 ai 的
python scripts/qq_context_export.py --group <群号> --uin <QQ号> --ctx 5
```

### Step 4b — 「某个人说了什么」：按人定位 + 按人导出

这是导出**整群**之外最常用的需求，两条命令解决。**不要**为这个需求去跑全群导出
再手工 grep，那条路既慢又会漏上下文。

```bash
# ① 先定位：QQ 号 -> uid -> 所在群 -> 群名
python scripts/qq_locate_person.py <目标QQ号>
#   QQ 号  : <目标QQ号>
#   昵称   : <昵称>
#   uid    : u_XXXXXXXXXXXX
#   所在群: <群号>  <群名>

# ② 再导出：该人在该群的全部发言 + 前后各 5 条上下文
python scripts/qq_context_export.py --group <群号> --uin <目标QQ号> --ctx 5
```

**为什么必须用脚本、不能手工 grep：**

1. **上下文会重复。** 一个人连续发 10 条消息时，如果按「每条前后各 5 条」展开，
   同一批上下文会打印 10 遍。脚本做**区间合并**：重叠/相接的上下文合并成一段，
   每段只输出一次，段内该人的发言用 `▶` 标出。
   实测量级：224 条发言 / ctx=5 → 逐条展开 2464 条 → 合并后 **995 条**（省 1469 条）。
2. **QQ 正文要过 protobuf。** `40800` / `40900` 都不是纯文本。见下方「解析硬知识」。

脚本内置自检：结束时打印 `▶ N/N` 与 `行 N/N`，**任一不等就是有 bug**，
不要拿输出当结果交出去。

`qq_locate_person.py` 只读 aux 库（`group_info.db` / `profile_info.db`，
合计约 345 MB），**完全不碰 24 GB 的 `nt_msg.db`**，所以秒出。
加 `--with-count` 才会去读剥头库统计发言条数（慢，但能确认「这个群他确实说过话」）。

#### 解析硬知识（2026-10 实测，踩过坑才总结出来的）

| 事实 | 说明 |
|---|---|
| `45101` = 正文 | 但**必须递归**进容器字段才能拿到，顶层看不到 |
| `40800` / `40900` **都是 protobuf** | 把 `40900` 当纯文本 `.decode()` 会得到乱码 |
| 有些消息 `40800` 只有元数据 | 正文全在 `40900` 里（实测 224 条里有 3 条如此）。**两条都要试** |
| 引用回复夹带元数据 | 被引用消息的 `uid`、群号、二进制长度前缀会混进 `45101`，必须过滤 |
| 长度前缀会变「残字」 | 前缀字节落在拉丁扩展/希腊/西里尔/阿拉伯/亚美尼亚/藏文区，解码后像文字（见过 `ݽպj`、`ª`、`ڔ`、`ཐ`）。**这些区段整片删** |

`chatlog-keeper` 的 `qq_db.py` 把引用容器记为 `47423`（`_NTQQ_MSG_REPLY_CONTAINER`），
本脚本的 `CONTAINER_FIELDS` 同时覆盖 `40800/40900/40801/47423`，两边口径可以互相对照。

**Never** run the exporter against a path the user did not configure, and never
point `SRC` at the live `nt_msg.db` — the 1024-byte `QQ_NT DB` header must be
stripped into a copy first.

### Step 5 — Run it

- Anything that may block on human input (QQ key extraction, first-time login)
  must run **in the foreground in a real, attachable terminal** — the user has to
  type the QQ password / login code. **Never background these**; a background
  process cannot receive the input and will hang.
- Everything else (export, decode, verify, audit) is safe to run in the
  foreground, watch the progress log, and may be backgrounded for very large runs.
- After a large copy (the stripped QQ db is ~23 GB), remind the user it is a
  temp artifact under `work/` and can be deleted once the export is verified.

### Step 6 — Report results, always with reconciliation

Report the concrete output directory and per-group counts. Then reconcile:

- **Per group**: the count printed by the exporter must equal the sum of the
  `分片来源` line in the export header. If not, a shard was missed — stop and fix.
- **WeChat**: `wx_verify_fix.py` must print `残留压缩串: 0` and
  `非压缩行被误改: 0`. Anything else means the decode pass was incomplete.
- **QQ damaged groups**: the recovery header reports `真正无法读取 N 行` with
  their rowids — report N. A non-zero N is expected data loss, not a bug.
- Run `gaps` at least once per platform and report the largest internal gap and
  the coverage ratio, so the user knows where history is thin.

---

## Script reference

| 脚本 | 作用 | 关键产物 |
|---|---|---|
| `trace_config.py` | 唯一配置层；打印生效配置（只打印路径） | — |
| `fetch_qq_key.ps1` | 提 QQ NT 16 位密钥（需用户登录一次） | `keys/QQ_DB_KEY_<uin>.txt` |
| `qq_strip_header.py` | 剥 1024 字节 `QQ_NT DB` 头，活库→副本 | `work/nt_msg_clear_<uin>.db` |
| `qq_export_all.py` | 按 `40027` 索引全群导出 | `export_qq_<date>/qq_<群号>.txt` |
| `qq_recover_by_rowid.py` | 索引损坏时按 rowid 逐行抢救 | 同上 + 文件头记录不可读 rowid |
| `qq_locate_person.py` | **按 QQ 号定位所在群**（号→uid→群号→群名），只读 aux 库 | 控制台表格 |
| `qq_context_export.py` | **按人导出发言 + 上下文，区间合并去重** | `export_qq_<date>/person_<uin>_group_<群号>_ctx<N>.txt` |
| `qq_survey_all.py` | QQ 全库盘点：每群行数/时间范围，按量排序 | 控制台表格 |
| `verify_counts.py` | 库内条数 vs 导出条数对账（差值应=非文本条数） | 控制台表格 |
| `wx_mem_scan.py` | 扫 Weixin.exe 内存拿裸密钥 | `keys/wx_db_key_map.json`、`wechat_keys.json` |
| `wx_match_salts.py` | 读每个 .db 文件头盐，与全量密钥配对 | 刷新密钥映射 + 覆盖报告 |
| `wx_copy_shards.py` | 抽微信 `message_0..6` 分片副本（不原地读活库） | `work/wx_shard_<i>/` |
| `wx_export_shards.py` | 合并 message_0..6 全分片导出 | `export_wx_<date>/wx_<群号>.txt` |
| `wx_fix_zstd.mjs` | zstd 解码 + 剥发送者前缀 + `_senders.tsv` | `..._decoded/` |
| `wx_verify_fix.py` | 逐行对账 | 控制台四项判定 |
| `wx_integrity.py` | 7 个分片逐个 `integrity_check` | 控制台结果 |
| `wx_survey_all.py` | 微信全库盘点：每群条数/最早时间/分片数 | 控制台表格 |
| `wx_gap_audit.py` | 最大内部空档 / 覆盖率审计 | 控制台表格 |

---

## Scenarios

- **"导出我的 QQ 全部群"** → `qq_strip_header.py` → `qq_export_all.py`
- **"补导某个 QQ 群"** → add it to `config.json` `groups.qq`, re-run `qq_export_all.py`
- **"某个群导出报 malformed"** → `qq_recover_by_rowid.py <群号>`；报告 `真正无法读取 N 行`
- **"某个人在哪个群 / 他说过什么"** → `qq_locate_person.py <QQ号>` 定位群 → `qq_context_export.py --group <群号> --uin <QQ号> --ctx 5`。**不要**先全群导出再手工 grep
- **"他这句话是在回什么"** → 调大 `--ctx`（如 10）；`--max-gap 5` 可把相近片段也合并成一段，读起来更连贯
- **"换个 QQ 号"** → Step 2 提新密钥存 `QQ_DB_KEY_<新号>.txt`，用 `QQT_QQ_UIN=<新号>` 覆盖，再走全流程
- **"导出微信群"** → `wx_mem_scan.py` → `wx_export_shards.py <群号...>` → `node wx_fix_zstd.mjs` → `wx_verify_fix.py`
- **"导出的微信正文是乱码"** → 说明没跑 zstd 解码，跑 `wx_fix_zstd.mjs`
- **"某个微信群消息特别少"** → `wx_gap_audit.py`，看是不是 PC 端那段没在线
- **"我的历史是不是缺了"** → `wx_gap_audit.py`，报告最大空档位置和天数

---

## Constraints — when to stop and ask

- **Never invent a key** (QQ 16 位 or WeChat `x'...'`). They come only from the
  official ps1 or a live process scan. If missing, say so and point to Step 2.
- **Never modify the live database in place.** Always copy + strip the header.
  The live DB is the only source; corrupting it has no fallback.
- **Never overwrite another account's key file.** One file per QQ number.
- **Interactive login must be foreground.** Never background a step that needs
  the user to type a code.
- **Confirm before a large run.** A full QQ export is a ~23 GB copy plus a
  multi-minute export; a full WeChat export is ~3 GB of shards. State the scope
  and the disk cost first.
- **Never delete `Tencent Files\<uin>\` or `xwechat_files\<account>\`.** Those are
  the source data. Only `work/` (temp copies) and `export_*` (derived text) are
  safe to remove.
- **Do not echo key values.** Report paths and pass/fail only.
- **Do not add real identifiers to this repo.** 真实 QQ号/微信号/群号群名/个人绝对路径
  一律不得写进 `scripts/`、`references/` 或任何入库文件。配置类信息放 `config.json`
  （已 gitignore），模板见 `config.example.json`。

