#!/usr/bin/env node
'use strict';
/**
 * csdbg — CS-Debug-Toolkit 命令行入口
 *
 * 设计要点:
 *   1. 零第三方依赖（只用 node 内置模块），npm 装完即可用，无原生编译风险。
 *   2. 本文件既是 CLI，也是"路径解析器"：把 toolkit / config / temp 三个位置
 *      固化下来，用环境变量传给 Python 脚本（CSDBG_CONFIG / CSDBG_TEMP），
 *      让 skill 文档不必写死路径。
 *   3. 透传子命令（server/rpa/ops/cross/gap）= 直接把参数交给对应 .py，
 *      参数与脚本 --help 完全一致，不做二次解析。
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const PKG_ROOT = path.resolve(__dirname, '..');
const SCRIPTS_DIR = path.join(PKG_ROOT, 'scripts');
const SKILLS_DIR = path.join(PKG_ROOT, 'skill');
const TEMPLATES_DIR = path.join(PKG_ROOT, 'templates');

const HOME_DIR = process.env.CSDBG_HOME || path.join(os.homedir(), '.csdbg');
const CONFIG_PATH = process.env.CSDBG_CONFIG || path.join(HOME_DIR, 'channels.json');
const TEMP_DIR = process.env.CSDBG_TEMP || path.join(HOME_DIR, 'temp');

// 透传子命令 → 脚本文件名（键即 csdbg 的子命令名）
const PASSTHROUGH = {
  server: 'server_log_query.py',
  rpa: 'rpa_log_query.py',
  ops: 'ops_log_query.py',
  cross: 'cross_analysis.py',
  gap: 'gap_analysis.py',
  'host-events': 'host_events_query.py',
  signatures: 'fault_signatures.py',
};

const DEFAULT_SKILL_TARGETS = [
  path.join(os.homedir(), '.agents', 'skills'),
  path.join(os.homedir(), '.claude', 'skills'),
];

// ------------------------------------------------------------------ 输出工具
const useColor = process.stdout.isTTY && !process.env.NO_COLOR;
const c = (code, s) => (useColor ? `\x1b[${code}m${s}\x1b[0m` : s);
const bold = (s) => c('1', s);
const dim = (s) => c('2', s);
const green = (s) => c('32', s);
const yellow = (s) => c('33', s);
const red = (s) => c('31', s);
const cyan = (s) => c('36', s);

function info(msg) { process.stdout.write(msg + '\n'); }
function ok(msg) { info(`  ${green('✓')} ${msg}`); }
function warn(msg) { info(`  ${yellow('!')} ${msg}`); }
function fail(msg) { info(`  ${red('✗')} ${msg}`); }
function step(msg) { info(`\n${bold(msg)}`); }

function die(msg, code = 1) {
  process.stderr.write(red('csdbg: ') + msg + '\n');
  process.exit(code);
}

// ------------------------------------------------------------------ 路径解析
function pkgVersion() {
  try {
    return JSON.parse(fs.readFileSync(path.join(PKG_ROOT, 'package.json'), 'utf8')).version || '0.0.0';
  } catch {
    return '0.0.0';
  }
}

/** 找可用的 Python 3 解释器：CSDBG_PYTHON > python3 > python > py -3。返回 argv 前缀数组或 null。 */
let _pyCache;
function findPython() {
  if (_pyCache !== undefined) return _pyCache;
  const candidates = [];
  if (process.env.CSDBG_PYTHON) {
    candidates.push(process.env.CSDBG_PYTHON.split(/\s+/).filter(Boolean));
  }
  candidates.push(['python3'], ['python'], ['py', '-3']);
  for (const argv of candidates) {
    const r = spawnSync(argv[0], argv.slice(1).concat(['-c', 'import sys;print(sys.version.split()[0])']), {
      encoding: 'utf8',
      windowsHide: true,
    });
    if (r.status === 0 && /\d+\.\d+/.test(r.stdout || '')) {
      _pyCache = { argv, version: (r.stdout || '').trim() };
      return _pyCache;
    }
  }
  _pyCache = null;
  return null;
}

function scriptPath(name) {
  const p = path.join(SCRIPTS_DIR, name);
  if (!fs.existsSync(p)) die(`脚本缺失: ${p}\n（npm 包不完整，请重装: npm i -g cs-debug-toolkit）`);
  return p;
}

function ensureTempDir() {
  try { fs.mkdirSync(TEMP_DIR, { recursive: true }); } catch { /* 交给脚本报错 */ }
}

/** 跑一个 toolkit 脚本；extraEnv 覆盖环境。返回 exit code。 */
function runPython(scriptName, args, extraEnv, timeoutMs) {
  const r = spawnPython(scriptName, args, extraEnv, 'inherit', timeoutMs);
  return r.status === null ? 1 : r.status;
}

/** 同上但捕获输出（doctor 用：只在失败时把输出打出来）。 */
function runPythonCapture(scriptName, args, extraEnv, timeoutMs) {
  return spawnPython(scriptName, args, extraEnv, 'pipe', timeoutMs);
}

// 透传数据查询命令的默认超时（SLS 慢查询/挂起时防止 csdbg 无限等待）
const DEFAULT_CMD_TIMEOUT = 900000;   // 15 分钟
const CHECK_CMD_TIMEOUT = 180000;     // doctor --check 3 分钟

function spawnPython(scriptName, args, extraEnv, stdio, timeoutMs) {
  const py = findPython();
  if (!py) {
    if (stdio === 'inherit') fail('未找到 Python 3。装好 Python 后重试，或用 CSDBG_PYTHON 指定解释器路径。');
    return { status: 127, stdout: '', stderr: 'python not found' };
  }
  ensureTempDir();
  const env = Object.assign({}, process.env, {
    CSDBG_CONFIG: CONFIG_PATH,
    CSDBG_TEMP: TEMP_DIR,
    PYTHONIOENCODING: 'utf-8',   // Windows 中文输出不乱码
    PYTHONUTF8: '1',
  }, extraEnv || {});
  const timeout = timeoutMs || DEFAULT_CMD_TIMEOUT;
  const r = spawnSync(py.argv[0], py.argv.slice(1).concat([scriptPath(scriptName)], args), {
    stdio,
    encoding: 'utf8',
    env,
    windowsHide: stdio !== 'inherit',
    timeout,
  });
  if (r.error && r.error.killed) {   // 超时被 kill
    const msg = `执行超时（>${Math.round(timeout / 60000)} 分钟），已终止。可缩小时间窗或 --limit 后重试。`;
    if (stdio === 'inherit') fail(msg);
    return { status: 124, stdout: '', stderr: msg };
  }
  if (r.error) {
    if (stdio === 'inherit') fail(`启动失败: ${r.error.message}`);
    return { status: 127, stdout: '', stderr: r.error.message };
  }
  return r;
}

// ------------------------------------------------------------- 配置读写/校验
function readConfig() {
  let raw;
  try {
    raw = fs.readFileSync(CONFIG_PATH, 'utf8');
  } catch (e) {
    return { error: `读取失败: ${e.message}` };
  }
  let cfg;
  try {
    cfg = JSON.parse(raw.replace(/^\uFEFF/, ''));
  } catch (e) {
    return { error: `JSON 解析失败: ${e.message}（旧版 schema？从 channels.example.json 重新复制）` };
  }
  const problems = [];
  const missing = ['endpoint', 'access_key_id', 'access_key_secret'].filter((k) => !cfg[k]);
  if (missing.length) problems.push(`缺少顶层字段: ${missing.join(', ')}`);
  if (!cfg.channels || !Object.keys(cfg.channels).length) problems.push('缺少 channels 段（RPA 渠道→logstore 映射）');
  if (!cfg.server || !cfg.server.logstore) problems.push('缺少 server.logstore（服务端日志用）');
  if (!cfg.server_project) problems.push('缺少 server_project');
  const ak = String(cfg.access_key_id || '');
  if (cfg.access_key_id && /^(<|YOUR|xxx|LTAI_?placeholder)/i.test(ak)) problems.push('access_key_id 还是模板占位符');
  return { config: cfg, problems };
}

function configTemplatePath() {
  const local = path.join(SCRIPTS_DIR, 'channels.example.json');
  if (!fs.existsSync(local)) die(`配置模板缺失: ${local}`);
  return local;
}

// ---------------------------------------------------------------- 子命令实现
function cmdHelp() {
  const v = pkgVersion();
  info(`${bold('csdbg')} ${dim('v' + v)} — CS-Debug-Toolkit 命令行（服务端 × RPA × 运维 × 主机/IP 四方日志排查）`);
  info('');
  info(bold('环境准备'));
  info(`  ${cyan('init')}                 生成配置骨架 ${dim('~/.csdbg/channels.json')} 并装 skill`);
  info(`  ${cyan('doctor')}               环境自检（Python/依赖/配置/cs-cli 认证/SLS 连通/skill 安装）`);
  info(`  ${cyan('selftest')}             离线自检（无网络/无 AK，验证工具链与依赖完整性）`);
  info(`  ${cyan('paths')} [--json]       打印 toolkit / scripts / config / temp / skill 路径`);
  info(`  ${cyan('install')} [选项]        只装 skill 到 agent 技能目录`);
  info(`  ${cyan('env')}                 打印脚本所需环境变量（供手动跑 python 脚本时参照）`);
  info('');
  info(bold('查日志（参数与脚本 --help 一致，原样透传）'));
  info(`  ${cyan('server')} <参数>          服务端 SLS 日志   ${dim('server_log_query.py')}`);
  info(`  ${cyan('rpa')} <参数>             RPA 端 SLS 日志   ${dim('rpa_log_query.py')}`);
  info(`  ${cyan('ops')} <参数>             运维操作记录      ${dim('ops_log_query.py')}`);
  info(`  ${cyan('cross')} <参数>           ★ 四方交叉分析     ${dim('cross_analysis.py')}`);
  info(`  ${cyan('gap')} <参数>             会话间隔/事故窗口  ${dim('gap_analysis.py')}`);
  info(`  ${cyan('signatures')} <参数>      故障签名知识库（--list/--check/--match-dir 复检）${dim('fault_signatures.py')}`);
  info(`  ${cyan('host-pull')} <参数>       远程拉起主机日志（需 ECD AK）${dim('—— host-pull --help 看用法')}`);
  info(`  ${cyan('host-events')} <参数>   目标设备 电源/重启/崩溃 事件（ECD 优先/SLS 兜底）${dim('host_events_query.py')}`);
  info('');
  info(bold('示例'));
  info(`  csdbg doctor`);
  info(`  csdbg rpa --check`);
  info(`  csdbg cross --conversation-id 0123456789abcdef... --channel douyin \\`);
  info(`        --start 2026-09-18T10:00:00 --end 2026-09-18T11:00:00`);
  info('');
  info(`${dim('子命令参数里用 -- 可隔断 csdbg 自身的解析，如: csdbg server -- --check')}`);
  info(`${dim('更多说明: ') }${path.join(PKG_ROOT, 'README.md')}`);
}

function cmdPaths(args) {
  const configExists = fs.existsSync(CONFIG_PATH);
  const data = {
    toolkit: PKG_ROOT,
    scripts: SCRIPTS_DIR,
    skill: SKILLS_DIR,
    templates: TEMPLATES_DIR,
    config: CONFIG_PATH,
    config_exists: configExists,
    temp: TEMP_DIR,
    home: HOME_DIR,
    python: (findPython() || {}).version || null,
  };
  if (args.includes('--json')) {
    info(JSON.stringify(data, null, 2));
    return 0;
  }
  info(`${bold('toolkit  ')} ${PKG_ROOT}`);
  info(`${bold('scripts  ')} ${SCRIPTS_DIR}`);
  info(`${bold('skill    ')} ${SKILLS_DIR}`);
  info(`${bold('config   ')} ${CONFIG_PATH}${configExists ? dim('  (已存在)') : red('  (缺失, 先跑 csdbg init)')}`);
  info(`${bold('temp     ')} ${TEMP_DIR}`);
  info(`${bold('python   ')} ${data.python || red('未找到 Python 3')}`);
  return 0;
}

function cmdEnv() {
  const isWin = process.platform === 'win32';
  info(dim('# 手动跑 python 脚本时先设这些变量（csdbg 子命令会自动带上）'));
  if (isWin) {
    info(`$env:CSDBG_CONFIG='${CONFIG_PATH}'`);
    info(`$env:CSDBG_TEMP='${TEMP_DIR}'`);
    info(`$env:PYTHONIOENCODING='utf-8'`);
  } else {
    info(`export CSDBG_CONFIG='${CONFIG_PATH}'`);
    info(`export CSDBG_TEMP='${TEMP_DIR}'`);
    info(`export PYTHONIOENCODING='utf-8'`);
  }
  return 0;
}

function cmdHostPull(args) {
  if (args.length < 2 || args.includes('--help') || args.includes('-h')) {
    info(`${bold('csdbg host-pull')} — 远程拉起主机本地 Windows 事件日志（需 ECD 权限）`);
    info('');
    info(bold('用法'));
    info(`  csdbg host-pull <desktopId> <scriptPath.ps1> [timeoutSec] [--save out.txt]`);
    info('');
    info(bold('说明'));
    info(`  通过阿里云 ECD RunCommand 在云电脑上执行 PowerShell 脚本并回传输出。`);
    info(`  产出可直接喂给 ${cyan('csdbg cross --host-bundle <out.txt>')}。`);
    info('');
    info(bold('前置条件'));
    info(`  1. ECD 凭证配置在 ${dim('~/.csdbg/ecd.json')}，格式：`);
    info(`     { "access_key_id": "...", "access_key_secret": "...", "region": "cn-..." }`);
    info(`  2. 安装 ECD SDK optionalDependencies（首次使用需手动补装）：`);
    info(`     ${cyan('npm install --no-save @alicloud/ecd20200930 @alicloud/openapi-core')}`);
    info('');
    info(bold('示例'));
    info(`  # 内置采集脚本（toolkit 自带 collect_host_events.ps1）`);
    info(`  csdbg host-pull ecd-abc123 scripts/collect_host_events.ps1 --save host.txt`);
    info('');
    info(`  # 自定义脚本`);
    info(`  csdbg host-pull ecd-abc123 ./my-script.ps1 180 --save result.txt`);
    return args.includes('--help') || args.includes('-h') ? 0 : 1;
  }

  const ecdConfigPath = process.env.CSDBG_ECD_CONFIG || path.join(HOME_DIR, 'ecd.json');
  if (!fs.existsSync(ecdConfigPath)) {
    fail(`ECD 配置不存在: ${ecdConfigPath}`);
    info('');
    info(`创建该文件并填入 ECD AK（${red('与 SLS AK 分开管理')}）：`);
    info(dim(`{
  "access_key_id": "LTAI...",
  "access_key_secret": "...",
  "region": "cn-hangzhou"
}`));
    return 1;
  }

  const runnerPath = path.join(__dirname, '..', 'lib', 'host-runner.js');
  if (!fs.existsSync(runnerPath)) {
    fail(`host-runner.js 缺失: ${runnerPath}`);
    return 1;
  }

  info(`${dim('[host-pull]')} runner: ${runnerPath}`);
  info(`${dim('[host-pull]')} ecd-config: ${ecdConfigPath}`);

  const env = Object.assign({}, process.env, {
    CSDBG_HOME: HOME_DIR,
    CSDBG_ECD_CONFIG: ecdConfigPath,
  });

  const r = spawnSync(process.execPath, [runnerPath].concat(args), {
    stdio: 'inherit',
    env,
    windowsHide: false,
  });
  return r.status === null ? 1 : r.status;
}

function parseInstallArgs(args) {
  const opts = { targets: [], force: false, dryRun: false, list: false, quiet: false };
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === '--target') {
      const v = args[++i];
      if (!v) die('--target 需要一个目录参数');
      opts.targets.push(path.resolve(v));
    } else if (a === '--force') opts.force = true;
    else if (a === '--dry-run') opts.dryRun = true;
    else if (a === '--list') opts.list = true;
    else if (a === '--quiet') opts.quiet = true;
    else die(`install: 未知参数 ${a}`);
  }
  if (!opts.targets.length) opts.targets = DEFAULT_SKILL_TARGETS.slice();
  return opts;
}

function listSkills() {
  if (!fs.existsSync(SKILLS_DIR)) return [];
  return fs.readdirSync(SKILLS_DIR)
    .filter((n) => fs.existsSync(path.join(SKILLS_DIR, n, 'SKILL.md')))
    .sort();
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === '__pycache__') continue;
      copyDir(s, d);
    } else if (entry.isFile()) {
      fs.copyFileSync(s, d);
    }
  }
}

function cmdInstall(args) {
  const opts = parseInstallArgs(args);
  const skills = listSkills();
  if (!skills.length) die(`没有找到任何技能（${SKILLS_DIR} 下无含 SKILL.md 的目录）`);

  if (opts.list) {
    info(`${bold('技能')}（${skills.length} 个，源: ${SKILLS_DIR}）`);
    skills.forEach((s) => info(`  - ${s}`));
    info(`\n${bold('安装目标')}（可用 --target 覆盖）`);
    opts.targets.forEach((t) => info(`  - ${t}`));
    return 0;
  }

  info(`${bold('安装 skill')} ${dim(`v${pkgVersion()}`)} → ${opts.targets.length} 个目标目录`);
  let copied = 0;
  let failed = 0;
  for (const target of opts.targets) {
    for (const s of skills) {
      const dest = path.join(target, s);
      if (opts.dryRun) {
        if (!opts.quiet) info(`  ${dim('[dry-run]')} ${dest}`);
        continue;
      }
      try {
        // 默认目标目录可能还不存在（该 agent 从未装过 skill）——直接创建，
        // 否则会静默跳过、使用者以为装好了但 agent 看不到。
        copyDir(path.join(SKILLS_DIR, s), dest);
        copied++;
        if (!opts.quiet) ok(`${s} → ${dest}`);
      } catch (e) {
        failed++;
        fail(`复制失败 ${dest}: ${e.message}`);
      }
    }
  }
  if (!opts.dryRun) {
    info('');
    if (failed) {
      info(red(`有 ${failed} 个技能写入失败。`));
    } else if (copied) {
      info(green(`完成：共写入 ${copied} 个技能目录。重启 agent 会话后即可用触发词唤起（如"交叉分析"）。`));
      info(dim('  目标目录里没在用的 agent，其技能目录空放着无副作用；要用别的目录: csdbg install --target <目录>'));
    } else {
      info(yellow('没有写入任何技能目录。'));
    }
  }
  return failed ? 1 : 0;
}

function cmdInit(args) {
  const force = args.includes('--force');
  const noSkills = args.includes('--no-skills');
  const interactive = args.includes('--interactive') || args.includes('-i');
  let akId = grabFlag(args, '--ak-id');
  let akSecret = grabFlag(args, '--ak-secret');
  let rc = 0;

  step('1/5 数据目录');
  fs.mkdirSync(HOME_DIR, { recursive: true });
  fs.mkdirSync(TEMP_DIR, { recursive: true });
  ok(`${HOME_DIR}`);

  step('2/5 Python 依赖');
  const py = findPython();
  if (!py) {
    warn('未找到 Python 3——查询脚本需要它，请先装 Python 3.9+ 并加入 PATH');
    rc = 1;
  } else {
    const dep = spawnSync(py.argv[0], py.argv.slice(1).concat(['-c', 'import aliyun.log']), {
      encoding: 'utf8', windowsHide: true,
    });
    if (dep.status === 0) {
      ok(`aliyun-log-python-sdk 已就位  ${dim('(' + py.argv.join(' ') + ')')}`);
    } else {
      info(`    ${dim('装 aliyun-log-python-sdk …')}`);
      const pip = spawnSync(py.argv[0], py.argv.slice(1).concat(['-m', 'pip', 'install', '-q', 'aliyun-log-python-sdk']), {
        stdio: 'inherit', windowsHide: true,
      });
      if (pip.status === 0) ok('aliyun-log-python-sdk 安装完成');
      else {
        warn(`自动装失败，请手动执行: ${py.argv.join(' ')} -m pip install aliyun-log-python-sdk`);
        rc = 1;
      }
    }
  }

  step('3/5 SLS 配置');
  const needPrompt = !akId || !akSecret;
  if (fs.existsSync(CONFIG_PATH) && !force) {
    warn(`已存在，保留不动: ${CONFIG_PATH}（要重置加 --force）`);
  } else {
    // 交互式输入 AK（显式 -i 时；支持 TTY 与管道输入）
    if (interactive && needPrompt) {
      info('');
      info(bold('请输入 SLS 只读 AK（需 log:GetLogStoreLogs 权限）：'));
      if (!akId) {
        akId = promptLine('  Access Key ID: ');
      }
      if (!akSecret) {
        akSecret = promptLine('  Access Key Secret: ');
      }
      info('');
    }

    const tmpl = JSON.parse(fs.readFileSync(configTemplatePath(), 'utf8'));
    if (akId) tmpl.access_key_id = akId;
    if (akSecret) tmpl.access_key_secret = akSecret;
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(tmpl, null, 2) + '\n', 'utf8');
    ok(`已生成 ${CONFIG_PATH}`);
  }

  if (!akId || !akSecret) {
    info('');
    warn('还差 SLS 只读 AK（需 log:GetLogStoreLogs 权限）：');
    info(`    编辑 ${CONFIG_PATH}，填 access_key_id / access_key_secret 两个字段。`);
    info(`    或重跑: csdbg init --force --ak-id <id> --ak-secret <secret>`);
    info(`    或重跑: csdbg init --force -i  （交互式输入）`);
  }

  step('4/5 安装 skill');
  if (noSkills) {
    warn('已按 --no-skills 跳过');
  } else {
    rc = cmdInstall(['--quiet']) || rc;
  }

  step('5/5 环境自检');
  info(`    ${dim('跑: csdbg doctor（含 SLS 连通性验证）')}`);
  info(`    ${dim('跑: csdbg selftest（离线自检，无网络/无 AK 也能验证工具链）')}`);
  info('');
  info(bold('可选：ECD 主机侧证据'));
  const ecdCfg = process.env.CSDBG_ECD_CONFIG || path.join(HOME_DIR, 'ecd.json');
  if (fs.existsSync(ecdCfg)) {
    ok(`ECD 配置已就位: ${ecdCfg}`);
  } else {
    info(`  需要"远程拉起主机日志/电源重启崩溃事件实锤"时再配（与 SLS AK 分开管理）：`);
    info(`    ${dim('创建 ' + ecdCfg + '，填入 access_key_id / access_key_secret / region')}`);
    info(`    ${dim('详见: csdbg host-pull --help')}`);
  }
  info('');
  info(bold('下一步'));
  info(`  1. 填好 AK（见上）`);
  info(`  2. ${cyan('csdbg doctor')}  自检，全绿即就绪`);
  info(`  3. 在 agent 里说："交叉分析 <会话ID>，为什么用户没收到回复"`);
  return rc;
}

/** 同步读一行用户输入（零依赖：直接读 fd 0）。返回 trim 后的字符串，EOF/无 TTY 返回 ''。 */
function promptLine(question) {
  process.stdout.write(question);
  const buf = Buffer.alloc(1);
  let line = '';
  try {
    while (true) {
      let n;
      try {
        n = fs.readSync(0, buf, 0, 1, null);
      } catch (e) {
        if (e.code === 'EAGAIN') continue;   // 非阻塞管道，重试
        if (e.code === 'EOF') break;
        throw e;
      }
      if (n === 0) break;                     // EOF
      const ch = buf.toString('utf8', 0, 1);
      if (ch === '\n') break;
      if (ch === '\r') continue;
      line += ch;
    }
  } catch { /* 读取失败当空处理 */ }
  return line.trim();
}

function grabFlag(args, name) {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] && !args[i + 1].startsWith('--') ? args[i + 1] : null;
}

function cmdDoctor() {
  info(`${bold('csdbg doctor')} ${dim(`v${pkgVersion()} · ${PKG_ROOT}`)}`);
  const fails = [];

  step('运行时');
  const major = Number(process.versions.node.split('.')[0]);
  if (major >= 14) ok(`Node ${process.versions.node}`);
  else { fail(`Node ${process.versions.node} 过旧（需 ≥14）`); fails.push('node'); }

  const py = findPython();
  if (py) {
    ok(`Python ${py.version}  ${dim('(' + py.argv.join(' ') + ')')}`);
    const dep = spawnSync(py.argv[0], py.argv.slice(1).concat(['-c', 'import aliyun.log; print("ok")']), {
      encoding: 'utf8', windowsHide: true,
    });
    if (dep.status === 0) ok('aliyun-log-python-sdk 已安装');
    else {
      fail('aliyun-log-python-sdk 未安装');
      info(`      ${dim(py.argv.join(' ') + ' -m pip install aliyun-log-python-sdk')}`);
      fails.push('sdk');
    }
  } else {
    fail('未找到 Python 3（装好后重试，或用 CSDBG_PYTHON 指定解释器）');
    fails.push('python');
  }

  step('配置文件');
  if (!fs.existsSync(CONFIG_PATH)) {
    fail(`不存在: ${CONFIG_PATH}`);
    info(`      ${dim('跑 csdbg init 生成骨架')}`);
    fails.push('config');
  } else {
    const r = readConfig();
    if (r.error) { fail(r.error); fails.push('config'); }
    else if (r.problems.length) {
      r.problems.forEach((p) => fail(p));
      info(`      ${dim('对照模板修: ' + configTemplatePath())}`);
      fails.push('config');
    } else {
      const chans = Object.keys(r.config.channels).join('/');
      ok(`可解析，AK 就位  ${dim(`channels=${chans}`)}`);
    }
  }

  step('CSR 数据源 cs-cli');
  const shell = process.platform === 'win32';
  const which = spawnSync(shell ? 'where' : 'which', ['cs-cli'], { encoding: 'utf8', shell, windowsHide: true });
  if (which.status !== 0) {
    fail('PATH 里没有 cs-cli');
    info(`      ${dim('npm i -g @bty/customer-service-cli')}`);
    fails.push('cs-cli');
  } else {
    const who = spawnSync('cs-cli', ['auth', 'whoami'], { encoding: 'utf8', shell, windowsHide: true, timeout: 60000 });
    const out = (who.stdout || '') + (who.stderr || '');
    // 只认 JSON 结构里的 success:true（带引号的键），避免把任意首行含 "true" 的输出误判为已认证
    if (/["']success["']\s*:\s*true/i.test(out)) {
      ok('cs-cli 已认证');
    } else {
      fail('cs-cli 未登录或异常');
      info(`      ${dim('cs-cli auth login')}`);
      fails.push('cs-cli-auth');
    }
  }

  step('skill 安装');
  const skills = listSkills();
  let installedAny = false;
  for (const t of DEFAULT_SKILL_TARGETS) {
    if (!fs.existsSync(t)) continue;
    const have = skills.filter((s) => fs.existsSync(path.join(t, s, 'SKILL.md')));
    if (have.length === skills.length && skills.length) {
      ok(`${t}  ${dim(have.length + '/' + skills.length)}`);
      installedAny = true;
    } else {
      warn(`${t} 只有 ${have.length}/${skills.length} 个`);
    }
  }
  if (!installedAny) {
    warn('未在默认技能目录发现完整安装');
    info(`      ${dim('跑 csdbg install（或 --target <你的 agent 技能目录>）')}`);
  }

  step('日志源连通性（需要配置就绪）');
  if (fails.includes('config')) {
    warn('配置未就绪，跳过 SLS 连通测试');
  } else {
    for (const [label, script] of [['RPA 端', 'rpa_log_query.py'], ['服务端', 'server_log_query.py']]) {
      const r = runPythonCapture(script, ['--check'], undefined, CHECK_CMD_TIMEOUT);
      if (r.status === 0) ok(`${label} SLS 源可查`);
      else {
        fail(`${label} SLS 源查询失败`);
        info(dim(((r.stdout || '') + (r.stderr || '')).trim().split('\n').slice(0, 8).map((l) => '      ' + l).join('\n')));
        fails.push('sls:' + script);
      }
    }
  }

  info('');
  if (fails.length) {
    info(red(`自检未通过 ${fails.length} 项: `) + fails.join(', '));
    return 1;
  }
  info(green('全部通过 ✅  可以开始排查了。'));
  info(`${dim('试试: csdbg cross --conversation-id <会话ID> --start <ISO> --end <ISO>')}`);
  return 0;
}

function cmdSelftest() {
  info(`${bold('csdbg selftest')} ${dim(`v${pkgVersion()} · ${PKG_ROOT}`)}`);
  const r = runPythonCapture('selftest.py', [], undefined, CHECK_CMD_TIMEOUT);
  info((r.stdout || '').trimEnd());
  if (r.status !== 0) {
    fail('离线自检未通过（依赖缺失或安装不完整）');
    const err = (r.stderr || '').trim();
    if (err) info(dim(err.split('\n').slice(0, 10).map((l) => '      ' + l).join('\n')));
    return 1;
  }
  return 0;
}

function cmdPostinstall() {
  // npm 生命周期脚本：只打印引导，绝不因环境缺失而失败（否则会打断 npm i -g）
  try {
    const skills = listSkills();
    info('');
    info(bold('cs-debug-toolkit') + ` 已安装（${skills.length} 个技能）`);
    info(`  下一步  ${cyan('csdbg init')}    生成配置 + 安装 skill 到 agent 技能目录`);
    info(`  然后    ${cyan('csdbg doctor')}  自检环境`);
    info('');
  } catch { /* ignore */ }
  return 0;
}

// -------------------------------------------------------------------- 主入口
function main(argv) {
  if (argv.includes('--version') || argv.includes('-v')) {
    info(pkgVersion());
    return 0;
  }
  const cmd = argv[0];
  const rest = argv.slice(1);

  if (!cmd || cmd === 'help' || cmd === '--help' || cmd === '-h') {
    cmdHelp();
    return 0;
  }
  if (cmd === '--postinstall') return cmdPostinstall();

  // 透传子命令：支持 `csdbg server -- --check` 的 `--` 隔断写法
  if (PASSTHROUGH[cmd]) {
    const sep = rest.indexOf('--');
    const args = sep >= 0 ? rest.slice(0, sep).concat(rest.slice(sep + 1)) : rest;
    return runPython(PASSTHROUGH[cmd], args);
  }

  switch (cmd) {
    case 'init': return cmdInit(rest);
    case 'doctor': return cmdDoctor();
    case 'selftest': return cmdSelftest();
    case 'install': return cmdInstall(rest);
    case 'paths': return cmdPaths(rest);
    case 'env': return cmdEnv();
    case 'host-pull': return cmdHostPull(rest);
    case 'version': info(pkgVersion()); return 0;
    default:
      fail(`未知子命令: ${cmd}`);
      info(`跑 ${cyan('csdbg help')} 看用法。`);
      return 2;
  }
}

process.exit(main(process.argv.slice(2)));
