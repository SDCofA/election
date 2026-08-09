from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

import boto3
from botocore.exceptions import ClientError

from .domain import RawSnapshot, SourceDefinition


class ImmutableObjectStore(Protocol):
    def put_if_absent(self, key: str, content: bytes, metadata: dict[str, str]) -> str: ...

    def read(self, key: str) -> bytes: ...


def _safe_key(key: str) -> PurePosixPath:
    path = PurePosixPath(key)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Object key must be a safe relative path")
    return path


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def put_if_absent(self, key: str, content: bytes, metadata: dict[str, str]) -> str:
        safe = _safe_key(key)
        target = self.root.joinpath(*safe.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as file:
                file.write(content)
        except FileExistsError:
            if target.read_bytes() != content:
                raise ValueError(f"Immutable object collision: {key}") from None

        manifest = target.with_suffix(target.suffix + ".metadata.json")
        encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
        try:
            with manifest.open("xb") as file:
                file.write(encoded)
        except FileExistsError:
            if manifest.read_bytes() != encoded:
                raise ValueError(f"Immutable metadata collision: {key}") from None
        return target.as_uri()

    def read(self, key: str) -> bytes:
        safe = _safe_key(key)
        return self.root.joinpath(*safe.parts).read_bytes()


class S3ObjectStore:
    def __init__(self, client, bucket: str, prefix: str = "") -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _key(self, key: str) -> str:
        safe = _safe_key(key).as_posix()
        return f"{self.prefix}/{safe}" if self.prefix else safe

    def put_if_absent(self, key: str, content: bytes, metadata: dict[str, str]) -> str:
        target = self._key(key)
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=target,
                Body=content,
                Metadata=metadata,
                IfNoneMatch="*",
            )
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status not in {409, 412}:
                raise
            existing = self.client.get_object(Bucket=self.bucket, Key=target)["Body"].read()
            if existing != content:
                raise ValueError(f"Immutable object collision: {key}") from error
        return f"s3://{self.bucket}/{target}"

    def read(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=self._key(key))["Body"].read()


class SnapshotWriter:
    def __init__(self, store: ImmutableObjectStore) -> None:
        self.store = store

    def persist(
        self,
        source: SourceDefinition,
        source_url: str,
        content: bytes,
        content_type: str,
        retrieved_at: datetime | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> RawSnapshot:
        retrieved = retrieved_at or datetime.now(UTC)
        digest = hashlib.sha256(content).hexdigest()
        key = f"raw/{source.id}/{retrieved:%Y/%m/%d}/{digest[:2]}/{digest}.bin"
        metadata = {
            "source-id": source.id,
            "sha256": digest,
            "license-id": source.license_id,
            "license-url": source.license_url,
            "attribution": source.attribution,
            "usage-scope": source.usage_scope,
        }
        uri = self.store.put_if_absent(key, content, metadata)
        return RawSnapshot(
            source_id=source.id,
            source_url=source_url,
            retrieved_at=retrieved,
            sha256=digest,
            byte_count=len(content),
            content_type=content_type,
            object_key=key,
            object_uri=uri,
            etag=etag,
            last_modified=last_modified,
            license_id=source.license_id,
            attribution=source.attribution,
            usage_scope=source.usage_scope,
        )


def object_store_from_env(default_root: Path) -> ImmutableObjectStore:
    bucket = os.getenv("ELEXION_S3_BUCKET")
    if not bucket:
        return LocalObjectStore(default_root)
    client = boto3.client(
        "s3",
        endpoint_url=os.getenv("ELEXION_S3_ENDPOINT"),
        region_name=os.getenv("ELEXION_S3_REGION", "us-east-1"),
    )
    return S3ObjectStore(client, bucket, os.getenv("ELEXION_S3_PREFIX", "elexion"))
