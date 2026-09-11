"""系统启动入口：FastAPI 应用 + 后台 Kafka 三消费者线程 + Prometheus 指标。"""
import threading

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from src.api import diagnostic, feedback, webhook
from src.config import load_config
from src.kafka_consumers import start_consumers
from src.kafka_producer import KafkaProducerWrapper
from src.rag_pipeline.pipeline import RAGPipeline
from src.runtime import get_engine, get_producer, init_runtime
from src.standardization.engine import StandardizationEngine
from src.storage.redis_client import RedisClient
from src.utils.logger import get_logger, setup_logging

app = FastAPI(title="AIOps RAG Knowledge Base", version="1.0.0")
app.include_router(webhook.router, prefix="/api/v1")
app.include_router(diagnostic.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.mount("/metrics", make_asgi_app())

logger = get_logger(__name__)


@app.on_event("startup")
def startup():
    """初始化标准化引擎、Kafka 生产者、RAG 流水线，并拉起三消费者线程。"""
    setup_logging()
    config = load_config()

    engine = StandardizationEngine(
        config_path=config["rules_path"], drain_config_path=config["drain_path"]
    )
    producer = KafkaProducerWrapper(
        bootstrap_servers=config["kafka"]["bootstrap_servers"],
        topic=config["kafka"]["topic_standardized"],
    )
    pipeline = RAGPipeline(config)
    redis_client = RedisClient(config["redis"]["url"])
    init_runtime(config, engine, producer, pipeline, redis_client)

    threading.Thread(
        target=start_consumers, args=(config, pipeline), daemon=True, name="kafka-consumers"
    ).start()
    logger.info("AIOps RAG system started (port=%s)", config["service_port"])


@app.on_event("shutdown")
def shutdown():
    try:
        get_engine().shutdown()
        get_producer().close()
    except RuntimeError:
        pass
    logger.info("AIOps RAG system stopped")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=load_config().get("service_port", 8080))
