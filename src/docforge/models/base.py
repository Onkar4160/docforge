from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict


def utcnow() -> datetime:
    return datetime.now(UTC)


class DFModel(BaseModel):
    """Base for every shared contract. ``extra="forbid"`` doubles as ``additionalProperties: false``
    in JSON schemas sent to the model for structured outputs."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class VersionedDocument(DFModel):
    """Persisted JSON documents carry a schema version (DATA_MODELS §11)."""

    schema_version: str = "1.0"
