from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import boto3


def encryption_args(algorithm: str, kms_key_id: str | None) -> dict[str, str]:
    if algorithm == "aws:kms":
        if not kms_key_id:
            raise ValueError("ELEXION_BACKUP_KMS_KEY_ID is required for aws:kms")
        return {"ServerSideEncryption": algorithm, "SSEKMSKeyId": kms_key_id}
    if algorithm != "AES256":
        raise ValueError("Backup encryption must be AES256 or aws:kms")
    return {"ServerSideEncryption": algorithm}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_database() -> dict[str, str | int]:
    dsn = os.environ["DATABASE_URL"]
    bucket = os.environ["ELEXION_S3_BUCKET"]
    prefix = os.getenv("ELEXION_BACKUP_PREFIX", "elexion/backups/postgres").strip("/")
    algorithm = os.getenv("ELEXION_BACKUP_ENCRYPTION", "AES256")
    now = datetime.now(UTC)
    key = f"{prefix}/{now:%Y/%m/%d}/elexion-{now:%Y%m%dT%H%M%SZ}.dump"

    with tempfile.TemporaryDirectory(prefix="elexion-backup-") as directory:
        path = Path(directory) / "elexion.dump"
        subprocess.run(
            ["pg_dump", "--format=custom", "--no-password", "--file", path],
            check=True,
            env={**os.environ, "PGDATABASE": dsn},
            timeout=3_600,
        )
        size = path.stat().st_size
        if size == 0:
            raise RuntimeError("pg_dump produced an empty backup")
        digest = _sha256(path)
        client = boto3.client(
            "s3",
            endpoint_url=os.getenv("ELEXION_S3_ENDPOINT"),
            region_name=os.getenv("ELEXION_S3_REGION", "us-east-1"),
        )
        extra = encryption_args(algorithm, os.getenv("ELEXION_BACKUP_KMS_KEY_ID"))
        client.upload_file(
            str(path),
            bucket,
            key,
            ExtraArgs={
                **extra,
                "Metadata": {"sha256": digest, "created-at": now.isoformat()},
            },
        )
        stored = client.head_object(Bucket=bucket, Key=key)
        if stored["ContentLength"] != size:
            raise RuntimeError("Uploaded backup size does not match pg_dump output")
        if stored.get("Metadata", {}).get("sha256") != digest:
            raise RuntimeError("Uploaded backup digest metadata does not match")
    return {"bucket": bucket, "key": key, "sha256": digest, "size": size}


def main() -> None:
    print(json.dumps(backup_database(), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
