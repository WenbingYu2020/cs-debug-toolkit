---
user-invocable: true
name: cs-router
description: |
  排查入口路由（cs-debug-toolkit meta-skill）：当问题描述含糊、不确定该用哪个技能时，
  按"问题类型 → 技能/命令"决策表路由，避免"单源够用却跑四方交叉（浪费配额）"或
  "该上四方却只查了单源（结论不牢）"。触发词：怎么排查、用哪个工具、路由、
  该查什么日志、cs-router、排查入口。
argument-hint: "[问题描述]（如：用户说没收到消息 / 会话为什么不接管 / 设备离线了）"
allowed-tools: Read, Bash
---

# cs-router · 排查入口路由（meta-skill）

四个技能功能有重叠，按**问题类型**路由到正确的入口。

## 决策表

| 用户问题形态 | 用哪个 | 为什么 |
|---|---|---|
| "这条回复为什么这样答 / 怎么触发的"（单条消息根因） | `cs-conversation-debug` | 单链路 debug trace 足够，含 llm_payload/flow_info |
| "这个设备/RPA 什么状态 / 执行日志报了什么错" | `cs-rpa-log` | 单源 RPA 日志，按 equipment_id/conversation_id 直查 |
| "消息全链路（含千牛/京东 IM 层收发）" | `e-chat-trace` | Agent trace + RPA 收发自动串联 |
| **"为什么超时/没回复/定责/根因"（跨端）** | **`cs-log-cross`** | 四方交叉（服务端×RPA×运维×主机），结论可复核 |
| 平响类 KPI 数据核对（日均值 vs 服务端真值） | `cs-log-cross` + `csdbg gap` | gap_analysis 出 user→assistant 间隔统计 |
| 设备离线/电源/重启/崩溃实锤 | `cs-log-cross --host-events-equipment` 或 `csdbg host-events` | 第④源专项；ECD 实锤优先 |

## 路由速记

- **定责/根因/为什么 → cs-log-cross**（四方）。其余按单源能答的原则走轻量技能。
- 拿不准时：先问一句"能给我 conversation_id 或设备ID吗"——有 ID 就按上表直接路由。
- 关键词触发：`根因 / 定责 / 多方 / 交叉 / 主机侧 / 运维变更 / 为什么没回复` → cs-log-cross。

## 成本提示

| 入口 | 相对成本 | 何时不值得 |
|---|---|---|
| cs-conversation-debug / cs-rpa-log | 低（单源） | —— |
| e-chat-trace | 中（双源串联） | 与 IM 层无关的纯 RPA 内部问题 |
| cs-log-cross | 高（4 源 + 大窗口） | 单条消息"为什么这样答"类问题（用 conversation-debug 即可） |

明确不需要交叉定责时，别默认跑 cs-log-cross——省配额、省时间。
