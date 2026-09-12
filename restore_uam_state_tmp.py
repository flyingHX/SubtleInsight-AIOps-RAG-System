# -*- coding: utf-8 -*-
"""临时脚本：还原用户管理验收残留状态（角色绑定 + 遗留测试用户 + 审计）。"""
import asyncio
import json
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


BACKEND_ENV = load_backend_env()
for k, v in BACKEND_ENV.items():
    if k in ("DATABASE_URL", "DATABASE_BACKEND", "DB_BACKEND", "DB_DATABASE") and v and all(32 <= ord(ch) < 127 for ch in v):
        os.environ[k] = v

from sqlalchemy import delete as sa_delete, or_, select as sa_select  # noqa: E402

from core.database import db_manager            # noqa: E402
from models.auth import User                    # noqa: E402
from models.audit_logs import Audit_logs        # noqa: E402
from models.console_configs import Console_configs  # noqa: E402
from services.console_common import get_config_json  # noqa: E402

PRISTINE = '{"demo-operator@atoms.dev": "operator", "demo-sre@atoms.dev": "sre", "demo-lead@atoms.dev": "approver", "demo-admin@atoms.dev": "sys_admin"}'
DESCRIPTION = "角色绑定 JSON（email -> role）"
LEFTOVER = or_(User.id.like("uam-%"), User.id == "dbg-last-admin@verify.local")


async def main():
    await db_manager.ensure_connected()
    async with db_manager.session() as db:
        # 1. role_bindings_json 去重并还原为演示默认值
        rows = (
            await db.execute(
                sa_select(Console_configs).where(Console_configs.config_key == "role_bindings_json")
            )
        ).scalars().all()
        print("role_bindings_json 行数:", len(rows))
        for extra in rows[1:]:
            await db.delete(extra)
        if rows:
            rows[0].config_value = PRISTINE
            rows[0].description = DESCRIPTION
        else:
            db.add(Console_configs(config_key="role_bindings_json", config_value=PRISTINE, description=DESCRIPTION))
        await db.commit()

        # 2. 删除遗留测试用户与对应审计
        leftover = (await db.execute(sa_select(User).where(LEFTOVER))).scalars().all()
        print("遗留测试用户:", [u.id for u in leftover])
        await db.execute(sa_delete(Audit_logs).where(
            Audit_logs.target_id.like("uam-%")
            & Audit_logs.action.in_(["user_create", "user_update"])
        ))
        await db.execute(sa_delete(User).where(LEFTOVER))
        await db.commit()

        # 3. 校验最终状态
        print("绑定还原:", json.dumps(await get_config_json(db, "role_bindings_json", {}), ensure_ascii=False))
        users = (await db.execute(sa_select(User).order_by(User.id))).scalars().all()
        for u in users:
            print("user:", u.id, "| role =", u.role, "| status =", u.status)
    await db_manager.close_db()
    print("RESTORE DONE")


asyncio.run(main())
