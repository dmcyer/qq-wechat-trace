# QQ 数据库导出手册（Windows）

> 2026-09-21 实战验证：QQNT 9.9.35-52892 / Python 3.14 / sqlcipher3
> **本文结构**：① 当前资产 → ② 快速路径（现在就做）→ ③ 避坑清单 → ④ 资产重建（失效才看）→ 附录
> 完整踩坑历程见附录 C「完整操作实录」。

---

## ⚠️ 先读这段：本手册是「实战实录」，不是「开箱即用的操作指南」

这份手册记录的是**实战方法论**，早期曾用写死路径的开发目录；**公开仓库以 `config.json` + `scripts/` 为准**（见下表）。
旧脚本名（`qq_export_group.py`、`qq_export_all_v2.py` …）与备份盘（`D:\qq_db_backup_<日期>\`）
是**当时的现场形态**，其中一部分脚本在整理成公开仓库时被重命名、合并或淘汰了。

**要直接照着手册跑一遍，请以 `scripts\` 里的实际文件为准**，对照关系如下：

| 手册里写的（当时的形态） | 仓库里对应的（现在的） | 说明 |
|---|---|---|
| `qq_export_group.py` | `scripts/qq_export_all.py` | 单群/多群导出 |
| `qq_export_all_v2.py` | `scripts/qq_export_all.py` | 已合并为一个脚本 |
| `qq_export_group_skip.py` | （已淘汰） | 其能力并入 `qq_recover_by_rowid.py`，见 §1.6 |
| `qq_recover_<群号>_v2.py` / `qq_export_<群号>.py`（旧名，带真实群号） | `scripts/qq_recover_by_rowid.py` | 按 rowid 抢救损坏群 |
| `strip_live.py` | `scripts/qq_strip_header.py` | 剥 1024 字节头 |
| `qq_check2.py` | `scripts/verify_counts.py` | 库内 vs 导出对账 |
| `qq_verify_person.py` | （已淘汰） | 目标人物对话块提取，未被收录 |
| `QQ_DB_KEY.txt`（单个密钥文件） | `keys/QQ_DB_KEY_<QQ号>.txt` | **一账号一文件**，见公开版 SKILL.md Step 2 |

**用法上的关键差异**：手册里所有脚本都写死了绝对路径；仓库版一律从 `config.json`
取路径（`from trace_config import cfg`）。所以仓库版的命令**不带路径参数**：

```bash
# 手册的写法（开发区，写死路径）
python scripts/qq_export_all.py <群号> ...

# 仓库版的写法（公开版，路径来自 config.json）
python scripts/qq_export_all.py
```

> 保留这份实录的价值在于**方法论和坑位**（§1.5 发送者字段、§1.6 损坏页 rowid 恢复、
> 避坑 #1–#17），这些与脚本名无关，照做仍然有效。

---

> ⚠️ **本文已脱敏**：账号、密钥、群号/群名、成员昵称均已替换为 `  <占位符> ` ` 形式。
> 账号与路径写在 config.json、keys/（gitignore，勿提交）。
> 方法论、命令、避坑内容不受影响，按对照表还原后可直接执行。
## 0. 当前资产状态（一劳永逸已就位，2026-09-21）

| 资产 | 位置 | 状态 |
|---|---|---|
| 原库备份 | `D:\qq_db_backup_<日期>\nt_db\nt_msg.db`（约 20GB+） | ✅ 完整快照（WAL 已合并） |
| **已解密库** | `<home>/work/nt_msg_clear_<QQ号>.db`（约 20GB+） | ✅ 可直接 SQL 查询，**导出不需要开 QQ** |
| 密钥 | `keys/QQ_DB_KEY_<QQ号>.txt` | ✅ 粘性（跨重启/跨登录不变） |
| 导出工具 | `scripts/qq_export_all.py` | ✅ 已实测（protobuf 解析+损坏跳过） |
| 会话名单 | `（运行 scripts/qq_survey_all.py 查看）` | ✅ 数百会话（群+私聊，★标目标群） |
| 数据规模 | group_msg_table **约千万级 条** / c2c 数万级 条 | 本地库历史远深于 API 能拉到的 |

**常用查询的连接代码**（所有操作都用这段开头）：
```python
import sqlcipher3
KEY = open(r'keys/QQ_DB_KEY_<QQ号>.txt').read().strip()  # 必须 strip
con = sqlcipher3.connect(r'<home>/work/nt_msg_clear_<QQ号>.db', isolation_level=None)
con.execute("PRAGMA cipher_page_size = 4096;")   # ★必须在 key 之前
con.execute(f"PRAGMA key = '{KEY}';")
con.execute("PRAGMA kdf_iter = 4000;")
con.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1;")
con.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;")
```

---

## 1. 快速路径

### 1.0 动手前检查清单（写新工具/脚本前必须过一遍）

1. **重读本手册第 1、2 节**——2026-09-22 凌晨的教训：刚写完“按群必须走 40027 索引”的坑，转身又写了全表扫描工具，白跑 1 小时
2. **先用一个群小规模验证**（LIMIT 100 秒回），再铺开全量
3. **控制台输出禁非 GBK 字符**（✔、emoji 会崩 py 输出）；长任务统一 `$env:PYTHONIOENCODING="utf-8"` 或只写日志文件
4. **损坏处理内置**：见第 2 节坑 5，别等报错再补工具
5. **新工具先 `python -m py_compile` 再跑**

### 1.1 全量导出（工具决策树）

| 场景 | 工具 | 用法 |
|---|---|---|
| 多个群全量（日常） | `scripts/qq_export_all_v2.py` | 直接跑，内置 7 个目标群，走 40027 索引，6 群约 6 分钟 |
| 单群全量 | 改 v2 里的 `TARGETS` 列表，或先试 `qq_export_group.py <群号> "1990-01-01 00:00:00" "2099-01-01 00:00:00" out.txt` | 时间范围拉满即全量 |
| 某群报 `malformed`（索引范围有损坏页） | `scripts/qq_export_group_skip.py <群号>` | 分块游标+跳过损坏区，文件头记录跳过区间 |

> 已产出：`<home>/export_qq_<日期>`（7 群 百万级条，111.6MB）

### 1.2 导出某个群的某个时段

```powershell
# 仓库根目录；路径来自 config.json
python scripts/qq_export_all.py
# 单群时段导出见 scripts/qq_context_export.py；损坏群见 scripts/qq_recover_by_rowid.py
```
工具自动：rowid 分页扫描 → 损坏页跳过 → protobuf 解析 → 北京时间输出。全表扫描约 10–30 分钟，数量无限制。

### 1.3 快速查一个群的最早 N 条（走索引，秒回）

```sql
-- ★40027 = 群号(整数)，有索引；40003 = 群内序号(≈时间序)，联合索引原生顺序
SELECT "40001","40033","40050","40090","40093","40800"
FROM group_msg_table WHERE "40027" = <群号> ORDER BY "40003" ASC LIMIT 100;
```

### 1.4 群号 ↔ 群名

```sql
SELECT "40021","40094" FROM recent_contact_v3_table WHERE "40094" != '';
-- 或直接查已导出名单: （运行 scripts/qq_survey_all.py 查看）（★=之前导过的目标群）
```

### 1.5 消息正文解析规则（40800 protobuf）

```
MsgBody{ repeated MsgContent content=40800 } → 45002=类型 45101=文本(UTF-8) 47602=表情文字
45002: 1文本 2图片 3文件 4语音 5视频 6表情 7引用回复 8系统灰条 9红包 10Ark 11商城表情 14Markdown 16合并转发
发送者: 40033=发送者QQ号, 40090=群名片, 40093=昵称; 时间: 40050=Unix秒(北京=+8h)
```

**发送者取值顺序 +「系统消息」陷阱（2026-09-24 实测，漏标约 2% 消息）**

```python
who = r[4] or r[5] or ('QQ%s' % r[2] if r[2] else '[系统消息]')
#      40090   40093        40033（0 则判定为系统消息）
```

| 字段 | 含义 | 注意事项 |
|---|---|---|
| `40033` | 发送者 QQ 号（**跨群稳定的唯一标识**） | **值为 `0` 表示这是系统消息** |
| `40090` | 群名片 | 每个群可不同，**不能用来跨群认人** |
| `40093` | 昵称 | 仅群名片为空时出现 |

**坑：`r[2] or '?'` 会把系统消息也变成 `'?'`。** Python 里 `0 or '?'` → `'?'`，
而 `40033=0` 正是 QQ 标记「入群提示 / 撤回 / 置顶 / 灰条」的方式（实测约占全部消息 2%）。
这类消息**本来就没有发送者**；标成 `?` 或 `QQ?` 会让人误判为「数据库损坏」或「账号被封」。
实测特征：`40033=0` 且 `40090`/`40093` 都是空字符串，内容解析出来是 `[灰条]` 或入群提示。
判定方法：直接读原始行看字段值，不要靠猜。

**跨群追踪某个人的唯一可靠办法**：用 `40033` 过滤，不要用群名片。
实测同一人在不同群的名片可以完全不同（A 群叫「X」、B 群叫「Y」），
按名字跨群搜会**整群漏掉**对方的发言。全库扫人的做法见 `qq_verify_person.py`：
`DISTINCT "40027"` 枚举全部群 → 每群索引枚举 rowid → 逐行点读 → 按 uid + 时间过滤。

### 1.6 损坏页群的完整导出：索引枚举 rowid + 逐行点读（2026-09-23/24 实测）

**症状**：按群索引导出时整群报 `database disk image is malformed`。

**原理**：损坏通常只影响**表数据页**，`(40027,40003)` 索引往往是好的。
所以仍能用索引枚举出该群全部 rowid，再逐行点读，只跳过真正坏的那几行。

**⚠️ 先识别哪些群中招**：`SELECT count(*) WHERE "40027"=?` **成功不代表群完好**——
它只走索引。必须看 `min("40050")` / `max("40050")`（要读表列）或直接读内容，
失败才说明有坏页。扫全库名单时这件事实测漏过三个群。

**旧工具为什么丢数据**（`qq_export_group_skip.py`）：它用
`WHERE "40027"=? AND "40003">? ORDER BY "40003" LIMIT n` 分块查，
一碰到坏行**整条语句中止**，于是指数退避往前跳。实测跳过了 5,136 个序号，
而那个区间其实只有 1,627 行、其中 1,625 行完全完好。

**正解**（现统一为 `scripts/qq_recover_by_rowid.py <群号>`，旧仓库里曾按群号命名脚本）：

```python
rids = con.execute('SELECT rowid FROM group_msg_table WHERE "40027"=?', (g,)).fetchall()

def read(batch):
    try:
        return con.execute('SELECT <列> FROM group_msg_table WHERE rowid IN (%s)'
                           % ','.join('?' * len(batch)), batch).fetchall()
    except Exception:
        pass
    if len(batch) == 1:
        坏行.append(batch[0]); return []        # 单个 rowid 也读不动，才认定真丢
    mid = len(batch) // 2
    return read(batch[:mid]) + read(batch[mid:])  # 二分定位，只丢真正坏的行

for i in range(0, len(rids), 200):
    read(rids[i:i + 200])                        # 200 一批，兼顾速度与定位精度
```

**实测效果**：

| 群 | 旧（跳过式） | 新（rowid 恢复） | 真丢 |
|---|---|---|---|
| <QQ_UIN> / <群号> | 378,522 | **380,905**（+2,383） | 2 行 |
| <QQ_UIN> / <群号> | — | 63,142 | 1 行 |
| <QQ_UIN> / <群号> | — | 43,758 | 0 行 |

这把方法与损坏位置无关：坏行落在哪儿都能绕过，且会把坏行 rowid 记进导出文件头备查。

### 1.7 目标人物对话上下文提取（2026-09-24 实测）

**要解决的事**：把"某个人参与过的对话"整段导出来，而不是零散单句。做法是
**锚点 + 固定窗口 + 重叠合并**。

**① 锚点 = 两类消息**

| 锚点 | 怎么认 |
|---|---|
| 他本人发言 | `40033`（uid）跨群稳定，**不要用群名片**——同一人在不同群名片可以完全不同 |
| 别人回复他的消息 | 见 ② |

**② 回复归因：QQ 不告诉你"回的是谁"**

`45002=7`（引用回复）的 protobuf 里**没有"被引消息的发送者"**字段，只有：

```
field 47423 {              ← 被引用的原消息
    field 45001 = ...      ← 看起来像 msgid，实际不是（样本里恒等于本条 msgid+1，全库查不到）
    field 45101 = '原文'   ← 只有这个能用
}
```

所以只能**用被引正文反推**。规则：

```python
text_pos = {}                        # 每段正文 -> 出现位置列表（全文 strip 后比对，两端都要 strip）
for i, m in enumerate(msgs):
    if m['text'].strip():
        text_pos.setdefault(m['text'].strip(), []).append(i)
        if m['uid'] == UID: his_idx.setdefault(m['text'].strip(), []).append(i)

for i, m in enumerate(msgs):
    if m['ctype'] == 7 and m['quoted']:
        prev = [j for j in text_pos[m['quoted'].strip()] if j < i]
        if prev and msgs[prev[-1]]['uid'] == UID:      # 严格：回复之前最近一次说这句的必须是他
            锚点.add(i)
```

**⚠️ 宽松规则的代价**：只要"他以前说过这句"就归因给他，命中数会从 349 涨到 1,368（4 倍），
而覆盖率从 47% 飙到 97% —— 等于没筛。**不可靠的归因不要当锚点**，让它只作为普通上下文出现。

**更硬的信号（下次可优先用）**：回复正文常常直接带 `@<他的群名片>`，
比正文匹配可靠，可用来交叉验证。

**③ 窗口与合并**

```python
for i in sorted(锚点):
    a, b = max(0, i-W), min(len(msgs)-1, i+W)
    if 已有块 and a <= 上一块右端+1:   # 重叠或相邻就并
        上一块右端 = max(上一块右端, b)
    else:
        开新块
```

**窗口取多大，先算密度再定**：

| 他发言数 / 全群 | 平均间隔 | ±100 覆盖 | ±20 覆盖 |
|---|---|---|---|
| 数千 / 数万 | 约十几条/次 | 宽窗口覆盖率高 | 窄窗口约半覆盖 |

**结论：先算"平均每几条出现一次"，再选 W。** 高频发言者（<30 条/次）用 ±20 以内；
±100 只对几乎不说话的人有意义。

**④ 实测产出**（账号 <QQ_UIN>）

| 群 | 他发言 | 确定回复他 | 块数 | 覆盖 |
|---|---|---|---|---|
| 群A | 数千 | 数百 | 数百 | 约半数群消息被上下文覆盖 |
| 群B | 数千 | 数百 | 数百 | 约三分之一群消息被上下文覆盖 |

输出行格式（三类信息一行搞定，方便 grep）：
```
2025-02-07 12:00:00 | <成员A>: [回复] <示例正文>  ←【回他】（引：<被引原文摘要>）
2025-01-24 12:00:00 | <群名片A>: [图片]  ←【他】
```

---

## 2. 避坑清单（动手前 30 秒过一遍）

| # | 坑 | 解法 |
|---|---|---|
| 1 | **数字列名必须加引号** `"40021"` | 不加引号 = 整数常量，`COUNT(DISTINCT 40021)` 恒等于 1，不报错但结果全错 |
| 2 | **按群查询走 `40027`（=群号）**，不要用 `40021` | 40021 无索引全表扫 千万级 行；`recent_contact` 里同名的 40027 是另一个空间，不能 join |
| 3 | `ORDER BY "40050"` 触发全群排序 | 改用 `ORDER BY "40003"`（联合索引原生顺序） |
| 4 | `CREATE INDEX` 报 malformed | 别给加密库加索引，用现有 (40027,40003) 索引 |
| 5 | 个别群索引查询报 `malformed` | 该群数据页有损坏，用 `qq_export_group_skip.py <群号>`（分块游标+跳过，文件头记录跳过区间） |
| 6 | 密钥带换行 | `open(...).read().strip()`，文件是 write 工具生成的带 `\n` |
| 7 | 64MB 截断探针报 malformed | 不是参数错，是文件不全；验证解密必须在完整文件上做 |
| 8 | Python 脚本 print emoji/✔ 崩控制台（GBK） | 控制台输出只用 ASCII/中文；或 `$env:PYTHONIOENCODING="utf-8"` |
| 9 | `sqlcipher3.connect(..., isolation_level=True)` 报 TypeError | 该参数只接受字符串或 None，只读连接用 `isolation_level=None` |
| 10 | **全表扫描慢**（千万级 行约 1 小时+） | 按群查询一律走 40027 索引（秒级）；全表扫描只作为最后手段 |
| 11 | **`40033=0` 被当成空发送者** | 那是 QQ 标记系统消息（入群/撤回/灰条）的方式，不是损坏也不是封号。判读与取值顺序见 1.5，别输出成 `?` 或 `QQ?` |
| 12 | **按群名片跨群认人** | `40090` 每个群可不同。跨群追踪某人必须用 `40033`（uid），见 1.5 |
| 13 | **多账号密钥互相覆盖** | 密钥按账号派生，一个账号一把，不可通用。按 `QQ_DB_KEY_<QQ号>.txt` 分文件存，**绝不覆盖 `QQ_DB_KEY.txt`**——覆盖等于旧号密钥永久丢失，得重新登录旧号再提一次 |
| 14 | **TARGETS 分批遗漏** | 群是分批导的时候（7 群 + 后来补 4 群），建新的导出脚本会照抄第一批的 TARGETS，把后补的群全漏掉。建脚本后先核对 `TARGETS` 行数与目标群清单一致 |
| 15 | **新增列后忘改索引** | 给 SELECT 加列（如在最前加 `40027`）会让后面所有 `r[n]` 全部错位，表现为"查无结果"而非报错。加列后逐行核对索引，并用已知非空数据验证 |
| 16 | **读完第一个 40800 内容段就 break** | QQ 的**回复类消息有多个 40800 段**（段1=类型+引文，段2=回复正文），break 早退会把正文整段吃掉，全变成空壳 `[回复]`。必须遍历全部段再汇总 |
| 17 | **拿回复里的 `45001` 当被引 msgid** | 那不是可查的消息 id（实测恒等于本条 msgid+1，全库找不到）。QQ 引用回复根本不带被引消息的发送者，只能靠被引正文反推，见 1.7 |

---

## 3. 资产失效时的重建流程（压缩版，细节见附录 C）

### 3.1 重新备份（要最新数据时）
```powershell
Get-Process -Name QQ | Stop-Process -Force   # 必须关，WAL 才合并
robocopy "<QQ_DATA_ROOT>\<QQ_UIN>\nt_qq" "D:\qq_db_backup_<新日期>" /E /Z /R:2 /W:5
```

### 3.2 重新提密钥（仅改密/重装后需要；需用户配合登录一次）
```powershell
irm https://raw.githubusercontent.com/QQBackup/qq-win-db-key/master/scripts/windows/ntqq/windows_ntqq_get_key.ps1 | iex
```
脚本自动拉起 QQ → **用户在窗口登录一次** → 打印 16 位密钥。也可 `-NoDebugForKey` 只做静态分析。

### 3.3 重新解密（新备份）
剥 1024 字节头 → 用第 0 节的连接代码打开（PRAGMA 顺序一字不差）。

---

## 附录 A：常见错误速查

| 报错 | 原因 | 解法 |
|---|---|---|
| `hmac check failed for pgno=1` | PRAGMA 顺序错 | `cipher_page_size` 移到 `key` 前面 |
| `database disk image is malformed` | 截断文件 / 损坏页 / 建索引 | 完整文件上操作；损坏页用 rowid 扫描跳过 |
| `file is being used by another process` | QQ 没关干净 | 3.1 |
| 密钥突然不灵 | 改密/重装 | 3.2 重提 |
| `unrecognized token` | SQL 引号冲突（微信场景） | 外层双引号（见微信手册 B3） |

## 附录 B：文件位置速查

| 内容 | 路径 |
|---|---|
| 已解密库（直接用） | `<home>/work/nt_msg_clear_<QQ号>.db` |
| 密钥 | `keys/QQ_DB_KEY_<QQ号>.txt` |
| 原库备份 | `D:\qq_db_backup_<日期>\nt_db\nt_msg.db` |
| 导出工具 | `scripts/qq_export_all.py` |
| 群名单 | `（运行 scripts/qq_survey_all.py 查看）` |
| 完整避坑笔记 | `备份与还原路径笔记.md` 第 5 节 |

## 附录 C：完整操作实录（2026-09-21，含走过的弯路）

> 真实时序。保留弯路是因为——下次遇到同样现象能对号入座省时间。

### 阶段 0：起点
- 曾用第三方 API/机器人拉取历史，触发平台风控后，**改为只走本地库离线导出**（与本仓库脚本路线一致）


### 阶段 1：备份（约 3 分钟）
1. 关掉全部 QQ 进程
2. robocopy `nt_msg.db` + `-wal` + `-shm` → `D:\qq_db_backup_<日期>`
3. **发现**：拷贝时 wal/shm 已不存在——SQLite 在连接关闭时已 checkpoint 并删除，主库自 11:03 起零写入 → 干净完整快照（事后“完整解密成功”反证）
4. 补拷两个 `.material` 文件

### 阶段 2：提取密钥
1. **推荐**：`scripts/fetch_qq_key.ps1` → `keys/QQ_DB_KEY_<QQ号>.txt`（拼 PRAGMA 前 trim）。
2. **可省的弯路**：自研 Frida hook（约 1～2 小时）；官方 ps1 通常一次过。
3. **教训**：有官方实现先读官方文档/脚本，再写代码。

### 阶段 3：解密（约 3 小时，全部耗在参数上）
1. 剥 1024 字节头 → 64MB 截断探针测试 → 报 `malformed`，**误判参数仍错**（其实参数已对，是文件不全）
2. 盲猜参数约 3 小时：iter × prf × reserve × iv × 页大小 × 编码——**全错**
3. **拐点**：读官方 `nt_msg_db_util/1.decrypt.py` docstring，发现 **PRAGMA 顺序**：`cipher_page_size=4096` 必须在 `PRAGMA key` 之前
4. **正解**：按官方顺序在完整文件上一次通过
- **教训**：有官方实现的任务，先读源码再写代码——这 3 小时本可省

### 阶段 4：成果与导出
1. 全库可读：`group_msg_table` **约千万级**、`c2c_msg_table` **数万级**
2. 群名单：`recent_contact_v3_table`（40021=群号、40094=群名）→ 数百会话量级
3. 踩坑：数字列名引号；`group_msg_table` 的 **40027=群号且有索引**（按群查询的正解）
4. 写 `qq_export_group.py`，实测导出 <群号> 最早 100 条成功（该群本地 数十万级、最早 2025-04-30）

### 时间线复盘
| 阶段 | 耗时 | 本可避免 |
|---|---|---|
| 备份 | 3 分钟 | — |
| 提密钥 | 约 2 小时 | 可省：优先官方 ps1 |
| 解密 | ~3 小时 | 全部（先读官方 docstring 就是 5 分钟） |
| 导出 | 20 分钟 | 列名引号/索引坑各踩一次 |

## 附录 D：第二次复盘——全量导出（2026-09-22 凌晨）

| 坑 | 耗时损失 | 根因 | 对策（已入手册） |
|---|---|---|---|
| 又写了全表扫描工具（手册明令走 40027 索引） | ~1 小时 | **写了文档不复查** | 第 1 节新增“动手前检查清单”第 1 条 |
| `isolation_level=True` TypeError | 2 分钟 | sqlcipher3 API 不熟 | 避坑表 #9 |
| `✔` 撞 GBK 控制台崩输出 | 5 分钟 | 已知环境坑再犯（记忆里有） | 避坑表 #8 + 检查清单第 3 条 |
| <群号> 报 malformed 整群跳过，补写第三个工具 | 10 分钟 | 错误处理没内置 | 工具决策树 + `qq_export_group_skip.py` 通用化 |
| **教训一句话** | — | **手册的价值在于被翻阅，不在于被写完** | 动手前先过检查清单 |

## 附录 E：长期使用注意（一劳永逸之后的维护）

| 事项 | 说明 | 动作 |
|---|---|---|
| **数据时效** | `nt_msg_clear.db` 是快照，之后的新消息不在里面 | 要最新数据：关 QQ → robocopy 重备 → 重新剥头（密钥不变，直接解） |
| **密钥失效** | 改密码/重装客户端才会失效（日常重启不影响，实测粘性） | 重跑官方 ps1，用户登一次即可 |
| **损坏页** | 个别群走索引查询会报 `malformed` | 用 `qq_export_group.py`（rowid 全扫描+自动跳过） |
| **别建索引** | 加密库上 CREATE INDEX 报 malformed | 用现有 (40027,40003) 索引 |
| **列名引号** | 数字列名必须 `"40021"` 加引号 | 不加=整数常量，结果全错还不报错 |
| **全量导出预期** | 千万级 行全量文本导出约 30–60 分钟（纯本地） | 数量无限制，只是时间和磁盘的事 |

