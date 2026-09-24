---
user-invocable: true
name: cs-rpa-log
description: |
  从阿里云 SLS 查询 RPA 日志，支持 4 个渠道（抖音/京东/拼多多/千牛）。
  可按设备 ID、会话 ID、消息内容查询，输出时间线分析和 JSON 原始数据。
  触发词：cs-rpa-log、RPA 日志查询、查询 RPA 日志、分析 RPA 报错、
  为什么发送失败、设备日志分析。
argument-hint: "<channel> [--equipment-id <id>] [--conversation-id <id>] [--query <text>] [--start <time>] [--end <time>]"
allowed-tools: Bash, Read
---

# cs-rpa-log · RPA 日志分析工具

## 用途

从阿里云 SLS (Log Service) 查询 BetterYeah 客服系统的 RPA 日志，支持：
- **4 个渠道**：抖音 (douyin) / 京东 (jingdong) / 拼多多 (pinduoduo) / 千牛 (qianniu)
- **多种查询方式**：设备 ID、会话 ID、消息内容关键词
- **时间线分析**：自动格式化输出日志时间线，高亮错误
- **关联分析**：配合 cs-cli 查询会话消息，做端到端根因分析

典型场景：
- "为什么这条消息发送失败？"
- "拼多多设备 xxx 在 12:33 触发了什么错误？"
- "查询抖音 WIS 店铺在 10:30-10:50 的 RPA 日志"

## 路径约定（先读）

**先判断安装形态**（下文命令二选一，优先形态 A）：

| 形态 | 判断依据 | 本技能的脚本调用 | 配置 |
|---|---|---|---|
| **A. CLI 安装**（`npm i -g cs-debug-toolkit`） | `csdbg` 命令存在 | `csdbg rpa <参数>`（参数与脚本完全一致） | `~/.csdbg/channels.json`（`csdbg paths` 的 `config` 行） |
| **B. zip 解包** | 有 `<TOOLKIT>/scripts/rpa_log_query.py` | `python <TOOLKIT>/scripts/rpa_log_query.py <参数>`（或先 `cd <TOOLKIT>` 后用 `scripts/rpa_log_query.py`） | `<TOOLKIT>/scripts/channels.json` |

下文示例统一写形态 B 的命令；形态 A 把 `python scripts/rpa_log_query.py` 整体换成 `csdbg rpa` 即可，
其余参数一字不改（`--output` 相对路径按当前目录解析，建议直接给绝对路径）。

- 形态 B 的 `<TOOLKIT>` = 本工具包安装目录（环境变量 `CS_TOOLKIT_HOME`；不确定时按本文件位置反推：上两级）。
- Windows 输出中文：`PYTHONIOENCODING=utf-8`；别把 stdout 接 `| head`（SIGPIPE 会让 `--output` 写不出来）。

## 前置条件

- Python 3 + `aliyun-log-python-sdk`
- 配置文件：形态 A `~/.csdbg/channels.json` / 形态 B `<TOOLKIT>/scripts/channels.json`
  （由 channels.example.json 复制后填入只读 AK）
- 阿里云 SLS 查询权限（`log:GetLogStoreLogs`）

自检：形态 A `csdbg doctor`；形态 B `python scripts/rpa_log_query.py --check`（验证 SLS 连接，列出所有 logstore）。

## 用法

### 1. 验证连接 / 列出渠道

```bash
python scripts/rpa_log_query.py --check
python scripts/rpa_log_query.py --list-channels
```

### 2. 按设备 ID 查询

```bash
python scripts/rpa_log_query.py \
  --channel douyin \
  --equipment-id "7802dae4ed574ad1ab32d5d587ba429d" \
  --start "2026-08-22T10:30:00" \
  --end "2026-08-22T10:50:00"
```

### 3. 按会话 ID 查询

```bash
python scripts/rpa_log_query.py \
  --channel douyin \
  --conversation-id "dbc7a1d886834093b1a895cbb34551e0" \
  --start "2026-08-22T10:30:00" \
  --end "2026-08-22T10:50:00"
```

### 4. 按消息内容搜索

```bash
python scripts/rpa_log_query.py \
  --channel pinduoduo \
  --query "检测到官方规则考试弹窗" \
  --start "2026-08-21T12:30:00" \
  --end "2026-08-21T12:40:00"
```

### 5. 保存到 JSON 文件（供交叉分析使用）

```bash
python scripts/rpa_log_query.py \
  --channel douyin \
  --conversation-id "dbc7a1d886834093b1a895cbb34551e0" \
  --start "2026-08-22T10:30:00" \
  --end "2026-08-22T10:50:00" \
  --output "./temp/rpa_logs.json"
```

## 参数说明

| 参数 | 必需 | 说明 |
|------|------|------|
| `--check` | | 验证 SLS 连接，列出所有 logstore |
| `--list-channels` | | 列出所有已配置的渠道 |
| `--channel` | ✅ | 渠道名称：douyin / jingdong / pinduoduo / qianniu |
| `--equipment-id` | | 设备 ID（RPA 客户端标识） |
| `--conversation-id` | | 会话 ID |
| `--query` | | 消息内容关键词搜索 |
| `--start` | ✅ | 开始时间 (ISO 8601 格式: `2026-08-22T10:30:00`) |
| `--end` | ✅ | 结束时间 |
| `--dev` | | 查询开发环境（默认查询生产环境） |
| `--limit` | | 最大返回条数（默认 1000） |
| `--output` | | 输出文件路径（JSON 格式） |
| `--config` | | 自定义配置文件路径 |

## 输出格式

### 控制台输出（时间线）

```
📊 查询参数:
  渠道: 抖音 (douyin)
  Logstore: project-douyin-rpa-prod
  时间范围: 2026-08-22T10:30:00 ~ 2026-08-22T10:50:00
  查询语句: "dbc7a1d886834093b1a895cbb34551e0"
  限制条数: 1000

✅ 查询成功，返回 24 条日志

================================================================================
日志时间线
================================================================================
[  1] 10:40:03 (  0.0s) [INFO ] message_logger       _log_message
      [接收] reply-message user=《风一样的男人》_ conv=dbc7a1d...

[  2] 10:40:28 (+  25.0s) [INFO ] working_phase        _logged_handle_message
      [中控下发] type=reply-message, data={"type":"reply-message"...

[ 10] 10:44:05 (+ 242.0s) [INFO ] message_logger       _log_message
      [发送] reply-message-result conv=dbc7a1d... status=failed
      ❌ ERROR: 无法确认当前活跃会话身份，中止发送
```

### JSON 输出（原始数据）

```json
[
  {
    "__time__": 1787366403,
    "__source__": "c93njvyl0d7l9mq",
    "level": "INFO",
    "module": "message_logger",
    "function": "_log_message",
    "message": "[接收] reply-message user=《风一样的男人》_...",
    "extra_equipment_id": "7802dae4ed574ad1ab32d5d587ba429d",
    "extra_conversation_id": "dbc7a1d886834093b1a895cbb34551e0",
    "extra_data": "{...}"
  }
]
```

## 配置文件结构

`channels.json`（形态 A `~/.csdbg/channels.json` / 形态 B `scripts/channels.json`）
由 `channels.example.json` 复制而来，schema 以模板为准：
顶层共享 `endpoint` + `access_key_id`/`access_key_secret`（只读 AK）+ `rpa_project` +
`channels.<渠道>.logstore/dev_logstore` + `server` 段（供 server_log_query.py 用）。
字段含义见模板内 `_notes`，**不要回显 AK 内容**。

## 常见场景示例

### 场景 1: "为什么这条消息发送失败？"

1. 从 cs-cli 或其他地方拿到 `conversation_id`
2. 查询该会话的 RPA 日志（用法 3），在输出时间线中找到 `status=failed` 的记录
3. 查看 `ERROR:` 行了解具体原因

### 场景 2: "拼多多设备在 12:33 触发了什么错误？"

```bash
python scripts/rpa_log_query.py \
  --channel pinduoduo \
  --equipment-id "92d9395355694fba821e36b8cc75f6fc" \
  --start "2026-08-21T12:28:00" \
  --end "2026-08-21T12:40:00"
```

### 场景 3: "查询今天抖音所有 '规则考试弹窗' 报错"

```bash
python scripts/rpa_log_query.py \
  --channel pinduoduo \
  --query "检测到官方规则考试弹窗" \
  --start "2026-08-21T00:00:00" \
  --end "2026-08-21T23:59:59" \
  --output "./temp/pdd_exam_errors.json"
```

## 配合 cs-cli 关联分析

1. **从 SLS 拉取 RPA 日志**，找到 `conversation_id`
2. **用 cs-cli 拉取会话详情**：
   ```bash
   cs-cli --workspace <workspace_id> conversation records <conversation_id>
   ```
3. **对比分析**：
   - RPA 日志：发送失败时间点 + 错误原因
   - 会话消息：AI 生成回复时间 + 消息内容
   - 计算延迟：从用户提问到 RPA 收到指令的时间差

## 故障排查

### 问题 1: `❌ 连接失败: Unauthorized`

**原因**：AK 权限不足或 AK 错误

**解决**：
1. 确认 AK 是否有 `log:GetLogStoreLogs` 权限
2. 检查 `scripts/channels.json` 中的 AK 是否正确

### 问题 2: `❌ 查询失败: ParameterInvalid`

**原因**：查询语法不支持该字段的 key-value 查询

**解决**：使用全文搜索（当前版本已默认全文检索）

### 问题 3: 查询返回 0 条日志

**原因**：时间范围不对或 ID 不匹配

**解决**：
1. 确认时间范围是否包含目标事件
2. 用 `--query` 做模糊搜索验证 ID 是否存在
3. 返回行数正好等于 `--limit` 时视为疑似截断，缩小窗口重拉，别直接下"没有日志"的结论

## 与其他 skill 的关系

- 需要**服务端 + RPA + 运维 + 主机/IP 四方对齐定责** → 用 `cs-log-cross`（主入口）
- 只有会话 ID、要单条回复根因 → 用 `cs-conversation-debug`
- 本技能聚焦**单源 RPA 日志快速查询**
