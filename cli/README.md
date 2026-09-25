# cs-debug-toolkit · `csdbg`

BetterYeah 客服**多方日志排查工具包**的命令行版：把「服务端 SLS × RPA SLS × 运维记录 × 主机/IP 侧」四方数据
拉到同一条时间轴上交叉取证，配合 4 个 agent skill（`SKILL.md` 跨智能体通用格式）指向根因。

脚本层与大模型无关——任何能读文件、跑 shell 的智能体（ZCode / Claude Code / Codex CLI / Cursor…）
加载 skill 后，用它自带的大模型完成最后的交叉论证即可。

---

## 快速安装（一行搞定）

```bash
npm install -g cs-debug-toolkit-<ver>.tgz && csdbg init -i
```

这会：
1. 全局安装 `csdbg` 命令
2. 自动安装 Python 依赖（`aliyun-log-python-sdk`）
3. 交互式输入 **SLS 只读 AK**（需 `log:GetLogStoreLogs` 权限）
4. 安装 4 个 agent skill 到 `~/.agents/skills/` 或 `~/.claude/skills/`

完成后直接在 agent 里说："交叉分析 <会话ID>，为什么用户没收到回复"

---


> **新版 npm 的脚本门禁（2026-09-25 实测）**：安装时可能出现
> `install-scripts ... not yet covered by allowScripts` 警告——**可忽略**：
> 本包 postinstall 只打印欢迎语，不装技能、不写配置。若想让脚本执行，把包名一起给：
> `npm i -g --allow-scripts=cs-debug-toolkit <tgz/URL>`；**漏了包名** npm 会去当前目录找
> `package.json` 并报 `ENOENT .../package.json`（npm 自己的提示语不完整，容易踩）。
> 无论是否执行 postinstall，装完都要跑 `csdbg install` 刷新 agent 技能目录，否则技能还是旧版。

## 分步安装

```bash
# 1. 安装 CLI
npm install -g cs-debug-toolkit     # 公开发布版
npm install -g ./cs-debug-toolkit-<ver>.tgz   # 内部分发的 tgz

# 2. 初始化（交互式输入 AK）
csdbg init -i

# 或非交互式（命令行传参）
csdbg init --ak-id LTAIxxxxxx --ak-secret <secret>

# 或手动编辑配置
csdbg init
nano ~/.csdbg/channels.json  # 填 access_key_id / access_key_secret
```

### 前置条件

| 依赖 | 用途 | 说明 |
|---|---|---|
| **Node.js ≥ 14** | 跑 `csdbg` | 本 CLI 零第三方依赖 |
| **Python 3.9+** | 跑取证脚本 | 依赖 `aliyun-log-python-sdk`：`python -m pip install aliyun-log-python-sdk` |
| **`cs-cli`** | 运维记录 / 会话数据 | `npm i -g @bty/customer-service-cli`，再 `cs-cli auth login` |
| **SLS 只读 AK** | 服务端 + RPA 日志 | 需 `log:GetLogStoreLogs` 权限，填进 `~/.csdbg/channels.json` |

自检：`csdbg doctor`（逐项检查上面四条 + 两个 SLS 源是否真的查得通）。

---

## 命令一览

```
csdbg init                  生成 ~/.csdbg/channels.json 并安装 skill
csdbg doctor                环境自检
csdbg paths [--json]         打印 toolkit / scripts / config / temp 路径
csdbg install [--target D]   只装 skill（可重复 --target，默认 ~/.agents/skills + ~/.claude/skills）
csdbg env                   打印手动跑脚本所需的环境变量
csdbg version

csdbg server <参数>          服务端 SLS 日志
csdbg rpa    <参数>          RPA 端 SLS 日志（4 渠道）
csdbg ops    <参数>          运维操作记录（走本地 cs-cli）
csdbg cross  <参数>          ★ 四方交叉分析，产出证据包（--host-bundle 加主机本地日志）
csdbg gap    <参数>          会话间隔 / 事故窗口统计
csdbg host-events <参数>     目标设备 电源/重启/崩溃 事件（第④源；ECD 优先 / SLS 心跳兜底）
```

六个取证子命令是**原样透传**：参数与对应脚本完全一致，`csdbg <cmd> --help` 即脚本帮助。
写参数时可用 `--` 隔断 csdbg：

```bash
csdbg cross --conversation-id 0123456789abcdef0123456789abcdef --channel douyin \
      --start 2026-09-18T10:00:00 --end 2026-09-18T11:00:00

csdbg rpa --check
csdbg ops --start 2026-09-18T00:00:00 --end 2026-09-18T23:59:59 --keyword FAQ
csdbg server --conversation-id <id> --level ERROR --start <ISO> --end <ISO>

# 第④源（主机/IP 侧）：主机本地 Windows 事件日志
# SLS 里查到 hostname 后，有两条取本地日志的路：
# 路径 A：把采集脚本拷到目标主机跑，回传 zip
csdbg cross --conversation-id <id> --start <ISO> --end <ISO> \
      --host-bundle "./RpaLogCollect_20260918_1200.zip"

# 路径 B：有云电脑（ECD）权限时，远程拉起一步完成（首次需补装 ECD SDK）
npm install --no-save @alicloud/ecd20200930 @alicloud/openapi-core
echo '{"access_key_id":"LTAI...","access_key_secret":"...","region":"cn-hangzhou"}' > ~/.csdbg/ecd.json
csdbg host-pull <desktopId> scripts/collect_host_events.ps1 --save host.txt
csdbg cross --conversation-id <id> --start <ISO> --end <ISO> --host-bundle ./host.txt

# 路径 C（固化流程，推荐）：目标设备 电源/重启/崩溃 事件一键抓取
#    ECD 权限下自动上主机拉事件日志实锤；无 ECD 时用 SLS 心跳重建（uptime 重置=重启、
#    断流≥5min=睡眠/关机、同次开机版本变化=崩溃/升级）
csdbg host-events <设备ID> --start "2026-09-21T00:00:00" --end "2026-09-22T23:59:59"
#    或直接并入四方证据包：
csdbg cross --conversation-id <id> --start <ISO> --end <ISO> --host-events-equipment <设备ID>
```

`--host-bundle` 支持三种形态：采集脚本产出的 `.zip`、已解压目录、或远程拉起的纯文本；
`--host-events-equipment` / `--host-events-desktop` 由 `host_events_query.py` 自动抓取目标设备
电源/重启/崩溃事件并入证据包。证据包里会多出 `host.json` 与「§3b 主机/IP 侧证据」专题
（summary + 电源/重启/崩溃/网络读数），用于把定界从「冻结/崩溃/睡眠/网络 四选一」推进到进程级实锤。

---

## 数据放哪

CLI 模式下所有可变数据都在 `~/.csdbg/`（不在 `node_modules` 里，升级/重装 npm 包不会丢）：

```
~/.csdbg/
├── channels.json     # SLS 凭证 + 渠道→logstore 映射（含密钥，勿外传/勿提交 git）
└── temp/             # 证据包 evidence_*/ 与分析报告 analysis_*.md
```

报告落盘规范（结论三段式、报告框架含【影响面 · 风险 · 建议】收尾段、证据区只留 screenshots、结案清理）见随包分发的
`docs/REPORT_STANDARD.md`；CLI 模式下默认交付目录就是上面的 `~/.csdbg/temp/`。

覆盖默认位置：环境变量 `CSDBG_HOME`（改根目录）、`CSDBG_CONFIG`、`CSDBG_TEMP`。
`csdbg paths` 永远打印当前生效的路径；`csdbg env` 打印手动跑 Python 脚本时要设的变量。

---

## 配置 `channels.json`

`csdbg init` 生成的骨架长这样（字段说明见文件内 `_notes`）：

```jsonc
{
  "endpoint": "cn-hangzhou.log.aliyuncs.com",
  "access_key_id": "<只读 AK>",
  "access_key_secret": "<只读 AK Secret>",
  "rpa_project": "customer-servhub-log",
  "server_project": "bty-prod-ack-log",
  "channels": {
    "douyin":    { "name": "抖音",   "logstore": "project-douyin-rpa-prod" },
    "jingdong":  { "name": "京东",   "logstore": "project-jd-rpa-prod" },
    "pinduoduo": { "name": "拼多多", "logstore": "project-pdd-rpa-prod" },
    "qianniu":   { "name": "千牛",   "logstore": "qianniu-rpa-new-prod" }
  },
  "server": { "logstore": "customer-servhub-api" }
}
```

> logstore 名以 `scripts/channels.example.json` 为准，`csdbg init` 生成的骨架即来自该模板；
> 若 SLS 侧 logstore 有调整，改 `channels.json` 即可，勿改脚本。

非交互式配置（CI / 批量装机，注意 shell 历史会留痕）：

```bash
csdbg init --force --ak-id <AccessKeyId> --ak-secret <AccessKeySecret>
```

---

## 装进不同智能体

`csdbg init` / `csdbg install` 会把 `skill/` 下的技能复制到 agent 技能目录：

| 环境 | 默认目标 | 备注 |
|---|---|---|
| ZCode / Codex CLI | `~/.agents/skills/` | Codex ≥ 2025-12 用 `codex --enable skills`；装完重启会话 |
| Claude Code | `~/.claude/skills/` | 重启会话 |
| 其他（Cursor / 自研） | 自选 | `csdbg install --target <你的技能目录>`；或直接把 `csdbg paths` 里 `skill` 目录下的 `SKILL.md` 当系统提示喂给它 |

技能靠 `description` 里的触发词唤起（"交叉分析""多方日志""RPA 日志""会话根因分析"等），
换大模型只影响最后论证的行文，取证链路不变。

---

## 六个技能

| 技能 | 定位 | 产物 |
|---|---|---|
| **`cs-log-cross`** | ★ 主入口：服务端 × RPA × 运维 × 主机/IP 四方交叉定责 | `~/.csdbg/temp/analysis_*.md`（规范见 `docs/REPORT_STANDARD.md`） |
| **`cs-fault-playbook`** | ★ 故障类型手册：22 类已积累问题 → 标准查询流程 → 判定 → 结论模板 | 归类结果 + 取证流程 |
| `cs-rpa-log` | 单源：4 渠道 RPA 日志快速查询 | 时间线 / JSON |
| `cs-conversation-debug` | 单链路：会话内单条回复根因 debug | 终端报告 |
| `e-chat-trace` | 单链路：消息全链路（Agent trace + RPA 自动串联） | 终端报告 |

`e-chat-trace` 读用户环境变量 `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET`，与 `csdbg` 配置互不影响。

---

## 常见问题

- **`csdbg` 找不到 python**：设 `CSDBG_PYTHON` 指向解释器全路径（Windows 下 `py -3` 自动兜底）。
- **中文乱码**：CLI 已自动设 `PYTHONIOENCODING=utf-8`；手动跑脚本时自己设。
- **JSON 解析报错**：`cs-cli` 输出尾部带版本升级提示噪音，脚本用 `raw_decode` 容错；自己写解析别 `json.loads` 整个 stdout。
- **`--output` 文件没生成**：检查是不是把 stdout 接了 `| head`（SIGPIPE 会杀死进程）。
- **返回行数正好等于 `--limit`**：视为疑似截断，缩小时间窗重拉，别直接下"没有日志"的结论。
- **`--check` 报 KeyError**：`channels.json` 是旧 schema，`csdbg init --force` 重新生成。

## 安全边界

1. `~/.csdbg/channels.json` 含 SLS AccessKey，**不要提交 git、不要外发**；本包不含任何密钥。
2. `~/.csdbg/temp/` 的报告含真实店铺名、会话 ID、出口 IP 等客户数据，外发前先脱敏。
3. 每人用**自己的** cs-cli 账号与 AK，便于审计。
4. 全流程只读取证：skill 已约束不得执行 `sa update` / `faq update` 等写命令。
