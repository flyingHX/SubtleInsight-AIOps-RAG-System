"""RAG 检索流水线核心：四步走（向量构建 -> 粗筛 -> ANN 精筛 -> 业务重排）+ LLM 推理。"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Dict, List

from ..models.event import StandardizedEvent
from ..utils.logger import get_logger
from ..utils.metrics import rag_latency, rag_search_total
from .embedder import BGEEmbedder
from .llm_client import LLMClient
from .milvus_client import MilvusClient
from .prompt_builder import build_prompt
from .reranker import Reranker

logger = get_logger(__name__)


class RAGPipeline:
    """完整的 RAG 检索推理引擎，目标检索 P99 < 500ms、LLM P99 < 3s。"""

    def __init__(self, config: dict):
        self.milvus = MilvusClient(config.get("milvus", {}))
        self.embedder = BGEEmbedder(config.get("embedder", {}))
        self.reranker = Reranker()
        self.llm = LLMClient(config.get("llm", {}))
        self.top_k = int(config.get("top_k", 20))
        self.final_k = int(config.get("final_k", 3))
        self.timeout_seconds = float(config.get("llm_timeout", 5.0))
        self.recent_window_days = int(config.get("recent_window_days", 30))
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rag-llm")

    def search(self, event: StandardizedEvent) -> Dict:
        """完整的 RAG 检索流水线入口。"""
        start_time = time.time()
        try:
            # Step 1: 生成查询向量
            query_text = self._build_query_text(event)
            query_vector = self.embedder.embed(query_text)

            # Step 2 + 3: 双路召回（结构化粗筛 + ANN 精筛）
            expr = self._build_filter_expr(event)
            partitions = self.milvus.recent_partitions(3)
            search_results = self.milvus.search(
                query_vector=query_vector,
                expr=expr,
                partition_names=partitions,
                limit=self.top_k,
                output_fields=[
                    "case_id", "root_cause", "solution", "start_time",
                    "topology_snapshot", "feedback_score", "alert_template",
                ],
            )

            if not search_results:
                rag_search_total.labels(status="no_result").inc()
                return self._fallback_no_result(event)

            # Step 4: 业务重排
            reranked = self.reranker.rerank(
                candidates=search_results,
                current_topology=event.topology,
                current_time=event.timestamp,
            )
            top_cases = reranked[: self.final_k]

            # 构建 Few-shot Prompt 并调用 LLM（超时熔断降级）
            prompt = build_prompt(event, top_cases)
            future = self.executor.submit(self.llm.invoke, prompt)
            try:
                llm_result = future.result(timeout=self.timeout_seconds)
                result = self._parse_llm_result(llm_result, top_cases, event)
                rag_search_total.labels(status="llm_ok").inc()
            except FutureTimeoutError:
                future.cancel()
                result = self._fallback_top1(event, top_cases, reason="LLM timeout")
                rag_search_total.labels(status="llm_timeout").inc()

            return result
        except Exception as exc:  # noqa: BLE001
            logger.error("RAG pipeline error for %s: %s", event.event_id, exc)
            rag_search_total.labels(status="error").inc()
            return self._fallback_no_result(event, reason=str(exc))
        finally:
            rag_latency.observe(time.time() - start_time)

    # ---------- 内部步骤 ----------
    @staticmethod
    def _build_query_text(event: StandardizedEvent) -> str:
        return (
            f"【故障类型】: {event.error_type}\n"
            f"【影响服务】: {event.service_name}\n"
            f"【告警特征】: {event.template}\n"
            f"【下游依赖】: {event.topology.get('downstream', [])}"
        )

    def _build_filter_expr(self, event: StandardizedEvent) -> str:
        since = event.timestamp - self.recent_window_days * 24 * 3600 * 1000
        return (
            f'service_name == "{event.service_name}" and '
            f'error_type == "{event.error_type}" and '
            f"start_time > {since}"
        )

    def _parse_llm_result(self, llm_output: str, top_cases: List[Dict], event: StandardizedEvent) -> Dict:
        parsed = self.llm.parse_json(llm_output)
        if parsed is None:
            return self._fallback_top1(event, top_cases, reason="LLM output parse failed")

        actions = parsed.get("suggest_actions") or [top_cases[0].get("solution", "")]
        return {
            "event_id": event.event_id,
            "root_cause": parsed.get("root_cause_service", top_cases[0].get("root_cause", "")),
            "solution": actions[0] if actions else top_cases[0].get("solution", ""),
            "confidence": float(parsed.get("confidence", 0.7)),
            "suggest_actions": list(actions),
            "is_fallback": False,
            "reason": None,
        }

    @staticmethod
    def _fallback_top1(event: StandardizedEvent, top_cases: List[Dict], reason: str) -> Dict:
        top = top_cases[0]
        return {
            "event_id": event.event_id,
            "root_cause": top.get("root_cause", "未知"),
            "solution": top.get("solution", "请人工介入"),
            "confidence": 0.5,
            "suggest_actions": [top.get("solution", "")],
            "is_fallback": True,
            "reason": reason,
        }

    @staticmethod
    def _fallback_no_result(event: StandardizedEvent, reason: str = "No similar cases found") -> Dict:
        return {
            "event_id": event.event_id,
            "root_cause": "未找到相似历史案例，请人工排查",
            "solution": "建议检查服务日志和监控指标",
            "confidence": 0.0,
            "suggest_actions": ["人工介入"],
            "is_fallback": True,
            "reason": reason,
        }

    # ---------- 知识库写入（自进化闭环）----------
    def write_case(
        self,
        event: StandardizedEvent,
        root_cause: str,
        solution: str,
        resolved_by: str = "human",
    ) -> str:
        """告警闭环后写入/覆盖知识案例：按 fingerprint 去重。"""
        from ..models.case import KnowledgeCase

        existing = self.milvus.query_by_fingerprint(event.fingerprint)
        case_id = (
            existing[0]["case_id"]
            if existing
            else f"case_{time.strftime('%Y%m%d_%H%M%S')}"
        )
        embedding = self.embedder.embed(
            f"{event.template} {event.service_name} {event.error_type} {root_cause} {solution}"
        )
        case = KnowledgeCase(
            case_id=case_id,
            fingerprint=event.fingerprint,
            service_name=event.service_name,
            cluster=event.cluster,
            error_type=event.error_type,
            severity=event.severity,
            start_time=event.timestamp,
            root_cause=root_cause[:2048],
            solution=solution[:2048],
            alert_template=event.template[:1024],
            topology_snapshot=json.dumps(event.topology, ensure_ascii=False)[:1024],
            resolved_by=resolved_by,
            embedding=embedding,
            created_at=int(time.time() * 1000),
        )
        ok = self.milvus.upsert_case(case.to_milvus_row())
        logger.info("Write case %s (ok=%s, dedup=%s)", case_id, ok, bool(existing))
        return case_id
