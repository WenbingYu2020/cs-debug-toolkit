# 故障类型手册 · 标准查询流程（22 型）

> 配套：`cs-fault-playbook/SKILL.md`（归类入口）｜`references/query-cookbook.md`（原子命令）｜
> `references/report-format.md`（报告格式）｜`templates/fault_signatures.json`（机器可匹配签名）。
> 全部命令**只读**；`<ch>` 取 `douyin|jingdong|pinduoduo|qianniu`，时间窗一律北京时间 ISO。
> 每型固定四块：**签名**（怎么认）→ **标准查询流程**（怎么查）→ **判定/排除**（怎么定）→ **结论模板+坑**。

---

## 1. 面板白屏 · 消息容器丢失（`panel-blank-scrollwrap`）

- **症状**：某客服账号全部在线会话"零服务"，但设备心跳/CPU 正常；平台侧响应时间飙升、多个客户 `>10分`。
- **签名**：`消息对话框容器未找到（jdwb）：共枚举 N 个 Chrome 帧，均无 scrollWrap`（每 30s 复现）；
  逐会话 `用户名校验超时，消息列表=None，probe_state='unavailable'，跳过`；**心跳 30s 零空窗**。
- **标准查询流程**
  ```bash
  cd <TOOLKIT>
  # ① 断点与规模（首个 ERROR + 逐会话跳过；先按账号名 LIKE 定位设备）
  python scripts/sls_sql_query.py --channel jingdong --sql-where "extra_client_username like '%<账号昵称>%'" \
    --start <ISO> --end <ISO> --limit 4000 --output rpa.json
  python scripts/sls_sql_query.py --channel jingdong --sql-where "message like '%消息对话框容器未找到%'" \
    --start <前7日> --end <ISO> --limit 5000 --output week.json        # 近 7 日基线对照
  # ② 会话影响面（谁在线、谁被跳过、跳过几次）
  python scripts/sls_sql_query.py --channel jingdong \
    --sql-where "extra_client_username like '%<账号昵称>%' and message like '%用户名校验超时%'" \
    --start <ISO> --end <ISO> --limit 4000 --output skip.json
  # ③ 心跳时间线（证明进程级全绿）
  python scripts/sls_sql_query.py --channel jingdong \
    --sql-where "extra_client_username like '%<账号昵称>%' and message like '%robot-health-report%'" \
    --start <ISO> --end <ISO> --limit 500 --output hb.json
  # ④ 现场帧（白屏实拍）+ 台账（最后更新时刻）+ 运维面
  python scripts/fetch_equipment_shots.py --equipment-id <eq_id> --workspace <ws_id> \
    --start <ISO> --end <ISO> --pick <HH:MM:SS> --out-dir ./shots
  python scripts/conv_list_all.py --workspace <ws_id> --agent <config_id> --day <YYYY-MM-DD> --out convs.json
  cs-cli monitor tickets list --agent <config_id>
  ```
- **判定 / 排除**：同时满足 ① 容器丢失 ERROR 高频复现 ② 逐会话 `probe_state=unavailable` 跳过
  ③ 心跳/CPU 正常 ④ 截图消息区白屏 → **RPA 页面态故障**（R0 RPA）；
  排除主机冻结（`host_events_query.py` 无电源/崩溃事件）、网络（WS 已连接、无重连）→ host/IP 记 R3。
  **是否"平台渲染"还是"RPA 定位"未定**时，写 R2 并把"现场刷新页面"列为 C1 检查。
- **坑**：容器丢失 ERROR 的**近 7 日基线**必须拉——个位数偶发是噪声，本故障是**单机高频**；
  CV 兜底"命中可见未读行"不等于能读内容（`left_badge=True` 只说明客户在等）。

---

## 2. 面板陈旧 · 锚点失效漏读（`panel-stale-anchor-loss`）

- **症状**：客户消息平台侧可见，BY 无记录；RPA 日志说"没有新消息"。
- **签名**：连续 `锚点` 丢失/失效警告；按"无新消息"跳过；时间窗与平台记录缺口吻合。
- **标准查询流程**
  ```bash
  python scripts/sls_sql_query.py --channel qianniu --sql-where "message like '%锚点%' and (message like '%丢失%' or message like '%失效%')" \
    --start <ISO> --end <ISO> --limit 2000 --output anchor.json
  # 对照：平台客户消息时刻 vs 服务端是否零记录
  python scripts/server_log_query.py --conversation-id <conv_id> --start <ISO> --end <ISO>
  ```
- **判定**：锚点警告密集 + 服务端在对应时刻**零记录**（消息未上报）→ 漏读成立；修复方向=锚点缺失时回落整窗扫描。
- **坑**：漏读会造成"BY 侧指标正常、平台侧指标恶化"的**双向假象**，报告里要用平台口径说明真实体验。

---

## 3. 陈旧状态残留 → AI 静默（`stale-running-state` / `sticky-manual-takeover`，第十五型家族）

- **症状**：会话有客户新消息，AI 完全未调用（零 `agent_service` 日志），也无人工接手。
- **签名**：跳过 WARNING 带 `没有消息需要处理` 且 `running_state=running`；
  或跳过 payload 带 `has_manual_takeover:true`（对照会话无该字段）；
  事件链仅 `MESSAGE_READ` 无 `PROCESSING_MESSAGES`；`debug reproduce` 报"聊天记录不存在"= AI 零调用铁证。
- **标准查询流程**
  ```bash
  python scripts/server_log_query.py --conversation-id <conv_id> --start <ISO> --end <ISO> --grep "没有消息需要处理,has_manual_takeover,PROCESSING_MESSAGES"
  python scripts/conv_timeline.py --workspace <ws_id> --conv <conv_id> --out tl.json     # 事件链与状态字段
  cs-cli debug reproduce <record_id>                                                     # 期望：聊天记录不存在
  ```
- **判定**：跳过 payload 含状态残留字段 + 零 AI 日志 → 守卫误判（R0 服务端/agent 侧）；修复=状态复位分支覆盖**同设备复发**（不仅设备/客服变更）。
- **坑**：**同根不同症**——「重复转接（14 型）」与「不接管（本型）」常被混为一谈，用事件链区分。

---

## 4. 去重跳过 → 假挂起（`dedup-skip-silent-stall`）

- **症状**：某会话客户在等，AI 不回；状态机像卡住，但设备与心跳正常。
- **签名**：`send_results` 含 `服务端检测重复消息，跳过推送`；`event_record` 停在 `REPLY_MESSAGE` 无后续；批量影响多会话。
- **标准查询流程**
  ```bash
  python scripts/dup_skip_audit.py --workspace <ws_id> --convs-file <ids.txt> --out audit.json
  # 判定"漏答（harmful）"还是无害重跑：被拦截记录指向的用户消息是否存在 success 回复
  python scripts/conv_timeline.py --workspace <ws_id> --conv <conv_id> --out tl.json
  ```
- **判定**：被拦回复的 `reply_user_record_id` **无任何 success 回复指向** → 漏答（R0 服务端去重策略）；否则为无害重跑。
- **坑**：去重是**整批**跳过，一处误判会同时打死一批消息；统计影响面用去重 key 而不是会话数。

---

## 5. 重复转接（`duplicate-transfer`，第十四型）

- **症状**：同一会话被转人工两次以上；人工侧看到重复工单。
- **签名**：`创建新会话 + 批量导入 N 条历史消息`；dispatcher 系统消息 `未命中任何规则：由 X 转交给 Y`；同会话二次 `route-to-a-live-agent`。
- **标准查询流程**
  ```bash
  python scripts/server_log_query.py --conversation-id <conv_id> --start <ISO> --end <ISO> \
    --grep "route-to-a-live-agent,创建新会话,未命中任何规则"
  python scripts/sls_sql_query.py --channel <ch> --sql-where "message like '%未命中任何规则%'" --start <ISO> --end <ISO> --limit 1000 --output disp.json
  ```
- **判定**：延迟上报 → 会话重建 → 已转人工状态丢失 → AI 基于历史重判（R0 服务端）；修复=重建会话时同步转移接管状态。
- **坑**：与 13 型（脱节）症状相似，判别点是"是否**新建了会话**并**批量导入**历史消息"。

---

## 6. 平台手动接待脱节（`manual-takeover-disconnect`，第十三型）

- **症状**：人工已在平台侧接待，系统仍不断转接/重试，30min+。
- **签名**：dispatcher `未命中任何规则` → `assistant_id` 不更新；同时段转接任务 `failed`；RPA 无感知持续重试。
- **标准查询流程**
  ```bash
  python scripts/server_log_query.py --conversation-id <conv_id> --start <ISO> --end <ISO> --grep "转交给,未命中任何规则,route-to-a-live-agent"
  cs-cli conversation get --conversation-id <conv_id>      # 看当前 assistant_id / 接管人
  cs-cli monitor tickets list --agent <config_id>          # 工单派发轨迹
  ```
- **判定**：平台侧接管动作**未进入系统状态**（assistant_id 不变）→ 链路脱节（R0 集成/服务端）。
- **坑**：`cs-cli` DB 不含工单派发过程，必须回 SLS 查 dispatcher 消息。

---

## 7. 转接无人在线（`transfer-no-human-online`，第十一型）

- **症状**：客户等很久才有人工回复。
- **签名**：首派 `no_human_online` → 约 8 分钟自动关闭 → 二次派发成功。
- **标准查询流程**
  ```bash
  python scripts/server_log_query.py --conversation-id <conv_id> --start <ISO> --end <ISO> --grep "no_human_online,route-to-a-live-agent"
  ```
- **判定**：延迟 = **人工上线时间**，非 AI/链路故障（R3 产品侧，业务排班）；报告中注明"人工响应不计 AI 平响"。
- **坑**：不要把它算成"AI 慢"；平响口径只统计 AI 回复。

---

## 8. 转人工回飘风暴（`transfer-storm`，第六型）

- **症状**：同一窗口会话被反复转接，人工侧看到"风暴"。
- **签名**：同窗口 `route-to-a-live-agent` 次数显著偏多（≥3）；多条消息各自触发转人工。
- **标准查询流程**
  ```bash
  python scripts/sls_sql_query.py --channel <ch> --sql-where "message like '%route-to-a-live-agent%'" \
    --start <ISO> --end <ISO> --limit 2000 --output storm.json
  ```
- **判定**：条数按会话聚合，同一会话 ≥3 次 → 风暴（R0 派发侧缺少幂等/合并）。
- **坑**：与"回飘"（转出又被转回）区分：要用会话维度而非全局条数。

---

## 9. 超时兜底（`customer-reply-timeout`）

- **症状**：平台/服务端出现超时转人工记录，平响长尾 100s+。
- **签名**：`customer-reply-timeout`。
- **标准查询流程**
  ```bash
  python scripts/server_log_query.py --conversation-id <conv_id> --start <ISO> --end <ISO> --grep "customer-reply-timeout"
  python scripts/gap_analysis.py --conversation-id <conv_id> --start <ISO> --end <ISO>   # user→assistant 间隔分布
  ```
- **判定**：超时是**结果**，必须继续定位"为什么超时"：AI 是否被调用（3/4/15 型）→ 内容是否被拦 → 额度是否可用（10 型）。
- **坑**：**禁止**把 `customer-reply-timeout` 直接写成根因。

---

## 10. 业务断供 · 积分/额度耗尽（`credit-exhausted`）

- **症状**：AI 拒答/兜底话术；同空间多会话同时段受影响；夜间无人接 → 长尾。
- **签名**：服务端出现额度/积分 `不足|耗尽`；专家 Agent 拒答；同时段多会话共现。
- **标准查询流程**
  ```bash
  python scripts/sls_sql_query.py --project bty-prod-ack-log --logstore customer-servhub-api \
    --sql-where "message like '%积分%' and (message like '%不足%' or message like '%耗尽%')" \
    --start <ISO> --end <ISO> --limit 2000 --output credit.json
  python scripts/conv_list_all.py --workspace <ws_id> --agent <config_id> --day <YYYY-MM-DD> --out convs.json
  ```
- **判定**：额度确已耗尽 → 业务断供（R0 业务/额度管理），P0 恢复额度；同空间多会话同时段是标志。
- **坑**：与"AI 内容缺陷（11 型）"区分：本型是**能力失效**（拒答），后者是**生成了但被丢**。

---

## 11. AI 内容缺陷 → 静默丢弃（`ai-silent-content-defect`）

- **症状**：AI 有调用记录但客户收不到回复，随后走超时兜底。
- **签名**：服务端有生成记录但无 `send`/回执；RPA 侧无下发记录；常见于卡片/售后类内容。
- **标准查询流程**
  ```bash
  python scripts/conv_timeline.py --workspace <ws_id> --conv <conv_id> --out tl.json   # 看 send_results / error_detail
  python scripts/server_log_query.py --conversation-id <conv_id> --start <ISO> --end <ISO> --grep "send,error,reject,content"
  cs-cli debug record <assistant_record_id>      # 看 flow_info 是否产出最终文本
  ```
- **判定**：日志链在"生成→发送"之间断，且有明确的拦截/校验报错 → AI 侧内容缺陷（R0 agent 内容链路）。
- **坑**：与去重跳过（4 型）区分：**是否有 `服务端检测重复消息`**。

---

## 12. 平台统计口径误差（`platform-metric-mismatch`，第十型 · 非故障）

- **症状**：平台报的平响远高于服务端真值（如 270s vs 22s）。
- **签名**：平台报值显著高于服务端；跨夜封顶 30min / 人工响应混入 / 送信失败长尾；历史趋势孤立尖峰次日即恢复。
- **标准查询流程**
  ```bash
  # 平台报值 × 日消息数 ≈ 服务端总量？差额 → 定位单条长尾
  python scripts/gap_analysis.py --workspace <ws_id> --agent <config_id> --start <ISO> --end <ISO>
  python scripts/conv_list_all.py --workspace <ws_id> --agent <config_id> --day <YYYY-MM-DD> --out convs.json
  # 单条长尾取证：转人工后人工首条回复 / 送信失败
  python scripts/conv_timeline.py --workspace <ws_id> --conv <conv_id> --out tl.json
  ```
- **判定**：把差额**逐条落到具体消息**（如某条 17:13 转人工回飘失败），并说明平台口径包含哪些（人工响应、跨夜封顶、送信失败）→ 非系统故障（R3），报告中注明口径差异。
- **坑**：**不要**仅凭"平台报值高"就下"系统慢"的结论；也不能只说"口径问题"而不给出可复核的差额来源。

---

## 13. 店铺黑名单拒发（`blacklist-no-reply`，第五型 · 非故障）

- **症状**：消息没有发出，平台口径不计回复 → 长尾。
- **签名**：RPA 侧命中 `黑名单`。
- **标准查询流程**
  ```bash
  python scripts/sls_sql_query.py --channel <ch> --sql-where "message like '%黑名单%'" --start <ISO> --end <ISO> --limit 1000 --output bl.json
  ```
- **判定**：命中黑名单 → 属业务规则（R3 无责），报告写明"非技术故障"。
- **坑**：黑名单是**店铺级**规则，会影响同店多个客服，不要误判为账号故障。

---

## 14. 客户端启动失败（`jd-client-startup-failure`，第十二型）

- **症状**：多台设备同时段起不来客户端；RPA 反复重启。
- **签名**：`Windows CreateProcess 错误码 8（内存资源不足）` 或 `UIA 业务树初始化失败`。
- **标准查询流程**
  ```bash
  python scripts/sls_sql_query.py --channel jingdong --sql-where "message like '%内存资源不足%' or message like '%CreateProcess%' or message like '%UIA业务树%'" \
    --start <ISO> --end <ISO> --limit 2000 --output startup.json
  # 主机侧确认（内存/进程/版本）
  csdbg host-pull --host <hostname> --script scripts/jm_host_cache_diag.ps1
  ```
- **判定**：内存型 → 重启主机释放；UIA 型 → 清客户端缓存（给出主机侧证据：内存占用、缓存目录大小）。
- **坑**：两类**处置完全不同**，必须先分类再给建议。

---

## 15. 空会话判定 + 放弃冷却（`empty-session-giveup`，第十七型）

- **症状**：客户真实存在但 RPA 报"顾客找不到"；转人工也不生效。
- **签名**：RPA `空会话 第 N/3 次确认`；服务端回执 `会话无任何消息内容，多轮确认为空会话已关闭`；
  后续转人工被 `放弃冷却期` 跳过；截图证明会话真实存在。
- **标准查询流程**
  ```bash
  python scripts/sls_sql_query.py --channel <ch> --sql-where "message like '%空会话%'" --start <ISO> --end <ISO> --limit 1000 --output empty.json
  python scripts/server_log_query.py --conversation-id <conv_id> --start <ISO> --end <ISO> --grep "会话无任何消息内容,放弃冷却"
  python scripts/fetch_equipment_shots.py --equipment-id <eq_id> --workspace <ws_id> --start <ISO> --end <ISO> --pick <HH:MM:SS> --out-dir ./shots
  ```
- **判定**：定位校验连续判空 → 异常会话丢弃 + 冷却吞转人工（R0 RPA 探测/冷却机制）；**"顾客找不到"是冷却文案，不是事实**。
- **坑**：没有截图时极易被带偏成"客户会话不存在"，务必取桌面帧。

---

## 16. 整窗全量上报 · 特殊类型判死（`fullwindow-special-type-batch`，第十六型）

- **症状**：老会话突然转人工；AI 完全没调用。
- **签名**：RPA 上报 `消息范围: all`（无锚点整窗）；历史 VIDEO/图片等特殊类型被当新消息；`unread_message_special_types` 整包判死。
- **标准查询流程**
  ```bash
  python scripts/sls_sql_query.py --channel jingdong --sql-where "message like '%消息范围: all%'" --start <ISO> --end <ISO> --limit 1000 --output all.json
  python scripts/conv_timeline.py --workspace <ws_id> --conv <conv_id> --out tl.json   # 看事件链与 caller
  ```
- **判定**：caller 是无锚点整窗 + 包内混有历史特殊类型 → RPA 上报缺陷（R0 RPA）；修复=上报前按锚点/时间过滤。
- **坑**：与"面板白屏"一同出现时，先定"消息从哪来"，再定"为何判死"。

---

## 17. 选店失败卡死（`shop-name-mismatch-stall`，第十九型）

- **症状**：设备长时间不接单，人工介入前一直卡在登录/选店环节。
- **签名**：`候选店铺名（按优先级）: [...]，页面可选店铺: [...]` → `页面上未找到店铺X` → `均未在页面上找到`（每 3s 一拍持续数小时）；
  `停在「请选择店铺」页且选店失败`；中控 `连续 N 次发送 power_on 指令未生效,需人工介入`。
- **标准查询流程（三线取证）**
  ```bash
  # ① 名称线：配置店铺名 vs 页面可选店铺
  python scripts/sls_sql_query.py --channel douyin --sql-where "message like '%均未在页面上找到%'" --start <ISO> --end <ISO> --limit 2000 --output shop.json
  # ② ID 线：配置 channel_login_shop_id 是否非空且进过启动/注册配置
  python scripts/sls_sql_query.py --channel douyin --sql-where "message like '%channel_login_shop_id%'" --start <ISO> --end <ISO> --limit 500 --output shopid.json
  # ③ 真值线：用上报通道反查实际店铺（Cookie SHOP_ID / order_data[].shop_id + shop_name）
  python scripts/sls_sql_query.py --channel douyin --sql-where "message like '%SHOP_ID%' or message like '%order_data%'" --start <ISO> --end <ISO> --limit 1000 --output truth.json
  ```
- **判定**：名称线不一致 + ID 线显示"有 ID 却没走 ID 分支"（故障时段该字段 0 命中）→ 选店策略缺陷（R0 RPA + 配置）；
  修复=绑定名/ID 对齐实际店铺 + 让 `channel_login_shop_id` 进启动配置 + 选店失败 N 次即告警。
- **坑**：**ID 全对不等于走了 ID 分支**——必须用"故障时段是否打印 ID 匹配日志"来判定，别只看配置值。

---

## 18. 账号名大小写/全半角不匹配（`account-name-case-mismatch`，第十八型）

- **症状**：RPA 报"找不到窗口/主窗口"，注入链完全不触发；同版本其他设备正常。
- **签名**：`咚咚主窗口未找到` 类告警；平台侧显示名与系统配置名**逐字符不同**（大小写、空格、全半角）。
- **标准查询流程**
  ```bash
  python scripts/sls_sql_query.py --channel jingdong --sql-where "message like '%主窗口未找到%'" --start <ISO> --end <ISO> --limit 1000 --output win.json
  # 必需的旁证：截图逐字符放大核对账号名（12% 缩放下 AI 与 ai 不可辨）
  python scripts/fetch_equipment_shots.py --equipment-id <eq_id> --workspace <ws_id> --start <ISO> --end <ISO> --pick <HH:MM:SS> --out-dir ./shots
  ```
- **判定**：配置名与 UI 实际名逐字符不一致（如 `AI-3` vs `ai-3`）→ 匹配失败（R0 配置/匹配逻辑）；修复=统一命名或改为大小写不敏感匹配。
- **坑**：**通用告警文案会吞掉真因**——"主窗口未找到"背后可能是窗口名、帧、版本任一原因，必须拿截图逐字符比对。

---

## 19. 客户端僵死 offline（`jd-offline-client-death`）

- **症状**：设备持续 offline，重启 RPA 也没恢复。
- **签名**：探测日志 `zero` / `never_success`；客户端进程僵死留 Qt 残留；RPA 重启误判"就绪"。
- **标准查询流程**
  ```bash
  python scripts/sls_sql_query.py --channel jingdong --sql-where "message like '%offline%' or message like '%probe%'" --start <ISO> --end <ISO> --limit 2000 --output probe.json
  csdbg host-pull --host <hostname> --script scripts/collect_rpa_logs.ps1    # 主机侧进程/日志
  ```
- **判定**：心跳断流 + 主机侧无电源事件 + 探测 `never_success` → 进程僵死（R0 客户端），处置=彻底结束残留进程再拉起。
- **坑**：与"主机冻结"区分：本型主机侧**无**电源/崩溃事件。

---

## 20. 主机资源饱和 → 会话冻结（`host-resource-freeze`）

- **症状**：某时段会话整体无响应，几十秒到几十分钟后自愈；客户端可能自行退出又重启。
- **签名**：`robot-health-report` 心跳**断流**（30s 一条出现空窗）；主机 CPU/内存打满；ECD 侧无"计划外重启"但有高负载；
  时间窗与服务端长尾完全吻合；同主机其它账号同时段同症。
- **标准查询流程**
  ```bash
  # ① 心跳断流时间线（断点=冻结起点）
  python scripts/sls_sql_query.py --channel <ch> --sql-where "extra_client_username like '%<账号昵称>%' and message like '%robot-health-report%'" \
    --start <ISO> --end <ISO> --limit 500 --output hb.json
  # ② 主机侧电源/重启/崩溃事件（ECD 实锤优先）
  python scripts/host_events_query.py --equipment-id <eq_id> --start <ISO> --end <ISO> --save host_events.txt
  # ③ 服务端侧长尾对照（同窗）
  python scripts/server_log_query.py --conversation-id <conv_id> --start <ISO> --end <ISO>
  ```
- **判定**：心跳断流窗 ⊂ 服务端长尾窗 + 主机资源饱和证据 → 主机资源故障（R0 host/IP 或基础设施）；
  若同时段全渠道多设备抖动，转 21 型。
- **坑**：**心跳断流 ≠ 主机故障**——先看 ECD 是否有电源/崩溃事件：无事件 + 高负载 = 资源饱和；有事件 = 主机层故障。

---

## 21. 云桌面出口网络抖动（`network-jitter-egress`）

- **症状**：延迟尖峰，多设备/多渠道同时段；一段时间后自行恢复。
- **签名**：同时段多渠道 RPA 发送/接收延迟同步升高；心跳 WS 重连、ping 超时；服务端侧无明显异常。
- **标准查询流程**
  ```bash
  # 同时段多设备对照（分组聚合，避免拉全量）
  python scripts/sls_sql_query.py --channel <ch> --sql-where "1=1" --start <ISO> --end <ISO> --limit 5000 --output all.json
  python scripts/srv_summarize.py --file all.json --start <HH:MM> --end <HH:MM> --grep "重连,timeout,延迟,retry"
  ```
- **判定**：抖动窗内**有话务**才算直接成因；打在无话务窗内只是背景噪声，不能当根因。
- **坑**：与"平台口径假象"叠加时最易误判——先算"平台报值 × 消息数 vs 服务端总量"，把单条长尾剔出去再谈网络。

---

## 22. 班前积压 vs 平台评估窗错配（`shop-offhours-backlog` · 非故障）

- **症状**：早间平响异常高，客服一上班就"看起来慢"。
- **签名**：消息到达集中在店铺上班前的时段；平台评估窗包含班前积压；服务端 AI 处理时长正常。
- **标准查询流程**
  ```bash
  python scripts/conv_list_all.py --workspace <ws_id> --agent <config_id> --day <YYYY-MM-DD> --out convs.json
  python scripts/gap_analysis.py --workspace <ws_id> --agent <config_id> --start <ISO> --end <ISO>   # 间隔分布按小时
  ```
- **判定**：高值来自"客户消息在下班时段到达、上班后才回复"，AI 侧处理正常 → 非故障（R3），报告写明口径错配。
- **坑**：不要把它写成"客服响应慢"——那是指标口径与排班问题。

---

## 23. 弹窗/浮层遮挡 → 重试风暴（`popup-overlay-retry-storm`）

- **症状**：单个客服账号双向延迟升高，其它账号正常；同空间其它设备健康。
- **签名**：工作台弹窗 `leave` 动画残留层遮挡点击；切会话点击失败后重试风暴串行阻塞主循环；批量落库。
- **标准查询流程**
  ```bash
  python scripts/sls_sql_query.py --channel <ch> --sql-where "extra_client_username like '%<账号昵称>%'" --start <ISO> --end <ISO> --limit 3000 --output dev.json
  python scripts/srv_summarize.py --file dev.json --grep "弹窗,leave,遮挡,重试,点击"
  # 对照：同空间其它账号同窗是否正常（定界到单机）
  ```
- **判定**：只有目标账号异常 + 日志出现浮层/重试串行 → RPA 交互阻塞（R0 RPA）；`agent_duration` 持平可排除服务端。
- **坑**：延迟可能"双向"（收也慢、发也慢），别只看发送侧。

---

## 通用收尾（每型都做）

1. **六源定责**：服务端 / agent / RPA / host·IP / 渠道平台 / 运维服务，逐源写 `排除（判据）/ 有责（责任点）/ 数据缺口（补数建议）` 与 `R0–R3`。
2. **影响面**：客户侧（会话数、客户数、是否在等）/ 数据侧（台账缺段）/ 指标侧（平台口径 vs 服务端真值）。
3. **建议排序**：P0 先止血（可立即执行）→ P1 防复发（自愈/探针/告警）→ P2 因果复核。
4. **报告双写**：`*_FINAL_REPORT.md` + `*_report.html`，结构见 `references/report-format.md`，ID 全篇完整 32 位。
