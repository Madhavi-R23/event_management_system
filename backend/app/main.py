import time
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest,
)

# /app/frontend inside the container (mounted from ./frontend)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
INDEX_FILE = FRONTEND_DIR / "index.html"

app = FastAPI(title="AuraEvents - Smart Event Matcher", version="0.1.0")

# ---- Prometheus metrics ----
REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "path"]
)
APP_UP = Gauge("aura_app_up", "1 if the app is running")
APP_UP.set(1)


@app.middleware("http")
async def track_metrics(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    route = request.scope.get("route")           # route template keeps label cardinality low
    path = route.path if route else "unmatched"
    if path != "/metrics":
        REQUEST_COUNT.labels(request.method, path, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
    return response


@app.get("/", include_in_schema=False)
async def index():
    if not INDEX_FILE.exists():
        return JSONResponse({"error": "frontend/index.html not found"}, status_code=503)
    return FileResponse(INDEX_FILE)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "aura-events", "version": app.version}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
