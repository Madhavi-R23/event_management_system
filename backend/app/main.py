import math
import time
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest,
)
from pydantic import BaseModel, Field

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
INDEX_FILE = FRONTEND_DIR / "index.html"

app = FastAPI(title="AuraEvents - Smart Event Matcher", version="0.2.0")

# CORS: lets a locally opened HTML file (origin "null") or another port call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------ metrics
REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "path"]
)
APP_UP = Gauge("aura_app_up", "1 if the app is running")
APP_UP.set(1)

# prometheus_client appends "_total": exposed as total_matches_requested_total
TOTAL_MATCHES_REQUESTED = Counter(
    "total_matches_requested", "Number of /matches requests served", ["interest"]
)
FUZZY_INFERENCE_SECONDS = Histogram(
    "fuzzy_inference_seconds", "Time spent in the fuzzy scoring step"
)


@app.middleware("http")
async def track_metrics(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    route = request.scope.get("route")
    path = route.path if route else "unmatched"
    if path != "/metrics":
        REQUEST_COUNT.labels(request.method, path, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
    return response


# ------------------------------------------------------------------ mock DB
# vibe: 1 mellow .. 3 high energy | time_slot: 1 morning .. 3 evening
# tech_level: 0 (not technical) .. 1 (very technical)
EVENTS = [
    {
        "id": 1, "title": "Pastel Pottery & Herbal Matcha Evening",
        "category": "creative", "vibe": 1, "time_slot": 3,
        "distance_km": 2.4, "tech_level": 0.1,
    },
    {
        "id": 2, "title": "Ambient AI & UI Builders Fireside",
        "category": "tech", "vibe": 2, "time_slot": 3,
        "distance_km": 4.1, "tech_level": 1.0,
    },
    {
        "id": 3, "title": "Botanical Garden Breathwork & Sound Bath",
        "category": "wellness", "vibe": 1, "time_slot": 1,
        "distance_km": 5.8, "tech_level": 0.0,
    },
]

# Same weights the UI shows in "Fuzzy Weights Synced"
W_VIBE, W_TIME, W_GEO = 0.45, 0.35, 0.20

# ------------------------------------------------------------------ fuzzy engine
def similar(a: float, b: float, sigma: float = 1.0) -> float:
    """Membership in the fuzzy set 'a is about the same as b' (Gaussian, 1.0 = identical)."""
    return math.exp(-((a - b) ** 2) / (2 * sigma ** 2))


def near_enough(dist_km: float, max_km: float) -> float:
    """Membership in 'close enough': 1.0 -> 0.7 inside the limit, fades to 0 by 1.5x the limit."""
    r = dist_km / max_km
    if r <= 1.0:
        return 1.0 - 0.3 * r
    if r <= 1.5:
        return 0.7 * (1.5 - r) / 0.5
    return 0.0


def score_event(event: dict, p: "Preferences") -> dict:
    mu_vibe = similar(p.vibe, event["vibe"])
    mu_time = similar(p.timing, event["time_slot"])
    mu_geo = near_enough(event["distance_km"], p.max_distance)

    # interest: soft tag match, optionally blended with the tech-interest slider
    mu_tag = 1.0 if p.interest in ("all", event["category"]) else 0.35
    if p.tech_interest is not None:
        mu_tech = similar(p.tech_interest / 100, event["tech_level"], sigma=0.4)
        mu_interest = 0.5 * mu_tag + 0.5 * mu_tech
    else:
        mu_interest = mu_tag

    base = W_VIBE * mu_vibe + W_TIME * mu_time + W_GEO * mu_geo
    final = base * (0.7 + 0.3 * mu_interest)   # interest modulates, never zeroes, the match
    pct = min(99, round(final * 100))

    label = "Perfect Vibe" if pct >= 90 else "Balanced Fit" if pct >= 75 else "Gentle Fit"
    return {
        **event,
        "score": pct,
        "label": label,
        "breakdown": {
            "vibe": round(mu_vibe, 3), "timing": round(mu_time, 3),
            "distance": round(mu_geo, 3), "interest": round(mu_interest, 3),
        },
    }


# ------------------------------------------------------------------ API
class Preferences(BaseModel):
    vibe: float = Field(1, ge=1, le=3, description="1 mellow .. 3 high energy")
    timing: float = Field(3, ge=1, le=3, description="1 morning .. 3 evening")
    max_distance: float = Field(8, ge=2, le=25, description="km")
    interest: Literal["all", "tech", "casual", "creative", "wellness", "food"] = "all"
    tech_interest: Optional[float] = Field(None, ge=0, le=100)


@app.post("/matches")
async def matches(prefs: Preferences):
    TOTAL_MATCHES_REQUESTED.labels(prefs.interest).inc()
    with FUZZY_INFERENCE_SECONDS.time():
        t0 = time.perf_counter()
        ranked = sorted(
            (score_event(e, prefs) for e in EVENTS), key=lambda e: e["score"], reverse=True
        )
        inference_ms = round((time.perf_counter() - t0) * 1000, 3)
    return {"count": len(ranked), "inference_ms": inference_ms, "matches": ranked}


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
