# Changelog

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
