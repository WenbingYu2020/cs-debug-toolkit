# 原子查询命令速查（query-cookbook）

> 全部命令**只读**。`<ch>` ∈ `douyin | jingdong | pinduoduo | qianniu`；时间一律北京时间 ISO（`YYYY-MM-DDTHH:MM:SS`）。
> 配置链：`--config` > `CSDBG_CONFIG` > 脚本同目录 `channels.json` > `~/.csdbg/channels.json`；输出目录同理（`CSDBG_TEMP`）。

## 1. SLS：RPA 端（设备/客户端行为，首选）

```bash
python scripts/sls_sql_query.py --channel <ch> \
  --sql-where "extra_client_username like '%<账号昵称>%'" \
  --start <ISO> --end <ISO> --limit 4000 --output rpa.json
```
- 按设备：`--sql-where "message like '%<equipment_id>%'"`
- 按会话：`--sql-where "message like '%<conversation_id>%'"`
- 多条件 AND/OR 直写 SQL；**不要**给关键词加引号（下划线会被分词）。
- 4 渠道并行：`rpa_log_query.py`（一次多渠道路径）；单渠道定点排查用本脚本更快。

## 2. SLS：服务端（BY 处理链路）

```bash
python scripts/server_log_query.py --conversation-id <conv_id> --start <ISO> --end <ISO> \
  --grep "关键词1,关键词2"            # 逗号分隔多关键词
python scripts/sls_sql_query.py --project bty-prod-ack-log --logstore customer-servhub-api \
  --sql-where "<SQL>" --start <ISO> --end <ISO> --limit 3000 --output srv.json
```
- 常用字段/关键词：`running_state`、`has_manual_takeover`、`没有消息需要处理`、`未命中任何规则`、
  `route-to-a-live-agent`、`customer-reply-timeout`、`服务端检测重复消息`、`no_human_online`。
- 服务端三指标（接待量 / 端到端平响 / 回复条数）走 `server_log_query.py` 的聚合模式。

## 3. 会话台账与时间线（cs-cli）

```bash
python scripts/conv_list_all.py --workspace <ws_id> --agent <config_id> --day <YYYY-MM-DD> --out convs.json
python scripts/conv_timeline.py  --workspace <ws_id> --conv <conv_id> --out tl.json
python scripts/dup_skip_audit.py --workspace <ws_id> --convs-file <ids.txt> --out audit.json
cs-cli conversation list --workspace <ws_id> --agent <config_id> --start <ISO> --end <ISO>
cs-cli conversation records <conv_id>
cs-cli debug record <assistant_record_id>       # 单条回复的 flow_info
cs-cli debug reproduce <record_id>              # AI 是否被调用（"聊天记录不存在"= 零调用）
cs-cli monitor tickets list --agent <config_id> # 工单/告警轨迹
cs-cli ops-record list                          # 运维变更记录
```
> `conv_list_all` 自动翻页；台账缺"工单派发过程"，那部分必须回 SLS。

## 4. 平响（响应时间）专项

```bash
python scripts/gap_analysis.py --conversation-id <conv_id> --start <ISO> --end <ISO>
python scripts/gap_analysis.py --workspace <ws_id> --agent <config_id> --start <ISO> --end <ISO>
```
- 产出：user→assistant 间隔分布 / `duration` / failed 签名统计；用于"平台报值 vs 服务端真值"对比。
- 判定要点：**平台口径**含人工响应、跨夜封顶（30min）、送信失败长尾；**服务端口径**只算 AI 往返。

## 5. 主机/IP 侧

```bash
python scripts/host_events_query.py --equipment-id <eq_id> --start <ISO> --end <ISO> --save host_events.txt
python scripts/cross_analysis.py --conversation-id <conv_id> --start <ISO> --end <ISO> \
  --host-bundle <RpaLogCollect_*.zip | 目录 | 文本>          # 主机本地面（Windows 事件/客户端日志）
csdbg host-pull --host <hostname> --script scripts/collect_rpa_logs.ps1
csdbg host-pull --host <hostname> --script scripts/jm_host_cache_diag.ps1   # 京麦缓存诊断
```
- ECD 远程拉起需**独立 ECD AK**（`ecd.json`），不随包分发；输出有 **24KB 截断**，拆小查询。

## 6. 设备截图回放（证据帧）

```bash
python scripts/fetch_equipment_shots.py --equipment-id <eq_id> --workspace <ws_id> \
  --start <ISO> --end <ISO> --pick <HH:MM:SS>,<HH:MM:SS> --out-dir ./shots
python scripts/fetch_equipment_shots.py --equipment-id <eq_id> --workspace <ws_id> \
  --start <ISO> --end <ISO> --list-only          # 先列帧清单再挑
```
- 帧源：RPA 30s 桌面截图 → `handle_upload`；下载走 `POST /v1/knowledge/oss/sign-url`（整 key 作 source + `Workspace-Id` 头）。
- 截图常含超时倒计时红字水印，是"客户在等"的直接证据。

## 7. 四方交叉一键取证

```bash
python scripts/cross_analysis.py --conversation-id <conv_id> --channel <ch> \
  --start <ISO> --end <ISO> [--host-events-equipment <eq_id>] [--host-bundle <zip>]
csdbg signatures --match-dir <证据包目录>       # 生成后立刻做签名匹配
```
- 产出 `evidence_*/`：`server.json` / `rpa_<ch>.json` / `ops.json` / `host.json` / `anchors.json` / `meta.json` / `evidence.md`。

## 8. 常见坑（踩过的）

| 坑 | 表现 | 规避 |
|---|---|---|
| 中文分词 | 搜 `失败` 命中不了 `登录执行失败` | 子串语义一律用 SQL `LIKE`（`sls_sql_query.py`） |
| 引号 | `--query '"abc_def"'` 命中 0 | 关键词**不加引号**；多词用 `AND` |
| limit 截断 | 返回行数 == `--limit` | 视为疑似截断，缩窗或 `group by` 重查 |
| 大 result 限制 | 单次取数有行数上限 | 分时段拉取；避免全量扫描（`--search "*"` 代价高） |
| 时间基准 | 多算 8 小时 | `__time__` **已是北京时间**，勿再 +8h |
| 输出被管道截断 | `--output` 没生成 | 别 `| head`（SIGPIPE 杀进程） |
| 升级噪音 | JSON 解析报错 | `csapi.py` 用 `raw_decode`；自己写解析别 `json.loads` 整段 |
| 心跳误读 | 把断流当主机故障 | 先看 ECD 有无电源/崩溃事件，再下结论 |
| 会话名与 ID | 用短码导致报告不合格 | ID 一律完整 32 位（见 report-format） |
