# PRD-002: 多方日志交叉分析功能区（重绘）

**版本**: v1.0  
**创建日期**: 2026-09-18  
**作者**: DevKit Team  
**状态**: 已实现并实测验证

---

## 一、背景与重绘目标

原 `cs-cli` 文件夹功能分散：RPA 日志查询（单源）、会话 debug（业务链路）、trace 提取，
彼此不连通。运维定责时需要人肉在**三个独立日志面**之间来回对齐时间线：

| 日志面 | 位置 | 单独工具 | 缺口 |
|--------|------|---------|------|
| 服务端 server 日志 | SLS `bty-prod-ack-log` / logstore `customer-servhub-api`（[控制台](https://sls.console.aliyun.com/lognext/project/bty-prod-ack-log/logsearch/customer-servhub-api?slsRegion=cn-hangzhou)） | ❌ 无 | 本次补齐 |
| RPA 端日志 | SLS `customer-servhub-log`（[控制台](https://sls.console.aliyun.com/lognext/project/customer-servhub-log/overview?slsRegion=cn-hangzhou)），4 渠道 | ✅ `rpa_log_query.py` | 已存在 |
| ops 运维日志 | 本地安装 `@bty/customer-service-cli`（`cs-cli ops-record`） | ❌ 无 | 本次补齐 |

**重绘后的功能区定位**：读取三方日志 → 交叉分析论证 → 得出问题结论，
**最终分析结论统一落盘 `temp/`**。

## 二、需求

1. **FR-1 服务端取证**：按 conversation_id / trace_id / request_id / dispatch_id / 关键词 + 时间窗口查询 `customer-servhub-api`，规范化字段并抽取业务 ID
2. **FR-2 RPA 取证**：沿用 `rpa_log_query.py`（4 渠道 × prod/dev）
3. **FR-3 ops 取证**：经本地 cs-cli 拉运维操作记录，支持时间窗/Agent/工作空间/关键词过滤，翻页直到覆盖窗口
4. **FR-4 交叉对齐**：三方按同一时间轴合并；锚点命中矩阵；跨源业务 ID 自动共现（不依赖用户输入）；ops 变更 ↔ 涉事 Agent 的因果嫌疑标记
5. **FR-5 结论交付**：LLM 按"断链定位→时间对齐→变更介入→反证→归因"5 问论证，报告写入 `temp/analysis_*.md`；证据包 `temp/evidence_*/` 可复核
6. **NFR**：任一源失败不阻塞其余源（结论注明缺源降级）；AK 不落任何输出；只读，不触碰写操作

## 三、设计

### 3.1 组件

```
scripts/server_log_query.py   FR-1（ServerLogQuery.query → 规范化记录 + ids 抽取）
scripts/ops_log_query.py      FR-3（_run_cs_cli 子进程 + raw_decode 容噪 + 客户端过滤）
scripts/cross_analysis.py     FR-4（编排三源 → anchors.json / timeline / evidence.md）
.claude/commands/cs-log-cross.md  FR-5（LLM 论证协议 + 结论模板 + temp/ 落盘）
```

### 3.2 关键数据字段

- **server 日志**：`asctime / levelname / message / otelTraceID / ws_request_id / dispatch_id / send_ids`；正则从 message 抽取 `conversation_id / record_id / request_id / dispatch_id / agent_id / workspace_id / equipment_id / user_id` + 裸 32hex 兜底
- **RPA 日志**：`level / module / function / message / error_detail / extra_*`；缩写键 `conv= / task=` 单独正则
- **ops 记录**：`record_id / created_at / workspace_id / agent_id / operator_name / path / remark`（时间窗与关键词为客户端过滤，created_at 降序支持提前终止翻页）

### 3.3 交叉论证协议（cs-log-cross Step 3 的 5 问）

1. 事件链路在哪一环断了/出错（服务端下发有而 RPA 接收无 → 网关/掉线；RPA status=failed → 端上执行）
2. 三方时间轴对齐（同一 conv/trace 跨源时差 = 下发延迟）
3. 运维操作介入（问题窗口前涉事 Agent 是否有 ops 变更 → 强因果嫌疑）
4. 反证检查（为每个候选根因在另一源找"该时段正常"的证据）
5. 归因（主因/次因/排除项 + 置信度；证据不足写"无法定论"+ 补拉命令）

## 四、验证记录（2026-09-18 实测）

| 项 | 结果 |
|----|------|
| `server_log_query.py --check` | ✅ bty-prod-ack-log/customer-servhub-api 连通 |
| `rpa_log_query.py --check` | ✅ 修复 `project`→`rpa_project` 键兼容后通过 |
| `ops_log_query.py --check` | ✅ cs-cli 认证（今朝【斑头雁】）|
| 真实会话端到端：conv=`68a04b17…00cf`，窗口 22:30~23:10 | server 726 条 / rpa:pinduoduo 13 条 / ops 0 条 |
| 锚点命中矩阵 | ✅ conversation_id 命中 server=639 / rpa=13 |
| 跨源 ID 共现 | ✅ `68a04b17…` 在 server+RPA 双源共现（修复 RPA `conv=` 抽取后）|
| 合并时间线 | ✅ 下发→接收→SOP→回发按秒对齐，WARNING 加 ⚠ |

## 五、边界

- SLS GetLogs 单源默认上限 1000 条（limit 可调），超限截断并在结论降级置信度
- ops 记录无服务端时间过滤，靠翻页+created_at 降序提前终止；窗口过旧时扫描成本高
- dev 环境 RPA 需 `--dev`（cross_analysis 当前只扫 prod）
- 结论质量依赖全文索引：`customer-servhub-api` 未索引字段只能靠 message 正则兜底

## 六、后续可演进

- [ ] `cross_analysis.py --with-cs-cli`：自动附加 `conversation records` 消息面证据
- [ ] 错误模式库沉淀：三方错位模式 → `~/cs-ops/memory/`
- [ ] dev 环境开关透传；HTML 版证据包
