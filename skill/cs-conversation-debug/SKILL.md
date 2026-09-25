---
user-invocable: true
name: cs-conversation-debug
description: |
  从会话 ID (conversation_id) 出发，展示完整消息列表，用户选择目标 Agent 回复后自动触发根因分析。
  适用于"只知道会话 ID，不知道哪条消息有问题"的场景。内置 4 维根因分析框架
  （与 cs-chat-debug 同框架；已知 record_id 且环境装有 cs-chat-debug 时直接用那个更快）。
  触发词：conversation debug、会话分析、从会话找问题、conversation_id 分析、
  分析这个会话、这个会话哪里有问题、会话根因分析。
argument-hint: "<conversation_id>"
allowed-tools: Bash, Read, Write
---

# CS-Conversation-Debug：从会话 ID 到根因分析

## 概述

输入一个 `conversation_id`，自动完成：

1. 拉取该会话的**完整消息列表**（`cs-cli conversation records`）
2. 以**时间线表格**展示所有消息（#/时间/role/type/内容摘要）
3. **用户选择**要分析的 Agent 回复序号
4. 并行拉取 **debug trace** + **上下文**
5. **4 维根因分析**（本技能内置，与 cs-chat-debug 同框架）
6. **直接在终端输出结构化报告**（模板见本目录 `references/report-templates.md`，不强制落盘）

## 路径约定（先读）

**本技能的中间产物目录 `<中间目录>`**，按安装形态二选一：

| 形态 | 判断依据 | `<中间目录>` |
|---|---|---|
| **A. CLI 安装**（`npm i -g cs-debug-toolkit`） | `csdbg` 命令存在 | `~/.csdbg/temp/conv-debug/`（`csdbg paths` 的 `temp` 行 + `conv-debug/`） |
| **B. zip 解包** | 有 `<TOOLKIT>/scripts/` 本地文件 | `<TOOLKIT>/temp/conv-debug/` |

- 形态 B 的 `<TOOLKIT>` = 本工具包安装目录（环境变量 `CS_TOOLKIT_HOME`；不确定时按本文件位置反推：上两级）。
- **不要写 /tmp**（Windows 兼容）；下文示例统一写 `<TOOLKIT>/temp/`，形态 A 下整体换成 `~/.csdbg/temp/`。
- `cs-cli` 按 PATH 解析；Windows 下 Python 读写文件必须 `encoding='utf-8'`。
- 本技能只用 cs-cli 数据链路，形态 A/B 的 `cs-cli` 用法完全一致（不涉及 `csdbg` 子命令）。

## 环境要求

- `cs-cli` 已认证（`cs-cli auth whoami` 验证；失败引导 `cs-cli auth login`）
- `python` 可用（解析 JSON）
- 纯 cs-cli 数据链路，不依赖 SLS AK

---

## 执行流程

### Step 0 — 输入解析

**接收**: `conversation_id` 字符串（32 位十六进制；宽松校验允许带连字符）。
格式不对直接报错说明，不继续。

### Step 1 — 拉取会话消息列表

**命令**:
```bash
cs-cli conversation records <conversation_id> > <TOOLKIT>/temp/conv-debug-records.json 2>&1
```

**⚠️ 关键数据结构说明（实测）**:

`conversation records` 返回的 `data` 是**数组**（不是 `{msg_list: [...]}`），每条记录的结构：

```json
{
  "role": "assistant",          // user | assistant
  "category": "agent_response", // "agent_response" = Agent 实际回复（有 trace）
                                // "report" = 导入的历史聊天记录（无 trace）
  "record_id": "0123456789ab...",   // 用于 debug record 的 ID（注意：不是 match_id）
  "context_type": "TEXT",       // TEXT | IMAGE | CARD
  "context": {
    "url": null,
    "text": "回复内容",
    "image": null
  },
  "message_time": "2026-08-13T12:25:35",  // ISO 格式（北京时间，非 Unix 时间戳）
  "transfer_to_human": false,
  "trace_info": {...} | null,   // 有 trace_info 的才能做 debug 分析
  "role_name": "示例旗舰店:客服A"  // 发送者名称
}
```

**解析 JSON** (Python):
```python
import json

# ⚠️ Windows 环境必须指定 encoding='utf-8'，否则 GBK 解码会失败
with open('<TOOLKIT>/temp/conv-debug-records.json', encoding='utf-8') as f:
    content = f.read()

# 安全解析（cs-cli 输出可能有尾部噪音如"发现新版本"提示）
decoder = json.JSONDecoder()
data, _ = decoder.raw_decode(content)

if not data.get('success'):
    print(f"❌ 拉取会话记录失败: {data.get('error', {}).get('message')}")
    exit(1)

records = data['data']  # data['data'] 是消息数组（不是字典！）
if not records:
    print("❌ 该会话无消息记录")
    exit(1)

user_records = [r for r in records if r['role'] == 'user']
user_id = user_records[0]['role_name'] if user_records else '未知用户'
agent_name = next((r['role_name'] for r in records if r['role'] == 'assistant'), '未知 Agent')
```

**提取关键字段**（逐条构建 index/record_id/role/type/category/time/summary/has_trace/transfer_to_human，
时间直接截取 `message_time[11:19]`，内容摘要按 TEXT/IMAGE/CARD 分别截断，参考
`references/report-templates.md` 中的完整解析代码）。

### Step 2 — 展示消息列表 + 用户选择

**终端输出**（markdown 表格）:

```markdown
## 会话消息列表（共 {N} 条）

**会话 ID**: {conversation_id}
**Agent**: {agent_name}
**用户**: {user_id}

| 序号 | 时间     | 角色      | 类型  | 类别           | Trace | 消息摘要                  |
|------|----------|-----------|-------|----------------|-------|---------------------------|
| 1    | 12:24:57 | assistant | TEXT  | agent_response | ✅    | 欢迎光临示例旗舰店... |
| 2    | 12:25:01 | user      | TEXT  | -              | -     | 那该材质的优势就是低糖吗...   |
| 3    | 12:25:11 | assistant | TEXT  | report         | ❌    | （导入的历史聊天记录）     |

**可分析消息**: {has_trace_count} 条（带 ✅ 的 agent_response）
```

**⚠️ 关键筛选规则**：只有同时满足以下条件的消息才能做根因分析：
`role == 'assistant'` 且 `category == 'agent_response'` 且 `trace_info` 非空。
一条都没有 → 明确告知"该会话无可分析的 Agent 回复（全是导入历史记录或缺 trace）"并停止。

**容错逻辑**:
- 只有 1 条可分析消息 → **自动选中**，跳过交互，直接进入 Step 3
- 有 2+ 条 → 请用户选择序号：环境有 AskUserQuestion 之类的交互工具就用它
  （列出选项：`#序号 [时间] 摘要` + record_id 前缀/是否转人工）；**没有就直接在回复里
  把带 ✅ 的消息列表贴出来让用户回序号**，等回答后再继续。超过 10 条只展示前 10 条并提示。

**提取用户选择后**：二次验证所选消息确实有 trace；找到它之前最近一条 user 消息作为
`user_query`（若前面没有 user 消息，如 Agent 主动打招呼，用会话第一条 user）。

### Step 3 — 拉取 debug trace

```bash
cs-cli debug record "<assistant_record_id>" > <TOOLKIT>/temp/conv-debug-trace.json 2>&1
```

解析（同样 `encoding='utf-8'` + `raw_decode`）：校验 `success` 与 `data.flow_info` 非空
（`category=report` 的消息会返回 null flow_info，无法分析）。
上下文 = 选中消息及其之前 3 条 records（role/time/text）。

### Step 4 — 4 维根因分析（内置框架）

数据来源：对话上下文用 Step 1 的 records 数组；技术链路用 Step 3 的 `flow_info`。

#### 4.1 用户最后真实诉求是什么？

- 从选中消息往前找最近的 user 消息（`context.text` 字段）
- **如果最后一条是"转人工"** → 真实诉求在它之前那条（CARD/IMAGE/TEXT）
- **如果用户发了纯图片**（context_type=IMAGE，context.text 为空）→ 期望 Agent 看图说话
- **如果用户发了商品 CARD** → 意图与该商品强相关

#### 4.2 Agent 这一轮回复对不对？

- 检查选中回复内容 vs 用户诉求：**是否回应了用户问题？** 还是**自顾自念了一段无关话术**？
- 使用 `flow_info` 字段：`reasoning`（推理）、`scene_summary`（场景理解）、`messages`（实际回复）

#### 4.3 转人工/失败的技术路径是什么？

**判定 4 类路径**：

| 类型 | 判定条件 | 含义 |
|---|---|---|
| **Layer 0 关键词硬短路** | `intent_thinking=null` + `event_one=null` + `debug_message` 含 "无思考过程" + `messages` 含 TRANSFER | LLM 完全没跑 |
| **AI 分析转人工** | `intent_thinking` 非空 + 最终输出 TRANSFER | 意图识别 LLM 主动判定该转 |
| **Agent 主动转人工** | `behavior.action` 含 SOP 中明确的转人工分支 | SOP 走到了"转人工"分支 |
| **答非所问 / 普通失败** | 没有 TRANSFER，但回复与用户诉求不匹配 | 路由错误 / SOP 缺陷 |

#### 4.4 配置根因在哪一层？

按优先级排查：

1. **商品数据是否完整？** → `flow_info.product_data` 字段全空 = 商品学习失败
2. **图片 OCR 有没有用上？** → `flow_info.context_infos.image_content` vs Agent 回复
3. **FAQ 是否截胡？** → `flow_info.business_context.faq` 命中且答案与回复高度相似
4. **SA situation 边界是否清晰？** → 命中的 `situation` 是否覆盖用户问法
5. **SOP 是否覆盖该子场景？** → `flow_info.behavior.action` 中是否有相关分支
6. **知识库 / common_knowledge？** → `flow_info.business_context.common`
7. **是否需要 Layer 0 兜底？** → 用户发纯图片/无文字等通用场景

### Step 5 — 输出结构化报告

按 `references/report-templates.md` 的模板直接在终端输出，文件名
`conv-debug_<会话前8位>_<HHMM>.md`。
默认不落盘；**用户要求留档/结案时**写入报告交付目录——本机 cs-cli 项目环境写
`D:\temp\<客服账号名>\`（先校验目录，不存在才创建；见 `docs/REPORT_STANDARD.md` §5.1），
外部分发包环境写 `<TOOLKIT>/temp/`。
支持重复分析：每次可选不同消息，各自输出新报告。

---

## 注意事项

1. **数据结构差异（实测发现）**：`data` 是数组；ID 字段是 `record_id`（不是 `match_id`）；
   时间字段是 `message_time`（ISO 格式，不是 Unix 时间戳）
2. **category 区分（关键）**：`agent_response` 有 trace 可分析；`report` 是导入历史记录无
   trace，不可分析——只展示/允许选择前者
3. **Windows 环境**：Python 读写必须 `encoding='utf-8'`；路径用 `os.path.join()` 风格拼接
4. **JSON 解析**：cs-cli 输出可能带尾部噪音（版本提示等），必须 `raw_decode` 而非 `json.loads`
5. **与 cs-chat-debug 的关系**：已知 `record_id` 且环境装有 cs-chat-debug → 直接用那个更快；
   本技能适用于"只有会话 ID"场景，分析框架完全一致
6. **认证失败**：`cs-cli auth whoami` 报错时引导 `cs-cli auth login --phone <手机号> --password <密码>`

## 关键经验：Layer 0 短路 vs AI 分析转人工 判定表

| 现象 | Layer 0 短路 | AI 分析转人工 |
|---|---|---|
| `intent_thinking` | **null** | 非空（有思考文本）|
| `event_one` / `event_two` | **null** | 通常有值 |
| `debug_message` 含 "无思考过程" | **是** | 否 |
| `general_qa_thinking` | **空字符串** | 可能有 |
| Agent 输出 | 固定话术 + TRANSFER | 个性化话术 + TRANSFER |
| 用户最后一条消息 | 通常含"转人工/人工客服/找客服"等关键词 | 任意 |

**判定后果**：
- **Layer 0 短路** → 真正的根因不在转人工本身，而在它**之前**用户为什么不爽。要分析倒数第 2~3 轮 Agent 回复
- **AI 分析转人工** → 直接看 `intent_thinking` 的判断逻辑，定位 SOP/SA 配置问题
