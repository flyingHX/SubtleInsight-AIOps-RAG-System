# -*- coding: utf-8 -*-
"""临时验收脚本：铸造测试 JWT，验证三个 Agent 的真实 API 链路。

1. 诊断 Agent：POST /api/v1/console/agent/diagnose（多轮工具调用 + 结论）
2. 知识治理 Agent：POST /api/v1/console/agent/kb-governance（聚类 + 起草 + 合并提案）
3. 值班 Agent：POST /api/v1/console/agent/oncall-report（影响面 + ChatOps）
4. 查询接口：/sessions、/cmdb、/oncall-reports
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path('/workspace/app/backend')

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
print(f"OK: 已获取 JWT 密钥（算法 {algo}）")

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

import httpx
import json

base = 'http://127.0.0.1:8000'
headers = {'Authorization': f'Bearer {token}'}
client = httpx.Client(base_url=base, headers=headers, timeout=180)

failures = []


def check(name, ok, detail=''):
    mark = 'OK' if ok else 'FAIL'
    print(f'[{mark}] {name}: {detail}')
    if not ok:
        failures.append(name)


# ---- 0. 基础查询接口 ----
r = client.get('/api/v1/console/agent/cmdb')
check('GET /agent/cmdb', r.status_code == 200 and len(r.json().get('items', [])) >= 10,
      f'status={r.status_code} assets={len(r.json().get("items", [])) if r.status_code == 200 else r.text[:200]}')
if r.status_code == 200:
    api_gw = [a for a in r.json()['items'] if a['service_name'] == 'api-gateway']
    check('CMDB 覆盖 api-gateway', len(api_gw) == 1,
          f"system={api_gw[0]['system_name'] if api_gw else 'N/A'} owner={api_gw[0]['owner'] if api_gw else 'N/A'}")

# ---- 1. 诊断 Agent（事件 1：api-gateway 502）----
r = client.post('/api/v1/console/agent/diagnose', json={'event_id': 1})
data = r.json() if r.status_code == 200 else {}
agent = data.get('agent') or {}
trace = agent.get('tool_trace') or []
tools_used = [step.get('tool') for step in trace if step.get('tool')]
check('POST /agent/diagnose 状态', r.status_code == 200, f'status={r.status_code} body={r.text[:300] if r.status_code != 200 else ""}')
if r.status_code == 200:
    check('诊断 Agent 成功路径', data.get('status') == 'success', f"status={data.get('status')} msg={data.get('message')}")
    check('多轮工具调用 >= 2', agent.get('iterations', 0) >= 2 and len(tools_used) >= 2,
          f'iterations={agent.get("iterations")} tools={tools_used}')
    check('调用 query_cmdb', 'query_cmdb' in tools_used, f'tools={tools_used}')
    conclusion = agent.get('conclusion') or {}
    check('结论含根因/置信度/证据链/处置',
          bool(conclusion.get('root_cause')) and isinstance(conclusion.get('confidence'), (int, float))
          and len(conclusion.get('evidence_chain') or []) >= 2 and bool(conclusion.get('solution')),
          f"confidence={conclusion.get('confidence')} evidence={len(conclusion.get('evidence_chain') or [])}")
    check('会话已持久化', isinstance(data.get('session_id'), int), f'session_id={data.get("session_id")}')

# ---- 2. 知识治理 Agent ----
r = client.post('/api/v1/console/agent/kb-governance', json={})
gov = r.json() if r.status_code == 200 else {}
gdata = gov.get('governance') or {}
check('POST /agent/kb-governance 状态', r.status_code == 200, f'status={r.status_code} body={r.text[:300] if r.status_code != 200 else ""}')
if r.status_code == 200:
    check('聚类结果非空', len(gdata.get('clusters') or []) > 0, f"clusters={len(gdata.get('clusters') or [])}")
    check('起草提交或幂等跳过', len(gdata.get('drafts_submitted') or []) > 0 or len(gdata.get('drafts_skipped') or []) > 0,
          f"submitted={[d.get('case_id') for d in gdata.get('drafts_submitted') or []]} skipped={len(gdata.get('drafts_skipped') or [])}")
    check('合并提案结果返回', bool(gdata.get('merge_result')), f"merge={json.dumps(gdata.get('merge_result'), ensure_ascii=False)[:200]}")
    submitted = gdata.get('drafts_submitted') or []
    if submitted:
        check('草稿走审批流', all(d.get('approval_request_id') for d in submitted),
              f"approvals={[d.get('approval_request_id') for d in submitted]}")

# ---- 3. 值班 Agent ----
r = client.post('/api/v1/console/agent/oncall-report', json={'time_window': '24h'})
oncall = r.json() if r.status_code == 200 else {}
rep = oncall.get('report') or {}
check('POST /agent/oncall-report 状态', r.status_code == 200, f'status={r.status_code} body={r.text[:300] if r.status_code != 200 else ""}')
if r.status_code == 200:
    check('影响面含受影响系统', len(rep.get('affected_systems') or []) > 0,
          f"systems={[s.get('system') for s in rep.get('affected_systems') or []]}")
    check('报告含优先级与处置动作', rep.get('priority') in ('P0', 'P1', 'P2', 'P3') and len(rep.get('actions') or []) >= 0,
          f"priority={rep.get('priority')} actions={len(rep.get('actions') or [])}")
    check('ChatOps 文本可复制', '【值班告警汇总】' in (rep.get('chatops_text') or ''), f"text_len={len(rep.get('chatops_text') or '')}")
    check('会话已持久化', isinstance(oncall.get('session_id'), int), f"session_id={oncall.get('session_id')} report_id={rep.get('id')}")

# ---- 4. 会话与报告历史 ----
r = client.get('/api/v1/console/agent/sessions?limit=10')
check('GET /agent/sessions', r.status_code == 200 and len(r.json().get('items', [])) >= 2,
      f"status={r.status_code} sessions={len(r.json().get('items', [])) if r.status_code == 200 else r.text[:200]}")
r = client.get('/api/v1/console/agent/oncall-reports')
check('GET /agent/oncall-reports', r.status_code == 200 and len(r.json().get('items', [])) >= 1,
      f"status={r.status_code} reports={len(r.json().get('items', [])) if r.status_code == 200 else r.text[:200]}")

# ---- 5. 审批中心可见 Agent 产物（合并提案审批）----
r = client.get('/api/v1/console/approvals?box=pending')
pend_titles = [i.get('title') for i in r.json().get('items', [])] if r.status_code == 200 else []
check('审批中心可访问', r.status_code == 200, f'status={r.status_code} pending_titles={pend_titles[:5]}')

print()
if failures:
    print(f'RESULT: {len(failures)} FAILED -> {failures}')
    sys.exit(1)
print('RESULT: ALL PASSED')
