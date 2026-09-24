# 常见错误与排障（troubleshooting）

> 快速索引：先看「错误 → 处置」表；细节在下方分节。环境自检优先跑 `csdbg doctor`（在线）
> 或 `csdbg selftest`（离线，无 AK 也能验证工具链）。

## 错误 → 处置速查

| 报错 / 现象 | 原因 | 处置 |
|---|---|---|
| `channels.json 不存在` / AK 仍是占位符 | 未初始化配置 | `csdbg init -i` 或按 `channels.example.json` 填 `access_key_id/secret` |
| `SLS 认证失败 (AuthenticationError)` | AK 无效/过期/无权限 | 检查 AK；确认有 `log:GetLogStoreLogs` 与两个 project 的读权限 |
| `SLS 查询配额不足 (QuotaExceededError)` | 限流/日配额 | 缩小时间窗或 `--limit`；稍后重试（标记「可重试」） |
| `ECS/ECD 配置不存在: ecd.json` | 未配第四源凭据 | `csdbg host-pull --help` 有模板；写到 `~/.csdbg/ecd.json`（与 SLS AK 分开） |
| `cs-cli 未登录` | CLI 未认证 | `cs-cli auth login` |
| `缺少依赖: pip install aliyun-log-python-sdk` | Python 依赖缺失 | `pip install -r requirements.txt`；`csdbg doctor` 可复核 |
| 中文输出乱码（Windows） | 控制台编码 | 前置 `PYTHONIOENCODING=utf-8`（csdbg 已自动设置） |
| 构建时 `包内发现个人路径/AK 痕迹` | 个人模式匹配到分发文件 | 检查 `scripts/leak_patterns.json` 的模式是否命中了 `.example`/文档；把个人模式收紧 |
| 构建 `pytest 不可用` 警告 | 未装 pytest | 可忽略（自动降级离线自检）；要完整体检 `pip install pytest` |
| 结果全部 `0 条` 但没报错 | 时间窗内确实无数据，或查询被静默跳过 | 看证据包 `evidence.md` 的「⚠ 数据源错误汇总」；确认时间窗覆盖了话务时段 |
| 夜里查默认窗口全 0 | 排班外无话务 | 显式给 `--start/--end`；带 `--conversation-id` 时已自动按会话首末消息推断窗口 |
| 主机侧日志被截断（~24KB） | ECD RunCommand 输出上限 | 缩短时间窗或分批取数；`host-pull` 会打印截断警告 |
| 服务端查询 `50000 条上限` 截断 | SLS 查询条数上限 | 用更精确的锚点/关键词 AND 查询；或拆分窗口分次取 |
| 心跳断流但分不清 睡眠/崩溃 | 缺第④源 | 证据包会出现「第④源升级建议」，按提示补 `--host-events-equipment <设备ID>` |
| `temp/` 磁盘膨胀 | 证据包堆积 | 默认自动归档最旧 evidence_* 为 zip（保留 5 个）；`CSDBG_EVIDENCE_KEEP=10` 调整，`CSDBG_NO_ARCHIVE=1` 关闭 |
| `csdbg` 命令找不到 | 未全局安装 | `npm i -g cs-debug-toolkit`；或 zip 形态改用 `python scripts/xxx.py` |

## 分节说明

### 1. 配置与凭据
- **两套 AK 分开管理**：SLS 只读 AK 在 `channels.json`（zip 形态：`scripts/` 下；CLI 形态：`~/.csdbg/`），
  ECD AK 在 `ecd.json`（`CSDBG_ECD_CONFIG` 可改路径）。两者权限不同、来源不同，不要混用。
- **形态判断**（命令二选一）：`csdbg paths` 能跑 → CLI 形态；有 `<TOOLKIT>/scripts/*.py` → zip 形态。
- 本地检视：`csdbg paths` 打印生效配置路径，`csdbg env` 打印手动跑 python 脚本所需环境变量。

### 2. 查询类异常如何读
所有数据源异常都有分类（`AuthenticationError / QuotaExceededError / TimeoutError / ParseError / NetworkError`），
且带 `recoverable` 标记：
- **可重试**（认证过期/超时/网络抖动）→ 刷新凭据或重跑；
- **不可恢复**（配额耗尽/解析失败）→ 需人工介入，别盲目重试。

证据包 `evidence.md` 顶部的「⚠ 数据源错误汇总」会按来源聚合展示；**没有这个段落**才说明各源是真 0 条。
配套：交叉分析会继续跑其余源（单源失败不阻断），并在结论中注明该源不可用。

### 3. 时间与窗口
- 一律**北京时间（UTC+8）**，与主机所在时区无关（已显式固定）。
- 默认窗口是「今天 00:00 ~ 现在」；带 `--conversation-id` 且未给窗口时，会按会话首末消息 ±10 分钟
  自动推断（限制在 08:00-23:59），避免夜间空窗误读为异常。
- 主机本地事件日志记录带 `time_tz: Asia/Shanghai` 标注来源时区。

### 4. 第④源（主机侧）排障
- `confidence` 字段区分可信度：`high`=ECD 事件日志实锤；`medium`=SLS 心跳重建推断。
  论证时不要把推断当实锤。
- 采集通道二选一：ECD 远程拉起（需权限）→ 一键；无权限 → 拷 `collect_*.ps1` 到目标机执行回传。
- 超 24KB 输出会被 ECD 截断，按提示缩窗分批。

### 5. 构建与发布（维护者）
- 质量门顺序：`py_compile` → 配置 JSON 可解析 → **冒烟测试（pytest 全量；缺 pytest 降级 selftest.py）** →
  泄漏扫描（读 `scripts/leak_patterns.json`）→ 清理 `__pycache__`。
- 泄漏扫描模式**不要**与分发版 `.example` 文件内容重叠（否则误报阻断构建）；个人模式只放
  `leak_patterns.json`（gitignore，不入包）。
- 构建前建议先 `git status`——产物默认含工作区未提交内容（`-Strict` 可强制阻断）。

### 6. 离线自检（无网络/无 AK）
```bash
csdbg selftest            # CLI 形态
python scripts/selftest.py  # zip 形态 / 源码
```
覆盖：依赖导入 → RPA 记录规范化（北京时间）→ 异常分类 → 心跳断流检测/升级提示 →
四方证据包端到端生成（中文时间/错误汇总/主机专题）→ 时区统一。全绿说明工具链可用，
剩下只差 AK/网络这类环境配置。
