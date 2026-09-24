#!/usr/bin/env node
'use strict';
/**
 * host-runner.js — 通过阿里云 ECD RunCommand 在云电脑上执行 PowerShell 脚本并回传输出。
 *
 * 由 `csdbg host-pull` 调用。设计要点：
 *   1. 自包含：只读 ~/.csdbg/ecd.json（ECD AK，与 SLS AK 分开），不依赖外部 aliyun 项目。
 *   2. ECD SDK 为 optionalDependency——base 安装保持零原生依赖；缺失时给出明确安装指引，不崩。
 *   3. 输出直接可喂 `csdbg cross --host-bundle`。
 *
 * 用法（内部由 csdbg host-pull 调起，一般不手动跑）:
 *   node host-runner.js <desktopId> <scriptFile.ps1> [timeoutSec] [--save out.txt]
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

function die(msg, code = 1) {
  process.stderr.write('host-runner: ' + msg + '\n');
  process.exit(code);
}

// ---- 解析参数
const args = process.argv.slice(2);
const saveIdx = args.indexOf('--save');
const savePath = saveIdx >= 0 ? args[saveIdx + 1] : null;
const positional = saveIdx >= 0
  ? args.filter((a, i) => i !== saveIdx && i !== saveIdx + 1)
  : args.slice();
const [desktopId, scriptFile, timeoutSecRaw] = positional;
const timeoutSec = Number(timeoutSecRaw || 120);

if (!desktopId || !scriptFile) {
  die('用法: host-runner.js <desktopId> <scriptFile.ps1> [timeoutSec] [--save out.txt]');
}
if (!fs.existsSync(scriptFile)) die(`脚本不存在: ${scriptFile}`);

// ---- 读 ECD 配置（AK 与 SLS 分开）
const ecdConfigPath = process.env.CSDBG_ECD_CONFIG
  || path.join(process.env.CSDBG_HOME || path.join(os.homedir(), '.csdbg'), 'ecd.json');
if (!fs.existsSync(ecdConfigPath)) {
  die(`ECD 配置不存在: ${ecdConfigPath}\n`
    + `创建它并填入 ECD AK（需 ecd:RunCommand / ecd:DescribeInvocations 权限）：\n`
    + `  {"access_key_id":"LTAI...","access_key_secret":"...","region":"cn-hangzhou"}`);
}
let cfg;
try {
  cfg = JSON.parse(fs.readFileSync(ecdConfigPath, 'utf8').replace(/^\uFEFF/, ''));
} catch (e) {
  die(`ECD 配置解析失败: ${e.message}`);
}
for (const k of ['access_key_id', 'access_key_secret', 'region']) {
  if (!cfg[k] || String(cfg[k]).startsWith('YOUR_')) die(`ECD 配置字段缺失或仍是占位符: ${k}`);
}

// ---- 载入 ECD SDK（optionalDependency，缺失给指引）
let ECDClient;
try {
  ({ ECDClient } = require('./ecd-client.js'));
} catch (e) {
  if (e.message.includes('ECD SDK not installed') || e.code === 'MODULE_NOT_FOUND') {
    die(`缺少 ECD SDK 依赖（@alicloud/ecd20200930 等）。\n`
      + `这是 optionalDependency，若安装时被跳过，手动补装：\n`
      + `  npm install --no-save @alicloud/ecd20200930 @alicloud/openapi-core\n`
      + `原始错误: ${e.message}`, 3);
  }
  throw e; // 其他错误直接抛
}

const client = new ECDClient(cfg.access_key_id, cfg.access_key_secret, cfg.region);
const script = fs.readFileSync(scriptFile, 'utf-8');

async function main() {
  let invokeId;
  try {
    const runResult = await client.runCommand(desktopId, script, { type: 'RunPowerShellScript', timeout: timeoutSec });
    invokeId = runResult.body.invokeId;
    process.stderr.write(`[invokeId] ${invokeId}\n`);
  } catch (e) {
    die(`下发失败: ${e.message}`, 2);
  }

  const maxAttempts = Math.max(10, Math.floor(timeoutSec / 2) + 15);
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    let inv;
    try {
      const result = await client.getInvocationResult(invokeId);
      inv = result.body.invocations && result.body.invocations[0]
        && result.body.invocations[0].invokeDesktops && result.body.invocations[0].invokeDesktops[0];
    } catch { continue; }
    const status = inv && inv.invocationStatus;
    if (status === 'Running' || status === 'Pending' || !status) continue;
    const output = Buffer.from((inv && inv.output) || '', 'base64').toString('utf-8');
    if (savePath) {
      fs.writeFileSync(savePath, output, 'utf-8');
      process.stderr.write(`[saved] ${savePath}\n`);
    }
    process.stdout.write(output);
    if (status !== 'Success') { process.stderr.write(`\n[status] ${status}\n`); process.exit(4); }
    process.stderr.write(`\n[status] Success, ${output.length} chars\n`);
    // RunCommand 输出上限约 24KB，超出会被截断——提醒
    if (output.length >= 24000) {
      process.stderr.write('[warn] 输出接近/超过 24KB，ECD 可能已截断；缩短时间窗或分批取数。\n');
    }
    return;
  }
  die('轮询超时（命令可能仍在执行，稍后可用 invokeId 复查）', 5);
}

main().catch((e) => die(`未预期错误: ${e.message}`, 9));
