# BTY CS-CLI 功能区 — 多方日志交叉分析

BetterYeah AI 客服平台（`@bty/customer-service-cli`）配套的**运维问题定责功能区**。

## 功能区定位

> **核心职能：把四方数据放到同一条时间轴上交叉分析论证，得出问题结论。**

| # | 数据源 | 位置 | 拉取通道 |
|---|--------|------|---------|
| 1 | **服务端 server 日志** | SLS `bty-prod-ack-log` / logstore `customer-servhub-api`（cn-hangzhou） | `scripts/server_log_query.py`（aliyun-log SDK） |
| 2 | **RPA 端日志** | SLS `customer-servhub-log` / 4 渠道 logstore（抖音/京东/拼多多/千牛，prod+dev） | `scripts/rpa_log_query.py`（aliyun-log SDK） |
| 3 | **ops 运维日志** | 本地已安装的 `@bty/customer-service-cli` → `cs-cli ops-record list/get` | `scripts/ops_log_query.py`（cs-cli 子进程） |
| 4 | **主机/IP 侧（目标设备）** | 设备 `equipment_id` / ECD 云电脑 | `scripts/host_events_query.py` → 电源/重启/崩溃事件（ECD 实锤优先 / SLS 心跳重建兜底） |

四方交叉取证后，**分析结论统一落盘到 [`temp/`](temp/)**（功能区最终交付物）：

```
锚点 (conversation_id / trace_id / request_id / dispatch_id / 关键词) + 时间窗口
    │
    ├── ① server_log_query.py   → 服务端处理链路（SOP/下发/状态机/ERROR）
    ├── ② rpa_log_query.py      → RPA 端执行（接收/发送/失败原因）
    ├── ③ ops_log_query.py      → 运维操作（谁在什么时间改了哪个 Agent 的什么配置）
    ├── ④ host_events_query.py  → 目标设备 电源/重启/崩溃 事件（第④源，ECD 优先/SLS 兜底）
    │
    ▼
cross_analysis.py  对齐四方 → temp/evidence_<时间>_<锚点>/
    │   ├── server.json / rpa_<channel>.json / ops.json / host.json   （原始证据）
    │   ├── anchors.json  （锚点命中矩阵 + 跨源 ID 共现 + ops 变更关联）
    │   ├── meta.json     （creator/标签/status，供批量审计与结论回填）
    │   └── evidence.md   （合并时间线 + 异常提取 + §3b 电源/重启/崩溃事件专项 + 关联结论素材
    │                      + 🧩 故障签名匹配（候选，内置知识库自动匹配））
    ▼
/cs-log-cross (LLM 交叉论证 6 问：断链定位 → 时间对齐 → 变更介入 → 主机侧判定 → 反证 → 归因)
    ▼
✅ temp/analysis_<YYYYMMDD-HHMM>-<slug>.md   （问题结论：主因/次因/排除项/置信度/建议）
```

> **数据源插件化**：四源（服务端/RPA/ops/主机）实现在 `scripts/sources.py` 的 `DataSource` 插件里，
> 由 `build_sources()` 注册表装配——新增数据源只需实现子类 + 注册一行，不改主流程。
>
> **故障签名匹配**：`templates/fault_signatures.json` 沉淀了 26 条故障签名（其中 17 条参与自动匹配），
> 覆盖面板白屏、状态残留、重复转接、选店失败、主机冻结、平台口径等 22 类已积累问题；
> 证据包生成时自动匹配候选并在 `evidence.md` 给出「命中特征 + 结论模板」；
> `csdbg signatures --list` 查看知识库、`--match-dir <证据包>` 对历史证据复检，本地可增补到 `~/.csdbg/`。

## 分发（给别人用）

本功能区可打包成两种形态分发，**同一份源**（脚本/skill 都从这里组装，别手工复制）：

| 形态 | 构建命令 | 产物 | 使用者怎么装 |
|---|---|---|---|
| **npm CLI**（推荐） | `powershell -File .\build_cli.ps1` | `dist\cs-debug-toolkit-<ver>.tgz` | `npm i -g <tgz>` → `csdbg init` → `csdbg doctor` |
| **zip 解包** | `powershell -File .\build_package.ps1` | `dist\cs-debug-toolkit.zip` | 解压 → `setup.ps1` |

两者都带 `skill/` 下 6 个技能（`cs-log-cross` / `cs-router` / **`cs-fault-playbook`** / `cs-rpa-log` / `cs-conversation-debug` / `e-chat-trace`），
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
│   ├── host_events_query.py     # ④ 目标设备 电源/重启/崩溃 事件（ECD 优先/SLS 心跳兜底）
│   ├── cross_analysis.py        # ★ 四方交叉对齐 → 证据包（插件驱动，含故障签名匹配）
│   ├── sources.py               # ★ 数据源插件层（DataSource 接口 + 注册表 build_sources）
│   ├── fault_signatures.py      # ★ 故障签名知识库（加载/匹配/--match-dir 复检）
│   ├── gap_analysis.py          #   平响排查：user→assistant 间隔 / duration / failed 签名统计
│   ├── csapi.py                 #   cs-cli 调用助手（raw_decode 解析 + data 解包，供下列脚本复用）
│   ├── conv_timeline.py         #   单会话逐条消息时间线（间隔 / duration / send_results / error_detail）
│   ├── conv_list_all.py         #   某 agent 指定日期全量会话清单（自动翻页）
│   ├── dup_skip_audit.py        #   "服务端检测重复消息，跳过推送"审计：判定去重是否造成漏答/状态挂起
│   ├── srv_summarize.py         #   服务端日志摘要（message 模式聚类 + 时间窗/关键词过滤）
│   ├── fetch_equipment_shots.py #   设备桌面截图帧：handle_upload 帧清单 → sign-url 签名下载 PNG
│   ├── sls_sql_query.py         #   通用 SLS SQL（LIKE 过滤，绕开中文分词坑）
│   ├── leak_scan.py             #   发版前公开内容扫描（扫 git 跟踪的整棵树，非仅分发包）
│   ├── telemetry.py             #   可选本地埋点（CSDBG_TELEMETRY=1 启用，仅写本地）
│   ├── selftest.py              #   离线自检（无网络/无 AK 验证工具链）
│   └── legacy/                  #   旧版分析脚本（路径为示例值，仅历史参考，勿用于新排查）
├── skill/                       # ★ 单源 skill 定义（分发用，build_*.ps1 从这里取）
│   ├── cs-log-cross/            #   四方交叉分析（主入口）
│   ├── cs-router/               #   排查入口路由（meta-skill）
│   ├── cs-fault-playbook/       #   ★ 故障类型手册：22 类症状 → 标准查询流程 → 判定 → 结论模板
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
├── templates/                   # HTML 报告模板 + fault_signatures.json（故障签名知识库）
├── temp/                        # ★ 功能区输出目录：证据包 + 分析结论（gitignore）
├── tests/                       # pytest 回归测试（离线，不依赖网络/AK）
└── docs/                        # PRD / 设计文档 / troubleshooting.md / REPORT_STANDARD.md + templates/
```

## 快速开始

```bash
# 0. 环境检查（前三个源各一项；第④源无需认证）
csdbg selftest                                # 离线自检：无 AK 也能验证工具链（依赖/证据包/时区）
csdbg doctor                                  # 在线自检：含 SLS 连通性 + cs-cli 认证
python3 scripts/server_log_query.py --check   # SLS 服务端
python3 scripts/rpa_log_query.py --check      # SLS RPA 端
python3 scripts/ops_log_query.py --check      # 本地 cs-cli 认证

# 1. 一键交叉取证（生成证据包）
python3 scripts/cross_analysis.py \
  --conversation-id 0123456789abcdef0123456789abcdef \
  --channel pinduoduo \
  --start "2026-09-18T22:30:00" --end "2026-09-18T23:10:00"

# 1b. 第④源专项：目标设备 电源/重启/崩溃 事件（固化排查流程，无需拷脚本）
python3 scripts/host_events_query.py --equipment-id "<设备ID>" \
  --start "2026-09-21T00:00:00" --end "2026-09-22T23:59:59" [--save host_events.txt]
#     或直接并入四方证据包：
python3 scripts/cross_analysis.py --conversation-id <id> \
  --start <ISO> --end <ISO> --host-events-equipment "<设备ID>"

# 2. 交叉论证 + 出结论（在项目目录内使用 Claude Code）
/cs-log-cross 0123456789abcdef0123456789abcdef 为什么 22:42 那条消息用户没收到？
#    → 结论自动写入 temp/analysis_20260918-2245-<slug>.md
```

## 可用 Skills

| Skill | 定位 | 输入 | 结论输出 |
|-------|------|------|---------|
| **`/cs-log-cross`** | ★ 四方日志交叉分析定责 | 锚点 ID/关键词 + 时间窗口 + 问题描述 | `analysis_*.md`（本机落 `D:\temp\<客服账号名>\`，外部分发落 `<输出目录>`） |
| `/cs-router` | 排查入口路由（meta-skill：按问题类型选工具） | 问题描述 | 路由建议 |
| **`/cs-fault-playbook`** | ★ 故障类型手册与标准查询流程（22 类已积累问题） | 现象描述 / 证据包 | 归类 + 标准取证流程 + 判定判据 |
| `/cs-rpa-log` | 单源：RPA 日志查询 | 渠道 + 设备/会话/关键词 | 终端/JSON |
| `/cs-conversation-debug` | 单链路：会话消息根因 debug | `conversation_id` | 终端（留档时落报告交付目录） |
| `/e-chat-trace` | 消息全链路排查（Agent trace + RPA 收发自动串联） | `conversation_id` | 终端（不落盘） |

> `/e-chat-trace` 是 `skill/` 下的独立技能（非 slash command，`.claude/commands/` 未内置入口）：
> 读环境变量 `ALIYUN_ACCESS_KEY_ID/ALIYUN_ACCESS_KEY_SECRET` 直连 SLS，不经 `channels.json`；
> 本机要直接用可引用 `skill/e-chat-trace/SKILL.md`，或按需在 `.claude/commands/` 补建入口。

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
| **分析结论** | 交付目录 `analysis_<YYYYMMDD-HHMM>-<slug>.md` | **功能区最终交付物**：结论先行、时间轴对齐、交叉论证、根因判定、建议 |

结论与报告的落盘位置（含证据区收口、结案清理）见 [docs/REPORT_STANDARD.md](docs/REPORT_STANDARD.md) §5：
**本机 cs-cli 环境**写 `D:\temp\<客服账号名>\`（报告 + `证据区\screenshots`，证据区**只有 screenshots**），
**外部分发包环境**写 `<输出目录>`（`~/.csdbg/temp` 或 `<TOOLKIT>/temp`）。

`temp/` 是排查过程中的临时中转区（`.gitignore` 不入库），**结案必须清零**（只留 `README.md`）：
报告与截图归交付目录的 `证据区\screenshots\`，其余（原始 json/日志/一次性脚本）一律不留存——复现靠报告内嵌命令。

## 与全局 cs-* skills 的关系

- **全局 skills**（`~/.claude/skills/cs-*`）：通用能力，任何目录可用（`cs-chat-debug`、`cs-testcase-debug` 等）
- **本功能区**：聚焦"**服务端 × RPA × 运维 × 主机/IP 四方交叉定责**"，是单源工具的上层组合

## 参考资源

- PRD：[docs/PRD-002-cross-log-analysis.md](docs/PRD-002-cross-log-analysis.md)（本功能区需求）
- 规范：[docs/REPORT_STANDARD.md](docs/REPORT_STANDARD.md)（结论三段式 / 报告五段固定格式 v1 + 六源定责 / 落盘与结案清理，强制）
- 风险：[docs/RISK_REVIEW.md](docs/RISK_REVIEW.md)（工具链风险与漏洞评估 + 修复方案）
- 排障：[docs/troubleshooting.md](docs/troubleshooting.md)（常见错误 → 处置索引）
- 模板：[docs/templates/final-report.html](docs/templates/final-report.html)（单文件自包含 HTML 报告骨架）
- 变更：[CHANGELOG.md](CHANGELOG.md) · 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)
- 控制台入口：[服务端日志](https://sls.console.aliyun.com/lognext/project/bty-prod-ack-log/logsearch/customer-servhub-api?slsRegion=cn-hangzhou) · [RPA 日志](https://sls.console.aliyun.com/lognext/project/customer-servhub-log/overview?slsRegion=cn-hangzhou)
- cs-cli 官方 README：`%APPDATA%/npm/node_modules/@bty/customer-service-cli/README.md`

## License

Internal use only — BetterYeah DevKit
