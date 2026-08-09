from __future__ import annotations

import asyncio
import statistics
import time

import httpx

from app.main import app
from app.repository import get_repository

REQUESTS = 60
P95_TARGET_MS = 300
PATH = "/v1/elections/de-next-bundestag/forecast"


async def main() -> None:
    await asyncio.to_thread(get_repository)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://load.test") as client:
        warm = await client.get(PATH)
        warm.raise_for_status()

        async def request() -> tuple[int, float, str]:
            started = time.perf_counter()
            response = await client.get(PATH)
            duration_ms = (time.perf_counter() - started) * 1_000
            return response.status_code, duration_ms, response.headers.get("cache-control", "")

        results = await asyncio.gather(*(request() for _ in range(REQUESTS)))

    statuses = [status for status, _, _ in results]
    durations = sorted(duration for _, duration, _ in results)
    cache_headers = [header for _, _, header in results]
    p95 = durations[max(0, int(len(durations) * 0.95) - 1)]
    if statuses != [200] * REQUESTS:
        raise SystemExit(f"Load smoke returned non-200 statuses: {statuses}")
    if not all("public" in header and "max-age=60" in header for header in cache_headers):
        raise SystemExit("Forecast responses are not publicly cacheable")
    if p95 >= P95_TARGET_MS:
        raise SystemExit(f"Cached API p95 {p95:.1f}ms exceeds {P95_TARGET_MS}ms")
    print(
        {
            "requests": REQUESTS,
            "median_ms": round(statistics.median(durations), 1),
            "p95_ms": round(p95, 1),
            "target_ms": P95_TARGET_MS,
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
