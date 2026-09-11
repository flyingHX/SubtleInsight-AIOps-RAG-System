"""人工触发诊断接口：按 event_id 加载事件并执行完整 RAG 检索推理。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..models.event import StandardizedEvent
from ..models.response import DiagnosticResult
from ..runtime import get_pipeline, get_redis
from ..utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class DiagnosticRequest(BaseModel):
    event_id: str


@router.post("/diagnostic", response_model=DiagnosticResult)
async def manual_diagnostic(req: DiagnosticRequest):
    """人工触发根因诊断：等效于消费者 2 的 manual_trigger 路径。"""
    event_dict = get_redis().get_event(req.event_id)
    if not event_dict:
        raise HTTPException(status_code=404, detail="Event not found")

    event = StandardizedEvent(**event_dict)
    result = get_pipeline().search(event)
    result.setdefault("latency_ms", 0)
    return DiagnosticResult(**result)
