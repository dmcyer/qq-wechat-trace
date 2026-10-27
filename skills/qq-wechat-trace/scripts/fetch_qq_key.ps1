<#
.SYNOPSIS
    获取 QQ NT 数据库密钥：拉取上游 QQBackup 的 ps1，打一个必需补丁后执行。

.DESCRIPTION
    为什么不把上游脚本直接放进仓库：
    上游 windows_ntqq_get_key.ps1 采用「非商用开源协议 第1版」，
    版权归 LY (Young-Lord)。把它随本仓库一起分发会和本仓库的 MIT 冲突，
    所以这里改为**运行时拉取**，仓库只保留本脚本（MIT）。

    本脚本做三件事：
      1. 取到上游脚本内容（默认依次尝试 $UPSTREAM_SOURCES 里的 4 个地址，
         前一个失败自动换下一个；也可用 -LocalPath 指定已下载的本地副本，
         便于离线/网络不通时使用）
      2. 打一个补丁：把 `exit $LASTEXITCODE` 改成 `exit 0`
      3. 在临时目录执行打补丁后的脚本

    补丁原因（2026-09-24 在 PowerShell 5.1 下实测复现）：
    上游第 66-74 行是 try { & $scriptBlock ...; exit $LASTEXITCODE } catch { Write-Warning ... }
    脚本刚启动、未跑过外部命令时 $LASTEXITCODE 尚未设置，Set-StrictMode 2.0 会对此抛异常，
    被自己的 catch 吞掉 → 不退出 → 整个脚本跑第二遍（QQ 启动两次、登录两次）。

    上游项目：https://github.com/QQBackup/qq-win-db-key
    上游许可：非商用开源协议 第1版（Non-Commercial Open Source License Version 1.0）
    版权：Copyright (c) LY (Young-Lord)

.PARAMETER LocalPath
    已下载到本地的上游 ps1 路径。不给则自动从上游拉取。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\fetch_qq_key.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\fetch_qq_key.ps1 -LocalPath C:\path\to\windows_ntqq_get_key.ps1
#>
[CmdletBinding()]
param(
    [string]$LocalPath
)

Set-StrictMode -Version 2.0

# 上游脚本的多个获取位置，按顺序回退。
#
# 为什么要有多个：raw.githubusercontent.com 在中国大陆经常连不上，
# 而"提密钥"是整条链里唯一必须联网的一步（其余环节 100% 离线）。
# 下面每个地址返回的都是同一个文件（44,107 字节），2026-10-27 实测内容一致。
$UPSTREAM_SOURCES = @(
    'https://raw.githubusercontent.com/QQBackup/qq-win-db-key/master/scripts/windows/ntqq/windows_ntqq_get_key.ps1',
    'https://cdn.jsdelivr.net/gh/QQBackup/qq-win-db-key@master/scripts/windows/ntqq/windows_ntqq_get_key.ps1',
    'https://gcore.jsdelivr.net/gh/QQBackup/qq-win-db-key@master/scripts/windows/ntqq/windows_ntqq_get_key.ps1',
    'https://gh-proxy.com/https://raw.githubusercontent.com/QQBackup/qq-win-db-key/master/scripts/windows/ntqq/windows_ntqq_get_key.ps1'
)
$PATCH_MARK   = '[qq-wechat-trace PATCH 2026-09-24]'

function Get-Upstream {
    if ($LocalPath) {
        if (-not (Test-Path -LiteralPath $LocalPath)) {
            throw "本地副本不存在: $LocalPath"
        }
        Write-Host "使用本地副本: $LocalPath"
        return [System.IO.File]::ReadAllText($LocalPath, [System.Text.Encoding]::UTF8)
    }
    $errors = @()
    foreach ($url in $UPSTREAM_SOURCES) {
        Write-Host "尝试拉取: $url"
        try {
            # 用 .NET 直接下，避免 IWR 在部分环境下的 TLS/proxy 行为差异
            $client = New-Object System.Net.WebClient
            $client.Headers.Add('User-Agent', 'qq-wechat-trace')
            $bytes = $client.DownloadData($url)
            if ($bytes.Length -lt 1000) {
                throw "下载内容过短（$($bytes.Length) 字节），不像脚本本体"
            }
            Write-Host "拉取成功: $url（$($bytes.Length) 字节）"
            return [System.Text.Encoding]::UTF8.GetString($bytes)
        }
        catch {
            $errors += "  - $url`n      $($_.Exception.Message)"
            Write-Host "  失败: $($_.Exception.Message)"
        }
    }

    throw ("全部 $($UPSTREAM_SOURCES.Count) 个地址都拉失败：`n" + ($errors -join "`n") +
           "`n`n离线解法（任选其一）：" +
           "`n  1) 浏览器打开上面任一地址，存成 windows_ntqq_get_key.ps1，然后：" +
           "`n       powershell -ExecutionPolicy Bypass -File scripts\fetch_qq_key.ps1 -LocalPath <文件路径>" +
           "`n  2) 如果你已经有提好的密钥文件（密钥跨重启不变），直接拷进 keys\ 目录，这一步可以整个跳过。")
}

function Repair-Script {
    param([string]$Text)

    $needle = 'exit $LASTEXITCODE'
    if ($Text -notmatch [regex]::Escape($needle)) {
        if ($Text -match [regex]::Escape($PATCH_MARK)) {
            Write-Warning "上游脚本似乎已包含补丁标记，跳过打补丁。"
        } else {
            Write-Warning "未找到 '$needle'，上游可能已改版；跳过打补丁（PS 5.1 下可能仍会跑两遍）。"
        }
        return $Text
    }

    $replacement = @"
exit 0   # $PATCH_MARK 原为 `exit `$LASTEXITCODE：
                  # PS 5.1 + Set-StrictMode 2.0 下该变量未设置会抛异常，
                  # 被下方 catch 吞掉导致本脚本整体跑第二遍（启动两次 QQ）。
"@
    # 用 [regex]::Replace 的 MatchEvaluator，避免把替换文本再次当正则解释
    $evaluator = [System.Text.RegularExpressions.MatchEvaluator] { param($m) $replacement }
    $patched = [regex]::Replace($Text, [regex]::Escape($needle), $evaluator, [System.Text.RegularExpressions.RegexOptions]::None, [TimeSpan]::FromSeconds(5)
    )
    Write-Host "已打补丁: 'exit `$LASTEXITCODE' -> 'exit 0'"
    return $patched
}

$text = Get-Upstream
$patched = Repair-Script -Text $text

$tmp = Join-Path $env:TEMP ('qq_get_key_patched_{0}.ps1' -f ([Guid]::NewGuid().ToString('N').Substring(0, 8)))
# utf8NoBOM：带 BOM 会让 PowerShell 5.1 解析脚本时报错
[System.IO.File]::WriteAllText($tmp, $patched, (New-Object System.Text.UTF8Encoding($false)))

try {
    Write-Host "执行补丁版: $tmp"
    & $tmp @args
    exit $LASTEXITCODE
}
finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}
