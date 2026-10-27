# qq-wechat-trace

## 合规声明

- **用途边界**：仅在本人电脑、本人 QQ 账号已落盘的本地消息库上做备份与文本导出；不面向未授权账号或他人数据，文档不包含绕过平台验证的用法。
- **数据与网络**：在 `work/` 等本地副本上只读处理，不改 QQ 安装目录中的活库；聊天内容与密钥留在本机，默认离线运行（首次拉取 QQ 密钥辅助脚本需联网一次），不上传至任何第三方服务。
- **责任**：密钥配置与读库可能带来账号、数据或合规方面影响；请自行评估后使用。维护者不对后续后果作任何保证，亦不构成法律意见或对不当使用的豁免。
- **形态**：开源 **Python 命令行脚本**，需自装依赖、复制 `config.example.json` 为 `config.json` 并填写路径与群名单；无图形界面安装包、无预编译一键分发。

## 快速说明

在 **Windows** 上读取本机 **QQ NT** 已同步到硬盘的消息库，按群导出为纯文本；比官方界面或接口逐条拉取快很多。

**本项目的特点是 QQ 库部分损坏时仍可尝试导出。** 若普通导出报错 `database disk image is malformed`，或某个群被整群跳过，用 **`qq_recover_by_rowid.py`**：先按索引列出该群全部 rowid，再逐行读内容；读失败的行跳过，其余正常写入文本。多数工具遇到这种情况会直接跳过整群；本项目提供按 rowid 的恢复导出。

## 隐私说明

QQ 号、群名单、密钥写在 `skills/qq-wechat-trace/config.json` 与 `keys/`（已 gitignore）；分享仓库或 zip 时不要带上它们。

---

## 1. 你需要准备什么

| 项目 | 说明 |
|------|------|
| **系统** | Windows 10/11（64 位）。脚本没在 macOS/Linux 上验证。 |
| **QQ** | **PC 新版 QQ 9**（QQNT，`Tencent Files\<QQ号>\nt_qq\nt_db\nt_msg.db`）。不是旧版 PCQQ，也不是手机备份。 |
| **账号与数据准备** | 本机已登录过、本地库里真有聊天记录；导出前建议先备份整个数据目录，但不是必须。 |
| **需要的权限** | QQ 提密钥时要能**前台登录 QQ 一次**。**注意：首次提密钥需登录 QQ，之后多数步骤只依赖本地数据。** |

大版本升级后若突然解不开，先看 [WINDOWS.md](skills/qq-wechat-trace/WINDOWS.md) 和 [references/QQ数据库导出手册.md](skills/qq-wechat-trace/references/QQ数据库导出手册.md) 里的避坑表。

---

## 2. 要装哪些组件、依赖什么

| 依赖 | 版本 / 说明 | 用来干什么 |
|------|-------------|------------|
| **Python** | 3.13 或 3.14 | 读库、导出、对账主体 |
| **sqlcipher3** | `pip install sqlcipher3==0.6.2` | 打开 SQLCipher 消息库（须与 Python 版本匹配的 wheel） |
| **PowerShell** | 5.1 即可（7.x 也行） | 拉取并执行 QQ 密钥脚本 |
| **Node.js** | **≥ 23.8** | 内置 `zlib.zstdDecompressSync`（部分维护脚本需要；自检见 DEPENDENCIES） |
| **tar**（bsdtar） | Win10 1803+ 一般自带 | 从备份包抽取分片副本 |
| **robocopy** | Windows 自带 | 备份活库（可选） |
| **pip** | 随 Python | 安装 `sqlcipher3` |
| **联网** | 仅首次 | `fetch_qq_key.ps1` 拉上游密钥脚本；已有密钥可跳过 |
| **管理员 / 杀软** | 视步骤 | 部分进程读内存步骤需管理员；调试器/扫内存可能被拦，见 WINDOWS.md |

版本锁定、PowerShell 5.1 坑、Node 可否换成纯 Python、国内镜像：[DEPENDENCIES.md](skills/qq-wechat-trace/DEPENDENCIES.md)。

**注意**：首次使用要在本机 QQ 配合下取得数据库密钥；上游密钥工具曾提示可能影响账号或数据。拿不准可先试用客户端自带备份/导出，或在备用机试跑。

---

## 3. 怎么操作（命令行，在仓库根目录）

当前目录应是 **`qq-wechat-trace` 仓库根**（能看到根目录的 `README.md`、`package.json`）。下面路径都带 `skills\qq-wechat-trace\` 前缀。

```powershell
# ① 配置（个人信息只写 config.json）
copy skills\qq-wechat-trace\config.example.json skills\qq-wechat-trace\config.json
# 填：QQ 号、数据根目录、要导的群

python skills\qq-wechat-trace\scripts\trace_config.py

# ② QQ：密钥 → 剥头副本 → 全群导出
powershell -ExecutionPolicy Bypass -File skills\qq-wechat-trace\scripts\fetch_qq_key.ps1
# 16 位密钥 → skills\qq-wechat-trace\keys\QQ_DB_KEY_<QQ号>.txt

python skills\qq-wechat-trace\scripts\qq_strip_header.py
python skills\qq-wechat-trace\scripts\qq_export_all.py

# ②-b 某个 QQ 群损坏、整群失败时（特色功能）
python skills\qq-wechat-trace\scripts\qq_recover_by_rowid.py <群号>
```

也可用根目录 `npm run deps`、`npm run qq:export` 等快捷命令（见 `package.json`）。`npm run qq:recover` **不会**自带群号参数，仍需像上面那样手动传 `<群号>` 或直接调用 Python。

- **网络**：默认只有「下载 QQ 密钥脚本」需要联网；已有密钥可跳过。国内见 [国内网络环境手册.md](skills/qq-wechat-trace/references/国内网络环境手册.md)。
- **Windows 坑**：PS 5.1 写密钥文件可能带 BOM，导致 `hmac check failed` → [WINDOWS.md](skills/qq-wechat-trace/WINDOWS.md)。

**导出文件**：每群一个 `.txt`，一行一条，`时间 | 昵称: 正文`。

---

## 4. 怎么放进 AI 里当「技能」用

本仓库自带 **`skills/qq-wechat-trace/SKILL.md`**：给 Agent 看的步骤、约束和命令（英文 frontmatter + 中文操作说明）。

**做法（通用）**：把整个文件夹 **`skills/qq-wechat-trace/`** 复制到你环境约定的 skill 目录，例如：

```text
<你的 skill 根>/qq-wechat-trace/    ← 里面要有 SKILL.md、scripts/、references/
```

若你用 **DSH**：复制到 `<DSH_HOME>/skills/qq-wechat-trace/`，重启或刷新 skill 列表。不要把这个仓库当「插件」用 `plugin add` 装。

**你在对话里怎么说**：例如「导出 QQ 聊天记录」「损坏 QQ 群 rowid 抢救」「按 QQ 号查在哪个群」——Agent 应读到 `SKILL.md` 后按步骤调用 `scripts/`，且**不应**把 `config.json` / 密钥内容贴回聊天。

换电脑从零配环境：[新电脑上手说明.md](skills/qq-wechat-trace/新电脑上手说明.md)。

---

## 本项目能解决哪些容易踩的坑

| 场景 | 脚本 |
|------|------|
| **QQ 库损坏、整群 malformed** | **`qq_recover_by_rowid.py`**（见 §3 ②-b） |
| 按人找群、按人导发言+上下文 | `qq_locate_person.py`、`qq_context_export.py` |
| 库内条数与导出文件对账 | `verify_counts.py` |

---

## 实测大概是什么量级

在维护者本机跑通过，**不是**你会得到的精确数字，只说明脚本扛得住大数据：

- **QQ**：多个群合计导出到 **百万级** 文本条；单库群消息总量也在 **千万级** 规模。
- **损坏 QQ 群**：索引仍是 **十万～百万行级** 时，逐行抢救可以只丢极少数坏行，而「整块跳过」会多丢 **千条级** 本来能读的消息。

---

## 目录结构

命令行默认在 **仓库根** `qq-wechat-trace/` 执行；skill 与脚本在 `skills/qq-wechat-trace/` 下。

```text
qq-wechat-trace/
├── README.md                         本说明
├── package.json                      npm 快捷命令（路径已指向 skills/…）
├── LICENSE                           本仓库自研代码 MIT
├── LICENSE-QQBackup-nc.txt           上游 QQ 密钥脚本协议副本（仓库内不含该脚本）
├── .gitignore
│
└── skills/qq-wechat-trace/           ★ 工具包 / DSH skill 本体（整目录可复制到 skill 根）
    ├── SKILL.md                      给 AI Agent 的操作手册（步骤、约束、触发词）
    ├── config.example.json           配置模板；复制为 config.json 后填写
    ├── config.json                   【本地】真实 QQ 号、路径、群名单（gitignore，勿提交）
    ├── requirements.txt              pip：sqlcipher3==0.6.2
    ├── DEPENDENCIES.md               依赖版本与安装说明
    ├── WINDOWS.md                    Windows 专项（BOM、长路径、管理员等）
    ├── 新电脑上手说明.md              换机、拷密钥、离线边界
    │
    ├── keys/                         【本地】密钥目录（gitignore）
    │   └── QQ_DB_KEY_<QQ号>.txt      QQ 16 字节密钥
    │
    ├── scripts/
    │   ├── trace_config.py           唯一配置入口；`python …/trace_config.py` 自检路径
    │   ├── fetch_qq_key.ps1          运行时拉上游 ps1 提 QQ 密钥（需联网一次）
    │   ├── qq_strip_header.py        剥 1024 字节 QQ_NT 头 → work 下剥头副本
    │   ├── qq_export_all.py          QQ 全群导出（config 里 groups.qq）
    │   ├── qq_recover_by_rowid.py    QQ 损坏群按 rowid 恢复导出
    │   ├── qq_survey_all.py          QQ 全库盘点（条数、是否已导出）
    │   ├── qq_locate_person.py       按 QQ 号查在哪些群
    │   ├── qq_context_export.py      某人在某群的发言 + 上下文（合并去重）
    │   └── verify_counts.py          库内条数 vs 导出文件对账
    │
    └── references/                   操作手册（细节、SQL、避坑；占位符路径，提交前勿粘贴未脱敏笔记）
        ├── QQ数据库导出手册.md
        ├── 备份与还原路径笔记.md
        └── 国内网络环境手册.md
```

### 运行后 `home` 下常见目录（由 config.json 指定，多在 gitignore）

`config.example.json` 里 `home` 默认类似 `./out`（相对 **skill 目录** `skills/qq-wechat-trace/` 解析）。导出与临时文件都在其下，例如：

```text
<home>/
├── work/                              临时副本（可删，验证通过后）
│   └── nt_msg_clear_<QQ号>.db         QQ 剥头后的库（体积接近源 nt_msg.db）
├── export_qq_<日期>/                   QQ 导出 txt
├── qq_export_state.json               群名/人数等辅助信息（导出文件头用）
└── export_*/ 下的 *.log               若自行记日志（仓库 .gitignore 含 *.log）
```

**注意**：不要把 `home` 设成 QQ **源库所在目录**（`qq_strip_header.py` 会拒绝在源库目录内写副本）。`config.json`、`keys/`、`<home>` 里的导出 txt **都不要提交或打进 zip 分享**。

---

## 已知限制 · 许可 · 隐私

- 仅供在 **本人有权访问的本机数据** 上做备份、检索与对账；请勿对他人账号或未授权数据使用。
- 密钥配置与读库导出可能带来账号、数据或合规方面的影响；请在了解风险后自行决定，维护者不对后续后果承担责任。
- 不解密图片/视频/语音文件。
- 自研代码 **MIT**；QQ 密钥脚本运行时来自 [QQBackup/qq-win-db-key](https://github.com/QQBackup/qq-win-db-key)（**非商用**协议），见 [LICENSE](LICENSE)、[LICENSE-QQBackup-nc.txt](LICENSE-QQBackup-nc.txt)。
- 勿提交 `config.json`、`keys/`、导出 txt；终端输出可能含群号与聊天片段，只留本机；往仓库粘贴个人笔记前请自行检查是否含账号与路径。
