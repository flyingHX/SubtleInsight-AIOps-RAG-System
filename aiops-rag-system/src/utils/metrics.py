"""Prometheus 指标埋点。"""
from prometheus_client import Counter, Histogram, Gauge

# 标准化引擎指标
standardization_total = Counter(
    "standardization_total", "Total standardization requests", ["source", "error_type"]
)
standardization_latency = Histogram(
    "standardization_latency_seconds",
    "Standardization latency",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1],
)
unknown_rate = Gauge("standardization_unknown_rate", "Rate of unclassified logs")

# RAG 检索指标
rag_search_total = Counter(
    "rag_search_total", "Total RAG search requests", ["status"]
)
rag_latency = Histogram(
    "rag_latency_seconds", "RAG pipeline latency",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0],
)

# 去重指标
dedup_reduction_rate = Gauge("dedup_reduction_rate", "Alert reduction rate by dedup")
