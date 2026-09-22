# BTY CS-CLI 功能区 — 多方日志交叉分析

BetterYeah AI 客服平台（`@bty/customer-service-cli`）配套的**运维问题定责功能区**。

## 功能区定位

> **核心职能：把四方数据放到同一条时间轴上交叉分析论证，得出问题结论。**

| # | 数据源 | 位置 | 拉取通道 |
|---|--------|------|---------|
| 1 | **服务端 server 日志** | SLS `bty-prod-ack-log` / logstore `customer-servhub-api`（cn-hangzhou） | `scripts/server_log_query.py`（aliyun-log SDK） |
| 2 | **RPA 端日志** | SLS `customer-servhub-log` / 4 渠道 logstore（抖音/京东/拼多多/千牛，prod+dev） | `scripts/rpa_log_query.py`（aliyun-log SDK） |
| 3 | **ops 运维日志** | 本地已安装的 `@bty/customer-service-cli` → `cs-cli ops-record list/get` | `scripts/ops_log_query.py`（cs-cli 子进程） |

四方交叉取证后，**分析结论统一落盘到 [`temp/`](temp/)**（功能区最终交付物）：

```
锚点 (conversation_id / trace_id / request_id / dispatch_id / 关键词) + 时间窗口
    │
    ├── ① server_log_query.py   → 服务端处理链路（SOP/下发/状态机/ERROR）
    ├── ② rpa_log_query.py      → RPA 端执行（接收/发送/失败原因）
    ├── ③ ops_log_query.py      → 运维操作（谁在什么时间改了哪个 Agent 的什么配置）
    │
    ▼
cross_analysis.py  对齐四方 → temp/evidence_<时间>_<锚点>/
    │   ├── server.json / rpa_<channel>.json / ops.json   （原始证据）
    │   ├── anchors.json  （锚点命中矩阵 + 跨源 ID 共现 + ops 变更关联）
    │   └── evidence.md   （合并时间线 + 异常提取 + 关联结论素材）
    ▼
/cs-log-cross (LLM 交叉论证 5 问：断链定位 → 时间对齐 → 变更介入 → 反证 → 归因)
    ▼
✅ temp/analysis_<YYYYMMDD-HHMM>-<slug>.md   （问题结论：主因/次因/排除项/置信度/建议）
```

## 分发（给别人用）

本功能区可打包成两种形态分发，**同一份源**（脚本/skill 都从这里组装，别手工复制）：

| 形态 | 构建命令 | 产物 | 使用者怎么装 |
|---|---|---|---|
| **npm CLI**（推荐） | `powershell -File .\build_cli.ps1` | `dist\cs-debug-toolkit-1.0.0.tgz` | `npm i -g <tgz>` → `csdbg init` → `csdbg doctor` |
| **zip 解包** | `powershell -File .\build_package.ps1` | `dist\cs-debug-toolkit.zip` | 解压 → `setup.ps1` |

两者都带 `skill/` 下 4 个技能（`cs-log-cross` / `cs-rpa-log` / `cs-conversation-debug` / `e-chat-trace`），
装进 agent 技能目录后由各自的大模型完成最后的交叉论证——脚本层与大模型无关。

- CLI 形态源码在 [`cli/`](cli/)（`bin/csdbg.js` 零第三方依赖）；配置与输出落 `~/.csdbg/`
  （`channels.json` + `temp/`），升级重装 npm 包不丢数据。
- 两个构建脚本都跑质量门：`py_compile`、配置模板 JSON 校验、个人路径/AK 泄漏扫描、`__pycache__` 清理。

## 目录结构

```
cs-cli/
├── scripts/
│   ├── channels.json            # SLS AK + 数据源配置（gitignore，勿提交）
│   ├── channels.example.json    # 配置模板
│   ├── server_log_query.py      # ① 服务端 SLS 日志查询
│   ├── rpa_log_query.py         # ② RPA 端 SLS 日志查询（4 渠道）
│   ├── rpa_log_report.py        #   RPA 日志 HTML 报告（辅助）
│   ├── ops_log_query.py         # ③ 本地 cs-cli ops 运维日志查询
│   └── cross_analysis.py        # ★ 四方交叉对齐 → 证据包（第④源 --host-bundle）
├── skill/                       # ★ 单源 skill 定义（分发用，build_*.ps1 从这里取）
│   ├── cs-log-cross/            #   四方交叉分析（主入口）
│   ├── cs-rpa-log/              #   单源 RPA 日志
│   ├── cs-conversation-debug/   #   单链路会话根因
│   └── e-chat-trace/            #   消息全链路
├── cli/                         # npm CLI 包源（package.json + bin/csdbg.js + README）
├── pack/                        # zip 分发包源（README + setup.ps1）
├── build_cli.ps1                # → dist\cs-debug-toolkit-<ver>.tgz
├── build_package.ps1            # → dist\cs-debug-toolkit.zip
├── .claude/
│   ├── commands/
│   │   ├── cs-log-cross.md      # ★ 功能区主入口：四方交叉分析 → temp/ 结论
│   │   ├── cs-rpa-log.md        # 单源：RPA 日志快速查询
│   │   └── cs-conversation-debug.md  # 单链路：会话内单条回复根因 debug
│   └── workflows/               # 低 token 混合 workflow（会话分析/延迟分析）
├── templates/                   # HTML 报告模板
├── temp/                        # ★ 功能区输出目录：证据包 + 分析结论（gitignore）
└── docs/                        # PRD / 设计文档
```

## 快速开始

```bash
# 0. 环境检查（前三个源各一项；第④源无需认证）
python3 scripts/server_log_query.py --check   # SLS 服务端
python3 scripts/rpa_log_query.py --check      # SLS RPA 端
python3 scripts/ops_log_query.py --check      # 本地 cs-cli 认证

# 1. 一键交叉取证（生成证据包）
python3 scripts/cross_analysis.py \
  --conversation-id 68a04b1770a442889ed175de395700cf \
  --channel pinduoduo \
  --start "2026-09-18T22:30:00" --end "2026-09-18T23:10:00"

# 2. 交叉论证 + 出结论（在项目目录内使用 Claude Code）
/cs-log-cross 68a04b1770a442889ed175de395700cf 为什么 22:42 那条消息用户没收到？
#    → 结论自动写入 temp/analysis_20260918-2245-<slug>.md
```

## 可用 Skills（slash commands）

| Skill | 定位 | 输入 | 结论输出 |
|-------|------|------|---------|
| **`/cs-log-cross`** | ★ 四方日志交叉分析定责 | 锚点 ID/关键词 + 时间窗口 + 问题描述 | `temp/analysis_*.md` |
| `/cs-rpa-log` | 单源：RPA 日志查询 | 渠道 + 设备/会话/关键词 | 终端/JSON |
| `/cs-conversation-debug` | 单链路：会话消息根因 debug | `conversation_id` | 终端 |

## 环境要求

- Python 3 + `aliyun-log-python-sdk`（SLS 两源）
- `@bty/customer-service-cli` 全局安装且已登录：`cs-cli auth login --phone <手机号> --password <密码>`
- SLS AK 配置在 `scripts/channels.json`（已在 `.gitignore`）
- 两个 SLS 项目的读权限（`log:GetLogStoreLogs`）+ `customer-servhub-api` 全文索引

## 两种运行模式（配置与输出的区别）

脚本的配置查找链：`--config` 参数 > 环境变量 `CSDBG_CONFIG` > 脚本同目录 `channels.json` > `~/.csdbg/channels.json`；
输出目录：环境变量 `CSDBG_TEMP` > 同级 `temp/`。

| 模式 | 配置 | 输出 | 调用方式 |
|---|---|---|---|
| 源码/zip | `scripts/channels.json` | `temp/` | `python scripts/xxx.py <参数>` |
| **npm CLI** | `~/.csdbg/channels.json` | `~/.csdbg/temp/` | `csdbg xxx <参数>`（参数一致） |

`csdbg paths` 打印当前生效的全部路径，`csdbg env` 打印手动跑脚本时要设的环境变量。

## 输出约定

| 产物 | 路径 | 说明 |
|------|------|------|
| 证据包 | `temp/evidence_<YYYYmmdd_HHMMSS>_<slug>/` | 各源原始日志 + 对齐结果，供复核 |
| **分析结论** | `temp/analysis_<YYYYMMDD-HHMM>-<slug>.md` | **功能区最终交付物**：结论先行、时间轴对齐、交叉论证、根因判定、建议 |

`temp/` 全部内容不入库（`.gitignore`），是工作产物区。

## 与全局 cs-* skills 的关系

- **全局 skills**（`~/.claude/skills/cs-*`）：通用能力，任何目录可用（`cs-chat-debug`、`cs-testcase-debug` 等）
- **本功能区**：聚焦"**服务端 × RPA × 运维 × 主机/IP 四方交叉定责**"，是单源工具的上层组合

## 参考资源

- PRD：[docs/PRD-002-cross-log-analysis.md](docs/PRD-002-cross-log-analysis.md)（本功能区需求）  
- 控制台入口：[服务端日志](https://sls.console.aliyun.com/lognext/project/bty-prod-ack-log/logsearch/customer-servhub-api?slsRegion=cn-hangzhou) · [RPA 日志](https://sls.console.aliyun.com/lognext/project/customer-servhub-log/overview?slsRegion=cn-hangzhou)
- cs-cli 官方 README：`%APPDATA%/npm/node_modules/@bty/customer-service-cli/README.md`

## License

Internal use only — BetterYeah DevKit
