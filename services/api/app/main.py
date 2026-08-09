from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime
from threading import Lock
from typing import Annotated

import nats
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from nats.aio.client import Client as NATS
from opentelemetry import trace
from redis.asyncio import Redis
from redis.exceptions import RedisError

from .events import event_hub
from .model_inputs import ModelEvidenceStoreUnavailable
from .models import (
    CatalogStatus,
    CoalitionReport,
    DriverReport,
    Election,
    ElectionDetail,
    ElectionMechanics,
    ForecastSnapshot,
    Health,
    Jurisdiction,
    MapLayer,
    ModelComparison,
    OfficialResults,
    SimulationSummary,
    SourceLedger,
)
from .operational_metrics import operational_metric_lines
from .repository import CatalogRepository, get_repository
from .telemetry import configure_telemetry

Repo = Annotated[CatalogRepository, Depends(get_repository)]
RATE_LIMIT = int(os.getenv("ELEXION_RATE_LIMIT_PER_MINUTE", "120"))
REDIS_URL = os.getenv("REDIS_URL")
NATS_URL = os.getenv("NATS_URL")
INTERNAL_TOKEN = os.getenv("ELEXION_INTERNAL_TOKEN")
_redis = Redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None
_rate_hits: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = Lock()
_metrics_lock = Lock()
_request_counts: dict[tuple[str, str, int], int] = defaultdict(int)
_request_duration: dict[tuple[str, str], tuple[float, int]] = defaultdict(lambda: (0.0, 0))
_request_duration_buckets = (0.025, 0.05, 0.1, 0.3, 0.5, 1.0, 2.5, 5.0)
_request_bucket_counts: dict[tuple[str, str, float], int] = defaultdict(int)
_nats_status = "disabled" if NATS_URL is None else "connecting"
_invalid_live_events = 0
_request_logger = logging.getLogger("elexion.http")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _nats_status
    await asyncio.to_thread(get_repository)
    connection: NATS | None = None
    if NATS_URL:
        try:
            connection = await nats.connect(
                servers=[NATS_URL],
                connect_timeout=2,
                max_reconnect_attempts=-1,
                reconnect_time_wait=2,
            )

            async def receive(message) -> None:
                global _invalid_live_events
                try:
                    event_hub.publish(json.loads(message.data.decode("utf-8")))
                except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                    with _metrics_lock:
                        _invalid_live_events += 1

            await connection.subscribe("elexion.events.>", cb=receive)
            _nats_status = "connected"
        except (nats.errors.Error, OSError, TimeoutError):
            _nats_status = "unavailable"
    try:
        yield
    finally:
        if connection is not None:
            with suppress(nats.errors.Error, OSError, TimeoutError):
                await connection.drain()
        _nats_status = "stopped" if NATS_URL else "disabled"


async def _consume_rate_limit(client: str) -> tuple[int, str, bool]:
    if _redis is not None:
        key = f"elexion:rate:{client}:{int(time.time() // 60)}"
        try:
            async with _redis.pipeline(transaction=True) as pipeline:
                pipeline.incr(key)
                pipeline.expire(key, 61)
                count, _ = await pipeline.execute()
            numeric_count = int(count)
            return max(0, RATE_LIMIT - numeric_count), "redis", numeric_count <= RATE_LIMIT
        except RedisError:
            pass
    now = time.monotonic()
    with _rate_lock:
        hits = _rate_hits[client]
        while hits and hits[0] <= now - 60:
            hits.popleft()
        if len(hits) >= RATE_LIMIT:
            return 0, "local-fallback", False
        hits.append(now)
        return max(0, RATE_LIMIT - len(hits)), "local-fallback", True


app = FastAPI(
    title="Elexion Global API",
    version="0.2.0",
    description="Versioned election catalog and probabilistic forecast interface.",
    openapi_url="/v1/openapi.json",
    docs_url="/docs",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)
_telemetry_enabled = configure_telemetry(app)


@app.middleware("http")
async def public_api_controls(request: Request, call_next):
    started = time.perf_counter()
    request_id = str(uuid.uuid4())
    if request.url.path.startswith("/v1/"):
        client = request.client.host if request.client else "unknown"
        remaining, rate_backend, allowed = await _consume_rate_limit(client)
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": "60", "Cache-Control": "no-store"},
            )
        else:
            response = await call_next(request)
    else:
        remaining = RATE_LIMIT
        rate_backend = "not-applicable"
        response = await call_next(request)
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    duration = time.perf_counter() - started
    with _metrics_lock:
        _request_counts[(request.method, route_path, response.status_code)] += 1
        total, count = _request_duration[(request.method, route_path)]
        _request_duration[(request.method, route_path)] = (total + duration, count + 1)
        for boundary in _request_duration_buckets:
            if duration <= boundary:
                _request_bucket_counts[(request.method, route_path, boundary)] += 1
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Backend"] = rate_backend
    response.headers["X-Request-ID"] = request_id
    if request.url.path == "/v1/stream":
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path.startswith("/v1/forecast-snapshots/") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.method == "GET" and request.url.path.startswith("/v1/"):
        response.headers["Cache-Control"] = "public, max-age=60, stale-if-error=300"
    span_context = trace.get_current_span().get_span_context()
    _request_logger.info(
        json.dumps(
            {
                "duration_ms": round(duration * 1_000, 3),
                "event": "http_request",
                "method": request.method,
                "request_id": request_id,
                "route": route_path,
                "status": response.status_code,
                "trace_id": f"{span_context.trace_id:032x}" if span_context.is_valid else None,
            },
            separators=(",", ":"),
        )
    )
    return response


@app.get("/health", response_model=Health, tags=["operations"])
def health(repo: Repo) -> Health:
    degraded = _nats_status == "unavailable" or repo.calendar_store_status == "unavailable"
    return Health(
        status="degraded" if degraded else "ok",
        version=app.version,
        timestamp=datetime.now(UTC),
        dependencies={
            "nats": _nats_status,
            "redis": "configured" if REDIS_URL else "fallback",
            "forecast_store": repo.forecast_store_status,
            "calendar_store": repo.calendar_store_status,
            "telemetry": "configured" if _telemetry_enabled else "disabled",
        },
    )


@app.get("/metrics", response_class=PlainTextResponse, tags=["operations"])
def metrics(repo: Repo) -> str:
    lines = [
        "# HELP elexion_http_requests_total HTTP requests by route and status.",
        "# TYPE elexion_http_requests_total counter",
    ]
    with _metrics_lock:
        for (method, route, status), count in sorted(_request_counts.items()):
            lines.append(
                f'elexion_http_requests_total{{method="{method}",route="{route}",status="{status}"}} {count}'
            )
        lines.extend(
            [
                "# HELP elexion_http_request_duration_seconds Request duration by route.",
                "# TYPE elexion_http_request_duration_seconds histogram",
            ]
        )
        for (method, route), (total, count) in sorted(_request_duration.items()):
            labels = f'method="{method}",route="{route}"'
            for boundary in _request_duration_buckets:
                bucket_count = _request_bucket_counts[(method, route, boundary)]
                lines.append(
                    f'elexion_http_request_duration_seconds_bucket{{{labels},le="{boundary:g}"}} {bucket_count}'
                )
            lines.append(
                f'elexion_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {count}'
            )
            lines.append(f"elexion_http_request_duration_seconds_sum{{{labels}}} {total:.9f}")
            lines.append(f"elexion_http_request_duration_seconds_count{{{labels}}} {count}")
        lines.extend(
            [
                "# HELP elexion_live_events_invalid_total Invalid NATS event envelopes.",
                "# TYPE elexion_live_events_invalid_total counter",
                f"elexion_live_events_invalid_total {_invalid_live_events}",
                "# HELP elexion_live_events_dropped_total SSE events dropped for slow clients.",
                "# TYPE elexion_live_events_dropped_total counter",
                f"elexion_live_events_dropped_total {event_hub.dropped_events}",
            ]
        )
    lines.extend(
        [
            "# HELP elexion_forecast_age_seconds Age of latest valid forecast snapshot.",
            "# TYPE elexion_forecast_age_seconds gauge",
        ]
    )
    now = datetime.now(UTC)
    for election_id, snapshot in sorted(repo.forecasts.items()):
        age = max(0.0, (now - snapshot.published_at).total_seconds())
        lines.append(f'elexion_forecast_age_seconds{{election_id="{election_id}"}} {age:.3f}')
    lines.extend(operational_metric_lines(os.getenv("DATABASE_URL")))
    return "\n".join(lines) + "\n"


@app.get("/v1/jurisdictions", response_model=list[Jurisdiction], tags=["catalog"])
def jurisdictions(repo: Repo) -> list[Jurisdiction]:
    return sorted(repo.jurisdictions.values(), key=lambda item: item.name)


@app.get("/v1/catalog/status", response_model=CatalogStatus, tags=["catalog"])
def catalog_status(repo: Repo) -> CatalogStatus:
    return repo.catalog_status()


@app.get("/v1/elections", response_model=list[Election], tags=["calendar"])
def elections(
    repo: Repo,
    jurisdiction: Annotated[str | None, Query()] = None,
) -> list[Election]:
    repo.refresh_calendars()
    values = repo.elections.values()
    if jurisdiction:
        values = (item for item in values if item.jurisdiction_id == jurisdiction)
    return sorted(
        values,
        key=lambda item: (item.election_date is None, item.election_date or date.max),
    )


@app.get("/v1/elections/{election_id}", response_model=ElectionDetail, tags=["forecast"])
def election_detail(
    election_id: str,
    repo: Repo,
) -> ElectionDetail:
    detail = repo.detail(election_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Election is not available")
    return detail


@app.get(
    "/v1/elections/{election_id}/forecast",
    response_model=ForecastSnapshot,
    tags=["forecast"],
)
def forecast(
    election_id: str,
    repo: Repo,
) -> ForecastSnapshot:
    snapshot = repo.forecasts.get(election_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Forecast is not available")
    return snapshot


def _require_internal_token(provided: str | None) -> None:
    if not INTERNAL_TOKEN:
        raise HTTPException(status_code=503, detail="Internal forecast boundary is disabled")
    if provided is None or not secrets.compare_digest(provided, INTERNAL_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid internal token")


@app.get(
    "/v1/internal/elections/{election_id}/forecast-candidate",
    response_model=ForecastSnapshot,
    tags=["internal"],
    include_in_schema=False,
)
def forecast_candidate(
    election_id: str,
    repo: Repo,
    model_family: str = Query(...),
    internal_token: str | None = Header(None, alias="X-Elexion-Internal-Token"),
) -> ForecastSnapshot:
    _require_internal_token(internal_token)
    try:
        snapshot = repo.candidate(election_id, model_family)
    except ModelEvidenceStoreUnavailable as error:
        raise HTTPException(
            status_code=503, detail="Model evidence store is unavailable"
        ) from error
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Model family or election is not available")
    return snapshot


@app.get(
    "/v1/elections/{election_id}/forecasts",
    response_model=list[ForecastSnapshot],
    tags=["forecast"],
)
def forecast_history(election_id: str, repo: Repo) -> list[ForecastSnapshot]:
    snapshots = repo.forecast_history(election_id)
    if not snapshots:
        raise HTTPException(status_code=404, detail="Forecast is not available")
    return snapshots


@app.get(
    "/v1/forecast-snapshots/{snapshot_id}",
    response_model=ForecastSnapshot,
    tags=["forecast"],
)
def forecast_snapshot(snapshot_id: str, repo: Repo) -> ForecastSnapshot:
    snapshot = repo.snapshots.get(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Forecast snapshot is not available")
    return snapshot


@app.get(
    "/v1/elections/{election_id}/forecast/alternatives/{model_family}",
    response_model=ForecastSnapshot,
    tags=["forecast"],
)
def alternative_forecast(
    election_id: str,
    model_family: str,
    repo: Repo,
) -> ForecastSnapshot:
    snapshot = repo.alternative(election_id, model_family)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Model family or election is not available")
    return snapshot


@app.get(
    "/v1/elections/{election_id}/model-comparison",
    response_model=ModelComparison,
    tags=["backtests"],
)
def model_comparison(
    election_id: str,
    repo: Repo,
) -> ModelComparison:
    comparison = repo.comparison(election_id)
    if comparison is None:
        raise HTTPException(status_code=404, detail="Election is not available")
    return comparison


@app.get(
    "/v1/elections/{election_id}/simulations",
    response_model=SimulationSummary,
    tags=["simulations"],
)
def simulation_summary(election_id: str, repo: Repo) -> SimulationSummary:
    summary = repo.simulation_summary(election_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Simulation is not available")
    return summary


@app.get(
    "/v1/elections/{election_id}/drivers",
    response_model=DriverReport,
    tags=["drivers"],
)
def drivers(election_id: str, repo: Repo) -> DriverReport:
    report = repo.driver_report(election_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Drivers are not available")
    return report


@app.get(
    "/v1/elections/{election_id}/coalitions",
    response_model=CoalitionReport,
    tags=["simulations"],
)
def coalitions(election_id: str, repo: Repo) -> CoalitionReport:
    report = repo.coalition_report(election_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Coalition simulation is not available")
    return report


@app.get(
    "/v1/elections/{election_id}/backtests",
    response_model=ModelComparison,
    tags=["backtests"],
)
def backtests(election_id: str, repo: Repo) -> ModelComparison:
    return model_comparison(election_id, repo)


@app.get(
    "/v1/elections/{election_id}/sources",
    response_model=SourceLedger,
    tags=["sources"],
)
def sources(election_id: str, repo: Repo) -> SourceLedger:
    ledger = repo.source_ledger(election_id)
    if ledger is None:
        raise HTTPException(status_code=404, detail="Source ledger is not available")
    return ledger


@app.get(
    "/v1/elections/{election_id}/map-layers",
    response_model=MapLayer,
    tags=["maps"],
)
def map_layers(election_id: str, repo: Repo) -> MapLayer:
    layer = repo.map_layer(election_id)
    if layer is None:
        raise HTTPException(status_code=404, detail="Map layer is not available")
    return layer


@app.get(
    "/v1/elections/{election_id}/mechanics",
    response_model=ElectionMechanics,
    tags=["calendar"],
)
def mechanics(election_id: str, repo: Repo) -> ElectionMechanics:
    view = repo.mechanics(election_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Election mechanics are not available")
    return view


@app.get(
    "/v1/elections/{election_id}/official-results",
    response_model=OfficialResults,
    tags=["results"],
)
def official_results(election_id: str, repo: Repo) -> OfficialResults:
    results = repo.official_results(election_id)
    if results is None:
        raise HTTPException(status_code=404, detail="Election is not available")
    return results


@app.get("/v1/stream", tags=["live"])
async def stream(request: Request, repo: Repo) -> StreamingResponse:
    async def events():
        snapshots = sorted(repo.forecasts.values(), key=lambda item: item.published_at)
        queue = event_hub.subscribe()
        last_event_id = request.headers.get("last-event-id")
        replay = snapshots
        snapshot_ids = [snapshot.id for snapshot in snapshots]
        if last_event_id in snapshot_ids:
            replay = snapshots[snapshot_ids.index(last_event_id) + 1 :]
        for snapshot in replay:
            payload = {
                "id": snapshot.id,
                "type": "forecast_publication",
                "snapshot_id": snapshot.id,
                "election_id": snapshot.election_id,
                "as_of": snapshot.as_of.isoformat(),
                "published_at": snapshot.published_at.isoformat(),
                "model_version": snapshot.model_version,
                "data_quality": snapshot.data_quality,
                "freshness": snapshot.freshness,
                "provenance": [item.model_dump(mode="json") for item in snapshot.provenance],
            }
            yield f"id: {snapshot.id}\nevent: forecast_publication\ndata: {json.dumps(payload)}\n\n"
        latest = snapshots[-1]
        try:
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20)
                    yield (
                        f"id: {payload['id']}\nevent: {payload['type']}\n"
                        f"data: {json.dumps(payload)}\n\n"
                    )
                except TimeoutError:
                    payload = {
                        "id": f"heartbeat-{int(time.time())}",
                        "type": "heartbeat",
                        "as_of": latest.as_of.isoformat(),
                        "published_at": datetime.now(UTC).isoformat(),
                        "model_version": latest.model_version,
                        "data_quality": latest.data_quality,
                        "freshness": latest.freshness,
                        "provenance": [item.model_dump(mode="json") for item in latest.provenance],
                        "latest": [snapshot.id for snapshot in snapshots],
                    }
                    yield f"event: heartbeat\ndata: {json.dumps(payload)}\n\n"
        finally:
            event_hub.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
