"""Object storage helpers shared by asset uploads and page datasets.

Reads R2 credentials lazily so importing the module never fails in tests or in
environments where R2 is not configured yet.
"""

from __future__ import annotations

import os
from typing import Optional

import boto3
from botocore.config import Config


class StorageNotConfiguredError(RuntimeError):
    pass


class StorageObjectNotFoundError(LookupError):
    pass


_client = None


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise StorageNotConfiguredError(f"Missing environment variable: {name}")
    return value


def bucket_name() -> str:
    return _require_env("R2_BUCKET_NAME")


def public_base_url() -> str:
    return _require_env("R2_PUBLIC_URL").rstrip("/")


def get_client():
    global _client
    if _client is None:
        account_id = _require_env("R2_ACCOUNT_ID")
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=_require_env("R2_ACCESS_KEY_ID"),
            aws_secret_access_key=_require_env("R2_SECRET_ACCESS_KEY"),
            config=Config(region_name="auto"),
        )
    return _client


def put_object(key: str, body: bytes, content_type: Optional[str] = None) -> None:
    get_client().put_object(
        Bucket=bucket_name(),
        Key=key,
        Body=body,
        ContentType=content_type or "application/octet-stream",
    )


def get_object(key: str) -> bytes:
    try:
        response = get_client().get_object(Bucket=bucket_name(), Key=key)
    except Exception as exc:  # botocore raises ClientError subclasses
        raise StorageObjectNotFoundError(f"Object not found: {key}") from exc
    return response["Body"].read()


def delete_object(key: str) -> None:
    try:
        get_client().delete_object(Bucket=bucket_name(), Key=key)
    except Exception:
        # Deleting storage must never block deleting the database record.
        pass


def public_url(key: str) -> str:
    return f"{public_base_url()}/{key}"
