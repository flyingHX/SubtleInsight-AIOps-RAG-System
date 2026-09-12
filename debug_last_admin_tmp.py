# -*- coding: utf-8 -*-
"""临时调试：定位最后 sys_admin 守卫未触发的原因。"""
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
_ENV_WHITELIST = ("DATABASE_URL", "DATABASE_BACKEND", "DB_BACKEND", "DB_DATABASE")
for k, v in BACKEND_ENV.items():
    if k in _ENV_WHITELIST and v and all(32 <= ord(ch) < 127 for ch in v):
        os.environ[k] = v

from fastapi import HTTPException                      # noqa: E402
from sqlalchemy import func, select                    # noqa: E402
from core.database import db_manager                   # noqa: E402
from models.auth import User                           # noqa: E402
from models.console_configs import Console_configs     # noqa: E402
from services.console_common import get_config_json, set_config  # noqa: E402
from services.user_admin import UserAdminService       # noqa: E402

DBG_EMAIL = "dbg-last-admin@verify.local"


async def main():
    await db_manager.ensure_connected()
    async with db_manager.session() as db:
        # 前置清理
        old = (await db.execute(select(User).where(User.id == DBG_EMAIL))).scalar_one_or_none()
        if old is not None:
            await db.delete(old)
            await db.commit()

        pristine = await get_config_json(db, "role_bindings_json", {})
        print("1. pristine bindings:", json.dumps(pristine, ensure_ascii=False))

        n_keys = (await db.execute(
            select(func.count()).select_from(Console_configs)
            .where(Console_configs.config_key == "role_bindings_json")
        )).scalar_one()
        print("2. role_bindings_json 行数（重复行会导致 LIMIT 1 不确定性）:", n_keys)

        db.add(User(id=DBG_EMAIL, email=DBG_EMAIL, name="dbg", role="user", status="active"))
        await db.commit()

        temp = {
            "demo-admin@atoms.dev": "viewer",
            "demo-operator@atoms.dev": "operator",
            "demo-sre@atoms.dev": "sre",
            "demo-lead@atoms.dev": "approver",
            DBG_EMAIL: "sys_admin",
        }
        await set_config(db, "role_bindings_json", json.dumps(temp, ensure_ascii=False, sort_keys=True))
        print("3. set 后读回 bindings:", json.dumps(await get_config_json(db, "role_bindings_json", {}), ensure_ascii=False))

        svc = UserAdminService(db)
        user = (await db.execute(select(User).where(User.id == DBG_EMAIL))).scalar_one()
        print("4. _binding_role:", await svc._binding_role(user))
        print("5. _count_active_sys_admins(exclude):", await svc._count_active_sys_admins(exclude_id=DBG_EMAIL))

        for payload in ({"status": "disabled"}, {"role": "viewer"}):
            try:
                await svc.update_user(
                    user_id=DBG_EMAIL,
                    name=payload.get("name"),
                    role=payload.get("role"),
                    status=payload.get("status"),
                    actor="dbg",
                    actor_email="nobody@verify.local",
                    actor_role="sys_admin",
                )
                print(f"6. payload={payload} -> UPDATE 成功（守卫未触发）")
            except Exception as exc:
                print(f"6. payload={payload} -> {type(exc).__name__} status={getattr(exc, 'status_code', None)} detail={getattr(exc, 'detail', exc)}")

        # 还原
        await set_config(db, "role_bindings_json", json.dumps(pristine, ensure_ascii=False, sort_keys=True))
        user2 = (await db.execute(select(User).where(User.id == DBG_EMAIL))).scalar_one_or_none()
        if user2 is not None:
            await db.delete(user2)
        await db.commit()
        print("7. 已还原绑定与调试用户")
    await db_manager.close_db()


asyncio.run(main())
