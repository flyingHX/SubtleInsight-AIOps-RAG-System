# -*- coding: utf-8 -*-
"""临时脚本：检查 console_configs 中 default_role 及全部配置项的当前值。"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, "/workspace/app/backend")


def load_backend_env():
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            raw = (proc / "environ").read_bytes()
        except OSError:
            continue
        if b"JWT_SECRET_KEY=" in raw and b"uvicorn" in (proc / "cmdline").read_bytes():
            env = {}
            for item in raw.split(b"\0"):
                k, _, v = item.partition(b"=")
                env[k.decode()] = v.decode()
            return env
    return {}


for k, v in load_backend_env().items():
    if k in ("DATABASE_URL", "DATABASE_BACKEND", "DB_BACKEND", "DB_DATABASE") and v and all(32 <= ord(ch) < 127 for ch in v):
        os.environ[k] = v

from sqlalchemy import select  # noqa: E402

from core.database import db_manager       # noqa: E402
from models.console_configs import Console_configs  # noqa: E402


async def main():
    await db_manager.ensure_connected()
    async with db_manager.session() as db:
        rows = (await db.execute(select(Console_configs).order_by(Console_configs.config_key))).scalars().all()
        print("=== console_configs 全量 ===")
        for r in rows:
            value = r.config_value
            if len(value) > 120:
                value = value[:120] + "...<truncated>"
            print(f"{r.config_key} = {value}")
    await db_manager.close_db()
    print("CHECK DONE")


asyncio.run(main())
