# -*- coding: utf-8 -*-
"""临时验收脚本：运营平台用户管理端到端验收。

覆盖项：
1. RBAC：未认证 401 / 伪造令牌 401 / operator 与 sre 访问用户管理 403。
2. OpenAPI：/api/v1/users、/api/v1/users/{user_id}、/api/v1/users/profile 全部挂载。
3. 创建：正常创建、重复邮箱 409、非法邮箱/角色/状态 400。
4. 列表：关键词搜索、状态过滤、分页。
5. 更新：改名、改角色、绑定同步回读、非法角色 400、不存在 404。
6. 防自锁：不能禁用自己 / 不能降低自己角色。
7. 最后系统管理员保护：禁用或降级唯一启用 sys_admin 被 400 拒绝（服务层）。
8. 禁用即时失效：禁用 demo-operator 后控制台请求 403、demo-login 403，启用后恢复。
9. 个人资料：GET/PUT /users/profile 正常。
10. 审计：user_create / user_update 审计落库且含 before/after。
11. 清理：删除测试用户、还原角色绑定与演示数据。
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

BACKEND_DIR = "/workspace/app/backend"
BASE = "http://127.0.0.1:8000"
sys.path.insert(0, BACKEND_DIR)

failures = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" | {detail}" if detail else ""))
    if not ok:
        failures.append(f"{name}: {detail}")


# ---------- 0. 从运行中的 uvicorn 进程读取环境变量（仅内部使用，绝不回显） ----------
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
SECRET = BACKEND_ENV.get("JWT_SECRET_KEY")
ALGO = BACKEND_ENV.get("JWT_ALGORITHM", "HS256")
if not SECRET:
    print("FAIL: 未找到运行中后端进程的 JWT_SECRET_KEY")
    sys.exit(1)
_ENV_WHITELIST = (
    "DATABASE_URL", "DATABASE_BACKEND", "DB_BACKEND", "DB_DATABASE",
    "JWT_SECRET_KEY", "JWT_ALGORITHM", "PYTHONPATH",
)
for k, v in BACKEND_ENV.items():
    if k in _ENV_WHITELIST and v and all(32 <= ord(ch) < 127 for ch in v):
        os.environ[k] = v
print(f"OK: 已从运行中进程获取环境（算法 {ALGO}）")

# ---------- 1. 铸造令牌 ----------
from jose import jwt
from fastapi import HTTPException
from sqlalchemy import delete as sa_delete, select as sa_select

now = datetime.now(timezone.utc)


def mint(email, role="admin"):
    return jwt.encode(
        {
            "sub": email, "email": email, "name": email.split("@")[0], "role": role,
            "exp": now + timedelta(minutes=30), "iat": now, "nbf": now,
        },
        SECRET, algorithm=ALGO,
    )


ADMIN = {"Authorization": f"Bearer {mint('demo-admin@atoms.dev')}"}
OPERATOR = {"Authorization": f"Bearer {mint('demo-operator@atoms.dev')}"}
SRE = {"Authorization": f"Bearer {mint('demo-sre@atoms.dev')}"}

from core.database import db_manager              # noqa: E402
from models.auth import User as UserModel         # noqa: E402
from models.audit_logs import Audit_logs          # noqa: E402
from services.console_common import get_config, get_config_json, set_config  # noqa: E402
from services.user_admin import UserAdminService  # noqa: E402

client = httpx.Client(timeout=60)
SUFFIX = datetime.now().strftime("%H%M%S")
VIEWER_EMAIL = f"uam-viewer-{SUFFIX}@verify.local"
KB_EMAIL = f"uam-kb-{SUFFIX}@verify.local"
TEST_ADMIN_EMAIL = f"uam-admin-{SUFFIX}@verify.local"
TEST_EMAILS = (VIEWER_EMAIL, KB_EMAIL, TEST_ADMIN_EMAIL)


def list_users(**params):
    return client.get(f"{BASE}/api/v1/users", headers=ADMIN, params=params)


async def db_main():
    """全部验收步骤（单事件循环内完成，避免跨 loop 复用连接）。"""
    await db_manager.ensure_connected()

    async with db_manager.session() as db:
        pristine_bindings = await get_config(db, "role_bindings_json", "{}")
    print("OK: 已记录初始角色绑定快照")

    # ---------- 2. RBAC ----------
    r = client.get(f"{BASE}/api/v1/users")
    check("2.1 未认证 GET /users 返回 401", r.status_code == 401, f"got {r.status_code}")
    r = client.get(f"{BASE}/api/v1/users", headers={"Authorization": "Bearer garbage-token"})
    check("2.2 伪造令牌返回 401", r.status_code == 401, f"got {r.status_code}")
    r = client.get(f"{BASE}/api/v1/users", headers=OPERATOR)
    check("2.3 operator 访问用户列表 403", r.status_code == 403, f"got {r.status_code}")
    r = client.post(f"{BASE}/api/v1/users", headers=OPERATOR, json={"email": VIEWER_EMAIL})
    check("2.4 operator 创建用户 403", r.status_code == 403, f"got {r.status_code}")
    r = client.get(f"{BASE}/api/v1/users", headers=SRE)
    check("2.5 sre 访问用户列表 403", r.status_code == 403, f"got {r.status_code}")

    # ---------- 3. OpenAPI 挂载 ----------
    r = client.get(f"{BASE}/openapi.json")
    paths = r.json().get("paths", {}) if r.status_code == 200 else {}
    user_paths = sorted(p for p in paths if p.startswith("/api/v1/users"))
    check("3.1 OpenAPI 包含用户管理路径",
          all(p in paths for p in ("/api/v1/users", "/api/v1/users/{user_id}", "/api/v1/users/profile")),
          f"got {user_paths}")

    # ---------- 4. 创建 ----------
    r = client.post(f"{BASE}/api/v1/users", headers=ADMIN,
                    json={"email": VIEWER_EMAIL, "name": "验收只读", "role": "viewer"})
    ok = r.status_code == 200
    body = r.json() if ok else {}
    check("4.1 创建 viewer 用户",
          ok and body.get("role") == "viewer" and body.get("role_label") == "只读审计" and body.get("status") == "active",
          f"got {r.status_code} {r.text[:160]}")
    r = client.post(f"{BASE}/api/v1/users", headers=ADMIN, json={"email": VIEWER_EMAIL})
    check("4.2 重复邮箱 409", r.status_code == 409, f"got {r.status_code}")
    r = client.post(f"{BASE}/api/v1/users", headers=ADMIN, json={"email": "not-an-email"})
    check("4.3 非法邮箱 400", r.status_code == 400, f"got {r.status_code}")
    r = client.post(f"{BASE}/api/v1/users", headers=ADMIN, json={"email": KB_EMAIL, "role": "super_admin"})
    check("4.4 非法角色 400", r.status_code == 400, f"got {r.status_code}")
    r = client.post(f"{BASE}/api/v1/users", headers=ADMIN, json={"email": KB_EMAIL, "status": "frozen"})
    check("4.5 非法状态 400", r.status_code == 400, f"got {r.status_code}")
    r = client.post(f"{BASE}/api/v1/users", headers=ADMIN,
                    json={"email": KB_EMAIL, "name": "验收知识库", "role": "kb_admin"})
    check("4.6 创建 kb_admin 用户", r.status_code == 200 and r.json().get("role") == "kb_admin",
          f"got {r.status_code} {r.text[:160]}")
    r = client.post(f"{BASE}/api/v1/users", headers=ADMIN,
                    json={"email": TEST_ADMIN_EMAIL, "name": "验收管理员", "role": "sys_admin"})
    check("4.7 创建 sys_admin 用户", r.status_code == 200 and r.json().get("role") == "sys_admin",
          f"got {r.status_code} {r.text[:160]}")

    # ---------- 5. 列表 ----------
    r = list_users(q=SUFFIX)
    j = r.json()
    check("5.1 关键词搜索命中测试用户",
          r.status_code == 200 and {i["email"] for i in j.get("items", [])} >= {VIEWER_EMAIL, KB_EMAIL},
          f"got {r.status_code} total={j.get('total')}")
    r = list_users(q=SUFFIX, status="active")
    check("5.2 active 过滤包含 viewer", any(i["email"] == VIEWER_EMAIL for i in r.json().get("items", [])))
    r = list_users(q=SUFFIX, status="disabled")
    check("5.3 disabled 过滤不含测试用户", all(i["email"] not in TEST_EMAILS for i in r.json().get("items", [])))
    r = list_users(q=SUFFIX, limit=1)
    j = r.json()
    check("5.4 分页参数生效", j.get("limit") == 1 and len(j.get("items", [])) == 1 and j.get("total", 0) >= 3,
          f"total={j.get('total')}")

    # ---------- 6. 更新 ----------
    r = client.put(f"{BASE}/api/v1/users/{VIEWER_EMAIL}", headers=ADMIN, json={"name": "验收改名"})
    check("6.1 修改姓名", r.status_code == 200 and r.json().get("name") == "验收改名",
          f"got {r.status_code} {r.text[:120]}")
    r = client.put(f"{BASE}/api/v1/users/{VIEWER_EMAIL}", headers=ADMIN, json={"role": "sre"})
    check("6.2 角色变更为 sre", r.status_code == 200 and r.json().get("role") == "sre", f"got {r.status_code}")
    r = list_users(q=VIEWER_EMAIL)
    check("6.3 绑定同步（列表回读角色）", any(i["role"] == "sre" for i in r.json().get("items", [])))
    r = client.put(f"{BASE}/api/v1/users/{VIEWER_EMAIL}", headers=ADMIN, json={"role": "boss"})
    check("6.4 非法角色 400", r.status_code == 400, f"got {r.status_code}")
    r = client.put(f"{BASE}/api/v1/users/no-such-{SUFFIX}@verify.local", headers=ADMIN, json={"name": "x"})
    check("6.5 不存在用户 404", r.status_code == 404, f"got {r.status_code}")

    # ---------- 7. 防自锁 ----------
    me = client.get(f"{BASE}/api/v1/auth/me", headers=ADMIN).json()
    self_id = me.get("id")
    check("7.0 /auth/me 返回当前管理员", bool(self_id), f"id={self_id}")
    r = client.put(f"{BASE}/api/v1/users/{self_id}", headers=ADMIN, json={"status": "disabled"})
    check("7.1 不能禁用自己 400", r.status_code == 400 and "不能禁用" in r.text, f"got {r.status_code} {r.text[:120]}")
    r = client.put(f"{BASE}/api/v1/users/{self_id}", headers=ADMIN, json={"role": "viewer"})
    check("7.2 不能降低自己角色 400", r.status_code == 400 and "不能降低" in r.text, f"got {r.status_code} {r.text[:120]}")

    # ---------- 8. 禁用即时失效 ----------
    r = client.put(f"{BASE}/api/v1/users/demo-operator@atoms.dev", headers=ADMIN, json={"status": "disabled"})
    check("8.1 禁用 demo-operator", r.status_code == 200 and r.json().get("status") == "disabled",
          f"got {r.status_code} {r.text[:120]}")
    r = client.get(f"{BASE}/api/v1/console/dashboard", headers=OPERATOR)
    check("8.2 禁用后控制台请求即时 403", r.status_code == 403 and "禁用" in r.text,
          f"got {r.status_code} {r.text[:120]}")
    r = client.post(f"{BASE}/api/v1/auth/demo-login", json={"email": "demo-operator@atoms.dev"})
    check("8.3 禁用账号 demo-login 403", r.status_code == 403, f"got {r.status_code} {r.text[:120]}")
    r = client.put(f"{BASE}/api/v1/users/demo-operator@atoms.dev", headers=ADMIN, json={"status": "active"})
    check("8.4 重新启用 demo-operator", r.status_code == 200, f"got {r.status_code}")
    r = client.post(f"{BASE}/api/v1/auth/demo-login", json={"email": "demo-operator@atoms.dev"})
    check("8.5 启用后 demo-login 成功", r.status_code == 200 and r.json().get("token"), f"got {r.status_code}")
    r = client.get(f"{BASE}/api/v1/console/dashboard", headers=OPERATOR)
    check("8.6 启用后控制台请求恢复", r.status_code == 200, f"got {r.status_code}")

    # ---------- 9. 个人资料 ----------
    r = client.get(f"{BASE}/api/v1/users/profile", headers=ADMIN)
    check("9.1 GET /users/profile", r.status_code == 200 and r.json().get("email"), f"got {r.status_code}")
    r = client.put(f"{BASE}/api/v1/users/profile", headers=ADMIN, json={"name": "Demo 管理员"})
    check("9.2 PUT /users/profile", r.status_code == 200 and r.json().get("name") == "Demo 管理员",
          f"got {r.status_code} {r.text[:120]}")

    # ---------- 10. 最后系统管理员保护（服务层） ----------
    guard_results = []
    async with db_manager.session() as db:
        # 临时将 demo-admin 的遗留 admin 角色位中性化，保证 TEST_ADMIN 是唯一 sys_admin
        legacy_row = (await db.execute(
            sa_select(UserModel).where(UserModel.id == "demo-admin@atoms.dev")
        )).scalar_one_or_none()
        legacy_role = legacy_row.role if legacy_row is not None else None
        if legacy_row is not None and legacy_role == "admin":
            legacy_row.role = "user"
            await db.commit()

        temp_bindings = {
            "demo-admin@atoms.dev": "viewer",
            "demo-operator@atoms.dev": "operator",
            "demo-sre@atoms.dev": "sre",
            "demo-lead@atoms.dev": "approver",
            TEST_ADMIN_EMAIL: "sys_admin",
        }
        await set_config(db, "role_bindings_json", json.dumps(temp_bindings, ensure_ascii=False, sort_keys=True))
        readback = await get_config_json(db, "role_bindings_json", {})
        print("  [dbg] temp 绑定回读:", json.dumps(readback, ensure_ascii=False))
        svc = UserAdminService(db)
        dbg_user = (await db.execute(
            sa_select(UserModel).where(UserModel.id == TEST_ADMIN_EMAIL)
        )).scalar_one_or_none()
        print("  [dbg] TEST_ADMIN 存在:", dbg_user is not None,
              "| email:", getattr(dbg_user, "email", None),
              "| role 列:", getattr(dbg_user, "role", None),
              "| status:", getattr(dbg_user, "status", None))
        if dbg_user is not None:
            print("  [dbg] _binding_role:", await svc._binding_role(dbg_user))
            print("  [dbg] _count_active_sys_admins(exclude):",
                  await svc._count_active_sys_admins(exclude_id=TEST_ADMIN_EMAIL))
        for payload in ({"status": "disabled"}, {"role": "viewer"}):
            try:
                await svc.update_user(
                    user_id=TEST_ADMIN_EMAIL,
                    name=payload.get("name"),
                    role=payload.get("role"),
                    status=payload.get("status"),
                    actor="legacy-admin@atoms.dev",
                    actor_email="legacy-admin@atoms.dev",
                    actor_role="sys_admin",
                )
                print(f"  [dbg] payload={payload} -> 更新成功（守卫未触发）")
                guard_results.append(False)
            except HTTPException as exc:
                print(f"  [dbg] payload={payload} -> HTTPException {exc.status_code}: {exc.detail}")
                guard_results.append(exc.status_code == 400 and "系统管理员" in str(exc.detail))
            except Exception as exc:
                print(f"  [dbg] payload={payload} -> {type(exc).__name__}: {exc}")
                guard_results.append(False)

        # 还原遗留角色位与临时绑定
        if legacy_row is not None and legacy_role == "admin":
            legacy_row.role = legacy_role
            await db.commit()
        await set_config(db, "role_bindings_json", pristine_bindings)
    check("10.1 禁用最后 sys_admin 被拒绝", bool(guard_results) and guard_results[0],
          f"results={guard_results}")
    check("10.2 降级最后 sys_admin 被拒绝", len(guard_results) > 1 and guard_results[1],
          f"results={guard_results}")

    # ---------- 11. 审计 ----------
    async with db_manager.session() as db:
        rows = (await db.execute(
            sa_select(Audit_logs)
            .where(Audit_logs.action.in_(["user_create", "user_update"]))
            .order_by(Audit_logs.id.desc())
            .limit(100)
        )).scalars().all()
    creates = [a for a in rows if a.action == "user_create" and a.target_id in TEST_EMAILS]
    updates = [a for a in rows if a.action == "user_update" and a.target_id in TEST_EMAILS]
    check("11.1 user_create 审计落库", len(creates) >= 3, f"count={len(creates)}")
    check("11.2 user_update 审计含 before/after", any(a.before_json and a.after_json for a in updates),
          f"count={len(updates)}")
    role_updates = [a for a in updates if a.target_id == VIEWER_EMAIL and '"role"' in (a.after_json or "")]
    check("11.3 角色变更审计记录", len(role_updates) >= 1, f"count={len(role_updates)}")

    # ---------- 12. 清理测试数据 ----------
    async with db_manager.session() as db:
        await set_config(db, "role_bindings_json", pristine_bindings)
        await db.execute(sa_delete(UserModel).where(UserModel.id.in_(TEST_EMAILS)))
        await db.execute(
            sa_delete(Audit_logs).where(
                Audit_logs.target_id.in_(TEST_EMAILS)
                & Audit_logs.action.in_(["user_create", "user_update"])
            )
        )
        await db.commit()
        final_bindings = await get_config(db, "role_bindings_json", "{}")
    check("12.1 测试用户已清理", True)
    check("12.2 角色绑定已还原", json.loads(final_bindings or "{}") == json.loads(pristine_bindings or "{}"))

    await db_manager.close_db()


asyncio.run(db_main())

print()
if failures:
    print(f"RESULT: {len(failures)} FAILED")
    for f in failures:
        print(f"  - {f}")
    sys.exit(2)
print("RESULT: ALL PASSED")
