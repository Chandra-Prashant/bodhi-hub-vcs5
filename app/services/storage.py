"""
Document storage — Architecture.md's "S3-compatible object storage".

Uploads and generated reports were landing on the application volume. That is
fine on a laptop and wrong in production for two reasons: the volume is not
replicated, so losing the instance loses every source document behind every
issued report; and it does not survive a container being replaced, which is how
the deployment in DEPLOY.md rolls out a new version.

The backend is chosen by configuration, and `LocalStorage` remains the default
so a developer needs no cloud credentials to run the system.

Keys are opaque and generated here. A user-supplied filename never becomes a
storage key — that is how a path traversal turns into an overwrite of somebody
else's document.
"""

from __future__ import annotations

import contextlib
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import settings


class StorageError(Exception):
    pass


class Storage(ABC):
    """Where uploaded documents and generated reports live."""

    name = "abstract"

    @abstractmethod
    def put(self, key: str, content: bytes) -> str:
        """Store bytes under `key`. Returns a locator to persist on the row."""

    @abstractmethod
    def get(self, locator: str) -> bytes:
        ...

    @abstractmethod
    def exists(self, locator: str) -> bool:
        ...

    @abstractmethod
    def delete(self, locator: str) -> bool:
        """Remove an object. Returns False if it was already gone.

        Absence is not an error: a delete that has to succeed twice is a delete
        that cannot be retried after a partial failure.
        """

    def new_key(self, organization: str, filename: str) -> str:
        """A collision-proof key that reveals nothing and traverses nowhere.

        The original filename is kept on the database row for display. It is
        deliberately not part of the key: a name arriving from a browser can
        contain path separators, and a key built from one can be made to point
        at another organization's object.
        """
        safe_org = "".join(c for c in organization if c.isalnum() or c in "-_")[:60]
        suffix = Path(filename).suffix.lower()[:12]
        return f"{safe_org or 'org'}/{uuid.uuid4()}{suffix}"


class LocalStorage(Storage):
    """Filesystem storage. The default, and correct for development."""

    name = "local"

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or settings.UPLOAD_DIR)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, locator: str) -> Path:
        path = (self.root / locator).resolve()
        # Defence in depth. Keys are generated, not user-supplied, but a future
        # caller passing one through would otherwise be able to escape the root.
        if not str(path).startswith(str(self.root.resolve())):
            raise StorageError(f"Refusing to access {locator!r} outside the "
                               f"storage root.")
        return path

    def put(self, key: str, content: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return key

    def get(self, locator: str) -> bytes:
        path = self._path(locator)
        if not path.is_file():
            raise StorageError(f"No stored object for {locator!r}.")
        return path.read_bytes()

    def exists(self, locator: str) -> bool:
        try:
            return self._path(locator).is_file()
        except StorageError:
            return False

    def delete(self, locator: str) -> bool:
        try:
            path = self._path(locator)
        except StorageError:
            return False
        if not path.is_file():
            return False
        path.unlink()
        # Remove the per-object directory if it is now empty, so the volume
        # does not accumulate empty folders over a long deployment.
        with contextlib.suppress(OSError):
            path.parent.rmdir()
        return True


class S3Storage(Storage):
    """S3-compatible object storage — AWS, MinIO, Cloudflare R2, Backblaze.

    boto3 is imported lazily so it is not a hard dependency of the whole
    application; a deployment using local storage never needs it installed.
    """

    name = "s3"

    def __init__(
        self,
        bucket: str | None = None,
        endpoint_url: str | None = None,
        region: str | None = None,
    ) -> None:
        self.bucket = bucket or settings.S3_BUCKET
        if not self.bucket:
            raise StorageError(
                "S3 storage selected but S3_BUCKET is not set.")
        self.endpoint_url = endpoint_url or (settings.S3_ENDPOINT_URL or None)
        self.region = region or (settings.S3_REGION or None)
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:  # noqa: BLE001
                raise StorageError(
                    "S3 storage selected but boto3 is not installed. "
                    "pip install boto3") from exc
            self._client = boto3.client(
                "s3", endpoint_url=self.endpoint_url, region_name=self.region)
        return self._client

    def put(self, key: str, content: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content)
        return key

    def get(self, locator: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=locator)
        except Exception as exc:  # noqa: BLE001 — botocore raises many shapes
            raise StorageError(f"Could not read {locator!r}: {exc}") from exc
        return response["Body"].read()

    def exists(self, locator: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=locator)
            return True
        except Exception:  # noqa: BLE001
            return False

    def delete(self, locator: str) -> bool:
        if not self.exists(locator):
            return False
        self.client.delete_object(Bucket=self.bucket, Key=locator)
        return True


_backend: Storage | None = None


def get_storage() -> Storage:
    """The configured backend, built once."""
    global _backend
    if _backend is None:
        choice = (settings.STORAGE_BACKEND or "local").strip().lower()
        if choice == "s3":
            _backend = S3Storage()
        elif choice == "local":
            _backend = LocalStorage()
        else:
            raise StorageError(
                f"Unknown STORAGE_BACKEND {choice!r}. Use 'local' or 's3'.")
    return _backend


def set_storage(backend: Storage | None) -> None:
    """Override the backend. For tests and for a caller wiring its own."""
    global _backend
    _backend = backend
