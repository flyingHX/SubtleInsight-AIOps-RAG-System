# -*- coding: utf-8 -*-
"""新一轮优化回归验收脚本：
1. 案例列表返回 related_event_count，且 >0 的案例确有关联日志；
2. 案例详情 related_events 完整（event_id/severity/raw_log）；
3. 新建案例日志预览 API：模板精确匹配、服务名兜底、无匹配返回空列表；
4. Agent 会话 session_type 过滤正常（diagnose/kb_governance/oncall）；
5. 值班历史报告返回完整结构（affected_systems/report/chatops_text）；
6. 认证边界：未认证访问返回 401。
"""
import asyncio
import json
import sys

import httpx

BASE = "http://localhost:8000"
FRONT_ORIGIN = "http://localhost:3000"

results: list[tuple[bool, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, f"{name}{(' | ' + detail) if detail else ''}"))


async def demo_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(f"{BASE}/api/v1/auth/demo-login", json={"email": "demo-admin@atoms.dev"})
    resp.raise_for_status()
    return resp.json()["token"]


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        token = await demo_token(c)
        headers = {"Authorization": f"Bearer {token}"}

        # ---- 6. 认证边界 ----
        async with httpx.AsyncClient(timeout=30) as anon:
            r = await anon.get(f"{BASE}/api/v1/console/kb/cases")
            check(r.status_code == 401, "未认证访问案例列表返回 401", f"status={r.status_code}")

        # ---- 1. 案例列表 related_event_count ----
        r = await c.get(f"{BASE}/api/v1/console/kb/cases?skip=0&limit=50", headers=headers)
        check(r.status_code == 200, "案例列表 200", f"status={r.status_code}")
        cases = r.json()["items"]
        with_count = [x for x in cases if x.get("related_event_count", 0) > 0]
        check(len(cases) > 0, "案例列表非空", f"count={len(cases)}")
        check(len(with_count) > 0, "存在关联日志数 > 0 的案例", f"with_count={len(with_count)}")

        # ---- 2. 案例详情 related_events ----
        target = with_count[0] if with_count else cases[0]
        cid = target["case_id"]
        r = await c.get(f"{BASE}/api/v1/console/kb/cases/{cid}", headers=headers)
        check(r.status_code == 200, f"案例详情 200（{cid}）", f"status={r.status_code}")
        detail = r.json()
        evs = detail.get("related_events") or []
        if (target.get("related_event_count") or 0) > 0:
            check(len(evs) > 0, f"详情关联实例日志非空（{len(evs)} 条）")
            ev0 = evs[0]
            check(
                all(k in ev0 for k in ("event_id", "service_name", "severity", "raw_log", "created_at")),
                "实例日志字段完整",
                f"keys={sorted(ev0.keys())}",
            )
        else:
            check(isinstance(evs, list), "无关联日志案例返回空列表")

        # ---- 3. 新建案例日志预览 ----
        # 3a 服务名兜底：取案例列表里的一个真实服务名
        svc = target["service_name"]
        r = await c.get(
            f"{BASE}/api/v1/console/kb/related-events?service={httpx.QueryParams({'service': svc})['service']}",
            headers=headers,
        )
        check(r.status_code == 200, "预览 API（服务名）200", f"status={r.status_code}")
        items = r.json().get("items", [])
        check(isinstance(items, list), "预览返回列表结构", f"count={len(items)}")

        # 3b 无匹配返回空列表
        r = await c.get(
            f"{BASE}/api/v1/console/kb/related-events?template=NO_SUCH_TEMPLATE_XYZ%123&service=no-such-service-xyz",
            headers=headers,
        )
        check(r.status_code == 200, "预览 API（无匹配）200", f"status={r.status_code}")
        check(r.json().get("items") == [], "无匹配返回空列表")

        # 3c 模板精确匹配：用目标案例的告警模板
        tpl = target.get("alert_template")
        if tpl:
            r = await c.get(
                f"{BASE}/api/v1/console/kb/related-events?template={httpx.QueryParams({'template': tpl})['template']}",
                headers=headers,
            )
            items_tpl = r.json().get("items", [])
            check(
                r.status_code == 200 and all(x.get("template") == tpl for x in items_tpl),
                "模板精确匹配（返回日志模板与查询一致）",
                f"count={len(items_tpl)}",
            )

        # ---- 4. Agent 会话过滤 ----
        for stype in ("diagnose", "kb_governance", "oncall"):
            r = await c.get(f"{BASE}/api/v1/console/agent/sessions?session_type={stype}&limit=5", headers=headers)
            rows = r.json().get("items", []) if r.status_code == 200 else []
            check(
                r.status_code == 200 and all(x["session_type"] == stype for x in rows),
                f"会话过滤 session_type={stype}",
                f"status={r.status_code} count={len(rows)}",
            )
        # 4b 治理会话 result 含 time_window（默认 24h 已持久化）
        r = await c.get(f"{BASE}/api/v1/console/agent/sessions?session_type=kb_governance&limit=1", headers=headers)
        rows = r.json().get("items", [])
        if rows:
            res = rows[0].get("result") or {}
            check("time_window" in res, "治理会话持久化 time_window", f"time_window={res.get('time_window')}")
            check("clusters" in res, "治理会话 result 含 clusters")
        else:
            check(True, "治理会话为空（跳过 result 校验）")
        # 4c 诊断会话 result 含 conclusion（前端最近结果还原依据）
        r = await c.get(f"{BASE}/api/v1/console/agent/sessions?session_type=diagnose&limit=1", headers=headers)
        drows = r.json().get("items", [])
        if drows:
            res = drows[0].get("result") or {}
            check("conclusion" in res, "诊断会话 result 含 conclusion")
        else:
            check(True, "诊断会话为空（跳过 result 校验）")

        # ---- 5. 值班历史报告完整结构 ----
        r = await c.get(f"{BASE}/api/v1/console/agent/oncall-reports", headers=headers)
        check(r.status_code == 200, "值班报告列表 200", f"status={r.status_code}")
        reports = r.json().get("items", [])
        check(len(reports) > 0, "存在历史值班报告", f"count={len(reports)}")
        if reports:
            rep = reports[0]
            check(
                isinstance(rep.get("affected_systems"), list),
                "报告含 affected_systems 列表",
                f"systems={len(rep.get('affected_systems') or [])}",
            )
            check(rep.get("report") is not None, "报告含结构化 report（展开详情依据）")
            rep_body = rep.get("report") or {}
            check(
                all(k in rep_body for k in ("impact_summary", "priority", "actions", "owners_to_notify", "chatops_text")),
                "report 结构字段完整",
            )
            check(bool(rep.get("chatops_text")), "报告含 chatops_text")
            if rep.get("affected_systems"):
                s0 = rep["affected_systems"][0]
                check(
                    all(k in s0 for k in ("system", "event_count", "max_severity", "owners", "services")),
                    "affected_systems 元素字段完整",
                )

    ok_all = all(ok for ok, _ in results)
    print("\n===== 回归验收结果 =====")
    for ok, name in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"\nRESULT: {'ALL PASSED' if ok_all else 'HAS FAILURES'}")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    asyncio.run(main())
