#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qq-wechat-trace 集中配置层 —— 全项目唯一允许出现个人信息的地方。

脱敏与可移植设计（四条原则）：

1. **单一来源**：QQ号、微信号、绝对路径、群号/群名只在本模块读取的 ``config.json``
   里出现一次。脚本一律 ``from trace_config import cfg``，不写死任何个人路径。
2. **永不提交**：``config.json`` 已写入 ``.gitignore``；仓库里只有
   ``config.example.json``（占位符 + 说明）。分享项目时不泄露任何个人数据。
3. **缺配置就明说**：任何必需项缺失时抛 ``ConfigError`` 并指出该填哪一项，
   **绝不猜测、绝不用默认值顶替**（照搬 telegram-download-chat SKILL.md 的
   "Never invent api_id / api_hash" 纪律）。
4. **环境变量可覆盖**：便于临时换账号 / 跑在不同机器上而不改文件。

环境变量（优先级高于 config.json）：
    QQT_QQ_UIN        QQ 号
    QQT_WX_ACCOUNT    微信账号目录名
    QQT_HOME          工作根目录（默认 <repo>/work）
    QQT_QQ_HOME       QQ 的 Tencent Files 根目录
    QQT_WX_HOME       微信 xwechat_files 根目录
    QQT_KEYS_DIR      密钥存放目录
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # skill bundle 根（本文件的上级目录）
CFG_FILE = os.path.join(ROOT, 'config.json')
CFG_EXAMPLE = os.path.join(ROOT, 'config.example.json')

PLACEHOLDER = object()          # 哨兵：占位符视作"未配置"


class ConfigError(RuntimeError):
    """配置缺失或仍是占位符时抛出。消息必须能让人直接知道该填什么。"""


def _expand(p, base=None):
    """展开成绝对路径。

    关键：相对路径必须以**skill bundle 根**为基准，不能以当前工作目录（cwd）为基准。

    为什么：原实现直接用 os.path.abspath()，而它解析相对路径时看的是 cwd。
    于是 config.json 里写 "./out" 时，产物会落到「你敲命令的那个目录」下——
    在 bundle 根跑是一个位置，从别处跑就变成另一个位置（2026-09-25 实测：
    在 bundle 根跑 python scripts/xxx.py，home 解析成了 <bundle>/out，
    而 cwd 在别处时却解析成 <cwd>/out，两者产物互不可见）。
    config.example.json 推荐的正是相对路径，所以这个坑很容易踩到。
    """
    if not p:
        return p
    p = os.path.expanduser(os.path.expandvars(p))
    if not os.path.isabs(p):
        p = os.path.join(base or ROOT, p)
    return os.path.abspath(p)


def _load():
    if os.path.exists(CFG_FILE):
        with open(CFG_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {}


class Config(object):
    def __init__(self, data):
        self._d = data if isinstance(data, dict) else {}

    # ---------- 基础工具 ----------
    def get(self, key, default=None):
        v = self._d.get(key, default)
        return v

    @staticmethod
    def _type_name(v):
        """给报错用的中文类型名——用户看不懂 'list' 这种词。"""
        if isinstance(v, bool):
            return '布尔值'
        if isinstance(v, dict):
            return '字典 {…}'
        if isinstance(v, (list, tuple)):
            return '列表 […]'
        if isinstance(v, str):
            return '字符串'
        if isinstance(v, (int, float)):
            return '数字'
        if v is None:
            return 'null'
        return type(v).__name__

    def need_mapping(self, key, hint):
        """取一个必须为字典的配置项。

        为什么单独做：`groups` 写成列表 / null / 字符串时，原实现在
        `self._d.get('groups', {}).get(which, [])` 处抛 AttributeError，
        绕过 ConfigError 处理直接吐 Python 堆栈（2026-09-25 实测复现）。
        类型不对属于「配置写错」，必须走友好报错通道。
        """
        v = self._d.get(key)
        if v is None or v == '' or v is PLACEHOLDER:
            return {}
        if not isinstance(v, dict):
            raise ConfigError('config.json 的 "%s" 应该是字典 {…}，实际是%s：%s'
                              % (key, self._type_name(v), hint))
        return v

    def need_path(self, key, default=None):
        """取一个路径类配置项，必须是字符串。

        为什么单独做：`"home": 123` 会在 os.path.abspath 处抛
        TypeError: expected str, bytes or os.PathLike object, not int（实测复现）。

        空字符串 / 纯空白也当「未配置」处理：`"home": ""` 会让所有产物路径退化成
        相对 bundle 根目录，`"home": "   "` 会生成一个名字是空格的目录——两者都不报错，
        属于静默错（2026-09-25 实测复现）。
        """
        v = self._d.get(key, default)
        if isinstance(v, str) and v.startswith('<') and v.endswith('>'):
            v = default
        if v is None:
            return None
        if not isinstance(v, str):
            raise ConfigError('config.json 的 "%s" 应该是字符串路径，实际是%s：%s'
                              % (key, self._type_name(v), v))
        if v == '' or (v.strip() == '' and default is not None):
            # 空 / 纯空白 → 视为未配置，回落到默认值（没有默认值时才报错）
            if default is None:
                raise ConfigError('config.json 的 "%s" 是空字符串；要么删掉这一项，要么填真实路径' % key)
            return default
        return v


    def need(self, key, hint):
        """取一个必需项；是占位符 / 空 / 缺失一律报错。"""
        v = self._d.get(key)
        if v is None or v == '' or v is PLACEHOLDER:
            raise ConfigError('config.json 缺少 "%s"：%s（可参考 config.example.json）' % (key, hint))
        if isinstance(v, str) and v.startswith('<') and v.endswith('>'):
            raise ConfigError('config.json 的 "%s" 还是占位符 %s：%s' % (key, v, hint))
        return v

    def opt(self, key, default=None):
        v = self._d.get(key, default)
        if isinstance(v, str) and v.startswith('<') and v.endswith('>'):
            return default
        return v

    # ---------- 账号 ----------
    @property
    def qq_uin(self):
        return os.environ.get('QQT_QQ_UIN') or self.need('qq_uin', '你的 QQ 号，纯数字')

    @property
    def wx_account(self):
        return os.environ.get('QQT_WX_ACCOUNT') or self.need('wx_account', '微信账号目录名，形如 wxid_xxxx 或其它目录名')

    # ---------- 根目录 ----------
    @property
    def home(self):
        p = os.environ.get('QQT_HOME') or self.need_path('home', os.path.join(ROOT, 'work'))
        return _expand(p)

    @property
    def qq_data_root(self):
        """QQ 的 Tencent Files 所在目录（其下每个账号一个子目录）。"""
        return _expand(os.environ.get('QQT_QQ_HOME') or
                       self.need('qq_data_root', 'QQ 数据根目录，一般是 <盘>:\\...\\Tencent Files'))

    @property
    def wx_data_root(self):
        """微信 xwechat_files 所在目录。"""
        return _expand(os.environ.get('QQT_WX_HOME') or
                       self.need('wx_data_root', '微信数据根目录，一般是 <盘>:\\...\\xwechat_files'))

    @property
    def keys_dir(self):
        p = os.environ.get('QQT_KEYS_DIR') or self.need_path('keys_dir', os.path.join(ROOT, 'keys'))
        return _expand(p)

    # ---------- 派生路径 ----------
    def qq_db(self, uin=None):
        uin = uin or self.qq_uin
        return os.path.join(self.qq_data_root, str(uin), 'nt_qq', 'nt_db', 'nt_msg.db')

    def wx_db_storage(self):
        return os.path.join(self.wx_data_root, self.wx_account, 'db_storage')

    def qq_key_file(self, uin=None):
        """密钥按账号分文件存放，绝不共用一个文件（覆盖=永久丢失旧号密钥）。"""
        uin = uin or self.qq_uin
        p = os.path.join(self.keys_dir, 'QQ_DB_KEY_%s.txt' % uin)
        if not os.path.exists(p):
            raise ConfigError('QQ 密钥文件不存在: %s\n'
                              '  → 先跑 Step 2 提密钥：powershell -ExecutionPolicy Bypass -File scripts/fetch_qq_key.ps1'
                              '，然后把打印的 16 位密钥写进这个文件（注意用 PowerShell 7 或 utf8NoBOM，见 WINDOWS.md 第 1 条）' % p)
        return p

    def qq_key(self, uin=None):
        """直接返回密钥字符串（去掉首尾空白与可能的 BOM）。

        为什么单独做：PS 5.1 的 Out-File -Encoding utf8 会写 UTF-8 BOM，
        Python 的 .strip() 去不掉 \\ufeff，SQLCipher 会报 hmac check failed，
        而报错信息完全指不到真因（WINDOWS.md 第 1 条，实测踩过）。
        """
        p = self.qq_key_file(uin)
        with open(p, encoding='utf-8-sig') as f:
            k = f.read().strip()
        if not k:
            raise ConfigError('QQ 密钥文件是空的: %s' % p)
        return k

    def qq_db_dir(self, uin=None):
        """QQ 的 nt_db 目录（nt_msg.db 与各 aux 库所在处）。"""
        return os.path.dirname(self.qq_db(uin))

    def qq_aux(self, name, uin=None):
        """QQ aux 库路径，如 qq_aux('group_info.db')。

        aux 库（group_info / profile_info 等）也带 1024 字节 NTQQ 头，
        读取前必须去头，见 scripts/qq_aux_read.py。
        """
        return os.path.join(self.qq_db_dir(uin), name)

    def wx_keymap(self):
        p = os.path.join(self.keys_dir, 'wx_db_key_map.json')
        if not os.path.exists(p):
            raise ConfigError('微信密钥映射不存在: %s\n'
                              '  → 先跑 Step 2 提密钥：python scripts/wx_mem_scan.py'
                              '（微信需保持运行，密钥只存在于进程内存）' % p)
        return p

    # ---------- 工作目录（相对 home，可随时删） ----------
    @property
    def work(self):
        w = os.path.join(self.home, 'work')
        os.makedirs(w, exist_ok=True)
        return w

    def qq_clear(self, uin=None):
        """剥头后的 QQ 解密库（临时产物，导完可删）。"""
        uin = uin or self.qq_uin
        return os.path.join(self.work, 'nt_msg_clear_%s.db' % uin)

    def wx_shard_dir(self, i):
        d = os.path.join(self.work, 'wx_shard_%d' % i)
        os.makedirs(d, exist_ok=True)
        return d

    def outdir(self, which, tag=None):
        import time
        tag = tag or time.strftime('%Y%m%d')
        d = os.path.join(self.home, 'export_%s_%s' % (which, tag))
        os.makedirs(d, exist_ok=True)
        return d

    # ---------- 群名单 ----------
    def groups(self, which):
        """which: 'qq' 或 'wx'。返回 {群号: 群名}。名单也属个人信息，只在 config 里。

        类型校验（2026-09-25 补）：这里曾经有三种坏法，其中一种**不报错但导出错数据**：
          - `groups` 写成列表 / null  → AttributeError，绕过 ConfigError 直接吐堆栈
          - `groups.qq` 是数字        → TypeError: 'int' object is not iterable
          - `groups.qq` 是字符串"123" → **静默把 "123" 逐字符拆成 {'1':'','2':'','3':''}**，
            于是去导出 3 个根本不存在的群，还不报错。静默错数据比崩溃危险得多，
            所以这里对字符串单独拦一道。
        """
        if which not in ('qq', 'wx'):
            raise ConfigError('groups() 的参数只能是 "qq" 或 "wx"，收到 %r' % (which,))
        d = self.need_mapping('groups', '形如 {"qq": [["<群号>", "<群名>"]], "wx": [["<群号>", "<群名>"]]}')
        g = d.get(which, [])
        if g is None or g == '':
            return {}
        if isinstance(g, str):
            raise ConfigError(
                'config.json 的 "groups.%s" 是字符串 %r，应该用列表包起来：\n'
                '  现在： "groups": {"%s": %r}\n'
                '  正确： "groups": {"%s": [["%s", "<群名>"]]}\n'
                '  → 字符串会被逐字符拆开，导致去导出错误的群（不报错，最危险）'
                % (which, g, which, g, which, g))
        if not isinstance(g, (list, tuple)):
            raise ConfigError('config.json 的 "groups.%s" 应该是列表 […]，实际是%s'
                              % (which, self._type_name(g)))
        out = {}
        for item in g:
            if isinstance(item, (list, tuple)) and len(item) >= 1:
                out[str(item[0])] = str(item[1]) if len(item) > 1 else ''
            elif isinstance(item, str):
                out[item] = ''
            elif isinstance(item, (int, float)) and not isinstance(item, bool):
                out[str(item)] = ''
            else:
                raise ConfigError(
                    'config.json 的 "groups.%s" 里有一项类型不对：%r（%s）\n'
                    '  → 每项应该是 ["<群号>", "<群名>"] 或直接写 "<群号>"'
                    % (which, item, self._type_name(item)))
        return out

    def describe(self):
        """打印当前生效配置（密钥内容绝不打印，只打印路径）。

        注意：自检的目的是"看路径配对没"，**不应因为密钥文件缺失而中断**——
        首次使用时密钥本来就还没有。所以密钥/路径类检查一律降级成状态文字，
        只有账号、根目录这类"必填项"缺失才抛 ConfigError（那才是真的没法继续）。
        """
        def safe(fn, miss_hint):
            """跑一个可能抛 ConfigError 的取值器，失败时返回提示文字而不是中断。"""
            try:
                return fn()
            except ConfigError:
                return miss_hint

        qq_uin = self.opt('qq_uin')
        wx_account = self.opt('wx_account')

        lines = [
            'repo       : %s' % ROOT,
            'config     : %s' % (CFG_FILE if os.path.exists(CFG_FILE) else '(未找到，用占位符)'),
            'home       : %s' % self.home,
            'qq_uin     : %s' % (qq_uin or '(未配置)'),
            'qq_db      : %s' % (self.qq_db() if qq_uin else '(需先配 qq_uin)'),
            'qq_key     : %s' % safe(self.qq_key_file, '(尚未提取 —— 见 Step 2)'),
            'wx_account : %s' % (wx_account or '(未配置)'),
            'wx_storage : %s' % (self.wx_db_storage() if wx_account else '(需先配 wx_account)'),
            'wx_keymap  : %s' % safe(self.wx_keymap, '(尚未提取 —— 见 Step 2)'),
            'qq groups  : %d 个' % len(self.groups('qq')),
            'wx groups  : %d 个' % len(self.groups('wx')),
        ]
        return '\n'.join(lines)


cfg = Config(_load())


# ---------------------------------------------------------------------------
# 统一错误出口：所有 `from trace_config import cfg` 的脚本都自动获得这个行为。
#
# 为什么需要：配置缺失是**使用者最常见的第一个错误**，不该甩一屏 Python 堆栈。
# 之前 9 个脚本在缺 config.json / 缺密钥时都直接吐 traceback，真正的提示语
# （"你该填哪一项"）被埋在几十行调用栈中间。
# ---------------------------------------------------------------------------
def _install_config_error_hook():
    _prev = sys.excepthook

    def _hook(etype, value, tb):
        if isinstance(value, ConfigError):
            sys.stderr.write('\n[配置错误] %s\n' % value)
            sys.stderr.write('提示：复制 config.example.json 为 config.json 后填入真实值；\n')
            sys.stderr.write('      跑 `python scripts/trace_config.py` 可只检查配置（不打印密钥）。\n')
            sys.exit(2)
        _prev(etype, value, tb)

    sys.excepthook = _hook


_install_config_error_hook()


if __name__ == '__main__':
    try:
        print(cfg.describe())
    except ConfigError as e:
        sys.stderr.write('[配置错误] %s\n' % e)
        sys.stderr.write('提示：复制 config.example.json 为 config.json 后填入真实值。\n')
        sys.exit(2)
