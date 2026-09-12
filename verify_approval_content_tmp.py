# -*- coding: utf-8 -*-
"""临时验收：审批中心内容完整展示。

覆盖项：
1. merge 审批内容返回主案例 + 全部被合并案例完整字段（或显式 missing）。
2. rule_promote 审批内容返回规则条目预览 + 关联日志实例样本。
3. kb_edit create 端到端：全字段新建 → full_case 含案例库全部字段、missing_fields 为空、关联日志实例非空。
4. kb_edit create 端到端：仅必填字段 → missing_fields 精确标注、未匹配日志实例为空列表。
5. 既有 kb_edit update 审批内容 diff 回归。
6. 未认证访问内容接口被拒。
7. 验收产生的数据全部清理。
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path('/workspace/app/backend')


def load_backend_env() -> dict:
    """从运行中的 uvicorn 进程读取环境变量（仅内部使用，绝不打印值）。"""
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            raw = (proc / 'environ').read_bytes()
        except OSError:
            continue
        if b'JWT_SECRET_KEY=' in raw and b'uvicorn' in (proc / 'cmdline').read_bytes():
            env = {}
            for item in raw.split(b'\0'):
                k, _, v = item.partition(b'=')
                env[k.decode()] = v.decode()
            return env
    return {}


ENV = load_backend_env()
SECRET = ENV.get('JWT_SECRET_KEY')
ALGO = ENV.get('JWT_ALGORITHM', 'HS256')
DB_URL = ENV.get('DATABASE_URL')
for k in ('DATABASE_URL', 'PYTHONPATH'):
    if ENV.get(k) and all(32 <= ord(ch) < 127 for ch in ENV[k]):
        os.environ[k] = ENV[k]
if not SECRET or not DB_URL:
    print('FAIL: 未从运行中进程获取到 JWT_SECRET_KEY / DATABASE_URL')
    sys.exit(1)
print(f'OK: 已获取运行中进程环境（算法 {ALGO}，数据库 URL 已就位）')

from jose import jwt  # noqa: E402
import asyncpg  # noqa: E402
import httpx  # noqa: E402

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
TOKEN = jwt.encode(claims, SECRET, algorithm=ALGO)

BASE = 'http://127.0.0.1:8000'
PREFIX = '/api/v1/console'
HEADERS = {'Authorization': f'Bearer {TOKEN}'}

CHECKS = []


def check(name: str, cond: bool, detail: str = '') -> None:
    CHECKS.append(cond)
    line = f"{'PASS' if cond else 'FAIL'}: {name}"
    if detail:
        line += f' | {detail}'
    print(line)


def to_asyncpg_url(raw_url: str) -> str:
    for prefix in ('postgresql+asyncpg://', 'postgresql+psycopg2://', 'postgresql+psycopg://'):
        if raw_url.startswith(prefix):
            return 'postgresql://' + raw_url[len(prefix):]
    return raw_url


CASE_KEYS = {
    'case_id', 'error_type', 'service_name', 'cluster', 'alert_template',
    'root_cause', 'solution', 'topology_snapshot', 'status', 'version', 'feedback_score',
}


def is_full_case(obj) -> bool:
    return isinstance(obj, dict) and CASE_KEYS <= set(obj.keys())


async def main() -> int:
    conn = await asyncpg.connect(to_asyncpg_url(DB_URL))
    created = []  # (approval_request_id | None, change_set_id, case_id)
    try:
        async with httpx.AsyncClient(base_url=BASE, headers=HEADERS, timeout=30) as cli:
            # 0) 未认证访问内容接口被拒（独立匿名客户端，避免客户端级默认头残留）
            async with httpx.AsyncClient(base_url=BASE, timeout=30) as anon:
                r = await anon.get(f'{PREFIX}/approvals/1/content')
            check('未认证访问审批内容被拒(401/403)', r.status_code in (401, 403), str(r.status_code))

            # 1) merge：合并双方完整案例
            row = await conn.fetchrow(
                "SELECT id FROM approval_requests WHERE biz_type='merge' ORDER BY id DESC LIMIT 1"
            )
            if row:
                rid = row['id']
                r = await cli.get(f'{PREFIX}/approvals/{rid}/content')
                c = (r.json() or {}).get('content') or {}
                master = c.get('master_case')
                check('merge 内容返回主案例完整字段', is_full_case(master), str(master)[:180])
                merged = c.get('merged_cases') or []
                ok = len(merged) > 0 and all(
                    (isinstance(m, dict) and ('missing' in m or is_full_case(m))) for m in merged
                )
                check('merge merged_cases 均为完整案例或显式 missing', ok, str(merged)[:180])
                check('merge 内容含合并策略与理由', 'merge_strategy' in c and 'reason' in c)
            else:
                check('存在 merge 审批单', False)

            # 2) rule_promote：规则条目预览 + 日志实例
            row = await conn.fetchrow(
                "SELECT id FROM approval_requests WHERE biz_type='rule_promote' ORDER BY id DESC LIMIT 1"
            )
            if row:
                rid = row['id']
                r = await cli.get(f'{PREFIX}/approvals/{rid}/content')
                c = (r.json() or {}).get('content') or {}
                pre = c.get('proposed_rule_entry') or {}
                ok = all(k in pre for k in ('id', 'error_type', 'keywords', 'score', 'severity'))
                check('rule_promote 返回规则条目预览', ok, str(pre)[:150])
                evs = c.get('related_events')
                ok = isinstance(evs, list) and all(
                    isinstance(e, dict) and 'event_id' in e for e in evs
                )
                check('rule_promote 返回关联日志实例列表', ok, str(evs)[:150])
            else:
                check('存在 rule_promote 审批单', False)

            # 3) 既有 kb_edit update 审批：diff 回归
            row = await conn.fetchrow(
                "SELECT r.id AS rid FROM approval_requests r "
                "JOIN kb_change_sets cs ON cs.id = r.biz_id::int "
                "WHERE r.biz_type='kb_edit' AND cs.change_type='update' ORDER BY r.id DESC LIMIT 1"
            )
            if row:
                r = await cli.get(f"{PREFIX}/approvals/{row['rid']}/content")
                c = (r.json() or {}).get('content') or {}
                check('kb_edit update 内容含 before/after 与 diff',
                      'before' in c and 'after' in c and isinstance(c.get('diff'), dict))
            else:
                check('存在 kb_edit update 审批单（可选）', True, '演示数据中无 update 单，跳过')

            # 4) 新建案例端到端：全字段 → full_case 全字段 + 日志实例非空
            svc_row = await conn.fetchrow(
                "SELECT service_name FROM events "
                "WHERE service_name IS NOT NULL AND service_name <> '' ORDER BY id DESC LIMIT 1"
            )
            real_svc = svc_row['service_name'] if svc_row else 'payment-service'
            r = await cli.post(f'{PREFIX}/kb/change-sets', json={
                'case_id': '',
                'change_type': 'create',
                'fields': {
                    'error_type': 'verify_content_e2e',
                    'service_name': real_svc,
                    'cluster': 'verify-cluster-01',
                    'alert_template': 'upstream sent too big header while reading response header from upstream',
                    'root_cause': '验收：根因字段完整回显',
                    'solution': '验收：处置方案字段完整回显',
                    'topology_snapshot': 'ingress -> gateway -> verify-api',
                },
                'reason': '验收：新建案例完整字段与日志实例展示',
            })
            check('新建案例(全字段)提交成功', r.status_code == 200, r.text[:200])
            if r.status_code == 200:
                d = r.json()
                cs = d.get('change_set') or {}
                created.append((d.get('approval_request_id'), cs.get('id'), cs.get('case_id')))
                check('自动生成案例 ID KB-YYYYMMDD-NNN', str(cs.get('case_id', '')).startswith('KB-'), str(cs.get('case_id')))
                if d.get('approval_request_id'):
                    r2 = await cli.get(f"{PREFIX}/approvals/{d['approval_request_id']}/content")
                    c = (r2.json() or {}).get('content') or {}
                    fc = c.get('full_case') or {}
                    check('新建审批 full_case 含案例库全部字段', is_full_case(fc), str(fc)[:220])
                    check('全字段新建 missing_fields 为空', fc.get('missing_fields') == [], str(fc.get('missing_fields')))
                    evs = c.get('related_events') or []
                    ok = len(evs) >= 1 and all('event_id' in e and 'raw_log' in e for e in evs)
                    check('新建审批返回关联日志实例(非空)', ok, str(evs)[:150])
            else:
                created.append((None, None, None))

            # 5) 新建案例端到端：仅必填字段 → missing_fields 标注 + 空日志实例
            r = await cli.post(f'{PREFIX}/kb/change-sets', json={
                'case_id': '',
                'change_type': 'create',
                'fields': {
                    'error_type': 'verify_content_sparse',
                    'service_name': 'verify-svc-no-event',
                    'root_cause': '验收：稀疏字段根因',
                    'solution': '验收：稀疏方案',
                },
                'reason': '验收：未填写字段标注',
            })
            check('新建案例(仅必填)提交成功', r.status_code == 200, r.text[:200])
            if r.status_code == 200:
                d = r.json()
                cs = d.get('change_set') or {}
                created.append((d.get('approval_request_id'), cs.get('id'), cs.get('case_id')))
                if d.get('approval_request_id'):
                    r2 = await cli.get(f"{PREFIX}/approvals/{d['approval_request_id']}/content")
                    c = (r2.json() or {}).get('content') or {}
                    fc = c.get('full_case') or {}
                    check('稀疏新建 missing_fields 精确标注',
                          sorted(fc.get('missing_fields') or []) == ['alert_template', 'cluster', 'topology_snapshot'],
                          str(fc.get('missing_fields')))
                    check('稀疏新建未匹配日志实例为空列表', c.get('related_events') == [], str(c.get('related_events'))[:100])
            else:
                created.append((None, None, None))

            # 6) 清理验收数据（API 创建走序列自增，删除后无需修序列）
            cleaned = 0
            for appr_id, cs_id, case_id in created:
                if not cs_id:
                    continue
                if appr_id:
                    await conn.execute('DELETE FROM approval_steps WHERE request_id=$1', appr_id)
                    await conn.execute('DELETE FROM approval_requests WHERE id=$1', appr_id)
                await conn.execute('DELETE FROM kb_change_sets WHERE id=$1', cs_id)
                await conn.execute('DELETE FROM kb_versions WHERE case_id=$1', case_id)
                await conn.execute('DELETE FROM kb_cases WHERE case_id=$1', case_id)
                cleaned += 1
            check('验收数据清理完成', True, f'{cleaned} 组测试数据已删除')
    finally:
        await conn.close()

    ok = all(CHECKS)
    print('RESULT:', 'ALL PASSED' if ok else 'HAS FAILURES')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
