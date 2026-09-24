---
user-invocable: true
name: cs-log-cross
description: |
  四方日志交叉分析（cs-debug-toolkit 主入口）：综合 ① 服务端 SLS 日志
  (bty-prod-ack-log/customer-servhub-api) + ② RPA 端 SLS 日志
  (customer-servhub-log 各渠道) + ③ 本地 cs-cli ops 运维日志 +
  ④ 主机/IP 侧证据（SLS 的 hostname/出口IP/心跳 + 主机本地 Windows 事件日志），
  按锚点（会话/trace/request/dispatch/关键词）+ 时间窗口拉取，交叉论证得出问题结论。
  最终分析报告写入 <TOOLKIT>/temp/。
  触发词：交叉分析、多方日志、日志交叉论证、cs-log-cross、四方交叉、
  服务端+RPA+运维+主机日志、结合日志分析这个问题、日志对齐、主机日志、
  设备电源事件、设备重启、崩溃事件、主机重启/睡眠/崩溃。
argument-hint: "[conversation_id|trace_id|request_id|dispatch_id|关键词] [--channel 渠道] [--start ISO] [--end ISO] [--host-bundle 主机证据zip/文本] [--问题描述]"
allowed-tools: Bash, Read, Write
---

# cs-log-cross · 四方日志交叉分析

## 功能区定位

本技能是 cs-debug-toolkit 的**主入口**。目标：把四方数据放到同一条时间轴上交叉论证，
区分「服务端问题 / RPA 端问题 / 运维操作引入的问题 / 主机侧问题 / 非问题」，产出**可复核的问题结论**。

| # | 数据源 | 位置 | 拉取方式 |
|---|--------|------|---------|
| 1 | 服务端 server 日志 | SLS `bty-prod-ack-log` / logstore `customer-servhub-api` | `<TOOLKIT>/scripts/server_log_query.py` |
| 2 | RPA 端日志 | SLS `customer-servhub-log` / `project-<channel>-rpa-prod` 等 4 渠道 | `<TOOLKIT>/scripts/rpa_log_query.py` |
| 3 | ops 运维日志 | 本地 `@bty/customer-service-cli`（`cs-cli ops-record list/get`） | `<TOOLKIT>/scripts/ops_log_query.py` |
| 4 | **主机/IP 侧** | 主机本地 Windows 事件日志 / 客户端日志（`.zip` 或文本） | `cross_analysis.py --host-bundle`；目标设备电源/重启/崩溃事件：`csdbg host-events <设备ID>`（ECD 优先 / SLS 心跳兜底） |

**关于第 ④ 源（别漏）**：主机侧分两层——

- **SLS 面（常态，已含在源②查询里）**：`equipment_id → hostname / 出口 IP / desktop`、
  `robot-health-report` 30s 心跳时间线。用回答"哪台机器""冻结/崩溃/睡眠/网络 四选一"。
- **主机本地面（升级手段，需要 `--host-bundle`）**：源②的心跳只能定到"哪一类"，要**进程级实锤**
  （谁打满 CPU、谁崩了、崩溃栈）必须上主机取本地日志。两条路：
  1. 在 Step 2 或源② 拿到 hostname 后，到那台机器跑 `collect_rpa_logs.ps1 -Days 7
     -FocusStart "…" -FocusEnd "…"`（脚本位置：形态 A 看 `csdbg paths` 的 `scripts` 行，
     形态 B 就是 `<TOOLKIT>/scripts/`；把它拷到目标机执行），回传 `RpaLogCollect_*.zip`；
  2. 有云电脑（ECD）权限时用远程拉起取数（见「约束与注意事项」第 7 条），产出文本同样可喂给
     `--host-bundle`；
  3. **一键抓取（固化进流程，无需拷脚本）**：只查"系统 电源/重启/崩溃"时直接
     `csdbg host-events <设备ID> --start <ISO> --end <ISO>`——ECD 权限下自动上主机拉事件日志实锤；
     无 ECD 时用 SLS 心跳时间线重建（uptime 重置→重启、断流≥5min→睡眠/关机、
     同次开机内版本变化→崩溃/升级）。该命令已内嵌进
     `cross_analysis.py --host-events-equipment <设备ID>`，跑 cross 时自动并入第④源。

  拿到后重跑一次带 `--host-bundle` 的 `cross_analysis.py`，或对已有证据包补做该参数。

四方由 `<TOOLKIT>/scripts/cross_analysis.py` 统一编排，产出证据包到 `temp/evidence_*/`；
**分析结论**（本技能最后一步）写入 `temp/analysis_*.md`。

## 路径约定（先读）

**先判断安装形态**（下面命令全部二选一，优先用形态 A）：

| 形态 | 判断依据 | 脚本调用 | 输出目录 |
|---|---|---|---|
| **A. CLI 安装**（`npm i -g cs-debug-toolkit`） | `csdbg` 命令存在（`csdbg paths` 能跑通） | `csdbg cross/server/rpa/ops` | `csdbg paths` 打印的 `temp`（默认 `~/.csdbg/temp`） |
| **B. zip 解包** | 有 `<TOOLKIT>/scripts/*.py` 本地文件 | `python <TOOLKIT>/scripts/xxx.py` | `<TOOLKIT>/temp/` |

- 形态 A 的 `<TOOLKIT>` = `csdbg paths` 输出里的 `toolkit` 行（即 npm 包安装目录）；
  配置问 `csdbg paths` 的 `config` 行，不要去找 `scripts/channels.json`。
- 形态 B 的 `<TOOLKIT>` = 本工具包解压目录（README 所在目录；通常已设为 `CS_TOOLKIT_HOME`，
  不确定时按本 SKILL.md 位置反推：`<TOOLKIT> = 本文件目录的上两级`）。
- 形态 B 下所有脚本在 `<TOOLKIT>/scripts/`，证据包/结论落 `<TOOLKIT>/temp/`。
- `cs-cli` 命令按 PATH 解析即可；如需指定全路径，设环境变量 `CS_CLI`。
- Windows 环境：Python 命令用 `python` 或 `python3`（哪个存在用哪个），输出带中文时先
  `PYTHONIOENCODING=utf-8`。

## 环境自检（首次使用或报错时跑）

```bash
# 形态 A（CLI）
csdbg doctor          # 一次跑完下面三项 + Python 依赖 + 配置可读性

# 形态 B（zip）
python <TOOLKIT>/scripts/server_log_query.py --check   # SLS 服务端源
python <TOOLKIT>/scripts/rpa_log_query.py --check      # SLS RPA 端源
python <TOOLKIT>/scripts/ops_log_query.py --check      # 本地 cs-cli 认证
```

任一项失败按「约束与注意事项」第 5 条引导用户修复，修好前其余源可继续用。

## 输入解析（Step 0）

从用户消息中识别：

1. **锚点**（至少一个，否则追问用户）：
   - 32 位 hex → 优先按 `conversation_id` 处理；若用户明说 trace/request/dispatch 则用 `--trace-id/--request-id/--dispatch-id`
   - 中文/短语 → `--query 关键词`
2. **时间窗口**：`--start` / `--end`（ISO 8601）。缺失时按锚点推断：
   - 有 conversation_id → 先 `cs-cli conversation records <id>` 取首末 `message_time`，前后各扩 10 分钟
   - 只有关键词/什么都没给 → 向用户确认时间范围（默认今天全天；环境有 AskUserQuestion
     之类的交互工具就用它，没有就直接在回复里问，等用户答完再继续）
3. **渠道**：用户提到"抖音/京东/拼多多/千牛"→ 映射 `--channel douyin/jingdong/pinduoduo/qianniu`；未提则全渠道扫
4. **问题描述**（可选）：用户的原始疑问，写进结论报告作为待证问题

### Step 0.5 — 第④源决策（是否需要主机侧证据）

**先按症状判断**，避免"先跑四方、不够再补④"的两轮往返：

| 症状 | 需要的源 | 动作 |
|------|---------|------|
| 平响/超时/会话不接管/AI 未回复 | 前三源即可 | 直接 `csdbg cross`；跨源无定论再补④ |
| RPA offline / 心跳断流 / 设备离线 | **必须上主机** | 直接带 `--host-events-equipment <设备ID>` 跑 cross（④并入证据包） |
| 用户报"消息未收到" / 发送失败 | 前三源 + 网络层 | 源②已含 SLS 心跳，先跑；需区分 冻结/崩溃/睡眠 时补④ |
| 需要进程级实锤（谁打满 CPU / 崩溃栈） | 前三源 + 主机本地面 | `--host-bundle`（collect_rpa_logs.ps1 回传 zip） |

判断口径：
- **ECD 实锤 vs SLS 推断**：④源记录带 `confidence` 字段（ECD 事件日志=`high`，SLS 心跳重建=`medium`），
  归因论证时按置信度分层，不要把推断当实锤。
- **自动升级提示**：cross 跑完若 evidence.md 出现「⚠ 第④源升级建议」（检测到源②心跳断流 ≥5min
  但未提供④），说明 SLS 无法区分 睡眠/崩溃/僵死，按提示补 `--host-events-equipment` 重跑。
- 不确定时：先跑前三源（快），无定论再补④。

## 执行流程

### Step 1 — 多方取证

```bash
# 形态 A（CLI 安装）
csdbg cross --conversation-id "<conv_id>" [--channel douyin] \
  --start "2026-09-18T10:00:00" --end "2026-09-18T11:00:00" \
  [--host-bundle "<RpaLogCollect_*.zip 或远程拉起输出.txt>"]     # 第④源，见下

# 形态 B（zip 解包）
cd <TOOLKIT>
python scripts/cross_analysis.py --conversation-id "<conv_id>" \
  [--channel douyin] --start "2026-09-18T10:00:00" --end "2026-09-18T11:00:00" \
  [--host-bundle "..."]
```

**第④源（主机/IP 侧）采集**：默认先跑前三源（SLS+cs-cli 快速定界），只有当源②的心跳/指标
无法区分"冻结/崩溃/睡眠/网络"四类，或需要进程级实锤时，才去主机取本地日志。三条路：

- **一键抓取电源/重启/崩溃事件（推荐，无需拷脚本）**：
  ```bash
  # 目标设备（equipment_id）+ 时间窗；ECD 云电脑可加 --desktop-id 走 RunCommand 实锤
  csdbg host-events <设备ID> --start "2026-09-21T00:00:00" --end "2026-09-22T23:59:59"
  # 或直接并入四方证据包（固化流程）：
  csdbg cross --conversation-id <id> --start <ISO> --end <ISO> --host-events-equipment <设备ID>
  ```
- **手动拷贝脚本**：`csdbg paths` 显示的 scripts 目录里有 `collect_host_events.ps1`，
  拷到目标主机跑（需本地登录或远程桌面），回传的 zip/文本喂 `--host-bundle`
- **远程拉起（需 ECD 权限）**：
  ```bash
  # 1. 配置 ECD AK（仅首次，与 SLS AK 分开）
  echo '{"access_key_id":"LTAI...","access_key_secret":"...","region":"cn-hangzhou"}' > ~/.csdbg/ecd.json
  
  # 2. 一步拉起+落盘
  csdbg host-pull <desktopId> $(csdbg paths | grep scripts | awk '{print $2}')/collect_host_events.ps1 \
    --save host_$(date +%Y%m%d_%H%M).txt
  
  # 3. 喂给 cross
  csdbg cross --conversation-id <id> --start <ISO> --end <ISO> --host-bundle ./host_*.txt
  ```

脚本会输出证据包路径（`temp/evidence_<时间戳>_<slug>/`）。
任一数据源失败时**继续跑其余源**，并在结论中注明该源不可用。

### Step 2 — 读取证据包

`Read` 以下文件（按需截断读取）：

1. `temp/evidence_*/evidence.md` — 锚点命中矩阵、跨源 ID 共现、合并时间线、异常提取、
   **主机侧专题（§3b）**、ops 关联、**🧩 故障签名匹配（候选）**
2. `anchors.json` — 机器可读的对齐结果（含 `signature_hits` 命中的签名 id）
3. 需要细粒度证据时，读 `server.json` / `rpa_<channel>.json` / `ops.json` / `host.json` 原始记录
4. 若锚点是 conversation_id，补充业务上下文：
   ```bash
   cs-cli conversation records <conversation_id> > temp/conv_records.json
   ```

### Step 3 — 交叉论证（核心分析）

按以下 6 问逐条论证，每个论点**必须引用日志中的具体证据行**（时间戳 + 来源 + 原文片段）：

1. **事件链路在哪一环断了/出错了？**
   - 服务端有 `[RPA下发]` 但 RPA 端无对应接收 → 断在网关/RPA 掉线
   - RPA `[接收]` 正常但发送 `status=failed` → RPA 端执行问题
   - 服务端 `customer-servhub-api` 有 ERROR/异常堆栈 → 服务端问题
2. **时间轴是否对齐？**
   - 同一 `conversation_id`/`trace_id` 在服务端与 RPA 的时间差 = 下发延迟
   - 延迟 > 阈值（如 30s）→ 结合服务端 `levelname` 与线程/WS 连接日志定位
3. **是否有运维操作介入？**
   - 查 `ops_flags` 与「ops 运维记录」：问题时间点前，涉事 Agent 是否被改过配置
     （FAQ 同步 / SA / 商品 / 节点模板发布，见 remark）？
   - **时间先后 + 对象一致（agent_id/workspace_id 共现）→ 强因果嫌疑**；再与 Agent 回复内容变化对照
4. **主机/IP 侧（第④源）指向哪台机器、属于哪一类？**
   - 源②的 `robot-health-report` 心跳断流时刻 ↔ 源①的用户消息落地时刻，**跨源时刻咬合**才能定事故窗
   - 四选一：**睡眠/休眠**（power 42/107 成对）｜**重启**（6005/6006/6008/41/1074）｜
     **崩溃**（Application Error/Hang 1000/1002、WER、07/04b 崩溃栈）｜**网络**（NIC/DHCP/4202 等）
   - 有 `--host-bundle` 时用 §3b 的原始读数**证伪**：心跳断了但主机侧无任何电源/崩溃事件
     → 更可能是 RPA 进程自身或客户端（如千牛/京东工作台）僵死，而非主机故障
   - 对目标设备跑了 `--host-events-equipment` 时，§3b 的「电源/重启/崩溃事件（专项抓取）」
     直接给判定链：uptime 重置=重启、断流≥5min 未重置=睡眠/关机、同次开机内版本变化=崩溃/升级
     （SLS 重建标 `[SLS推断]`，ECD 实锤标 `[主机事件日志]`，两者置信度不同，论证时区分）
   - 主机侧与其它源冲突时（如主机日志显示设备整夜在线、RPA 却报 offline）→ 以主机侧为准定"主机无责"，
     把矛头转回客户端进程 / 面板状态
5. **反证检查**：为每个候选根因找反驳证据——另一源是否有"该时段工作正常"的日志？
   （例：怀疑 RPA 掉线 → 查服务端是否仍持续收到该设备的消息回执；
     怀疑主机故障 → 查心跳是否只是"跳过排班时段"而非真断流）
6. **归因结论**：主因 / 次因 / 排除项，各自置信度（高/中/低）与判定依据。

**证据不足时**：明确写"无法定论"，列出缺哪份日志、用什么命令补拉
（给出可直接复制运行的 `server_log_query.py` / `rpa_log_query.py` 命令行；
缺主机本地面时给出 `collect_rpa_logs.ps1` 的完整参数）。

### Step 4 — 输出结论到 temp/（必做，工具包交付物）

写文件：`<输出目录>/analysis_<YYYYMMDD-HHMM>-<slug>.md`
（`<输出目录>` = 形态 A 的 `~/.csdbg/temp`，或形态 B 的 `<TOOLKIT>/temp`；拿不准就 `csdbg paths` 看 `temp` 行）

```markdown
# 多方日志交叉分析报告

**生成时间**: ...
**锚点**: conversation_id=... / trace_id=...
**时间窗口**: ...
**数据源**: 服务端 ✅ n 条 | RPA(渠道) ✅ n 条 | ops ✅ n 条 | 主机/IP ✅ n 条（或 ⚪ 未采集）
**证据包**: temp/evidence_.../

## 一、结论先行（一句话）
> <问题定性 + 根因归属（服务端/RPA/运维变更/配置/主机侧） + 置信度>

## 二、待证问题
<用户原始疑问>

## 三、四方时间轴对齐
<关键节点表格：时间 | 来源 | 事件 | 证据摘录>

## 四、交叉论证
### 论点 1: <...>
- 证据（服务端）: `[时间] 原文`
- 证据（RPA）: ...
- 证据（ops）: ...
- 证据（主机/IP 侧）: ...          ← 无主机本地日志时，写 SLS 面的 hostname/出口 IP/心跳
- 反证检查: ...
（逐条展开 Step 3 的 6 问）

## 五、根因判定
| 层 | 判定 | 依据 |
|---|---|---|
| 服务端 | ✅/⚠/❌ | ... |
| RPA 端 | ... | ... |
| 运维变更 | ... | ... |
| 业务配置(FAQ/SA/SOP) | ... | ... |
| **主机/IP 侧** | ✅/⚠/❌/⚪ | 睡眠/重启/崩溃/网络 四选一；无本地日志时注明"仅 SLS 面，未上主机" |

**每层必须给出三态之一（有责 / 排除 / 数据缺口）**；某层缺数据不许省略整行，
写"⚪ 数据缺口"并转成建议项（如"建议在 hostname 那台机器跑 collect_rpa_logs.ps1 补证"）。

## 六、修复/排查建议
<可执行动作；含需要补拉日志时的完整命令（含 collect_rpa_logs.ps1 的完整参数）>

## 附录：证据索引
<evidence 包内文件与本报告引用的行号/时间戳>
```

同时把报告全文要点贴回终端（用户不需要打开文件也能看结论）。

### Step 5 — 沉淀提示

如结论涉及"新类型的四方错位模式"（例如某类下发丢失的日志特征、
或"心跳断流但主机侧无电源/崩溃事件 → 客户端进程僵死"这类判据），
建议追加一句：可考虑沉淀为案例笔记或 testcase（有持久记忆的 agent 写回记忆；
没有的追加到 `<TOOLKIT>/temp/case-lessons.md`）。

## 约束与注意事项

1. **只读取证**：全流程不得修改 Agent 配置（不跑 `sa update`/`faq update` 等写命令）
2. **AK 安全**：SLS AK 存于形态 A 的 `~/.csdbg/channels.json` / 形态 B 的 `scripts/channels.json`
   （勿外传/勿提交 git），任何输出/报告不得回显 AK
3. **Windows 环境**：Python 文件读写一律 `encoding='utf-8'`；cs-cli 输出用 `raw_decode` 解析
4. **大日志**：单源超过 limit 时，在报告里注明截断，结论置信度相应降级
5. **认证失败**：`cs-cli auth whoami` / `rpa_log_query.py --check` / `server_log_query.py --check`
   分别对应前三个源，引导用户逐项修复；第④源无需认证（zip 本地读，或见第 7 条）
6. **与单源 skill 的关系**：只需要看 RPA → `cs-rpa-log`；只需会话 debug → `cs-conversation-debug`；
   **需要跨服务端/RPA/运维/主机四方对齐定责时才用本技能**
7. **第④源的远程拉起**：SLS 查到 `hostname` 后，有三条取本地日志的路：
   - **路径 A（手动）**：把 `csdbg paths` 显示的 scripts 目录里的 `collect_host_events.ps1` 拷到目标主机执行，回传 zip
   - **路径 B（远程）**：有云电脑（ECD）权限时，用 `csdbg host-pull <desktopId> <script.ps1> --save host.txt`
     一步完成远程拉起+本地落盘（ECD AK 配在 `~/.csdbg/ecd.json`，**与 SLS AK 分开管理**）
   - **路径 C（一键，推荐）**：`csdbg host-events <设备ID> [--desktop-id <ecd-xxx>] [--start ISO] [--end ISO]`
     自动走 ECD 实锤 → SLS 心跳重建兜底（`scripts/host_events_query.py`），输出可直接喂 `--host-bundle`；
     `cross_analysis.py --host-events-equipment <设备ID>` 将其固化进四方证据包（§3b 专项段）。
     仅查"电源/重启/崩溃"时用它，不必整包收集。

   三条路产出的文本/zip 都可直接喂 `--host-bundle`。取数脚本内核心命令：
   `Get-WinEvent -FilterHashtable @{LogName='System'; ID=6005,6006,6008,41,1074,1076; StartTime=…; EndTime=…}`（开关机/异常关机）
   + Application 日志 1000/1002（崩溃/挂起）+ Tcpip/Operational 4202/4201（网络）
