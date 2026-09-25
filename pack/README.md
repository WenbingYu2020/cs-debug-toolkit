# CS-Debug-Toolkit：BetterYeah 客服多方日志排查工具包（开箱即用版）

把「客服对话问题的多方日志取证与定责」能力打包成可分发工具：
**agent skill（流程指挥）+ 数据拉取/分析脚本（确定性取证）**。
脚本层与大模型无关——任何能读文件、跑 shell 的智能体（ZCode / Claude Code / Codex CLI /
Cursor 等）加载 skill 后，用它自带的大模型完成最后的交叉论证即可。

## 技能一览

| 技能 | 定位 | 输入 | 产物 |
|------|------|------|------|
| **`cs-log-cross`** | ★ 主入口：服务端 × RPA × 运维 × 主机/IP 四方日志交叉定责 | 锚点 ID/关键词 + 时间窗口 + 问题描述 | `temp/analysis_*.md` 报告（规范见 `docs/REPORT_STANDARD.md`） |
| **`cs-fault-playbook`** | ★ 故障类型手册：22 类已积累问题 → 标准查询流程 → 判定 → 结论模板 | 现象描述 / 证据包 | 归类 + 取证流程 |
| `cs-rpa-log` | 单源：4 渠道 RPA 日志快速查询 | 渠道 + 设备/会话/关键词 | 时间线 / JSON |
| `cs-conversation-debug` | 单链路：会话内单条回复根因 debug | `conversation_id` | 终端报告 |
| `e-chat-trace` | 单链路：消息全链路（Agent trace + RPA 日志自动串联） | `conversation_id` | 终端报告 |

配套脚本（`scripts/`）：`cross_analysis.py`（四方对齐→证据包，第④源用 `--host-bundle` 喂入）、`server_log_query.py` /
`rpa_log_query.py`（SLS 两源）、`ops_log_query.py`（本地 cs-cli 运维记录）、
`gap_analysis.py`（会话间隔/事故窗口统计）、`collect_rpa_logs.ps1`（事故主机日志采集）、
`sls_sql_query.py`（SLS SQL LIKE 精确子串，绕开中文分词）、`srv_summarize.py`（服务端日志摘要）、
`conv_timeline.py` / `conv_list_all.py`（单会话时间线 / 全量会话清单）、`dup_skip_audit.py`（去重拦截审计）、
`fetch_equipment_shots.py`（设备桌面截图回放取证）。

> **另一种装法（npm CLI）**：如果更想要命令行安装（配置与输出统一落 `~/.csdbg/`，升级不丢数据），
> 用 npm 包 `cs-debug-toolkit`，**一行搞定**：
> ```bash
> npm install -g cs-debug-toolkit-<ver>.tgz && csdbg init -i
> ```
> 这会自动装 Python 依赖、交互式输入 SLS AK、安装 4 个 skill，完成后直接在 agent 里说：
> "交叉分析 <会话ID>，为什么用户没收到回复"。
>
> 两种形态同源构建，技能与脚本内容一致，按团队习惯选一种即可。

## 目录结构

```
cs-debug-toolkit/
├── README.md                      # 本文件
├── requirements.txt               # Python 依赖
├── setup.ps1                      # ★ 一键初始化（装依赖、配路径、生成配置骨架、装技能）
├── scripts/                       # 数据拉取与分析脚本（纯 stdlib + aliyun-log SDK）
│   ├── channels.example.json      #   SLS 凭证配置模板（复制为 channels.json 填 AK）
│   └── ...                        #   其余见上表；channels.json 含密钥，勿外传
├── skill/                         # ★ 4 个 agent skill（SKILL.md，跨智能体通用格式）
│   ├── cs-log-cross/
│   ├── cs-rpa-log/
│   ├── cs-conversation-debug/
│   └── e-chat-trace/
├── templates/                     # HTML 报告模板
└── temp/                          # 排查输出目录（证据包 + 分析报告落这里）
```

## 开箱三步

> 前置机器要求：Windows + PowerShell、Python 3.9+、Node.js（含 npm）、
> 能访问阿里云 SLS（`bty-prod-ack-log` / `customer-servhub-log` 项目）的网络环境。

### 第 1 步：一键初始化

在包根目录执行（若被脚本策略拦截，加 `-ExecutionPolicy Bypass`）：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

它会：设置 `CS_TOOLKIT_HOME` 环境变量、安装 Python 依赖、安装 `@bty/customer-service-cli`、
复制配置模板、把 4 个 skill 装进你的 agent 技能目录、跑连接自检。

### 第 2 步：配两把"钥匙"（这两样没法随包分发，只能每人自己配）

| 钥匙 | 怎么弄 | 验证 |
|---|---|---|
| **cs-cli 登录态** | 用你的 BetterYeah 账号执行 `cs-cli auth login` | `cs-cli auth whoami` |
| **SLS 查询 AK** | 向管理员申请一个只读 AK（需 `log:GetLogStoreLogs` 权限），填进 `scripts/channels.json` | `python scripts/rpa_log_query.py --check` 与 `python scripts/server_log_query.py --check` |

（可选）`e-chat-trace` 技能另读用户环境变量 `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET`。

### 第 3 步：开查

装好后，在**支持 agent skill 的环境**里直接说：

> 结合服务端/RPA/运维日志分析一下 <会话ID> 这个问题：为什么 xx 时间用户没收到回复？

agent 会按 `cs-log-cross` 技能自动走完「四方取证 → 证据包 → 交叉论证 → 结论报告」，
报告写入 `temp/`。也可以绕过 agent 手动跑脚本（各脚本 `--help` 有参数说明）。

## 接入不同智能体

skill 采用开放格式（SKILL.md + 可选 scripts），各环境的接入方式：

| 环境 | 接入方式 |
|------|---------|
| ZCode / Claude Code | `setup.ps1` 已自动装到 `~/.agents/skills/` 与 `~/.claude/skills/`；重启会话即可 |
| **Codex CLI** | 把 `skill/*` 各目录复制到 `~/.agents/skills/`（或项目 `.codex/skills/`），Codex ≥2025-12 版本用 `codex --enable skills` 启用；或在 `AGENTS.md` 里写明"排查客服问题时先读 `<路径>/skill/cs-log-cross/SKILL.md` 并照做" |
| 其他智能体（Cursor / 自研等） | 无需专门支持：把 `SKILL.md` 内容作为系统提示/任务说明喂给它，允许它执行 Bash 命令即可——skill 本质是"流程说明书 + 可执行脚本" |

技能触发词都写在各 SKILL.md 的 description 里（如"交叉分析""多方日志""平响""RPA 日志"），
改用其他大模型只影响最后论证环节的文笔，不影响取证链路。

## 常见问题

- **JSON 解析报错**：cs-cli 输出尾部带版本升级提示噪音，脚本已用 `raw_decode` 容错；
  自己写解析时别 `json.loads` 整个 stdout。
- **中文乱码**：先 `$env:PYTHONIOENCODING='utf-8'`。
- **`--output` 文件没生成**：检查是不是把 stdout 接了 `| head`（SIGPIPE 会杀死进程）。
- **SLS 返回行数正好等于 `--limit`**：视为疑似截断，缩小时间窗重拉，别直接下"没有日志"的结论。
- **skill 不被识别**：确认技能目录（含 SKILL.md）在你环境的技能加载路径下
  （ZCode：`~/.agents/skills/`；Claude Code：`~/.claude/skills/`；Codex：`~/.agents/skills/`
  或 `.codex/skills/`），装完重启会话。
- **`server_log_query.py --check` 报 KeyError**：`channels.json` 是旧 schema，删掉后重新从
  `channels.example.json` 复制。

## 安全边界（分发前必读）

1. `scripts/channels.json` 含 SLS AccessKey 密钥，**绝对不要打进分发包/提交 git**——
   本包默认不含它，setup.ps1 只生成模板。
2. `temp/` 里的分析报告含真实店铺名、会话 ID、出口 IP 等客户数据，外发前先脱敏。
3. 每位使用者用自己的 cs-cli 账号与 AK，便于审计，也避免共享密钥泄露。
4. 全流程只读取证：skill 已约束不得执行 `sa update` / `faq update` 等写命令。
