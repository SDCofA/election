from pathlib import Path

import pytest

from elexion_pipeline import backup
from elexion_pipeline.backup import encryption_args


def test_backup_encryption_contracts():
    assert encryption_args("AES256", None) == {"ServerSideEncryption": "AES256"}
    assert encryption_args("aws:kms", "key-1") == {
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": "key-1",
    }
    with pytest.raises(ValueError, match="required"):
        encryption_args("aws:kms", None)
    with pytest.raises(ValueError, match="AES256 or aws:kms"):
        encryption_args("none", None)


def test_backup_upload_is_encrypted_and_verified(monkeypatch):
    uploaded: dict = {}

    class FakeS3:
        def upload_file(self, path, bucket, key, ExtraArgs):
            uploaded.update(path=path, bucket=bucket, key=key, extra=ExtraArgs)

        def head_object(self, Bucket, Key):
            assert (Bucket, Key) == (uploaded["bucket"], uploaded["key"])
            return {
                "ContentLength": Path(uploaded["path"]).stat().st_size,
                "Metadata": uploaded["extra"]["Metadata"],
            }

    def fake_dump(command, **kwargs):
        assert "--dbname" not in command
        assert kwargs["env"]["PGDATABASE"] == "postgresql://db/elexion"
        Path(command[-1]).write_bytes(b"verified-pg-dump")

    monkeypatch.setenv("DATABASE_URL", "postgresql://db/elexion")
    monkeypatch.setenv("ELEXION_S3_BUCKET", "backups")
    monkeypatch.setattr(backup.subprocess, "run", fake_dump)
    monkeypatch.setattr(backup.boto3, "client", lambda *args, **kwargs: FakeS3())
    result = backup.backup_database()
    assert result["size"] == len(b"verified-pg-dump")
    assert uploaded["extra"]["ServerSideEncryption"] == "AES256"
    assert uploaded["extra"]["Metadata"]["sha256"] == result["sha256"]
