# E-Chat-Trace：电商客服消息全链路排查工具

基于 4 个真实案例（优勤官方旗舰店）总结的标准化排查 skill。

**v2.0 更新**：Agent 侧改为直接查 SLS 日志（不再依赖 cs-cli debug record）

## 快速开始

```bash
# 方式 1: 通过 Claude Code 调用
e-chat-trace <conversation_id>

# 方式 2: 直接运行脚本
python3 skill/e-chat-trace/e-chat-trace.py <conversation_id>

# 指定目标消息
e-chat-trace <conversation_id> "您好，很高兴为您服务。"
```

## 功能

✅ **自动识别渠道**：千牛/抖音/京东/拼多多  
✅ **全链路排查**：Agent（SLS）+ RPA（SLS）  
✅ **智能诊断**：消息延迟、欢迎语延迟、发送失败、内容错误  
✅ **根因定位**：基于 4 案例经验的模式识别  
✅ **终端输出**：不生成文件，直接看报告

## 环境要求

```bash
# 1. cs-cli 已认证（仅用于拉取 conversation records）
cs-cli auth whoami

# 2. Python 依赖
pip install aliyun-log-python-sdk

# 3. 阿里云 SLS 凭证（环境变量）
export ALIYUN_ACCESS_KEY_ID="<your_key>"
export ALIYUN_ACCESS_KEY_SECRET="<your_secret>"
```

## 双 SLS 日志源

**Agent 日志**（v2.0 新增）：
- Project: `bty-prod-ack-log`
- Logstore: `customer-servhub-api`
- 包含：推理链路、意图识别、SOP 命中、工具调用、耗时
- 链接: [SLS Console](https://sls.console.aliyun.com/lognext/project/bty-prod-ack-log/logsearch/customer-servhub-api?slsRegion=cn-hangzhou)

**RPA 日志**：
- Project: `customer-servhub-log`
- Logstore: 根据渠道自动选择
- 包含：消息收发、面板操作、队列状态
- 千牛: `qianniu-rpa-new-prod`
- 抖音: `project-douyin-rpa-prod`
- 京东: `project-jd-rpa-prod`
- 拼多多: `project-pdd-rpa-prod`

## 典型场景

| 场景 | 示例 |
|------|------|
| Agent 回复延迟 | 用户等待时间过长 |
| 欢迎语延迟 | 用户进线后长时间无欢迎语 |
| 消息发送失败 | 消息未到达用户 |
| 消息内容错误 | Agent 回复不正确 |

## 排查逻辑

```
1. 拉取 conversation records → 构建消息时间线
2. 自动识别渠道 → 选择对应 RPA logstore
3. 检测异常 → 消息延迟/欢迎语延迟/消息丢失
4. 拉取 Agent trace → 分析推理链路
5. 查询 RPA 日志 → 匹配典型问题模式
6. 综合分析 → 定位根因（Agent 侧/RPA 侧）
7. 终端输出报告 → 根因结论 + 修复建议
```

## RPA 问题模式速查

| 模式 | 日志关键词 | 严重程度 |
|------|----------|---------|
| 发送队列堵塞 | `reply-message 入队` → `发送成功` >60s | 🔴 严重 |
| 面板串台误判 | `昵称已属其他会话` / `串台` | 🔴 严重 |
| 面板未确认重试 | `面板未确认` / `匹配待确认` | 🔴🔴 极严重 |
| 处理队列排队 | `列表快照` + `接待=` >10 | 🟡 中等 |
| 欢迎语延迟 | 进线到欢迎语 >30s | 🔴 严重 |

## 报告示例

```
================================================================================
           E-Chat 消息链路排查报告
================================================================================

会话 ID: eb27d27901214b36a75223a2bc5f62a1
渠道: 千牛（淘宝/天猫）
用户: huangwenhuan2005

================================================================================
核心结论
================================================================================

🔴 Agent 回复延迟 128 秒

责任方: RPA 侧

延迟分解:
  • Agent 推理: 9.67秒 (8%)
  • RPA + 其他: 118秒 (92%) ← 主因

================================================================================
修复建议
================================================================================

🔴 P0: 优化 RPA 发送队列
   • 增加发送并发能力
   • 提高 Agent 回复优先级
```

## 文件结构

```
skill/e-chat-trace/
├── SKILL.md           # Skill 定义（frontmatter + 详细文档）
├── e-chat-trace.py    # 核心实现脚本
└── README.md          # 本文件
```

## 参考案例

基于以下 4 个真实案例设计：

1. **案例1** (eb27d279...): Agent 回复延迟 128 秒 → RPA 发送队列堵塞
2. **案例2** (2aff2934...): 欢迎语延迟 66 秒 → RPA 处理队列排队
3. **案例3** (8f195295...): 欢迎语延迟 95 秒 → RPA 面板串台误判
4. **案例4** (083af3ea...): 欢迎语延迟 195 秒 → RPA 面板未确认，3次重试

详细报告: `~/cs-ops/memory/e-chat-debug/优勤-消息延迟根因分析-4案例合并报告.md`

## 注意事项

⚠️ **SLS 凭证**：需要配置环境变量 `ALIYUN_ACCESS_KEY_ID` 和 `ALIYUN_ACCESS_KEY_SECRET`  
⚠️ **时区**：所有时间戳统一使用北京时间（Asia/Shanghai）  
⚠️ **渠道识别**：自动识别，识别失败时提示用户确认  
⚠️ **不生成文件**：报告仅输出到终端，不保存文件

## License

内部工具，仅供公司使用。

---

**创建日期**: 2026-09-04  
**版本**: v1.0  
**作者**: BTY 技术运营
