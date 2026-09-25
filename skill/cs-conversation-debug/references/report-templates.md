# cs-conversation-debug · 报告模板与解析代码

供 SKILL.md Step 1（解析代码）与 Step 5（报告模板）引用。二选一模板输出即可。

## 一、关键字段提取代码（Step 1 用）

```python
import json

with open('<TOOLKIT>/temp/conv-debug-records.json', encoding='utf-8') as f:
    content = f.read()
decoder = json.JSONDecoder()
data, _ = decoder.raw_decode(content)

records = data['data']

messages = []
for idx, record in enumerate(records, start=1):
    record_id = record['record_id']      # ⚠️ 用 record_id 而非 match_id
    role = record['role']                 # user | assistant
    msg_type = record['context_type']     # TEXT | IMAGE | CARD
    category = record.get('category', '') # agent_response | report

    # 时间解析：message_time 是 ISO 格式（北京时间），直接截取 HH:MM:SS
    msg_time = record['message_time']
    time_str = msg_time[11:19]  # "2026-08-13T12:25:35" → "12:25:35"

    # 内容摘要
    context = record.get('context', {})
    text = context.get('text', '') or ''
    image = context.get('image', '') or ''

    if msg_type == 'TEXT':
        summary = text[:30] + '...' if len(text) > 30 else text
    elif msg_type == 'IMAGE':
        summary = f"[图片] {image[:40]}" if image else "[图片]"
    elif msg_type == 'CARD':
        summary = f"商品卡：{text[:20]}" if text else "[商品卡]"
    else:
        summary = text[:30] if text else f"[{msg_type}]"

    messages.append({
        'index': idx,
        'record_id': record_id,
        'role': role,
        'type': msg_type,
        'category': category,
        'time': time_str,
        'summary': summary,
        'has_trace': record.get('trace_info') is not None,
        'transfer_to_human': record.get('transfer_to_human', False)
    })

# 可分析消息 = assistant + agent_response + 有 trace
analyzable_msgs = [
    m for m in messages
    if m['role'] == 'assistant'
    and m['category'] == 'agent_response'
    and m['has_trace']
]
```

## 二、模板 A：标准 4 维根因报告（默认用这个）

```markdown
# 单条对话根因分析报告

**Record ID**: `<assistant_record_id>`
**会话 ID**: `<conversation_id>`
**Agent**: `<agent_config_name>`（`<agent_config_id>`）
**用户 ID**: `<user_id>`
**时间**: `<北京时间>`

---

## 一、结论先行（一句话）

> <一句话讲清楚为什么会发生（转人工/失败/答非所问），根因在哪一层>

---

## 二、完整对话还原（{N} 条）

| # | 时间 | role | type | 内容 |
|---|---|---|---|---|
| 1 | HH:MM:SS | user | CARD | 商品卡：xxx |
| ... | ... | ... | ... | ... |

**注**：标注关键转折点（用户诉求出现位置、Agent 答非所问位置、转人工触发位置）

---

## 三、技术链路还原

用户输入 "<最后一条 user 消息>"
   ↓
<判定：意图识别 LLM 是否执行？根据 intent_thinking/event_one/event_two>
   ↓
<判定：一般咨询 LLM 是否执行？根据 general_qa_thinking>
   ↓
<判定：实际触发的路径 — Layer 0 短路 / SOP 转人工 / 答非所问>
   ↓
<最终输出>

**证据**：
- `intent_thinking`: null/具体值
- `event_one` / `event_two`: null/具体值
- `debug_message` 关键片段：...
- `behavior.action`: ...

---

## 四、根因分析

### 🔴 主因：<一句话>
<具体证据 + 用户消息 + Agent 回复 + 期望行为的对比>

### 🟡 次因（如有）：<一句话>

### 🟢 非问题（确认无责的层）：

| 层 | 评估 |
|---|---|
| Layer 0 硬规则 | ✅ 无责 / ⚠️ 有问题 |
| 意图路由（SA） | ✅ / ⚠️ |
| SOP 流程 | ✅ / ⚠️ |
| 商品数据 | ✅ / ⚠️ |
| FAQ | ✅ / ⚠️ |
| 知识库 | ✅ / ⚠️ |

---

## 五、修复建议

| 优先级 | 修复项 | 具体动作 | 命令/位置 |
|---|---|---|---|
| P0 | ... | ... | ... |
| P1 | ... | ... | ... |

---

## 六、数据字段校正（如发现）

| 字段 | 平台值 | 实际情况 | 建议 |
|---|---|---|---|
| ... | ... | ... | ... |

---

## 七、附：testcase 补充建议（可选）

如果该问题具有典型性，建议补一条测试用例覆盖该场景。
```

## 三、模板 B：flow_info 详版报告（需要技术细节时用）

```markdown
# 会话根因分析报告

**生成时间**: {YYYY-MM-DD HH:MM:SS}
**会话 ID**: {conversation_id}
**消息 ID**: {record_id}
**Agent**: {agent_name}

---

## 1. 对话上下文

**[{time}] {role}**: {text}
...（选中消息及之前 3 条）

---

## 2. Agent 回复

**内容**: {flow_info['messages'][0]}
**响应时间**: {flow_info['response_time']:.2f}s
**是否转人工**: {transfer_to_human}

---

## 3. 意图路由分析

**一级意图 (event_one)**: {flow_info['event_one']}
**二级意图 (event_two)**: {flow_info['event_two']}
**是否售后**: {flow_info['is_after_sales']}
**场景描述**: {flow_info['scene_summary'][:200]}...
**路由判定**: ✅/⚠️ {意图路由是否准确}

---

## 4. 知识召回分析

### 4.1 商品数据
召回商品数: {len(flow_info['llm_payload']['product_data'])}
（每个商品列：标题 / ID / 链接）

### 4.2 其他知识库
- FAQ 知识: {len(flow_info['llm_payload']['faq_knowledge'])} 条
- 通用知识: {len(flow_info['llm_payload']['common_knowledge'])} 条
- 活动知识: {len(flow_info['llm_payload']['activity_knowledge'])} 条

---

## 5. 根因判定

**回复质量**: ✅ PASS / ⚠️ PARTIAL / ❌ FAIL

**判定依据**:
1. {意图路由是否准确}
2. {知识召回是否充分}
3. {回复内容是否相关}
4. {是否有幻觉}
5. {是否合理转人工}

---

## 6. 优化建议

**当前表现**: {总结}
**可选优化方向**: {1-3 条}
**综合评价**: {一句话总结}

---

## 附录：完整 Flow Info（截断 1000 字符）
```

## 四、执行示例（截选）

用户输入 `/cs-conversation-debug 0123456789abcdef0123456789abcdef`：

1. Step 1 输出消息列表表格（50 条消息，14 条可分析），请用户选择
2. 用户回 `4` → 拉取 `debug record 0123456789ab...` → 解析 flow_info
3. 输出报告（节选）：

```markdown
**回复质量**: ✅ PASS

**根因**: 无问题。意图路由准确（商品咨询 → 商品属性），成功召回目标商品（某型号电饭煲），
回复内容直接回答用户问题（材质优势不止低糖，还有材质、加热方式、口感提升），
引用商品详情页真实信息，未触发转人工。

**优化建议**:
- 响应时间可优化（当前 8.02s）
- 回复信息密度适中，无需调整
```
