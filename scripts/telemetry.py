#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""telemetry.py — 可选本地使用埋点（默认关闭，仅写本地文件，绝不上传）

启用: 环境变量 CSDBG_TELEMETRY=1
落盘: ${CSDBG_HOME:-~/.csdbg}/usage.jsonl（JSON Lines，仅统计字段，无业务内容）

用途: 统计工具使用情况（哪些入口/锚点类型/源组合），为运维决策提供本地依据。
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

CST = timezone(timedelta(hours=8))


def _usage_path() -> Path:
    home = Path(os.environ.get('CSDBG_HOME') or (Path.home() / '.csdbg'))
    return home / 'usage.jsonl'


def log_usage(skill: str, anchors: Dict, sources: List[str],
              success: bool, extra: Dict = None) -> None:
    """写一条本地使用记录。未启用/任何失败都静默跳过（埋点绝不阻断主流程）。

    skill:   入口标识（如 cs-log-cross / cross_analysis）
    anchors: 锚点 dict（只记录"用了哪类锚点"，不记录锚点值，避免落业务 ID）
    sources: 各源命中键（如 ['server','rpa:qianniu','ops']）
    success: 是否全部源成功
    """
    if not os.environ.get('CSDBG_TELEMETRY'):
        return
    try:
        rec = {
            'ts': datetime.now(tz=CST).isoformat(timespec='seconds'),
            'skill': skill,
            'anchor_types': sorted(k for k, v in (anchors or {}).items() if v),
            'sources': sorted(sources or []),
            'success': bool(success),
        }
        if extra:
            rec.update(extra)
        p = _usage_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        pass
