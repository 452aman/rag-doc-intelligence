"""Request IDs, structured JSON logs and a dependency-free /metrics endpoint (Prometheus text format)."""
import json
import logging
import sys
import time
import uuid
from bisect import bisect_left
from collections import defaultdict

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings

BUCKETS = [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30]


class Metrics:
    def __init__(self) -> None:
        self.requests: dict[tuple[str, str, str], int] = defaultdict(int)
        self.hist: dict[str, list[int]] = defaultdict(lambda: [0] * (len(BUCKETS) + 1))
        self.sums: dict[str, float] = defaultdict(float)
        self.counters: dict[str, float] = defaultdict(float)   # app counters, e.g. llm_tokens_total

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        self.requests[(method, route, str(status))] += 1
        self.hist[route][bisect_left(BUCKETS, seconds)] += 1
        self.sums[route] += seconds

    def inc(self, name: str, value: float = 1) -> None:
        self.counters[name] += value

    def render(self) -> str:
        out = ["# TYPE http_requests_total counter"]
        for (m, r, s), n in sorted(self.requests.items()):
            out.append(f'http_requests_total{{method="{m}",route="{r}",status="{s}"}} {n}')
        out.append("# TYPE http_request_duration_seconds histogram")
        for route, counts in sorted(self.hist.items()):
            cum = 0
            for i, b in enumerate(BUCKETS):
                cum += counts[i]
                out.append(f'http_request_duration_seconds_bucket{{route="{route}",le="{b}"}} {cum}')
            cum += counts[-1]
            out.append(f'http_request_duration_seconds_bucket{{route="{route}",le="+Inf"}} {cum}')
            out.append(f'http_request_duration_seconds_sum{{route="{route}"}} {self.sums[route]:.4f}')
            out.append(f'http_request_duration_seconds_count{{route="{route}"}} {cum}')
        for name, v in sorted(self.counters.items()):
            out.append(f"# TYPE {name} counter\n{name} {v}")
        return "\n".join(out) + "\n"


metrics = Metrics()
log = logging.getLogger("app.access")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        base.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        return json.dumps(base)


def setup_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_app_configured", False):
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter() if get_settings().log_json else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.handlers = [h]
    root.setLevel(logging.INFO)
    root._app_configured = True  # type: ignore[attr-defined]


class RequestContext(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        t0 = time.perf_counter()
        status = 500
        try:
            response: Response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
        finally:
            dt = time.perf_counter() - t0
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)   # templated path keeps metric cardinality bounded
            if path not in ("/metrics", "/health", "/ready"):
                metrics.observe(request.method, path, status, dt)
                log.info("request", extra={"extra_fields": {"request_id": rid, "method": request.method, "path": request.url.path, "status": status, "ms": round(dt * 1000, 1)}})


def install(app: FastAPI) -> None:
    setup_logging()
    app.add_middleware(RequestContext)

    @app.get("/metrics", include_in_schema=False)
    def metrics_endpoint():
        return Response(metrics.render(), media_type="text/plain; version=0.0.4")
