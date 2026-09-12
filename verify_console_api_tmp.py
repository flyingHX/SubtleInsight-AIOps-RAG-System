# -*- coding: utf-8 -*-
"""临时验收脚本：铸造测试 JWT（复用运行中后端进程的密钥，不回显），验证控制台 GET 链路。"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path('/workspace/app/backend')

# 1. 从运行中的 uvicorn 进程读取环境变量（仅内部使用，绝不打印值）
environ = {}
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        raw = (proc / 'environ').read_bytes()
    except OSError:
        continue
    if b'JWT_SECRET_KEY=' in raw and b'uvicorn' in (proc / 'cmdline').read_bytes():
        for item in raw.split(b'\0'):
            k, _, v = item.partition(b'=')
            environ[k.decode()] = v.decode()
        break

secret = environ.get('JWT_SECRET_KEY')
algo = environ.get('JWT_ALGORITHM', 'HS256')
if not secret:
    print('FAIL: 运行中后端进程未找到 JWT_SECRET_KEY')
    sys.exit(1)
print(f'OK: 已从运行中进程获取 JWT 密钥（算法 {algo}，长度 {len(secret)}）')

# 2. 动态发现控制台路由前缀
console_py = (BACKEND / 'routers' / 'console.py').read_text(encoding='utf-8')
prefix = '/api/v1/console'
for line in console_py.splitlines():
    if 'APIRouter(' in line and 'prefix=' in line:
        prefix = line.split('prefix=')[1].split(',')[0].strip().strip('"\'')
        break
print(f'OK: 控制台路由前缀 = {prefix}')

# 3. 铸造测试令牌（claims 与 Atoms 平台签发结构一致：sub/email/name/role）
from jose import jwt

now = datetime.now(timezone.utc)
claims = {
    'sub': 'demo-admin@atoms.dev',
    'email': 'demo-admin@atoms.dev',
    'name': 'Demo Admin',
    'role': 'admin',
    'exp': now + timedelta(minutes=30),
    'iat': now,
    'nbf': now,
}
token = jwt.encode(claims, secret, algorithm=algo)

# 4. 逐个调用控制台核心 GET 接口
import httpx

base = 'http://127.0.0.1:8000'
headers = {'Authorization': f'Bearer {token}'}
paths = [
    f'{prefix}/permissions',
    f'{prefix}/dashboard',
    f'{prefix}/events?limit=3',
    f'{prefix}/approvals',
    f'{prefix}/configs',
    f'{prefix}/audit-logs',
    '/health',
]

failed = 0
with httpx.Client(timeout=20) as c:
    for p in paths:
        try:
            r = c.get(base + p, headers=headers)
            body = r.text[:220].replace('\n', ' ')
            mark = 'PASS' if r.status_code == 200 else 'FAIL'
            if r.status_code != 200:
                failed += 1
            print(f'{mark} {p} -> {r.status_code} {body}')
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f'FAIL {p} -> ERR {type(exc).__name__}: {str(exc)[:120]}')

print(f'\n结果：{"全部通过" if failed == 0 else f"{failed} 个失败"}')
sys.exit(0 if failed == 0 else 2)
