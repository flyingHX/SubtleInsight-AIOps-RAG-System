# -*- coding: utf-8 -*-
"""临时脚本：以原后端进程相同的环境变量重启 uvicorn（不回显任何密钥）。"""
import os
import sys
from pathlib import Path

ENV_BIN = Path("/tmp/backend_environ.bin")

raw = ENV_BIN.read_bytes()
restored = 0
for item in raw.split(b"\0"):
    if not item:
        continue
    key, _, value = item.partition(b"=")
    if key:
        os.environ[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
        restored += 1

os.chdir("/workspace/app/backend")
os.execvp(
    sys.executable,
    [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--reload",
        "--reload-exclude",
        "*.log",
        "--reload-exclude",
        "*.pyc",
    ],
)
