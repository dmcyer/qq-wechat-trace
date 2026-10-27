# 依赖审计（2026-09-24 实测）

结论先说：**不依赖任何 Windows 发行包、不需要 PowerShell 7、不需要装运行库。**
全是跨平台标准工具。唯一的版本硬闸是 Node ≥ 23.8，而它可以被消掉。

## 运行时矩阵

| 依赖 | 本机版本 | 是否必需 | 干什么用 | 风险 |
|---|---|---|---|---|
| **Python** | 3.14.0 | ✅ 必需 | 解密/导出/对账主体 | 低 |
| **`sqlcipher3`** | 0.6.2 | ✅ 必需 | SQLCipher 打开加密库 | **编译型 wheel，须与 Python 版本匹配** |
| **Node** | v24.14.1 | ✅ 必需（仅微信 zstd 一步） | `zlib.zstdDecompressSync` | **≥ 23.8 才有这个 API** |
| `tar`（bsdtar） | 3.8.8，带 libzstd 1.5.7 | ✅ 必需 | 抽微信分片副本 | 低（Win10 1803+ 自带） |
| `robocopy` | Windows 内置 | ✅ 必需 | 备份 QQ 活库 | 无 |
| PowerShell | 7.6.6（也有 5.1） | ✅ 必需 | 提 QQ 密钥 | **无**，见下 |
| `pip` | — | 条件 | 装 sqlcipher3 | 低 |
| 运行时下载上游 ps1 | — | 条件 | `fetch_qq_key.ps1` 拉 QQBackup 的脚本 | **网络**；国内见《国内网络环境手册》§4 |
| **管理员权限** | — | ✅ 必需（仅微信扫内存） | `wx_mem_scan.py` 读别的进程内存 | 报"拒绝访问 0x5"就用管理员重跑 |
| **杀软白名单** | — | 建议 | 附加调试器 / 扫进程内存可能被拦 | 见 WINDOWS.md §2 |

## 三个你担心的点，逐条回答

### ① 依赖 Windows 发行包吗？—— 不依赖

没有 MSVC 运行库、没有 .NET、没有 Inno Setup、没有打包安装器、没有 vendor 二进制。
所有依赖要么是 Python/Node 的包管理器能装的，要么是 Windows 自带的。

唯一"编译型"的是 `sqlcipher3`，但它是 PyPI 上的正规 wheel：

```bash
pip install sqlcipher3==0.6.2
```

装不上时的备选：用系统包管理器装 SQLCipher 库，或换 `pysqlcipher3`。
这是**唯一需要编译工具链的可能点**，且只在装不上 wheel 时才触发。

### ② 需要 PowerShell 7 吗？—— 不需要，但 PS 5.1 有一个真 bug

`scripts/fetch_qq_key.ps1`（本仓库自研的 MIT wrapper，运行时去上游拉那份第三方 ps1）
转述的上游注释写着：

> Compatible with Windows PowerShell 5.0 and PowerShell Core 7.0.

但"兼容"不等于没坑。该脚本第 66–74 行是这个结构：

```powershell
try {
    & $scriptBlock @PSBoundParameters     # 以 UTF-8 重入自身
    exit $LASTEXITCODE                    # ← 想在这里退出
}
catch {
    Write-Warning "UTF-8 Auto-Reload Failed: $_"
}
# 若没有退出，下面的代码会再跑一遍
```

**在 PowerShell 5.1 + `Set-StrictMode -Version 2.0` 下**，脚本刚启动、还没跑过任何外部命令，
`$LASTEXITCODE` **尚未设置**——StrictMode 2.0 对这种变量直接抛异常，
于是 `catch` 把这个"退出"吞掉了，执行**继续往下走，整个脚本跑第二遍**。

2026-09-24 在 5.1 下实测复现：

```
inner: 准备 exit
catch 接住了: The variable '$LASTEXITCODE' cannot be retrieved because it has not been set.
>>> AFTER: 没有退出，代码继续跑（= 脚本会跑第二遍）
```

**后果**：QQ 被启动两次、需要登录两次，且第二遍的输出和状态容易看花眼。

**处理方式**：本仓库的 wrapper 在运行时给拉下来的副本打了补丁
（`exit $LASTEXITCODE` → `exit 0`，原地留注释说明原因），所以 `scripts/fetch_qq_key.ps1`
是修过的。**如果你自己从上游拉原版，务必也改这一行**，或者干脆用 PowerShell 7 跑。

> 📌 教训：**"声明兼容 5.0"不等于"在 5.0 下没坑"**。README/注释里的兼容性声明只是意图，
> 不是验证结论。所有版本声明都要按 `WINDOWS.md` §1 的做法实测一遍再信。

### ③ 需要能访问 GitHub 吗？—— 需要一次，但只有一次

只有 `fetch_qq_key.ps1` 需要联网（拉一份上游脚本过来）。
脚本内置 4 个镜像地址自动回退（raw / jsDelivr ×2 / gh-proxy），
国内一般可达；全不通时用 `-LocalPath` 手动指定，
或者**带上已有的密钥文件把这步整个跳过**（密钥跨重启不变）。

**其余全部环节 100% 离线**：剥头、导出、zstd 解码、对账、审计都不联网。

### ④ Node 是唯一的硬闸

`zlib.zstdDecompressSync()` 是 **Node 23.8.0** 才加进 `node:zlib` 的。
低于这个版本，微信的 zstd 解码一步直接跑不了（本机 v24.14.1，满足）。

## 消掉 Node 依赖（可选优化）

如果想让整条链**只剩 Python**，把 `wx_fix_zstd.mjs` 改写为 Python：

```bash
pip install zstandard
```

```python
# 替代 zlib.zstdDecompressSync 的三行
import zstandard
data = zstandard.ZstdDecompressor().decompress(raw, max_output_size=64 * 1024 * 1024)
text = data.decode('utf-8')
```

需要改的只有两处：解压调用，和"Python bytes repr → bytes"的反序列化
（现在 mjs 里手写了一个 `parsePyBytesRepr`，Python 版可以用 `ast.literal_eval`
直接还原，反而更短更稳）。

**取舍**：留 Node = 零新依赖但要求 Node ≥ 23.8；换 Python = 多一个
`zstandard` 包但去掉整个 Node 要求。对分发来说后者更干净，本仓库目前保留 Node 版
（因为实测可用），`max_output_size` 那个坑要注意——小消息没问题。

## 另一个可选的"重依赖"消解

微信导出那步需要从 tar 里抽 7 个分片。如果不想依赖 bsdtar，可以用 Python 的
`tarfile` 标准库（`import tarfile; tarfile.open(...).extractall()`），行为一致。
目前用 `tar` 是因为它 4 秒能抽完 3 GB，纯 Python 会慢一个量级但可接受。

## 版本锁定建议

发不到仓库的话无所谓；要发布就在 `README` 写明：

```
Python  >= 3.13
Node    >= 23.8      （若采用上面的 Python 改写则不需要）
tar     bsdtar（Windows 10 1803+ / GNU tar 均可）
PowerShell >= 5.1
sqlcipher3 == 0.6.2
```

