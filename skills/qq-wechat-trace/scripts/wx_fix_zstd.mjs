// 微信导出修复 v2：把未解码的 zstd 压缩消息还原成正文
// 与 v1(fix_wx_zstd.mjs) 的区别：同时兼容 Python bytes repr 的单引号 b'...' 和双引号 b"..." 两种形式
//   （Python 在内容含单引号时会自动改用双引号，v1 只认单引号，会把双引号形式全部漏掉）
// 输入：wx_export_<date>\wx_*.txt        （只读，绝不修改）
// 输出：wx_export_<date>_decoded\wx_*.txt + _senders.tsv（旁证）
//
// 用法：
//   node scripts/wx_fix_zstd.mjs                  # 读 config.json 推断导出目录
//   node scripts/wx_fix_zstd.mjs <导出目录>        # 显式指定
//   QQT_OUT_WX=<导出目录> node scripts/wx_fix_zstd.mjs
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

// 定位导出目录：显式参数 > 环境变量 > config.json 的 home 下找 export_wx_*
function resolveDirs() {
  const explicit = process.argv[2] || process.env.QQT_OUT_WX;
  if (explicit) return { src: explicit, dst: explicit + '_decoded' };

  // 从 config.json 取 home（与 trace_config.py 保持同样的默认：<repo>/work）
  const repo = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), '..');
  let home = path.join(repo, 'work');
  const cfgFile = path.join(repo, 'config.json');
  if (fs.existsSync(cfgFile)) {
    try {
      const cfg = JSON.parse(fs.readFileSync(cfgFile, 'utf8'));
      if (cfg.home) home = path.resolve(repo, cfg.home);
    } catch (e) {
      console.error('[警告] config.json 解析失败，回退默认 home：' + e.message);
    }
  }

  if (!fs.existsSync(home)) {
    console.error(
      '[中止] 找不到 home 目录：' + home + '\n' +
      '  → 先跑 python scripts/wx_export_shards.py <群号...> 生成导出，\n' +
      '    或用 `node scripts/wx_fix_zstd.mjs <导出目录>` 显式指定。');
    process.exit(2);
  }
  const cands = fs.readdirSync(home)
    .filter((d) => d.startsWith('export_wx_') && !d.endsWith('_decoded'))
    .map((d) => path.join(home, d))
    .filter((d) => fs.statSync(d).isDirectory());
  if (cands.length === 0) {
    console.error(
      '[中止] 在 ' + home + ' 下找不到 export_wx_* 导出目录\n' +
      '  → 先跑 python scripts/wx_export_shards.py <群号...>，或用参数显式指定目录。');
    process.exit(2);
  }
  // 多个候选时取最新的那个（按目录名里的日期排）
  cands.sort();
  const src = cands[cands.length - 1];
  if (cands.length > 1) {
    console.error('[提示] 发现多个导出目录，使用最新的：' + path.basename(src));
  }
  return { src, dst: src + '_decoded' };
}

const { src: SRC_DIR, dst: DST_DIR } = resolveDirs();
const ZSTD_MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);

fs.mkdirSync(DST_DIR, { recursive: true });

// 把 Python bytes repr 正文（不含首尾引号）还原成 Buffer
// Python bytes 的 repr 只使用 \xNN 与 \t \n \r \\ 及引号转义；遇到别的转义直接抛错，避免静默出错字节
function parsePyBytesRepr(s) {
  const out = [];
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c !== '\\') { out.push(s.charCodeAt(i) & 0xff); continue; }
    const n = s[++i];
    switch (n) {
      case 'x': {
        const h = s.substr(i + 1, 2);
        if (!/^[0-9a-fA-F]{2}$/.test(h)) throw new Error('bad hex escape \\x' + h);
        out.push(parseInt(h, 16)); i += 2; break;
      }
      case 'n': out.push(10); break;
      case 'r': out.push(13); break;
      case 't': out.push(9); break;
      case '\\': out.push(92); break;
      case "'": out.push(39); break;
      case '"': out.push(34); break;
      default: throw new Error('unexpected escape \\' + n);
    }
  }
  return Buffer.from(out);
}

// 在一行里找出所有 "…: b'…'" 或 "…: b\"…\"" 的候选，返回正文与切分点
// 我们的行格式固定是「时间 | 发送者: 正文」，repr 一定在行尾
function findCandidates(line) {
  const cands = [];
  for (const q of ["'", '"']) {
    const needle = ': b' + q;
    const idx = line.lastIndexOf(needle);
    if (idx === -1) continue;
    if (!line.endsWith(q)) continue;
    const bodyStart = idx + needle.length;
    if (line.length <= bodyStart + 1) continue; // 空 repr
    cands.push({ head: line.slice(0, idx), body: line.slice(bodyStart, line.length - 1), quote: q });
  }
  return cands;
}

// 解压后正文形如 "wxid_xxx:\n<真正的消息>" —— 剥掉内嵌的发送者前缀
function stripSenderPrefix(text) {
  let m = text.match(/^(?:wxid_[A-Za-z0-9_\-]+|[0-9]+@openim):[\r\n]*/);
  if (m) return { rest: text.slice(m[0].length), id: m[0].replace(/[:\r\n]+$/, '') };
  m = text.match(/^([A-Za-z0-9][A-Za-z0-9_.\-]{2,59}):\r?\n/);
  if (m) return { rest: text.slice(m[0].length), id: m[1] };
  return { rest: text, id: null };
}

const report = [];

for (const name of fs.readdirSync(SRC_DIR).filter(f => f.endsWith('.txt')).sort()) {
  const src = path.join(SRC_DIR, name);
  const raw = fs.readFileSync(src, 'utf8');
  const eol = raw.includes('\r\n') ? '\r\n' : '\n';
  const endsWithNewline = raw.endsWith(eol);
  const lines = raw.split(/\r?\n/);
  if (endsWithNewline && lines[lines.length - 1] === '') lines.pop();

  let decoded = 0, failed = 0, notZstd = 0, prefixStripped = 0;
  let dq = 0, sq = 0; // 双引号 / 单引号 形式各解出多少
  const senderMap = [];
  const outLines = [];

  for (let li = 0; li < lines.length; li++) {
    const line = lines[li];
    const cands = findCandidates(line);
    if (cands.length === 0) { outLines.push(line); continue; }

    let done = false;
    for (const cand of cands) {
      let data;
      try { data = parsePyBytesRepr(cand.body); }
      catch (e) { continue; }              // 这个候选不是合法 repr，试下一个
      if (data.length < 4 || !data.subarray(0, 4).equals(ZSTD_MAGIC)) { notZstd++; continue; }
      let text;
      try { text = zlib.zstdDecompressSync(data).toString('utf8'); }
      catch (e) { failed++; continue; }
      const sp = stripSenderPrefix(text);
      if (sp.id) { prefixStripped++; senderMap.push(`${li + 1}\t${sp.id}\t${cand.head.split('|').pop().trim()}`); text = sp.rest; }
      text = text.replace(/\r\n|\r|\n/g, '⏎');
      if (cand.quote === '"') dq++; else sq++;
      outLines.push(`${cand.head}: ${text}`);
      decoded++;
      done = true;
      break;
    }
    if (!done) outLines.push(line);
  }

  const out = outLines.join(eol) + (endsWithNewline ? eol : '');
  const withNote = out.replace(
    /(^时间说明:.*$)/m,
    `$1${eol}修复说明: ${decoded} 条原本以 zstd 压缩字节串存留的消息已解码（2026-09-23 修复，原始文件未改动；真实发送者见同目录 _senders.tsv）`
  );
  fs.writeFileSync(path.join(DST_DIR, name), withNote, 'utf8');
  if (senderMap.length) {
    fs.writeFileSync(path.join(DST_DIR, name.replace(/\.txt$/, '_senders.tsv')),
      '原行号\t解出的真实wxid\t文件内显示名\n' + senderMap.join('\n') + '\n', 'utf8');
  }
  report.push({ name, total: lines.length, decoded, failed, notZstd, prefixStripped, senders: senderMap.length, dq, sq });
}

console.log('文件名'.padEnd(24), '总行'.padStart(7), '已解码'.padStart(8), '失败'.padStart(5),
            '非zstd'.padStart(6), '剥前缀'.padStart(6), '双引号'.padStart(6));
let T = { total: 0, decoded: 0, failed: 0, notZstd: 0, senders: 0, dq: 0 };
for (const r of report) {
  console.log(r.name.padEnd(24), String(r.total).padStart(7), String(r.decoded).padStart(8),
              String(r.failed).padStart(5), String(r.notZstd).padStart(6),
              String(r.prefixStripped).padStart(6), String(r.dq).padStart(6));
  T.total += r.total; T.decoded += r.decoded; T.failed += r.failed;
  T.notZstd += r.notZstd; T.senders += r.senders; T.dq += r.dq;
}
console.log('-'.repeat(60));
console.log('合计'.padEnd(24), String(T.total).padStart(7), String(T.decoded).padStart(8),
            String(T.failed).padStart(5), String(T.notZstd).padStart(6), String(T.senders).padStart(6),
            String(T.dq).padStart(6));
console.log(`\n输出目录: ${DST_DIR}`);
