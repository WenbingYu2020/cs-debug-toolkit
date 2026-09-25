#!/usr/bin/env python3
"""cs-cli 调用助手：运行 cs-cli 子命令，raw_decode 解析 JSON（尾部有升级噪音），支持翻页。

cs-cli 可执行文件解析顺序：环境变量 `CS_CLI` > PATH 上的 cs-cli > npm 全局 bin 目录。
（cs-cli 即 `@bty/customer-service-cli`，需另行安装；本模块只做调用与解析。）
"""
import json
import os
import shutil
import subprocess
import sys


def _resolve_cli():
    env = os.environ.get("CS_CLI")
    if env:
        return env
    for name in ("cs-cli", "cs-cli.cmd"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        os.path.join(os.environ.get("APPDATA", ""), "npm", "cs-cli.cmd"),  # Windows npm 全局
        os.path.expanduser("~/.npm-global/bin/cs-cli"),                    # 自定义 prefix
        "/usr/local/bin/cs-cli",
        "/opt/homebrew/bin/cs-cli",
    ]
    for cand in candidates:
        if cand and os.path.exists(cand):
            return cand
    return "cs-cli"


CS_CLI = _resolve_cli()


def run(args, timeout=180):
    p = subprocess.run([CS_CLI] + args, capture_output=True, timeout=timeout)
    out = p.stdout.decode("utf-8", errors="replace")
    err = p.stderr.decode("utf-8", errors="replace")
    raw = out.lstrip()
    try:
        obj, idx = json.JSONDecoder().raw_decode(raw)
    except Exception:
        return None, out, err, p.returncode
    return obj, out, err, p.returncode


def data(args, timeout=180):
    obj, out, err, rc = run(args, timeout)
    if obj is None:
        print("PARSE FAIL rc=%s\nSTDOUT:%s\nSTDERR:%s" % (rc, out[:2000], err[:1000]), file=sys.stderr)
        return None
    if isinstance(obj, dict) and obj.get("success") is False:
        print("API FAIL:", json.dumps(obj, ensure_ascii=False)[:800], file=sys.stderr)
        return None
    if isinstance(obj, dict) and "data" in obj:
        return obj["data"]
    return obj


if __name__ == "__main__":
    d = data(sys.argv[1:])
    print(json.dumps(d, ensure_ascii=False, indent=1)[:8000] if d is not None else "NONE")
