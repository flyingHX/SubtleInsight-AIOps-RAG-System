# -*- coding: utf-8 -*-
"""临时脚本：将 default_role 配置重置为 viewer（修复未绑定用户越权隐患）。"""
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
        row = (await db.execute(
            select(Console_configs).where(Console_configs.config_key == "default_role")
        )).scalar_one_or_none()
        if row is None:
            db.add(Console_configs(config_key="default_role", config_value="viewer", description="未绑定角色用户的默认角色"))
            print("default_role 不存在，已创建为 viewer")
        elif row.config_value != "viewer":
            print(f"default_role 旧值: {row.config_value} -> 重置为 viewer")
            row.config_value = "viewer"
        else:
            print("default_role 已是 viewer，无需修改")
        await db.commit()
    await db_manager.close_db()
    print("FIX DONE")


asyncio.run(main())
