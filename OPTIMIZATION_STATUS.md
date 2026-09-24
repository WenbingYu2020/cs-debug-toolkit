# 优化计划执行状态 — 逐项核验（2026-09-24 回归）

> 对照原始《cs-cli 项目缺陷风险与优化建议》（11 项，P0–P4）逐条核验代码真实状态。
> 原始报告全文已恢复存档：`temp/原始缺陷分析报告_20260923.md`。
> 本文件是**权威状态**；`OPTIMIZATION_SUMMARY.md` 为中途快照（其部分结论已被本轮核验修正）。

## 状态总表

| 优先级 | 问题 | 原估成本 | 状态 | 证据 |
|---|---|---|---|---|
| P0 | 1. 错误处理缺陷 | 2 天 | ✅ **完成** | `exceptions.py` 异常层级 + 两段式捕获（cross_analysis 全部 6 处 handler / gap_analysis）；证据包「数据源错误汇总」段；gap_analysis 脏时间戳 WARN 跳过；`tests/test_exceptions.py` 15 项 |
| P0 | 3. AK 泄露风险 | 1 天 | ✅ **完成** | ①泄露规则外置 `leak_patterns.json`+`.example`，双构建动态读取（构建门 C 实测通过）②`csdbg init` 末尾新增 ECD 配置提示；`host-pull --help` 与报错路径均含创建向导 ③形态检测：`CSDBG_CONFIG/CSDBG_TEMP/CSDBG_ECD_CONFIG` 环境变量链 + 每脚本候选路径回退（双形态实测均可用，未另加统一函数） |
| P1 | 2. 第④源路径依赖 | 3 天 | ✅ **完成** | ①Step 0.5 决策树（`skill/cs-log-cross/SKILL.md` + `.claude/commands/` 双轨）②`confidence` 置信度字段（ECD=high / SLS 推断=medium）+ `time_tz` 标注 ③证据包自动「第④源升级建议」（心跳断流 ≥5min 且无④时） |
| P1 | 4. 性能瓶颈 | 2 天 | ✅ **完成** | ①全渠道并行（原串行 4 渠道 → 并行上限 4，独立 LogClient）②`gap_analysis` 自适应并发 `min(10,max(2,n//50))` ③证据包自动归档（保留 5，`CSDBG_EVIDENCE_KEEP`/`CSDBG_NO_ARCHIVE` 可调）；另：三源（server/RPA/ops）并行 |
| P2 | 5. 时间跨时区 | 1 天 | ✅ **完成** | ①CST=UTC+8 全模块统一（含补漏的 `rpa_log_report.py`）②智能时间窗（会话首末 ±10min、限 08:00-23:59）③主机事件 `time_tz: Asia/Shanghai` 标注。测试 19 项（含中文时间 6 项） |
| P2 | 6. 缺少测试 | 5 天 | ✅ **完成** | ①pytest 73 项（离线、假 SDK）②构建冒烟门（pytest 全量；缺 pytest 降级离线自检）③离线自检 `csdbg selftest` / `scripts/selftest.py`（6 项端到端）④`csdbg doctor` SLS 连通性（复核确认已有） |
| P3 | 7-9. 体验优化 | 3 天 | ✅ **完成** | ⑦`docs/troubleshooting.md`（错误→处置速查，随包分发）⑧`cs-router` meta-skill 路由（技能数 4→5）⑨`telemetry.py` 可选本地埋点 + 证据包 `meta.json`（creator/标签/状态） |
| P4 | 10-11. 架构演进 | 10 天+ | ✅ **完成** | ⑩`scripts/sources.py` 插件化数据源（`DataSource` 抽象 + `QueryOutcome` + `build_sources()` 注册表，五插件实装，主流程插件驱动不改行为）⑪`templates/fault_signatures.json` 故障签名知识库（16 条：13 自动匹配 + 3 参考）+ `fault_signatures.py`（加载/校验/匹配/`--match-dir` 复检）+ 证据包「🧩 故障签名匹配（候选）」段 + `csdbg signatures` 命令 |

## 本轮回归发现并修复的差项

首轮实施经核验存在 4 类未做齐/误判，本轮已全部补齐：

1. **P1-2 曾被我误判为"无需改动"**（当时只核了 ecd.json 路径链）。原问题实为"路径依赖与用户认知负担"——
   决策树/置信度/自动升级三条均缺失 → 本轮补齐。
2. **P2-5 遗漏 `rpa_log_report.py`**（2 处 naive datetime）→ 已修。
3. **P1-4 只做了三源并行**，原建议的"渠道级并行 / 自适应并发 / 证据包压缩"未做 → 本轮补齐。
4. **P2-6 只有单测**，原建议的"冒烟入构建 / 离线自检 / doctor 连通性"未做（doctor 连通性此前已有）
   → 本轮补齐并接入质量门。

## 验证记录（2026-09-24）

| 项 | 结果 |
|---|---|
| pytest 全量 | 94 passed（0.16s，含 P4 新增 21 项：插件层 9 + 签名库 12） |
| 离线自检（源码 & 构建产物） | 7/7 通过（新增：签名匹配、证据包含签名段落） |
| 知识库校验 `--check` | 16 条通过（id 唯一 / 正则可编译） |
| 匹配器真实数据验证 | 历史证据包 `--match-dir` 复检无假阳性；合成用例命中第十五型 |
| npm 形态构建 `build_cli.ps1` | ✅ v1.2.0 tgz；冒烟门通过；技能数 5 |
| zip 形态构建 `build_package.ps1` | ✅ 冒烟门通过；技能数 5 |
| 泄漏扫描（两份产物） | ✅ 无个人数据/路径/AK 痕迹 |
| 插件化回归 | 主流程输出/证据文件与重构前逐项一致（server/rpa_*/ops/host/anchors/meta/evidence.md） |

## 后续可选（非本次范围）

- 知识库继续增补家族条目（第一批/第二型等历史签名如可考据可补）；
- 插件层可再扩展第五源（如网关/客户端监控日志），注册表加一行即可；
- 原报告 P3-7 的两项非必需子项（`INSTALL.md` 抽取、`temp/{evidence,analysis,cases}` 目录重构）：
  未做——README 已覆盖安装路径约定；目录重构会破坏既有 skill/文档引用，判定低收益高风险。
