"""Content-addressed filesystem blob store (ADR-008). Paths returned are relative and opaque to callers."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from docforge.core.errors import NotFoundError, StorageError


@dataclass(frozen=True)
class BlobRef:
    path: str
    sha256: str
    size: int


class BlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, data: bytes, suffix: str = "") -> BlobRef:
        digest = hashlib.sha256(data).hexdigest()
        suffix = suffix if suffix.startswith(".") or not suffix else f".{suffix}"
        rel = f"{digest[:2]}/{digest[2:4]}/{digest}{suffix.lower()}"
        target = self.root / rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-rename so readers never see a partial file.
            fd, tmp = tempfile.mkstemp(dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, target)
            except Exception as exc:
                Path(tmp).unlink(missing_ok=True)
                raise StorageError(f"failed to write blob {rel}") from exc
        return BlobRef(path=rel, sha256=digest, size=len(data))

    def put_file(self, path: Path) -> BlobRef:
        return self.put_bytes(path.read_bytes(), path.suffix)

    def resolve(self, rel: str) -> Path:
        target = (self.root / rel).resolve()
        if not target.is_relative_to(self.root):
            raise StorageError("blob path escapes store root")
        if not target.is_file():
            raise NotFoundError(f"blob {rel} not found")
        return target

    def read_bytes(self, rel: str) -> bytes:
        return self.resolve(rel).read_bytes()

    def exists(self, rel: str) -> bool:
        try:
            self.resolve(rel)
            return True
        except (NotFoundError, StorageError):
            return False
