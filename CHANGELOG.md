# Changelog

## [1.3.1] - 2026-09-25

### Fixed

- **子命令拼错给候选提示**：`csdbg docto` 现在会多打一行 `是否想用 csdbg doctor ？`
  （编辑距离 ≤2 匹配，乱输入不给误导候选）——此前只有一行「未知子命令」，
  新手容易误判成"装坏了"。覆盖 init/doctor/selftest/install/paths/env/host-pull/version
  与全部透传子命令（server/rpa/ops/cross/gap/host-events/signatures）。

### Docs

- `docs/troubleshooting.md` 新增三条速查：新版 npm 的 `install-scripts ... allowScripts` 警告
  **可忽略**（本包 postinstall 只打印欢迎语）；`npm i -g --allow-scripts=...` **漏包名**会让 npm
  去当前目录找 `package.json` 并报 `ENOENT`（npm 提示语不完整导致的坑）；升级后技能仍是旧的
  → 需 `csdbg install` 刷新 agent 技能目录。
- `cli/README.md` 安装小节加同款提示（含正确写法）。


## [1.3.0] - 2026-09-25

### Added

#### 排查取证脚本 7 个（`scripts/`）
- **`csapi.py`**：cs-cli 调用助手（`raw_decode` 解析尾部升级噪音 + `data` 解包）；
  可执行文件解析顺序 `CS_CLI` 环境变量 > PATH > npm 全局 bin，**不再硬编码本机路径**
- **`conv_timeline.py`**：单会话逐条消息时间线（间隔 / duration / send_results / error_detail）
- **`conv_list_all.py`**：某 agent 指定日期全量会话清单（自动翻页）
- **`dup_skip_audit.py`**：去重拦截审计——被"服务端检测重复消息，跳过推送"拦下的回复，
  逐个判定是**漏答（harmful）**还是无害重跑（去重生效），用于定位状态机假挂起
- **`srv_summarize.py`**：服务端日志摘要（message 模式聚类 + 时间窗/关键词过滤）
- **`fetch_equipment_shots.py`**：设备桌面截图回放取证（`handle_upload` 帧清单 → `sign-url` 签名下载 PNG）
- **`sls_sql_query.py`**：通用 SLS SQL 查询（`LIKE` 精确子串，绕开中文分词坑）

#### 报告规范与模板（`docs/`）
- **`docs/REPORT_STANDARD.md`**：排查与报告**强制标准**——证据交叉验证（多源对齐、同事实双源、
  截图逐字符放大、口径/时间基准、冲突即报）、结论**三段式**（已证 / 未证候选 / 判别性检查清单）、
  报告四段框架、单文件自包含 HTML 报告规范、§5.1 报告落盘位置、§5.2 证据产物落盘与结案清理、交付自检清单
- **`docs/templates/final-report.html`**：HTML 报告骨架（中心竖轴时间线 + 证据表 + 三段式结论区，内联 CSS 无外链）
- 两个构建脚本随包分发上述文档与模板（此前只分发 `troubleshooting.md`）

#### 故障签名知识库（`templates/fault_signatures.json`）
- 新增**第十九型** `shop-name-mismatch-stall`：中控下发店铺名与平台可选店铺不一致 → 选店失败卡死
  （名称线 / ID 线 / 真值线三条取证路径 + 修复方向），签名总数 16 → **17 条**

### Changed

- **（五次修订）定责表双写 MD + HTML**：D 溯源数据源定责必须**同时**出现在 `_FINAL_REPORT.md` 与 `_report.html`，
  数据/结论/等级完全一致，只写一处判不合格（HTML 侧为「溯源数据源定责（六源）」色块表格）。
  同步 `docs/REPORT_STANDARD.md` §3/§4/§6 与四份 skill（`cs-log-cross` ×2、`cs-pingxiang-debug` ×2）。
  回补历史交付：两份抖音渠道报告（选店失败 / 登录恢复停留手机号页）
  已补齐 D 定责表（含责任等级）+「影响面 · 风险 · 建议（收尾）」段，MD 与 HTML 同步；HTML 补注入 badge/mono 样式。

- **（四次修订）定责表加「责任等级」**：D. 溯源数据源定责表由三列扩为四列
  `数据源 | 定责结论 | 责任等级 | 一句话依据（+备注）`；**等级用 R 编号**：**R0 主责**（直接造成本次故障/影响）/
  **R1 次责**（放大影响或导致发现·恢复延迟）/ **R2 待定**（数据缺口未排除，需补证后再定级，须附补数建议）/ **R3 无责**（有证据排除）。
  ※ **R 与建议的 P0–P2 分开**：R = 谁的锅（定责表），P = 先做什么（收尾段建议排序）；同一事故允许多个 R0 或全 R3。
  HTML 定责块同步加等级色块（R0 红 / R1 橙 / R2 黄 / R3 绿）。同步更新 `docs/REPORT_STANDARD.md` §3/§4/§6 与
  `skill/cs-log-cross`、`skill/cs-pingxiang-debug`（含 toolkit 泛化副本）；两份 09-25 报告已补等级列。

- **（三次修订）溯源数据源定责 + ID 全量输出**：
  ① 报告「二、最终结论报告」新增 **D. 溯源数据源定责（六源）** 必备小节——表格 `数据源 | 定责结论 | 依据 | 备注`，
  固定顺序 **服务端 → agent → RPA → host/IP → 渠道平台 → 运维服务**，每条给 **有责 / 排除 / 数据缺口** 三态之一；
  六源清单同步进 §2 证据交叉验证，HTML 版新增「溯源数据源定责（六源）」色块表格（置于结论三段区之后）。
  ② **ID 铁律**：设备 ID（equipment_information_id）与会话 ID（conversation_id）**必须完整 32 位，禁止 `…` 省略**——
  正文 / 表格 / 时间线 / HTML 结论卡（原「设备ID短码」写法已废止）一律全量。
  同步更新 `docs/REPORT_STANDARD.md` §2/§3/§4/§6、`skill/cs-log-cross`、`skill/cs-pingxiang-debug`（含 toolkit 泛化副本）；
  已交付的两份 09-25 报告（京东渠道）已补 D 定责表并把全部省略 ID 还原为完整值。

- **证据区收口**：交付目录 `D:\temp\<客服账号名>\证据区\` **只保留 `screenshots\`**；
  `sls\` / `host\` / `scripts\` 三个子目录**一律不创建、出现即删**（原始 json/日志与主机原文从不落盘，
  一次性复现改为**命令块内嵌报告**「五、附件与溯源」）。结案清理流程由三步扩为四步：归集 → 核对 → 删除 → **收口**。
- **报告框架加收尾段**：每个客服账号的最终报告必须以 **「四、影响面 · 风险 · 建议」收尾（缺则不合格）**——
  影响面（客户侧/数据侧/指标口径三层，给可核对数字）+ 风险（含"下次复发条件"与监控盲区）+ P0→P2 建议表；
  「附件与溯源」降为附录（五）。HTML 版对应新增「影响面 · 风险 · 建议」块（置于页脚前）。
- 同步更新：`docs/REPORT_STANDARD.md` §3/§4/§5.1/§5.2/§6、`README.md` 输出约定、`skill/cs-log-cross`、
  `temp/README.md`；已交付的 4 个账号目录按新规收口完毕。

- **skill 报告落盘升级为交付目录制**（`cs-log-cross` / `cs-conversation-debug`）：
  本机 cs-cli 环境写 `D:\temp\<客服账号名>\`（报告与 `证据区\` 同处；证据区最终**只留 `screenshots\`**，见下方二次修订），
  外部分发包环境写 `<输出目录>`；`temp/` 降级为临时中转区，结案清零
- README / `cli/README.md` / `pack/README.md` 同步工具清单与报告规范入口

### Fixed

- **公开发布内容脱敏**（仓库为 public）：真实人名 / 机器名 / 设备 ID、真实买家账号与昵称、
  客户品牌名与商品名、真实生产 32 位会话·设备·工作空间 ID（示例位改为假值）、
  个人路径（`C:\Users\<user>`、内网工作目录）全部替换
- 新增脚本跨平台化：模块导入路径改用 `os.path.dirname(os.path.abspath(__file__))`，
  不再依赖 Windows 反斜杠切分（macOS / Linux 可用）

### Testing

- pytest 全量通过；双形态构建质量门（`py_compile` / 配置模板 JSON / 泄漏扫描）通过

---

## [1.2.0] - 2026-09-24

### Added

#### 插件化数据源（P4-10）
- **`scripts/sources.py`**：数据源插件层
  - `DataSource` 抽象基类 + `QueryOutcome` 统一返回结构（entries/files/errors/log/meta/merge）
  - 五个插件实现：`ServerLogSource` / `RPALogSource`（渠道并行）/ `OpsSource` /
    `HostBundleSource` / `HostEventsSource`
  - `build_sources(args)` 注册表：**新增数据源 = 实现子类 + 注册一行**，不改主流程
  - 规范化与主机侧读取工具（`normalize_rpa` / `parse_host_time` / `load_host_bundle` 等）迁移至
    `sources.py`，`cross_analysis.py` 再导出保持向后兼容（含测试引用路径）
- `cross_analysis.run()` 主流程改为插件驱动：前三源并行（`order<40`）→ 主机侧串行，输出与行为保持一致

#### 故障签名知识库（P4-11）
- **`templates/fault_signatures.json`**：16 条沉淀故障签名结构化（第十三~十七型、业务断供、
  黑名单、面板锚点、启动失败等；13 条参与自动匹配，3 条参考条目），含
  `signature`（可读特征）/ `evidence_pattern`（机器匹配：regex_all/regex_any/min_count/max_count）/
  `conclusion_template`（结论模板）；通用化无客户数据，可复制到 `~/.csdbg/` 本地增补（同 id 覆盖）
- **`scripts/fault_signatures.py`**：加载 + 匹配器 + CLI
  - `--list` / `--check`（校验 id 唯一、正则可编译）/ `--match-dir <证据包目录>`（对已有证据包复检）
  - `csdbg signatures` 透传命令
- **证据包集成**：`evidence.md` 新增「🧩 故障签名匹配（候选）」段（命中特征 + 结论模板），
  `anchors.json`/`meta.json` 记录 `signature_hits`；终端同步提示

### Testing
- 新增 `tests/test_sources.py`（9 项：注册表/各源插件错误路径）与
  `tests/test_fault_signatures.py`（12 项：KB 加载校验/匹配语义/max_count）
- 离线自检扩展至 7 项（新增签名匹配 + 证据包含签名段落断言）；pytest 94 项全通过

---

## [1.1.0] - 2026-09-24

### Added

#### 第④源（主机侧）体验（P1-2）
- **Step 0.5 决策树**：`skill/cs-log-cross/SKILL.md` + `.claude/commands/cs-log-cross.md` 双轨加入
  「按症状判断是否需要第④源」决策表，避免"先跑四方、不够再补④"两轮往返
- **置信度分层**：主机事件记录新增 `confidence` 字段（ECD 事件日志=`high` 实锤 /
  SLS 心跳重建=`medium` 推断），论证时区分可信度；记录新增 `time_tz: Asia/Shanghai`
- **自动升级提示**：证据包检测到源② `robot-health-report` 心跳断流 ≥5min 且未提供第④源时，
  `evidence.md` 自动附「⚠ 第④源升级建议」（含补采命令），终端同步提示

#### 性能与资源控制（P1-4）
- **渠道级并行**：RPA 4 渠道由串行改并行（`ThreadPoolExecutor` 上限 4，每渠道独立 LogClient）
- **自适应并发**：`gap_analysis.py` 并发度按会话数自适应（`min(10, max(2, n//50))`），规避 API 限流
- **证据包自动归档**：`evidence_*` 目录超过保留数（默认 5）自动压缩为 zip；
  `CSDBG_EVIDENCE_KEEP` 调整、`CSDBG_NO_ARCHIVE=1` 关闭

#### 时间处理补全（P2-5）
- `rpa_log_report.py` 时区统一（此前遗漏的 2 处 naive datetime）
- **智能时间窗**：带 `--conversation-id` 且未给窗口时，按会话首末消息 ±10min 自动推断
  （限 08:00-23:59），避免夜间空窗 0 条被误读为异常；失败回退默认窗口
- 证据包报告（evidence.md）时间显示中文化（`2026年09月24日 12:11:26`），原始 JSON 保持 ISO

#### 测试与自检（P2-6）
- **构建冒烟门**：`build_cli.ps1` / `build_package.ps1` 打包前跑 pytest 全量；
  未装 pytest 自动降级为离线自检 `scripts/selftest.py`
- **离线自检**：`csdbg selftest`（无网络/无 AK 验证工具链：依赖/规范化/异常/证据包/时区）
- `csdbg doctor` 已有 SLS 连通性验证（本版复核确认）

#### 路由与可观测性（P3）
- **`cs-router` meta-skill**（skill 数 4→5）：按问题类型路由到正确入口，
  避免"单源够用却跑四方"或"该上四方却只查单源"
- **`docs/troubleshooting.md`**：常见错误 → 处置速查（配置/异常分类/时间窗/④源/构建/自检），随包分发
- **可选本地埋点** `scripts/telemetry.py`（`CSDBG_TELEMETRY=1` 启用，只写本地 usage.jsonl，绝不上传）
- **证据包元数据** `meta.json`（creator/锚点/标签/status 初值），供批量审计与结论回填

#### 配置引导（P0-3 收尾）
- `csdbg init` 末尾新增「可选：ECD 主机侧证据」提示（含 ecd.json 路径与 host-pull --help 指引）

#### 早前完成项（本版本文档化）
- **异常处理分级**（P0-1）：`exceptions.py` 异常层级 + 两段式捕获 + 证据包「数据源错误汇总」段；
  覆盖 `gap_analysis` 脏时间戳容错（WARN 跳过不崩溃）
- **泄漏扫描外置**（P0-3）：`leak_patterns.json`（gitignore）+ `.example` 模板，双构建动态读取
- **三方并行**：服务端/RPA/ops 三源并行查询（第④源依赖前三源结果，保持串行）

### Fixed

#### 正确性
- `_query_rpa` 异常分支一处元组返回错误（`return ch, e` → `return ch, None, e`）
- `leak_patterns.example.json` 内容与真实模式重叠导致的构建误报（占位符改为不重叠假值）

### Testing
- pytest 73 项全通过（0.1s）；离线自检 6 项全通过；双形态构建冒烟门通过

---

## [1.0.0] - 先前版本

初始版本：
- 四方日志交叉分析（server / RPA / ops / host）
- 双形态分发（npm CLI + zip）
- 4 个技能：cs-log-cross, cs-rpa-log, cs-conversation-debug, e-chat-trace
- 质量门：py_compile、JSON 校验、泄漏扫描、__pycache__ 清理
