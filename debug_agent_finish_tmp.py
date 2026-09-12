# -*- coding: utf-8 -*-
"""临时调试：完整复现诊断 Agent ReAct 循环，打印每一轮与最终 finish 输出。"""
import asyncio
import json

from core.database import db_manager
from models.Events import Events
from schemas.aihub import ChatMessage, GenTxtRequest
from services.aihub import AIHubService
from services.console_agent import (
    DIAGNOSE_AGENT_SYSTEM_PROMPT,
    MAX_ITERATIONS,
    _build_diagnose_tools,
)
from services.console_ai import extract_json_payload
from sqlalchemy import select

aihub = AIHubService()


async def main():
    async with db_manager.session() as db:
        event = (await db.execute(select(Events).where(Events.id == 1))).scalar_one_or_none()
        tools = _build_diagnose_tools(db, event)
        task = (
            f"请诊断告警：event_id={event.event_id}（数据库主键 {event.id}）。\n"
            "建议流程：get_alert_detail →（按需）query_cmdb 确认主机所属系统/服务/负责人与日志路径 → "
            "read_recent_logs / query_rules / search_kb 交叉验证 → finish 输出根因结论。"
        )
        messages = [
            ChatMessage(role="system", content=DIAGNOSE_AGENT_SYSTEM_PROMPT),
            ChatMessage(role="user", content=task),
        ]
        iterations = 0
        while iterations < MAX_ITERATIONS:
            iterations += 1
            resp = await aihub.gentxt(GenTxtRequest(model="deepseek-v4-flash", messages=messages, temperature=0.2, max_tokens=1200))
            print(f"===== ROUND {iterations} RAW =====")
            print(resp.content[:2500])
            payload = extract_json_payload(resp.content)
            if payload is None:
                print(">>> invalid json")
                messages = messages + [ChatMessage(role="user", content="上一轮输出不是合法 JSON，请严格按约定只输出一个 JSON 对象。")]
                continue
            if payload.get("finish"):
                print(">>> FINISH RESULT KEYS:", list(payload.get("result", {}).keys()) if isinstance(payload.get("result"), dict) else type(payload.get("result")))
                print(">>> finish payload:", json.dumps(payload, ensure_ascii=False)[:1500])
                return
            action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
            tool_name = str(action.get("tool") or "")
            args = action.get("args") if isinstance(action.get("args"), dict) else {}
            handler = tools.get(tool_name)
            if handler is None:
                observation = {"error": f"未知工具 {tool_name}", "available": sorted(tools)}
            else:
                observation = await handler(args)
            obs_text = json.dumps(observation, ensure_ascii=False)[:4000]
            print(f">>> tool={tool_name} obs_len={len(obs_text)}")
            messages = messages + [
                ChatMessage(role="assistant", content=json.dumps(payload, ensure_ascii=False)),
                ChatMessage(role="user", content=f"OBSERVATION（工具 {tool_name} 返回）：\n{obs_text}\n\n请继续：若信息足够请输出 finish JSON，否则输出下一轮 action。"),
            ]
        print(">>> hit MAX_ITERATIONS")


asyncio.run(main())
