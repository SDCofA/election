from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..domain import FetchResult, SourceDefinition
from ..registry import SourceRegistry
from ..storage import SnapshotWriter


class RetryableFetchError(RuntimeError):
    pass


class SourceResponseError(RuntimeError):
    pass


class HttpSnapshotFetcher:
    def __init__(
        self,
        registry: SourceRegistry,
        writer: SnapshotWriter,
        client: httpx.Client | None = None,
    ) -> None:
        self.registry = registry
        self.writer = writer
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
            headers={"User-Agent": "ElexionGlobal/0.1 (+data provenance)"},
        )

    @staticmethod
    def _url(source: SourceDefinition, endpoint: str) -> str:
        url = endpoint if urlparse(endpoint).scheme else urljoin(source.base_url, endpoint)
        parsed = urlparse(url)
        if parsed.hostname is None or parsed.hostname.lower() not in source.allowed_hosts:
            raise ValueError(f"Host is not allowlisted for {source.id}")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and source.allow_insecure_http
        ):
            raise ValueError(f"Insecure transport rejected for {source.id}")
        if parsed.username or parsed.password:
            raise ValueError("Credentials are not permitted in source URLs")
        return url

    def fetch(
        self,
        source_id: str,
        endpoint: str,
        *,
        params: dict[str, str | int] | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchResult | None:
        source = self.registry.require_approved(source_id)
        url = self._url(source, endpoint)
        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        response: httpx.Response | None = None
        retrying = Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.2, min=0.2, max=2),
            retry=retry_if_exception_type((httpx.TransportError, RetryableFetchError)),
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                response = self.client.get(url, params=params, headers=headers)
                if response.status_code == 304:
                    return None
                if response.status_code == 429 or response.status_code >= 500:
                    raise RetryableFetchError(
                        f"Transient response {response.status_code} from {source.id}"
                    )

        assert response is not None
        if response.is_redirect:
            raise SourceResponseError(f"Redirect rejected from {source.id}")
        if response.status_code >= 400:
            raise SourceResponseError(f"Response {response.status_code} from {source.id}")
        final_host = urlparse(str(response.url)).hostname
        if final_host is None or final_host.lower() not in source.allowed_hosts:
            raise SourceResponseError("Final response host is not allowlisted")

        declared_length = response.headers.get("content-length")
        if declared_length and int(declared_length) > source.max_bytes:
            raise SourceResponseError(f"Payload exceeds {source.max_bytes} bytes")
        content = response.content
        if len(content) > source.max_bytes:
            raise SourceResponseError(f"Payload exceeds {source.max_bytes} bytes")
        content_type = response.headers.get("content-type", "application/octet-stream").split(
            ";", 1
        )[0]
        if content_type not in source.content_types:
            raise SourceResponseError(f"Unexpected content type {content_type} from {source.id}")

        snapshot = self.writer.persist(
            source=source,
            source_url=str(response.url),
            content=content,
            content_type=content_type,
            retrieved_at=datetime.now(UTC),
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
        )
        return FetchResult(snapshot=snapshot, content=content)
