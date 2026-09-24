# PRD-001: cs-conversation-debug — 从会话 ID 到根因分析

**版本**: v1.0  
**创建日期**: 2026-08-13  
**作者**: DevKit Team  
**状态**: Draft

---

## 前言：cs-cli 全量命令速查表

> 本速查表来自 `@bty/customer-service-cli` v0.6.5 官方 README，供快速查阅。

### 认证与配置

| 命令 | 说明 |
|------|------|
| `auth login --phone <手机号> --password <密码>` | 登录 |
| `auth logout` | 退出登录 |
| `auth whoami` | 查看当前登录用户 |
| `config set --cs-api <url> --ai-api <url>` | 设置 API 地址 |
| `config get` | 查看当前配置（含全局和本地） |
| `config init` | 在当前目录初始化本地配置 (`.cs-cli.json`) |
| `config set-workspace <workspace_id> [--global]` | 设置默认工作空间 |

### 工作空间与 Agent

| 命令 | 说明 |
|------|------|
| `workspace list` | 列出所有工作空间 |
| `workspace points-consumes-daily [--start <日期>] [--end <日期>]` | 按天查询工作空间积分消耗 |
| `agent list [--page N] [--page-size N]` | 列出 Agent 列表 |
| `agent get <config_id>` | 获取 Agent 详情 |
| `agent update <config_id> --data <json\|@file>` | 更新 Agent 配置 |
| `ops-agent conversations [--agent-id <id>]` | 查询客服助手会话列表 |

### 知识配置

| 命令 | 说明 |
|------|------|
| **SA（场景动作）** | |
| `sa list --agent <id> [--intent <意图>]` | 列出场景动作 |
| `sa search --agent <id> --keyword <关键词>` | 搜索场景动作 |
| `sa create --agent <id> --first-label <L1> --second-label <L2> --situation <场景> --action <动作>` | 创建场景动作 |
| `sa update --agent <id> --id <SA_ID> ...` | 更新场景动作 |
| `sa delete --agent <id> --id <SA_ID> --first-label <L1> --second-label <L2>` | 删除场景动作 |
| `sa versions --agent <id> --id <SA_ID>` | 查看修改记录 |
| **商品** | |
| `product list --agent <id> [--keyword <关键词>]` | 列出商品 |
| `product get --agent <id> --product-id <商品ID>` | 获取商品详情 |
| `product update --agent <id> --product-id <商品ID> --update <json>` | 更新商品信息 |
| `product learn --agent <id> --url <URL...>` | 通过商品 URL 异步学习 |
| `product sync-taobao --agent <id>` | 触发淘宝店铺商品同步 |
| **FAQ** | |
| `faq list --agent <id>` | 列出 FAQ 文件 |
| `faq content --agent <id> --file <文件名>` | 列出文件内答案组 |
| `faq add --agent <id> --file <文件名> --questions <问题> --answers <答案>` | 添加 FAQ 内容 |
| `faq update --agent <id> --file <文件名> --group-id <id> ...` | 更新 FAQ 答案组 |
| `faq delete --agent <id> --file <文件名> --group-id <id>` | 删除 FAQ 答案组 |
| **扩展知识库** | |
| `knowledge list --agent <id>` | 列出扩展知识库文件 |
| `knowledge content list --knowledge-id <id>` | 列出段落 |
| `knowledge content add --knowledge-id <id> --content <text\|@file>` | 新增段落 |
| `knowledge content update --knowledge-id <id> --chunk-id <id> ...` | 更新段落 |
| `knowledge content delete --knowledge-id <id> --chunk-id <id>` | 删除段落 |

### 会话与调试

| 命令 | 说明 |
|------|------|
| `conversation list [--agent <id>] [--user <用户名>]` | 搜索会话 |
| `conversation records <conversation_id>` | 获取会话聊天记录 |
| `conversation context-search --query <文本> [--start <时间>] [--end <时间>]` | 通过上下文内容模糊搜索对话记录 |
| `conversation transfer-human --agent <id> --start <时间> --end <时间>` | 查询转人工会话 |
| `debug ask --agent <id> --text <消息> [--user <用户名>]` | 向 Agent 发送消息并等待回复 |
| `debug reproduce <record_id> [--dry-run]` | 根据 record_id 复现 Agent 回复 |
| `debug record <record_id>` | 获取记录的调试信息（flow_info） |
| `debug trace <trace_id>` | 根据 Langfuse Trace ID 获取完整 Trace 详情 |

### 工单与修复

| 命令 | 说明 |
|------|------|
| `issue list [--agent <id>] [--status <状态>]` | 列出工单 |
| `issue get <issue_id>` | 获取工单详情 |
| `issue create --title <标题> --content <内容>` | 单条创建工单 |
| `issue create --file <path> \| --stdin` | 批量创建工单 |
| `issue update <issue_id> --data <json>` | 单条更新工单 |
| `issue update-owner <issue_id> --owner <user_id\|花名>` | 单条改派负责人 |
| `repair-record list [--issue <工单ID>]` | 列出修复记录 |
| `repair-record create --issue <工单ID> --agent <AgentID> --action <修复动作>` | 创建修复记录 |
| `ops-record list [--workspace <工作空间ID>]` | 列出运维操作记录 |
| `ops-record create --workspace <工作空间ID> --agent <AgentID>` | 创建运维操作记录 |

### 运营监控与看板

| 命令 | 说明 |
|------|------|
| `monitor agents` | Agent 生命周期列表 |
| `monitor statistics` | Agent 运营统计 |
| `dashboard summary [--config-id <id>]` | 全局或单店 KPI 汇总 |
| `dashboard trend [--config-id <id>]` | 趋势（每日/周/月接待客户数、转人工率） |
| `dashboard shops` | 全部店铺统计列表 |
| `dashboard intent --config-id <id>` | 单店各意图消息级转人工统计 |

### 测试与高级功能

| 命令 | 说明 |
|------|------|
| `testset list --customer-agent-config-id <id>` | 列出测试集 |
| `testset create --customer-agent-config-id <id> --file <cases.xlsx>` | 创建测试集 |
| `testset run --testset <id> --agent <id> [--wait]` | 触发整批回归 |
| `testset export --testset <id> --batch <id> --output <path>` | 导出批次结果 |
| `activity list --agent <id>` | 列出活动 |
| `activity create --data <json>` | 创建活动 |
| `node-template get --agent <id> [--stage <s>]` | 获取节点模板内容 |
| `node-template publish --agent <id> --stage <s>` | 发布节点模板草稿上线 |

---

## 一、项目定位

本文件夹 `D:\我的工作台\bty-cs-cli` 的功能定位：

**为 BetterYeah AI 客服平台的运维工程师和 QA 人员提供基于 cs-cli 的自动化分析工具与文档。**

核心价值：
1. **降低调试门槛** — 从会话 ID 快速定位有问题的消息，无需手动翻阅完整对话记录
2. **标准化根因分析** — 复用成熟的 4 维分析框架，输出结构化报告
3. **知识沉淀** — 所有分析报告自动归档到 `~/cs-ops/memory/e-chat-debug/`，供后续检索

---

## 二、需求背景

### 2.1 现状

运维人员收到客户反馈"某次对话有问题"时，通常只能拿到：
- **conversation_id**（会话 ID）
- 模糊描述："转人工了" / "答非所问" / "商品信息错误"

**痛点**：
1. 需要先跑 `cs-cli conversation records <conversation_id>` 查看完整对话
2. 手动在几十条消息中定位有问题的 Agent 回复
3. 拿到 `record_id` 后再跑 `cs-cli debug record <record_id>` 查 trace
4. 重复劳动，无标准流程

### 2.2 现有工具的覆盖情况

| 工具 | 入口 | 用途 | 局限性 |
|------|------|------|--------|
| `/cs-chat-debug` | `record_id` | 单条回复根因分析 | **需要事先知道 record_id** |
| `/cs-trace` | `trace_id` | Langfuse Trace 提取 | 底层工具，无业务分析 |
| `cs-cli conversation records` | `conversation_id` | 查看完整对话 | 只展示，不分析 |

**缺失环节**：**从 conversation_id → 选择目标消息 → 自动触发根因分析**

---

## 三、需求描述

### 3.1 功能概述

**Skill 名称**: `cs-conversation-debug`

**触发方式**: `/cs-conversation-debug <conversation_id>`

**核心流程**:

```
用户输入 conversation_id
    ↓
Step 1: 拉取会话消息列表（cs-cli conversation records）
    ↓
Step 2: 展示时间线表格（#/时间/role/type/内容摘要）
    ↓
用户选择要分析的 assistant 回复序号
    ↓
Step 3: 并行拉取 debug trace + msg_list 上下文
    ↓
Step 4: 4 维根因分析（复用 cs-chat-debug 框架）
    ↓
Step 5: 输出结构化报告
    ↓
Step 6: 保存到 ~/cs-ops/memory/e-chat-debug/
```

### 3.2 输入规格

| 输入 | 类型 | 必填 | 示例 |
|------|------|------|------|
| `conversation_id` | string | ✅ | `65d29cfb142a471e9da55d850d3148ed` |

### 3.3 输出规格

#### 3.3.1 终端输出

**阶段 1 — 消息列表展示**（Step 2）

```markdown
## 会话消息列表（共 15 条）

**会话 ID**: 65d29cfb142a471e9da55d850d3148ed  
**Agent**: 无印良品客服（a0901fe383064c2abefb0bf1cd52988e）  
**用户 ID**: jd_12345678

| # | 时间 | role | type | 内容摘要 |
|---|------|------|------|---------|
| 1 | 14:23:01 | user | CARD | 商品卡：棉柔巾 |
| 2 | 14:23:05 | assistant | TEXT | 您好，这款棉柔巾... |
| 3 | 14:23:30 | user | TEXT | 有赠品吗 |
| 4 | 14:23:35 | assistant | TEXT | 当前没有赠品活动... |
| 5 | 14:24:00 | user | IMAGE | [图片] |
| 6 | 14:24:10 | assistant | TEXT | 根据您发的图片... |
| 7 | 14:24:30 | user | TEXT | 转人工 |
| 8 | 14:24:31 | assistant | TEXT | [TRANSFER] 正在为您转接... |

**请输入要分析的 assistant 回复序号**（2 / 4 / 6 / 8）:
```

**阶段 2 — 根因分析报告**（Step 5）

格式同 `/cs-chat-debug` 输出（完整 markdown 报告）。

#### 3.3.2 文件归档

**路径**: `~/cs-ops/memory/e-chat-debug/{record_id前8位}-{店铺缩写}-{简短问题描述}.md`

**示例**: `0b73179f-无印良品-图片答非所问导致转人工.md`

---

## 四、详细设计

### 4.1 Step 1 — 拉取会话消息列表

**命令**:
```bash
cs-cli conversation records <conversation_id> --table
```

**解析字段**:
- `match_id` → `record_id`
- `role` → `user` | `assistant`
- `type` → `TEXT` | `IMAGE` | `CARD`
- `content.text` → 内容摘要（截取前 30 字符）
- `timestamp` → 转北京时间（`HH:MM:SS`）

**筛选逻辑**:
- 只展示 `role=assistant` 的行号供用户选择
- 隐藏 `role=user` 的序号（但仍展示在表格中作为上下文）

### 4.2 Step 2 — 用户交互

**实现方式**: 使用 `AskUserQuestion` 工具

```typescript
AskUserQuestion({
  questions: [{
    question: "请选择要分析的 assistant 回复序号",
    header: "选择目标消息",
    multiSelect: false,
    options: [
      { label: "#2 — 您好，这款棉柔巾...", description: "14:23:05 assistant TEXT" },
      { label: "#4 — 当前没有赠品活动...", description: "14:23:35 assistant TEXT" },
      { label: "#6 — 根据您发的图片...", description: "14:24:10 assistant TEXT" },
      { label: "#8 — [TRANSFER] 正在为您转接...", description: "14:24:31 assistant TEXT" }
    ]
  }]
})
```

**容错**:
- 如果会话中没有任何 `assistant` 消息 → 报错退出："该会话中没有 Agent 回复记录"
- 如果只有 1 条 `assistant` 消息 → 自动选中，跳过交互

### 4.3 Step 3 — 并行拉取 debug 数据

**目标**:
- 拿到选中的 `assistant_record_id`
- 找到它之前最近一条 `user_record_id`

**命令**（并行执行）:
```bash
# 1. 拉 assistant 回复的 debug trace
cs-cli debug record <assistant_record_id> > /tmp/cs-conv-debug-trace.json

# 2. 用 user_record_id 还原完整 msg_list 上下文
cs-cli debug reproduce <user_record_id> --dry-run > /tmp/cs-conv-debug-msglist.json
```

**容错**:
- 如果 `assistant_record_id` 前没有 `user` 消息 → 使用该会话的第一条 `user` 消息
- 如果是会话第一条消息（进线打招呼）→ `user_record_id` 为空，跳过 reproduce

### 4.4 Step 4 — 根因分析

**完全复用** `/cs-chat-debug` 的分析框架：

1. **用户最后真实诉求是什么？**
2. **Agent 上一轮回复对不对？**
3. **转人工/失败的技术路径是什么？**（Layer 0 短路 / AI 分析转人工 / SOP 转人工 / 答非所问）
4. **配置根因在哪一层？**（商品数据 / 图片 OCR / FAQ / SA / SOP / 知识库）

**证据来源**:
- `flow_info` 中的 `intent_thinking` / `event_one` / `event_two` / `debug_message` / `behavior`
- `product_data` / `business_context.faq` / `context_infos.image_content`

### 4.5 Step 5 — 输出报告

**格式**（与 cs-chat-debug 完全一致）:

```markdown
# 单条对话根因分析报告

**Record ID**: `<assistant_record_id>`
**会话 ID**: `<conversation_id>`
**Agent**: `<agent_config_name>`（`<agent_config_id>`）
**用户 ID**: `<user_id>`
**时间**: `<北京时间>`

---

## 一、结论先行（一句话）

> <一句话讲清楚为什么会发生>

---

## 二、完整对话还原（{N} 条 msg_list）

| # | 时间 | role | type | 内容 |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

---

## 三、技术链路还原

```
用户输入 "<最后一条 user 消息>"
   ↓
<判定：意图识别 LLM 是否执行？>
   ↓
<最终输出>
```

**证据**:
- `intent_thinking`: ...
- `event_one` / `event_two`: ...
- `debug_message` 关键片段: ...

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

---

## 六、数据字段校正（如发现）

---

## 七、附：testcase 补充建议（可选）
```

### 4.6 Step 6 — 保存报告

**路径**: `~/cs-ops/memory/e-chat-debug/`

**命名**: `{assistant_record_id前8位}-{店铺缩写}-{简短问题描述}.md`

**权限检查**: 目录不存在时自动创建 `mkdir -p ~/cs-ops/memory/e-chat-debug`

---

## 五、与现有 skill 的关系

### 5.1 与 cs-chat-debug 的区别

| 维度 | cs-chat-debug | cs-conversation-debug（本 skill） |
|------|---------------|----------------------------------|
| **入口** | `record_id` | `conversation_id` |
| **适用场景** | 已知问题消息的精准分析 | 只知道会话 ID，需要先定位问题消息 |
| **交互** | 无（直接分析） | 有（展示消息列表 + 用户选择） |
| **分析框架** | 4 维根因分析 | **完全复用** cs-chat-debug 的 4 维框架 |
| **报告归档** | `~/cs-ops/memory/e-chat-debug/` | **共用**同一目录 |

### 5.2 与 cs-trace 的区别

- **cs-trace**: 底层 Langfuse Trace 提取工具，无业务层分析
- **本 skill**: 业务层根因分析，内部会调用 `cs-cli debug record`（含 trace_id）

### 5.3 调用链

```
用户
  ↓
/cs-conversation-debug <conversation_id>
  ↓
cs-cli conversation records <conversation_id>
  ↓
用户选择 assistant 回复序号
  ↓
cs-cli debug record <assistant_record_id>
cs-cli debug reproduce <user_record_id> --dry-run
  ↓
复用 cs-chat-debug 的分析框架
  ↓
输出报告 + 保存到 ~/cs-ops/memory/e-chat-debug/
```

---

## 六、边界与约束

### 6.1 前置条件

- `cs-cli` 已认证（`cs-cli auth whoami` 验证）
- 输入的 `conversation_id` 存在且可访问
- Python3 可用（用于 JSON 解析）

### 6.2 不支持的场景

- **多会话批量分析** — 本 skill 一次只处理一个会话
- **历史会话追溯** — 如果会话记录已被清理，拉不到消息列表
- **非 Agent 回复的分析** — 只能选择 `role=assistant` 的消息

### 6.3 性能约束

- 消息列表 > 100 条时，建议在表格上方加 **分页提示**（"显示前 50 条，剩余 XX 条"）
- `debug record` 调用可能需要 5-10 秒，需在终端提示 "正在拉取 trace..."

---

## 七、验证计划

### 7.1 单元测试场景

| 场景 | 输入 | 预期输出 |
|------|------|---------|
| 正常流程 | 有效 conversation_id，包含 3 条 assistant 回复 | 展示消息列表，用户选择后生成报告 |
| 空会话 | conversation_id 存在但无任何消息 | 报错："该会话无消息记录" |
| 只有 user 消息 | 会话中只有 user，无 assistant | 报错："该会话中没有 Agent 回复记录" |
| 单条 assistant | 会话中只有 1 条 assistant 回复 | 自动选中，跳过交互 |
| 无效 conversation_id | 不存在的 ID | `cs-cli conversation records` 报错，skill 提示用户检查 ID |

### 7.2 集成测试

1. 在 `D:\我的工作台\bty-cs-cli\` 目录下启动 Claude Code
2. 输入 `/cs-conversation-debug 65d29cfb142a471e9da55d850d3148ed`
3. 验证消息列表正确展示
4. 选择一条 assistant 回复
5. 验证 debug trace 正常拉取
6. 验证报告生成并保存到 `~/cs-ops/memory/e-chat-debug/`

---

## 八、里程碑

| 里程碑 | 交付物 | 状态 |
|--------|--------|------|
| M1 — 文档完成 | 本 PRD 文档 | ✅ Draft |
| M2 — Skill 实现 | `.claude/commands/cs-conversation-debug.md` | 🚧 In Progress |
| M3 — 测试验证 | 集成测试通过 | ⏳ Pending |
| M4 — 发布上线 | Skill 可用 | ⏳ Pending |

---

## 九、FAQ

**Q1: 为什么不直接自动分析最后一条 assistant 回复？**  
A1: 很多情况下问题不在最后一条（比如用户最后说"转人工"，但真正问题在倒数第 2 轮）。让用户手动选择更精准。

**Q2: 能否支持批量分析一个会话中所有 assistant 回复？**  
A2: 技术上可行，但单次分析已经需要 10-30 秒。批量分析耗时过长，建议拆成多次调用。

**Q3: 报告归档目录为什么和 cs-chat-debug 共用？**  
A3: 两者都是"单条回复根因分析"，共用目录便于后续统一检索和知识沉淀。

---

## 附录 A：参考资源

- cs-cli 官方 README: `/c/Users/13328/AppData/Roaming/npm/node_modules/@bty/customer-service-cli/README.md`
- cs-chat-debug Skill 定义: `C:\Users\13328\.claude\skills\cs-chat-debug\SKILL.md`
- BTY 执行链路图解: `preprocess → judge → combined → condition_1 → business → solution new`
