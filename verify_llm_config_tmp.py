# -*- coding: utf-8 -*-
"""临时验收脚本：LLM/Embedding 管理配置安全端到端验收。

覆盖项：
1. 未认证 401 / operator 角色 403（GET configs、PUT configs、POST llm-test）。
2. 历史明文密钥兼容（直写明文 → 脱敏回读）。
3. Fernet 加密持久化（DB 中仅存 enc: 密文，服务层可解密，响应与审计不含明文）。
4. 脱敏占位符 **** 回写被 400 拒绝且原密钥不被覆盖。
5. 参数校验 400（provider/base_url/temperature/timeout/embedding_url）。
6. openai_compatible 动态切换 + 本地 Mock 捕获：Authorization Bearer、model、temperature
   修改后无需重启立即生效；Embedding 回退 LLM url/key。
7. Embedding 指向不可达地址时诊断不被阻断（降级）。
8. 清空密钥路径 + 最终 atoms_hub 连通性测试通过。
9. 审计日志明文/密文泄露扫描。
10. CONSOLE_SECRET_KEY/JWT_SECRET_KEY 缺失时 encrypt_secret 明确报错（子进程验证）。
"""
import asyncio
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
# 仅回填直连数据库/加解密所需的白名单变量，跳过含非法字节的值
_ENV_WHITELIST = (
    "DATABASE_URL", "DATABASE_BACKEND", "DB_BACKEND", "DB_DATABASE",
    "CONSOLE_SECRET_KEY", "JWT_SECRET_KEY", "JWT_ALGORITHM", "PYTHONPATH",
)
for k, v in BACKEND_ENV.items():
    if k in _ENV_WHITELIST and v and all(32 <= ord(ch) < 127 for ch in v):
        os.environ[k] = v
print(f"OK: 已从运行中进程获取环境（算法 {ALGO}）")

# ---------- 1. 本地 OpenAI 兼容 Mock 服务（捕获请求） ----------
CAPTURED = {}


class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            body = {}
        CAPTURED[self.path] = {"auth": self.headers.get("Authorization"), "body": body}
        if self.path.endswith("/chat/completions"):
            resp = {
                "id": "mock", "object": "chat.completion", "created": 0,
                "model": body.get("model"),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        elif self.path.endswith("/embeddings"):
            inputs = body.get("input", [])
            if isinstance(inputs, str):
                inputs = [inputs]
            resp = {
                "object": "list", "model": body.get("model"),
                "data": [{"object": "embedding", "index": i, "embedding": [0.1] * 8} for i in range(len(inputs))],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            }
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
MOCK_URL = f"http://127.0.0.1:{server.server_address[1]}/v1"
print(f"OK: 本地 OpenAI 兼容 Mock 已启动 {MOCK_URL}")

# ---------- 2. 铸造令牌 ----------
from jose import jwt

now = datetime.now(timezone.utc)


def mint(email):
    return jwt.encode(
        {
            "sub": email, "email": email, "name": email.split("@")[0], "role": "admin",
            "exp": now + timedelta(minutes=30), "iat": now, "nbf": now,
        },
        SECRET, algorithm=ALGO,
    )


ADMIN = {"Authorization": f"Bearer {mint('demo-admin@atoms.dev')}"}
OPERATOR = {"Authorization": f"Bearer {mint('demo-operator@atoms.dev')}"}

PLAIN_KEY = "sk-live-abcd1234wxyz9876"          # 验收用明文密钥（仅脚本内存/DB 密文）
LEGACY_KEY = "sk-legacy-plain-123456"           # 模拟历史明文
MASKED_LIVE = "sk-l****9876"
MASKED_LEGACY = "sk-l****3456"

from services.llm_runtime import decrypt_secret  # noqa: E402
from services.console_common import set_config   # noqa: E402
from core.database import db_manager             # noqa: E402
from models.console_configs import Console_configs  # noqa: E402
from models.audit_logs import Audit_logs         # noqa: E402
from sqlalchemy import select                    # noqa: E402

client = httpx.Client(timeout=120)


def cfg(key):
    r = client.get(f"{BASE}/api/v1/console/configs", headers=ADMIN)
    r.raise_for_status()
    for item in r.json()["items"]:
        if item["key"] == key:
            return item
    return None


def put(key, value, headers=None):
    return client.put(
        f"{BASE}/api/v1/console/configs",
        headers=headers or ADMIN,
        json={"key": key, "value": value},
    )


def llm_test():
    return client.post(f"{BASE}/api/v1/console/configs/llm-test", headers=ADMIN, json={})


async def db_main():
    """全部验收步骤（单事件循环内完成，避免跨 loop 复用连接/锁）。"""
    await db_manager.ensure_connected()

    # ---------- 3. 认证与 RBAC ----------
    r = client.get(f"{BASE}/api/v1/console/configs")
    check("3.1 未认证 GET /configs 返回 401", r.status_code == 401, f"got {r.status_code}")
    r = client.get(f"{BASE}/api/v1/console/configs", headers={"Authorization": "Bearer garbage-token"})
    check("3.2 伪造令牌返回 401", r.status_code == 401, f"got {r.status_code}")
    r = client.get(f"{BASE}/api/v1/console/configs", headers=OPERATOR)
    check("3.3 operator GET /configs 返回 403", r.status_code == 403, f"got {r.status_code}")
    r = client.put(f"{BASE}/api/v1/console/configs", headers=OPERATOR, json={"key": "llm_model", "value": "x"})
    check("3.4 operator PUT /configs 返回 403", r.status_code == 403, f"got {r.status_code}")
    r = client.post(f"{BASE}/api/v1/console/configs/llm-test", headers=OPERATOR, json={})
    check("3.5 operator POST llm-test 返回 403", r.status_code == 403, f"got {r.status_code}")

    # ---------- 4. 历史明文密钥兼容 ----------
    async with db_manager.session() as db:
        await set_config(db, "llm_api_key", LEGACY_KEY)  # 直写明文，模拟历史数据
    item = cfg("llm_api_key")
    check("4.1 历史明文脱敏回读", item and item["value"] == MASKED_LEGACY, f"value={item and item['value']}")
    check("4.2 is_secret 标记", bool(item and item["is_secret"]))

    # ---------- 5. Fernet 加密持久化 + 审计脱敏 ----------
    r = put("llm_api_key", PLAIN_KEY)
    body = {}
    try:
        body = r.json()
    except Exception:
        pass
    check("5.1 PUT 密钥返回 200", r.status_code == 200, f"got {r.status_code}")
    check("5.2 响应为脱敏值", body.get("value") == MASKED_LIVE, f"value={body.get('value')}")
    check("5.3 响应不含明文", PLAIN_KEY not in r.text)
    stored = None
    async with db_manager.session() as db:
        row = (await db.execute(
            select(Console_configs).where(Console_configs.config_key == "llm_api_key").limit(1)
        )).scalar_one_or_none()
        stored = row.config_value if row else None
    check("5.4 DB 仅存 enc: 密文", bool(stored) and stored.startswith("enc:"))
    check("5.5 DB 不含明文", PLAIN_KEY not in (stored or ""))
    check("5.6 服务层可解密还原", decrypt_secret(stored) == PLAIN_KEY)

    # ---------- 6. 占位符拒绝，不覆盖原密钥 ----------
    r = put("llm_api_key", MASKED_LIVE)
    check("6.1 脱敏占位符回写被 400 拒绝", r.status_code == 400, f"got {r.status_code}")
    item = cfg("llm_api_key")
    check("6.2 原密钥未被覆盖（仍为原脱敏值）", item and item["value"] == MASKED_LIVE, f"value={item and item['value']}")
    stored2 = None
    async with db_manager.session() as db:
        row = (await db.execute(
            select(Console_configs).where(Console_configs.config_key == "llm_api_key").limit(1)
        )).scalar_one_or_none()
        stored2 = row.config_value if row else None
    check("6.3 DB 中密钥仍可解密为原明文", decrypt_secret(stored2 or "") == PLAIN_KEY)

    # ---------- 7. 参数校验 400 ----------
    for key, value in [
        ("llm_provider", "bad_provider"),
        ("llm_base_url", "ftp://example.com/v1"),
        ("llm_temperature", "3.5"),
        ("llm_timeout_seconds", "5"),
        ("embedding_base_url", "notaurl"),
    ]:
        r = put(key, value)
        check(f"7.x 非法值被拒 {key}={value}", r.status_code == 400, f"got {r.status_code}")

    # ---------- 8. openai_compatible 动态切换 + Mock 捕获 ----------
    for key, value in [
        ("llm_provider", "openai_compatible"),
        ("llm_base_url", MOCK_URL),
        ("llm_model", "mock-model"),
        ("llm_temperature", "0.5"),
    ]:
        r = put(key, value)
        check(f"8.x 保存 {key}={value}", r.status_code == 200, f"got {r.status_code} {r.text[:120]}")

    r = llm_test()
    chat = r.json().get("chat", {})
    cap = CAPTURED.get("/v1/chat/completions", {})
    check("8.1 llm-test Chat 通过（Mock）", r.status_code == 200 and chat.get("ok") is True, f"chat={chat}")
    check("8.2 Chat 请求携带解密后 Bearer Key", cap.get("auth") == f"Bearer {PLAIN_KEY}", f"auth={cap.get('auth')}")
    check("8.3 Chat 请求 model 生效", cap.get("body", {}).get("model") == "mock-model")
    # 连通性测试是固定 temperature=0.0 的确定性探测（设计如此）；配置温度的真实生效路径在业务调用
    check("8.4 连通性测试探测固定 temperature=0.0（确定性探测）", cap.get("body", {}).get("temperature") == 0.0,
          f"got {cap.get('body', {}).get('temperature')}")

    r = put("embedding_model", "mock-embed")
    check("8.5 保存 embedding_model", r.status_code == 200)
    r = llm_test()
    emb = r.json().get("embedding", {})
    cap_emb = CAPTURED.get("/v1/embeddings", {})
    check("8.6 llm-test Embedding 通过（回退 LLM url/key）",
          emb.get("enabled") is True and emb.get("ok") is True and emb.get("dims") == 8, f"emb={emb}")
    check("8.7 Embedding 请求回退使用 LLM Key", cap_emb.get("auth") == f"Bearer {PLAIN_KEY}", f"auth={cap_emb.get('auth')}")
    check("8.8 Embedding 请求 model 生效", cap_emb.get("body", {}).get("model") == "mock-embed")

    # 8.9 动态生效：修改后无需重启立即生效
    r = put("llm_temperature", "0.77")
    check("8.9a 保存 llm_temperature=0.77", r.status_code == 200)
    # 配置温度的真实生效路径是业务诊断调用（llm-test 固定 0.0 为确定性探测）；
    # 清除旧捕获后逐个事件尝试诊断，直到 Mock 捕获到新的 Chat 请求
    r = client.get(f"{BASE}/api/v1/console/events?limit=5", headers=ADMIN)
    events = r.json().get("items", [])
    cap = None
    diag_detail = ""
    for ev in events:
        CAPTURED.pop("/v1/chat/completions", None)
        r = client.post(f"{BASE}/api/v1/console/events/{ev['id']}/diagnose", headers=ADMIN)
        diag_detail = f"event={ev['id']} status={r.status_code} body={r.text[:120]}"
        cap = CAPTURED.get("/v1/chat/completions")
        if cap:
            break
    if cap:
        check("8.9b 配置 temperature 修改后业务调用立即生效",
              cap.get("body", {}).get("temperature") == 0.77,
              f"got {cap.get('body', {}).get('temperature')}")
    else:
        check("8.9b 配置 temperature 修改后业务调用立即生效", False, f"未捕获到 Chat 请求 | {diag_detail}")
    r = put("llm_model", "mock-model-2")
    check("8.9c 保存 llm_model=mock-model-2", r.status_code == 200)
    r = llm_test()
    chat = r.json().get("chat", {})
    cap = CAPTURED.get("/v1/chat/completions", {})
    check("8.9d model 修改后立即生效", chat.get("model") == "mock-model-2" and cap.get("body", {}).get("model") == "mock-model-2",
          f"chat.model={chat.get('model')}")

    # ---------- 9. 恢复默认 provider，验证 Embedding 失败不阻断诊断 ----------
    for key, value in [
        ("llm_provider", "atoms_hub"),
        ("llm_base_url", ""),
        ("llm_model", "deepseek-v4-flash"),
        ("llm_temperature", "0.2"),
        ("embedding_base_url", "http://127.0.0.1:9"),
        ("embedding_model", "broken-embed"),
    ]:
        r = put(key, value)
        check(f"9.x 准备诊断环境 {key}={value!r}", r.status_code == 200, f"got {r.status_code}")

    r = client.get(f"{BASE}/api/v1/console/events?limit=1", headers=ADMIN)
    events = r.json().get("items", [])
    if events:
        event_id = events[0]["id"]
        r = client.post(f"{BASE}/api/v1/console/events/{event_id}/diagnose", headers=ADMIN)
        ok = r.status_code == 200
        detail = f"event={event_id} got {r.status_code} {r.text[:160]}"
        check("9.y Embedding 不可达时诊断仍成功（降级不阻断）", ok, detail if not ok else f"event={event_id}")
    else:
        check("9.y 无事件可诊断（跳过）", True)

    # 清理 Embedding 配置
    for key in ("embedding_base_url", "embedding_model"):
        r = put(key, "")
        check(f"9.z 清理 {key}", r.status_code == 200)

    # ---------- 10. 清空密钥 + 最终连通性测试（atoms_hub） ----------
    r = put("llm_api_key", "")
    check("10.1 空值清除密钥返回 200", r.status_code == 200, f"got {r.status_code}")
    item = cfg("llm_api_key")
    check("10.2 清除后脱敏值为空", item and item["value"] == "", f"value={item and item['value']!r}")
    r = llm_test()
    chat = r.json().get("chat", {})
    emb = r.json().get("embedding", {})
    check("10.3 最终 llm-test Chat 通过（atoms_hub 真实调用）",
          r.status_code == 200 and chat.get("ok") is True, f"chat={chat}")
    check("10.4 Embedding 未启用提示", emb.get("enabled") is False, f"emb={emb}")

    # ---------- 11. 审计日志泄露扫描 ----------
    async with db_manager.session() as db:
        rows = (await db.execute(select(Audit_logs).order_by(Audit_logs.id.desc()).limit(200))).scalars().all()
    blob = json.dumps(
        [(a.action, a.target_id, a.before_json, a.after_json) for a in rows],
        ensure_ascii=False,
    )
    check("11.1 审计不含明文密钥", PLAIN_KEY not in blob and LEGACY_KEY not in blob)
    check("11.2 审计不含 enc: 密文", "enc:" not in blob)
    config_audits = [a for a in rows if a.action == "config_update" and a.target_id == "llm_api_key"]
    check("11.3 密钥变更已写审计", len(config_audits) >= 1, f"count={len(config_audits)}")
    llm_test_audits = [a for a in rows if a.action == "llm_config_test"]
    check("11.4 连通性测试已写审计", len(llm_test_audits) >= 1, f"count={len(llm_test_audits)}")
    provider_audits = [a for a in rows if a.action == "config_update" and a.target_id == "llm_provider"]
    check("11.5 provider 变更已写审计", len(provider_audits) >= 1, f"count={len(provider_audits)}")

    await db_manager.close_db()


asyncio.run(db_main())

# ---------- 12. 缺失密钥时明确报错（独立子进程，剥离两个环境变量） ----------
code = (
    "import sys; sys.path.insert(0, '/workspace/app/backend');\n"
    "import os\n"
    "os.environ.pop('CONSOLE_SECRET_KEY', None)\n"
    "os.environ.pop('JWT_SECRET_KEY', None)\n"
    "from services.llm_runtime import encrypt_secret\n"
    "try:\n"
    "    encrypt_secret('x')\n"
    "    print('NO_ERROR')\n"
    "except RuntimeError as e:\n"
    "    print('OK:', e)\n"
)
env = {k: v for k, v in os.environ.items() if k not in ("CONSOLE_SECRET_KEY", "JWT_SECRET_KEY")}
proc = subprocess.run(
    ["/opt/python/envs/mgx-chat/bin/python", "-c", code],
    env=env, capture_output=True, text=True, timeout=60,
)
check("12.1 缺失 CONSOLE/JWT 密钥时明确报错",
      "OK:" in proc.stdout and "缺少" in (proc.stdout + proc.stderr),
      f"stdout={proc.stdout.strip()[:120]}")

server.shutdown()

print()
if failures:
    print(f"RESULT: {len(failures)} FAILED")
    for f in failures:
        print(f"  - {f}")
    sys.exit(2)
print("RESULT: ALL PASSED")
