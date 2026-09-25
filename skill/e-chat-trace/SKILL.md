---
user-invocable: true
name: e-chat-trace
description: |
  电商客服消息全链路排查工具。输入 conversation_id + 问题描述，自动拉取 Agent trace + RPA 日志，
  综合分析 Agent 推理链路与 RPA 收发链路，定位消息延迟、发送失败、内容异常等问题的根因。
  支持千牛/抖音/京东/拼多多四大渠道，自动识别渠道并查询对应 RPA 日志。
  分析结论直接输出到终端，不生成文件。
  触发词：e-chat-trace、消息链路排查、查消息延迟、RPA 日志分析、消息发送异常、
  为什么延迟、消息没发出去、回复慢、欢迎语延迟。
argument-hint: "<conversation_id> [目标消息内容或问题描述]"
allowed-tools: Bash, Read
---

# E-Chat-Trace：电商客服消息全链路排查工具

## 概述

输入 conversation_id（可附带目标消息内容或问题描述），自动完成：

1. 拉取会话的**完整消息记录**（cs-cli），构建消息时间线
2. 根据会话数据**自动识别渠道**（千牛/抖音/京东/拼多多）
3. 查询 **Agent 日志**（阿里云 SLS：bty-prod-ack-log/customer-servhub-api）
4. 查询对应渠道的 **RPA 日志**（阿里云 SLS：customer-servhub-log/{渠道 logstore}）
5. 综合分析 Agent + RPA 全链路，**定位根因**
6. **终端输出**结构化报告（不保存文件）

```
输入:
  conversation_id 字符串             例如: 0123456789abcdef0123456789abcdef
  可选: 目标消息内容或问题描述        例如: "您好，很高兴为您服务。" 或 "消息延迟"

输出:
  终端: 结构化排查报告（根因结论 + 时间线 + 日志证据 + 修复建议）
  不生成文件
```

## 适用场景

| 场景 | 典型表现 | 排查重点 |
|---|---|---|
| **消息发送延迟** | 用户等待回复时间过长 | RPA 发送队列 + Agent 推理耗时 |
| **欢迎语延迟** | 用户进线后长时间无欢迎语 | RPA 面板识别 + 队列排队 |
| **消息发送失败** | 消息未到达用户 | RPA 发送结果 + 平台 API |
| **消息内容错误** | Agent 回复内容不正确 | Agent trace + SOP + 知识库 |
| **消息丢失** | 用户消息未被处理 | RPA 读取 + Agent 接收 |
| **重复发送** | 同一消息发送多次 | RPA 重试 + 队列去重 |
| **转人工异常** | 不应转人工却转了 | Agent 意图识别 + SOP |

## 环境要求

- `cs-cli` 已认证（`cs-cli auth whoami` 验证）
- `python3` 可用（用于解析 JSON）
- 阿里云 SLS 凭证已配置（环境变量 `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET`）
- `aliyun-log-python-sdk` 已安装（`pip install aliyun-log-python-sdk`）

---

## 执行流程

### Step 0：输入解析

解析用户输入，提取：
- `conversation_id`：会话 ID（必需）
- `target_message`：目标消息内容（可选，用于定位具体消息）
- `issue_description`：问题描述（可选，如"消息延迟"/"发送失败"）

如果用户只提供了 conversation_id，skill 将分析整个会话的所有异常。
如果提供了目标消息内容，将重点分析该消息的发送链路。

### Step 1：拉取会话消息记录

```bash
cs-cli conversation records <conversation_id> --page-size 100
```

解析返回的 JSON，提取每条消息的：
- `record_id`
- `role`（user/assistant/system）
- `category`（report/agent_response）
- `message_time`（用户看到的时间）
- `created_at`（系统入库时间）
- `reply_time`（实际发送时间）
- `duration_time`（总耗时）
- `agent_duration_time`（Agent 推理耗时）
- `context.text`（消息内容）

**构建消息时间线表**：按 message_time 排序，标注每条消息的角色、类型、时间差。

### Step 2：自动识别渠道

**渠道识别逻辑**（按优先级）：

1. **从 role_id / role_name 字段识别**：
   - 包含"千牛" / "淘宝" / "天猫" → `qianniu`
   - 包含"抖音" / "douyin" → `douyin`
   - 包含"京东" / "jd" → `jd`
   - 包含"拼多多" / "pdd" → `pdd`

2. **从 equipment_information_id 识别**：
   - 查询关联的设备信息，判断渠道

3. **从 user_name 前缀识别**：
   - `jd_` 开头 → `jd`
   - `tb_` / `taobao_` 开头 → `qianniu`
   - `dy_` 开头 → `douyin`
   - `pdd_` 开头 → `pdd`

4. **从 message_id 格式识别**：
   - 千牛消息 ID 格式：`数字.PNM`
   - 京东消息 ID 格式：`jd-xxx`

5. **兜底**：询问用户确认渠道

**渠道 → SLS logstore 映射**：

| 渠道 | logstore |
|------|----------|
| 千牛（淘宝/天猫） | `qianniu-rpa-new-prod` |
| 抖音 | `project-douyin-rpa-prod` |
| 京东 | `project-jd-rpa-prod` |
| 拼多多 | `project-pdd-rpa-prod` |

### Step 3：异常检测与目标消息定位

遍历消息时间线，检测以下异常：

**3.1 消息延迟检测**（Agent 回复）：
```python
for msg in messages:
    if msg.category == 'agent_response':
        total_delay = msg.reply_time - msg.created_at
        agent_time = msg.agent_duration_time
        non_agent_time = total_delay - agent_time
        
        if total_delay > 60:  # 超过 60 秒
            flag_as_delayed(msg, total_delay, agent_time, non_agent_time)
```

**3.2 欢迎语延迟检测**：
```python
# 找到第一条用户消息和欢迎语
first_user_msg = first(m for m in messages if m.role == 'user')
welcome_msg = first(m for m in messages if '您好' in m.text and m.role == 'assistant')

if welcome_msg and first_user_msg:
    delay = welcome_msg.message_time - first_user_msg.message_time
    if delay > 30:  # 超过 30 秒
        flag_welcome_delay(delay)
```

**3.3 消息丢失检测**：
```python
# 检查用户消息后是否有 Agent 回复
for i, msg in enumerate(messages):
    if msg.role == 'user' and msg.category != 'report':
        next_assistant = find_next_assistant_msg(messages, i)
        if not next_assistant:
            flag_message_lost(msg)
```

**3.4 消息顺序异常检测**：
```python
# 检查 message_time 和 created_at 的一致性
for msg in messages:
    if msg.created_at and msg.message_time:
        diff = msg.created_at - msg.message_time
        if abs(diff) > 120:  # 超过 2 分钟差异
            flag_time_anomaly(msg, diff)
```

如果用户指定了目标消息，直接定位该消息进行分析。
如果没有指定，分析所有检测到的异常。

### Step 4：查询 Agent 日志（阿里云 SLS）

对于需要分析的 `category=agent_response` 消息，不再使用 `cs-cli debug record`，而是直接查 SLS。

**4.1 Agent SLS 配置**：
```
endpoint: cn-hangzhou.log.aliyuncs.com
project: bty-prod-ack-log
logstore: customer-servhub-api
region: cn-hangzhou
```

**4.2 查询 Agent 日志**：

使用 `aliyun-log-python-sdk`：

```python
from aliyun.log import LogClient

client = LogClient(
    'cn-hangzhou.log.aliyuncs.com',
    os.environ['ALIYUN_ACCESS_KEY_ID'],
    os.environ['ALIYUN_ACCESS_KEY_SECRET']
)

# 按 conversation_id 查询 Agent 日志
sql = f"{conversation_id} | SELECT * WHERE __topic__ = 'agent-trace' LIMIT 100"
response = client.execute_logstore_sql(
    'bty-prod-ack-log', 'customer-servhub-api',
    from_time, to_time, sql, False
)
```

**4.3 Agent 日志关键字段**：

| 字段 | 含义 |
|------|------|
| `conversation_id` | 会话 ID |
| `record_id` | 消息记录 ID |
| `event_one` / `event_two` | 意图识别（一级/二级） |
| `behavior_situation` / `behavior_action` | SA/SOP 命中情况 |
| `llm_start_time` / `llm_end_time` | LLM 调用时间 |
| `llm_duration` | LLM 推理耗时（秒） |
| `total_duration` | 总处理耗时（秒） |
| `transfer_to_human` | 是否转人工 |
| `response_content` | Agent 回复内容 |
| `tool_calls` | 工具调用记录 |
| `error_message` | 错误信息 |

**4.4 Agent 日志模式识别**：

| 模式 | 检查方法 | 含义 |
|------|---------|------|
| **LLM 推理超时** | `llm_duration > 30s` | LLM 调用时间过长 |
| **工具调用失败** | `tool_calls` 包含 error | 商品查询、订单查询等工具失败 |
| **意图识别错误** | `event_one/event_two` 与用户诉求不匹配 | 意图路由错误 |
| **SOP 未命中** | `behavior_action` 为空 | 没有匹配的 SOP |
| **转人工触发** | `transfer_to_human = true` | 主动或被动转人工 |
| **API 异常** | `error_message` 不为空 | Agent 服务异常 |

**Agent 推理评估标准**：
```
✅ 正常: total_duration < 15 秒
⚠️ 偏慢: 15 秒 < total_duration < 30 秒
🔴 异常: total_duration > 30 秒
```

### Step 5：查询 RPA 日志（阿里云 SLS）

**5.1 确定查询参数**：
- `logstore`：根据 Step 2 识别的渠道
- `time_range`：异常消息前后 3 分钟
- `shop_name`：从 role_name 提取店铺名

**5.2 阿里云 SLS 查询**：

使用 `aliyun-log-python-sdk`：

```python
from aliyun.log import LogClient

client = LogClient(
    'cn-hangzhou.log.aliyuncs.com',
    os.environ['ALIYUN_ACCESS_KEY_ID'],
    os.environ['ALIYUN_ACCESS_KEY_SECRET']
)

# 先查询该店铺在该时段的所有日志
sql = f"{shop_name} | SELECT * LIMIT 500"
response = client.execute_logstore_sql(
    'customer-servhub-log', logstore,
    from_time, to_time, sql, False
)
```

**5.3 日志过滤与关联**：

从返回的日志中，按 conversation_id 或用户昵称过滤出相关日志。

**5.4 RPA 日志模式识别**：

基于前面 4 个案例总结的典型模式：

| 模式 | 日志关键词 | 含义 |
|------|----------|------|
| **发送队列堵塞** | `reply-message 入队` → `发送消息成功` 间隔 >60s | Agent 回复入队后长时间未发送 |
| **面板串台误判** | `新用户面板昵称已属其他会话` / `疑似串台` | 昵称冲突导致拒绝建会话 |
| **面板未确认重试** | `面板未确认` / `匹配待确认` / `count=` | 面板状态不确定，多次重试 |
| **处理队列排队** | `列表快照` + `接待=N`（N>10） | 高负载排队 |
| **欢迎语发送** | `欢迎语发送成功` | 欢迎语实际发送时间 |
| **消息上报** | `receive-message` / `消息已上报` | RPA 上报消息到 Agent |
| **回复接收** | `reply-message` | RPA 收到 Agent 回复 |
| **发送结果** | `reply-message-result` | 消息发送结果（成功/失败） |
| **UI 锁** | `UI 锁忙` | RPA 客户端繁忙 |
| **商品抓取失败** | `面板买家昵称未对上，放弃商品抓取` | 昵称不一致 |

### Step 6：综合分析与根因定位

**6.1 构建端到端时间线**：

合并 conversation records + Agent SLS 日志 + RPA SLS 日志，按时间排序：

```
[时间]       [来源]         [事件]
13:44:00     [Conv]         用户发送消息"今天会发货吗"
13:44:06     [RPA-SLS]      receive-message msgs=16（RPA 上报消息）
13:44:08     [Agent-SLS]    Agent 收到请求（request_start）
13:44:08     [Agent-SLS]    意图识别：催发货&催物流（planner）
13:44:10     [Agent-SLS]    工具调用：order_query（867ms success）
13:44:18     [Agent-SLS]    LLM 推理完成（response_time=9.67s）
13:44:17     [RPA-SLS]      收到 Agent 回复，入队（reply-message）
13:46:25     [RPA-SLS]      消息发送到平台（发送消息成功）
13:46:26     [Conv]         reply_time 记录
```

**双 SLS 交叉验证**：Agent SLS 记录了"请求开始→推理完成"的时间，RPA SLS 记录了"消息上报→收到回复→发送成功"的时间，两者可以交叉对齐，精确定位延迟环节。

**6.2 延迟分解**：

将总延迟分解为各环节：
1. **用户消息 → RPA 上报**：RPA 读取延迟
2. **RPA 上报 → Agent 开始**：消息同步延迟
3. **Agent 开始 → Agent 完成**：推理耗时
4. **Agent 完成 → RPA 收到**：回复传输延迟
5. **RPA 收到 → RPA 发送**：发送队列延迟
6. **RPA 发送 → 平台确认**：平台 API 延迟

**6.3 根因判定**：

按延迟占比确定主因：
- 占比 > 50% 的环节为主因
- 占比 > 20% 的环节为次因

**6.4 严重程度评估**：

| 延迟范围 | 评级 |
|---------|------|
| < 30 秒 | ✅ 正常 |
| 30-60 秒 | 🟡 中等 |
| 60-120 秒 | 🔴 严重 |
| > 120 秒 | 🔴🔴 极严重 |

### Step 7：终端输出报告

**直接在终端输出，不保存文件**。

报告格式：

```
================================================================================
           E-Chat 消息链路排查报告
================================================================================

会话 ID: <conversation_id>
渠道: <channel_name>
店铺: <shop_name>
用户: <user_name>
时间: <time_range>

================================================================================
核心结论
================================================================================

<emoji> <一句话根因总结>

责任方: <Agent 侧 / RPA 侧 / 平台侧>

延迟分解:
  • <环节1>: <耗时> (<占比>%) [← 主因/次因]
  • <环节2>: <耗时> (<占比>%)
  ...

================================================================================
完整时间线
================================================================================

<时间轴，合并 Conv + Agent + RPA 三方数据>

================================================================================
Agent 推理分析
================================================================================

<Agent trace 分析结果，包含推理时长、意图识别、SOP 命中等>

================================================================================
RPA 日志分析
================================================================================

<RPA 日志关键证据>

================================================================================
修复建议
================================================================================

<P0/P1 修复建议>

================================================================================
```

---

## 注意事项

1. **SLS 双源查询**：Agent 日志查 `bty-prod-ack-log/customer-servhub-api`，RPA 日志查 `customer-servhub-log/{渠道 logstore}`
2. **并行拉取**：conversation records、Agent 日志、RPA 日志可以并行查询
3. **渠道识别要准确**：查错 RPA logstore 会找不到日志
4. **时间窗口要足够大**：日志查询时间范围取异常消息前后 5 分钟（Agent 可能有处理延迟）
5. **不保存文件**：所有分析结果直接输出到终端
6. **SLS 认证**：需要环境变量 `ALIYUN_ACCESS_KEY_ID` 和 `ALIYUN_ACCESS_KEY_SECRET`
7. **SLS 查询限制**：
   - Agent 日志按 conversation_id 全文搜索，客户端按 record_id 过滤
   - RPA 日志用店铺名全文搜索，客户端按 conversation_id / 用户名过滤
   - 单次最多返回 100-500 条
8. **JSON 解析**：cs-cli 输出可能带尾部噪音（版本更新提示），用 `json.JSONDecoder().raw_decode()` 解析
9. **时区**：所有时间戳统一使用北京时间（Asia/Shanghai）
10. **Agent 日志字段**：从 SLS 直接读取，不再依赖 cs-cli debug record

---

## 典型问题模式速查表

### Agent 侧问题

| 问题 | 检查方法 | 关键字段 |
|------|---------|---------|
| 推理超时 | trace.response_time > 30s | response_time |
| 意图错误 | event_one/event_two 与用户诉求不匹配 | event_one, event_two |
| SOP 未覆盖 | behavior.action 为空 | behavior |
| FAQ 截胡 | FAQ 命中且回复内容一致 | llm_payload.faq_knowledge |
| 商品数据缺失 | product_data 为空 | llm_payload.product_data |
| 转人工错误 | transfer_to_human=True 但不应转 | transfer_to_human |

### RPA 侧问题

| 问题 | 检查方法 | 日志关键词 |
|------|---------|----------|
| 发送队列堵塞 | 入队到发送间隔 > 60s | `reply-message 入队` → `发送消息成功` |
| 面板串台 | 昵称冲突拒绝建会话 | `昵称已属其他会话` / `串台` |
| 面板未确认 | 多次重试确认 | `面板未确认` / `匹配待确认` |
| 队列排队 | 接待用户数 > 10 | `列表快照` + `接待=` |
| 欢迎语延迟 | 进线到欢迎语 > 30s | `欢迎语发送成功` |
| 消息上报延迟 | 上报时间晚于消息时间 | `receive-message` |
| 发送失败 | 发送结果非 success | `reply-message-result` + `status=` |
| UI 锁占用 | 客户端繁忙 | `UI 锁忙` |

---

## SLS 查询参考

### 阿里云 SLS 两大日志源

**Agent 日志**：
```
endpoint: cn-hangzhou.log.aliyuncs.com
project: bty-prod-ack-log
logstore: customer-servhub-api
说明: Agent 服务端日志，包含推理链路、意图识别、SOP 命中、工具调用、耗时等
链接: https://sls.console.aliyun.com/lognext/project/bty-prod-ack-log/logsearch/customer-servhub-api?slsRegion=cn-hangzhou
```

**RPA 日志**：
```
endpoint: cn-hangzhou.log.aliyuncs.com
project: customer-servhub-log
logstore: 根据渠道选择（见下表）
说明: RPA 客户端日志，包含消息收发、面板操作、队列状态等
链接: https://sls.console.aliyun.com/lognext/project/customer-servhub-log/overview?slsRegion=cn-hangzhou
```

### RPA logstore 映射

| 渠道 | logstore（生产） | logstore（开发） |
|------|-----------------|-----------------|
| 千牛（淘宝/天猫） | qianniu-rpa-new-prod | qianniu-rpa-new-dev |
| 抖音 | project-douyin-rpa-prod | project-douyin-rpa-dev |
| 京东 | project-jd-rpa-prod | project-jd-rpa-dev |
| 拼多多 | project-pdd-rpa-prod | project-pdd-rpa-dev |
| 千牛（旧版） | project-qianniu-rpa-prod | — |

### SLS 查询语法

```python
from aliyun.log import LogClient

client = LogClient(endpoint, access_key_id, access_key_secret)

# Agent 日志查询
agent_sql = f"{conversation_id} | SELECT * LIMIT 100"
agent_response = client.execute_logstore_sql(
    'bty-prod-ack-log', 'customer-servhub-api',
    from_time, to_time, agent_sql, False
)

# RPA 日志查询
rpa_sql = f"{shop_name} | SELECT * LIMIT 500"
rpa_response = client.execute_logstore_sql(
    'customer-servhub-log', rpa_logstore,
    from_time, to_time, rpa_sql, False
)
```

### 环境变量

```bash
export ALIYUN_ACCESS_KEY_ID="<your_key>"
export ALIYUN_ACCESS_KEY_SECRET="<your_secret>"
```

---

## 跨技能协作

| 技能 | 用途 | 调用时机 |
|------|------|---------|
| `cs-chat-debug` | 单条 Agent 回复的深度根因分析 | 当发现 Agent 推理有问题时 |
| `cs-issue-analyse` | 系统性问题分析 | 当发现是配置/SOP 问题时 |
| `cs-sop-check` | SOP 配置检查 | 当发现 SOP 未覆盖时 |

**区别**：
- `e-chat-trace`：**端到端链路排查**，Agent + RPA 全链路，侧重"为什么消息延迟/失败"
- `cs-chat-debug`：**Agent 回复根因分析**，侧重"为什么 Agent 这样回复"
