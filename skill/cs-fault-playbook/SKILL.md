---
user-invocable: true
name: cs-fault-playbook
description: |
  故障类型手册与标准查询流程（cs-debug-toolkit）：把已沉淀的 22 类客服链路故障
  （AI 静默/状态残留、重复转接、面板白屏与锚点失效、选店失败、客户端启动失败、
  主机资源冻结、网络抖动、平台口径误差、黑名单、业务断供…）固化成
  「症状 → 类型 → 标准查询流程 → 判定 → 结论模板」的可执行手册。
  适用：现象已知、要按既有经验快速取证并定性（避免每次从零摸索查询路径）。
  触发词：故障类型、什么毛病、标准查询流程、排查手册、playbook、症状归类、
  这类问题怎么查、以前是不是遇到过、老问题、按手册查。
argument-hint: "[现象描述 / 证据包目录]（如：客户说没人回复但设备看着正常 / 平台报平响 100s）"
allowed-tools: Read, Bash
---

# cs-fault-playbook · 故障类型手册与标准查询流程

**一句话**：先把现象归到已知类型，再按该型的**标准查询流程**取证，最后按
工具包内 `docs/REPORT_STANDARD.md` §3/§4 的标准格式出报告（MD + HTML 双写）。

## 与其它技能的分工

| 技能 | 职责 |
|---|---|
| `cs-router` | 决定**用哪个技能**（单源 or 四方） |
| **`cs-fault-playbook`（本技能）** | 决定**按哪一型查、查什么、怎么判、结论怎么写** |
| `cs-log-cross` / `cs-rpa-log` / `cs-conversation-debug` / `e-chat-trace` | 执行取证（拉日志、出证据包） |

## 四步工作流（固定顺序，不要跳步）

**Step 1 · 归类**：用下面的「症状速查表」把现象对到类型（可多型并存 → 逐型排除）。
拿不准就先跑 Step 2 的自动匹配，再回来比对候选。

**Step 2 · 自动匹配（先跑，1 条命令）**

```bash
# 对已生成的证据包复检（命中特征 + 结论模板）
csdbg signatures --match-dir <证据包目录>          # CLI 形态
python scripts/fault_signatures.py --match-dir <证据包目录>   # 源码/zip 形态
csdbg signatures --list                            # 看全部签名与匹配规则
```
还没有证据包时，先按 cs-router 路由跑 `cross_analysis.py` 生成一个，再回到这里。

**Step 3 · 按型取证**：打开 `references/playbook.md` 对应小节，照抄命令模板（只读、可直接粘贴），
把每条命令产出的**证据原文**贴进证据表（来源 + 时间戳 + 原文片段）。
原子查询命令速查见 `references/query-cookbook.md`（中文分词、limit 截断、时间窗等坑都在里面）。

**Step 4 · 出结论与报告**：结论必须**三段式**（已证 / 未证候选 / 判别性检查清单），
报告必须五段 + 六源定责 + 影响面收尾，MD 与 HTML **双写且内容一致**——
格式与硬性要求见 `references/report-format.md`（= 工具包 `docs/REPORT_STANDARD.md` §3/§4）与
`docs/templates/final-report.html`（骨架，`<TOOLKIT>` = 工具包根目录）。

## 症状速查表

| 现象关键词 | 类型（签名 id） | 首查（一条命令开始） | 判定一句话 |
|---|---|---|---|
| 客户没收到回复，但设备/进程"全绿" | `panel-blank-scrollwrap`（面板白屏） | `sls_sql_query.py --channel <ch> --sql-where "message like '%消息对话框容器未找到%'"` | 命中 ERROR 且逐会话 `probe_state=unavailable` → RPA 页面态故障 |
| 面板有消息但 RPA 按"无新消息"跳过 | `panel-stale-anchor-loss` | 同上，改搜 `锚点` + `丢失\|失效` | 锚点丢失警告 + 平台无记录 → 漏读 |
| 消息零派发、AI 完全没被调用 | `stale-running-state` / `sticky-manual-takeover` | 服务端搜 `没有消息需要处理` / `has_manual_takeover` | 跳过 payload 带状态残留字段 → 守卫误判 |
| 回复被"跳过推送"、会话状态假挂起 | `dedup-skip-silent-stall` | 服务端搜 `服务端检测重复消息` + 看 `event_record` 是否停在 `REPLY_MESSAGE` | 与近期非失败消息重复 → 整批跳过 |
| 同一会话被反复转人工 | `transfer-storm` / `duplicate-transfer` | 服务端搜 `route-to-a-live-agent`（≥3）/ `未命中任何规则` | 次数异常 / 有"创建新会话+批量导入" → 风暴或重判 |
| 人工明明已接待，系统还在转 | `manual-takeover-disconnect` | 服务端搜 `转交给` + 同时段转接任务 `failed` | assistant_id 不更新 + dispatcher 未命中 → 脱节 |
| 转人工后迟迟没人回 | `transfer-no-human-online` / 人工响应延迟 | 服务端搜 `no_human_online`；拉转接成功时刻 vs 人工首条回复 | 首派失败→重试 / 延迟本质=人工上线时间（非 AI） |
| 平响指标异常高（100s+） | `customer-reply-timeout` → 深挖根因 | 服务端搜 `customer-reply-timeout`，再查同窗 AI 是否被调用 | 超时是**结果**不是原因，必须继续定位 |
| 平台报值与服务端真值差很多 | `platform-metric-mismatch` | 平台报值 × 日消息数 vs 服务端总量，差额定位单条长尾 | 口径差（跨夜封顶/人工响应/送信失败）→ 非故障 |
| AI 拒答 / 额度话术 | `credit-exhausted` | 服务端搜 `积分` + `不足\|耗尽`；看同空间是否多会话同时段 | 额度耗尽 → 业务断供（P0 恢复额度） |
| 消息发不出去 | `blacklist-no-reply` | RPA 侧搜 `黑名单` | 店铺黑名单拒发且不计回复 → 非故障 |
| 设备离线 / 起来又掉 | `jd-offline-client-death`（僵死）| 设备 `robot-health-report` 心跳时间线 + ECD 电源事件 | 心跳断流但主机无电源事件 → 进程僵死 |
| 客户端起不来 | `jd-client-startup-failure` | RPA 侧搜 `内存资源不足\|CreateProcess\|UIA业务树` | 内存型重启主机 / UIA 型清缓存 |
| 登录后卡在选店铺 | `shop-name-mismatch-stall` | RPA 侧搜 `均未在页面上找到`，比对配置店铺名与页面可选店铺 | 名称线/ID线/真值线三线取证 |
| 窗口找不到 / 注入不触发 | `account-name-case-mismatch` | RPA 侧搜 `咚咚主窗口未找到` + **截图逐字符放大核对账号名** | 大小写/全半角不一致 → 匹配不中 |
| 整窗消息被当新消息 | `fullwindow-special-type-batch` | RPA 侧搜 `消息范围: all` | 历史 VIDEO 等特殊类型整包上报 → 判死转人工 |
| 报"顾客找不到" | `empty-session-giveup` | RPA 侧搜 `空会话`；服务端搜 `会话无任何消息内容` | 定位校验判空 + 放弃冷却吞转人工 |
| 会话冻结 / 客户端自己退出 | `host-resource-freeze` | 心跳断流时间线 + `host_events_query.py` 电源/崩溃事件 + 主机 CPU/内存 | 主机资源饱和 → 会话冻结后自愈 |
| 延迟尖峰、同时段多设备 | `network-jitter-egress` | 同时段全渠道 RPA 发送延迟 + 心跳 WS 重连 | 云桌面出口抖动（打在有话务窗口才算成因） |
| 平响高但集中在上班前后 | `shop-offhours-backlog`（非故障） | 店铺上班时间 vs 平台评估窗；消息到达时间分布 | 班前积压被平台算进窗口 → 口径错配 |
| 回复慢、全店一起慢 | `agent-duration-drift`（非故障） | `gap_analysis.py` 逐日 `agent_duration` + 同店对照 agent | 连日缓涨 + 对照持平 → 服务端链路渐重 |
| 点击失效、重试风暴 | `popup-overlay-retry-storm` | RPA 侧搜弹窗/`leave`/遮挡 + 重试 | 浮层未消失挡住点击 → 串行阻塞 |

> 类型命名与机器可匹配特征以 `templates/fault_signatures.json` 为准（本表是它的**人读版**；
> 表格里没有的新现象，先按 §0「没有实物证据不下结论」取证，再考虑在本地 `~/.csdbg/fault_signatures.json` 增补签名）。

## 通用纪律（每次都适用）

1. **口径先对齐**：`__time__` 已是北京时间（勿 +8h）；服务端 `asctime` 与 RPA 日志逐秒对齐后再下时序结论。
2. **中文分词坑**：连续中文是整 token（搜 `失败` 查不到 `登录执行失败`）→ 子串语义一律用 `sls_sql_query.py` 的 SQL `LIKE`。
3. **截断即怀疑**：返回行数正好等于 `--limit` 视为疑似截断，缩窗或换 `group by` 重查，别下"没有日志"的结论。
4. **ID 完整**：设备 ID / `conversation_id` 全篇完整 32 位（**禁止省略**）。
5. **一果多因**：多型并存时逐型写"成立/排除 + 判据"，不要只留最顺眼的一条。
6. **定责与建议分开**：六源定责用 `R0 主责 / R1 次责 / R2 待定 / R3 无责`；建议用 `P0/P1/P2`。
7. **证据不留 dump**：原始 json/日志按规范清除，报告内嵌关键原文 + 复现命令（见 `report-format.md` §证据与复现）。
