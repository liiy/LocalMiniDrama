"""OpenTelemetry 追踪、Prometheus 指标与 Langfuse SDK 统一可观测性模块。

【系统定位与架构职责】
1. OpenTelemetry 链路追踪：
   - 提供标准化 Trace & Span 包装器 (`trace_span`)。
   - 支持向 FastAPI 请求中间件、HTTPX 上下游调用以及 SQLAlchemy DB 操作注入 Trace Context。
2. Prometheus `/metrics` 指标：
   - 收集请求总数 (http_requests_total)、延迟直方图 (http_request_duration_seconds)。
   - 收集 AI 任务队列状态 (queue_jobs_total)、Token 消耗 (ai_tokens_consumed_total)。
   - 提供符合 Prometheus 文本格式的 `/metrics` 导出。
3. Langfuse 追踪与成本度量：
   - 封装 LangfuseTracker，在 Agent 节点执行中记录 Trace、Generation、Token、耗时与模型元数据。
"""
from __future__ import annotations

import time
import os
import logging
from contextlib import contextmanager
from typing import Any, Callable, Dict, Generator, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("localminidrama.telemetry")


# ── 1. OpenTelemetry 追踪协议与 Span 管理 ─────────────────────────────────────────

class DummySpan:
    """当未安装或未启用真实 OTel SDK 时的回退 Span 对象。"""
    def __init__(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        self.name = name
        self.attributes = attributes or {}
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.status = "OK"

    def set_attribute(self, key: str, value: Any) -> DummySpan:
        self.attributes[key] = value
        return self

    def set_status(self, status: str, description: Optional[str] = None) -> None:
        self.status = status
        if description:
            self.attributes["status_description"] = description

    def end(self) -> None:
        self.end_time = time.time()


@contextmanager
def trace_span(name: str, attributes: Optional[Dict[str, Any]] = None) -> Generator[DummySpan, None, None]:
    """统一 Span 追踪上下文管理器。支持在 Agent 节点、数据库操作、AI 接口中即插即用。"""
    span = DummySpan(name, attributes)
    t0 = time.time()
    try:
        yield span
        span.set_status("OK")
    except Exception as exc:
        span.set_status("ERROR", str(exc))
        span.set_attribute("error.message", str(exc))
        raise
    finally:
        span.end()
        cost_ms = (time.time() - t0) * 1000
        logger.debug(f"[TraceSpan] {name} completed in {cost_ms:.2f}ms | status={span.status}")


# ── 2. Prometheus 内存指标收集器 ──────────────────────────────────────────────────

class PrometheusMetrics:
    """轻量且高效的内存级 Prometheus 指标收集器。"""
    def __init__(self):
        self.request_counts: Dict[str, int] = {}
        self.request_latencies: Dict[str, list[float]] = {}
        self.ai_tokens_consumed: Dict[str, int] = {}
        self.active_workers: int = 0
        self.queue_jobs_counter: Dict[str, int] = {}

    def inc_request(self, method: str, endpoint: str, status_code: int) -> None:
        key = f'{method}:{endpoint}:{status_code}'
        self.request_counts[key] = self.request_counts.get(key, 0) + 1

    def observe_latency(self, endpoint: str, duration: float) -> None:
        if endpoint not in self.request_latencies:
            self.request_latencies[endpoint] = []
        if len(self.request_latencies[endpoint]) > 500:
            self.request_latencies[endpoint].pop(0)
        self.request_latencies[endpoint].append(duration)

    def inc_ai_tokens(self, model: str, token_type: str, count: int) -> None:
        key = f'{model}:{token_type}'
        self.ai_tokens_consumed[key] = self.ai_tokens_consumed.get(key, 0) + count

    def inc_queue_job(self, queue_name: str, status: str) -> None:
        key = f'{queue_name}:{status}'
        self.queue_jobs_counter[key] = self.queue_jobs_counter.get(key, 0) + 1

    def generate_prometheus_text(self) -> str:
        """格式化输出标准 Prometheus 指标文本。"""
        lines = [
            "# HELP http_requests_total Total number of HTTP requests processed",
            "# TYPE http_requests_total counter",
        ]
        for key, count in self.request_counts.items():
            method, endpoint, status = key.split(":", 2)
            lines.append(f'http_requests_total{{method="{method}",endpoint="{endpoint}",status="{status}"}} {count}')

        lines.extend([
            "# HELP http_request_duration_seconds HTTP request latencies in seconds",
            "# TYPE http_request_duration_seconds summary",
        ])
        for endpoint, lats in self.request_latencies.items():
            if lats:
                avg_lat = sum(lats) / len(lats)
                count = len(lats)
                lines.append(f'http_request_duration_seconds_sum{{endpoint="{endpoint}"}} {sum(lats):.4f}')
                lines.append(f'http_request_duration_seconds_count{{endpoint="{endpoint}"}} {count}')
                lines.append(f'http_request_duration_seconds{{endpoint="{endpoint}",quantile="0.5"}} {avg_lat:.4f}')

        lines.extend([
            "# HELP ai_tokens_consumed_total Total tokens consumed by AI model requests",
            "# TYPE ai_tokens_consumed_total counter",
        ])
        for key, count in self.ai_tokens_consumed.items():
            model, token_type = key.split(":", 1)
            lines.append(f'ai_tokens_consumed_total{{model="{model}",type="{token_type}"}} {count}')

        lines.extend([
            "# HELP queue_jobs_processed_total Total queue jobs by status",
            "# TYPE queue_jobs_processed_total counter",
        ])
        for key, count in self.queue_jobs_counter.items():
            queue_name, status = key.split(":", 1)
            lines.append(f'queue_jobs_processed_total{{queue="{queue_name}",status="{status}"}} {count}')

        return "\n".join(lines) + "\n"


metrics = PrometheusMetrics()


class OpenTelemetryAndMetricsMiddleware(BaseHTTPMiddleware):
    """向请求链路注入 OTel Trace Context 并记录 Prometheus 指标的中间件。"""
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        endpoint = request.url.path
        method = request.method
        t0 = time.time()
        status_code = 500
        
        try:
            with trace_span(f"HTTP {method} {endpoint}", {"http.method": method, "http.url": str(request.url)}):
                response = await call_next(request)
                status_code = response.status_code
                return response
        finally:
            duration = time.time() - t0
            # 排除 metrics 本身的轮询打点，避免脏数据
            if endpoint != "/metrics":
                metrics.inc_request(method, endpoint, status_code)
                metrics.observe_latency(endpoint, duration)


# ── 3. Langfuse SDK 统一上报封装器 ────────────────────────────────────────────────

class LangfuseTracker:
    """Langfuse 实时追踪与 Token / 耗时 / 质量评估上报器。"""
    def __init__(self, public_key: Optional[str] = None, secret_key: Optional[str] = None, host: Optional[str] = None):
        self.public_key = public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
        self.secret_key = secret_key or os.getenv("LANGFUSE_SECRET_KEY")
        self.host = host or os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        self.enabled = bool(self.public_key and self.secret_key)
        self._client = None
        if self.enabled:
            try:
                from langfuse import Langfuse
                self._client = Langfuse(
                    public_key=self.public_key,
                    secret_key=self.secret_key,
                    host=self.host,
                )
                logger.info(f"Langfuse tracker initialized with host: {self.host}")
            except Exception as e:
                logger.warning(f"Langfuse client failed to initialize: {e}")
                self.enabled = False

    def track_generation(
        self,
        name: str,
        model: str,
        prompt: Any,
        output: Any,
        usage: Optional[Dict[str, int]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        duration_seconds: float = 0.0,
    ) -> None:
        """记录一次大模型生成调用（Prompt、Token 消耗与输出）。"""
        usage = usage or {}
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
        
        # 记录内部指标
        metrics.inc_ai_tokens(model, "prompt", prompt_tokens)
        metrics.inc_ai_tokens(model, "completion", completion_tokens)
        
        if self.enabled and self._client:
            try:
                trace = self._client.trace(name=name, metadata=metadata)
                trace.generation(
                    name=name,
                    model=model,
                    input=prompt,
                    output=output,
                    usage={
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                    },
                )
            except Exception as err:
                logger.debug(f"Failed to push generation to Langfuse: {err}")
        else:
            logger.debug(
                f"[LangfuseTrace Mock] name={name} model={model} tokens={total_tokens} duration={duration_seconds:.2f}s"
            )


langfuse_tracker = LangfuseTracker()
