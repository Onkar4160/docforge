from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from docforge.core.errors import NotFoundError, StorageError
from docforge.models.artifact import Artifact, ArtifactVersion, version_key
from docforge.models.conversation import Job, Message, Session, Task, UploadedFile
from docforge.models.evidence import ResearchDossier
from docforge.models.intent import Interpretation
from docforge.models.llm import LLMCallRecord
from docforge.models.quality import QualityReport
from docforge.models.template import TemplateManifest
from docforge.storage.db import Record

M = TypeVar("M", bound=BaseModel)


class Repository(Generic[M]):
    """Typed CRUD over the ``records`` table for one model kind."""

    def __init__(
        self,
        sessions: sessionmaker,
        kind: str,
        model: type[M],
        *,
        key: Callable[[M], str] = lambda m: m.id,  # type: ignore[attr-defined]
        parent: Callable[[M], str | None] = lambda m: None,
    ) -> None:
        self._sessions = sessions
        self.kind = kind
        self.model = model
        self._key = key
        self._parent = parent

    def put(self, obj: M) -> M:
        data = obj.model_dump(mode="json", by_alias=True)
        try:
            with self._sessions.begin() as s:
                row = s.get(Record, (self.kind, self._key(obj)))
                if row is None:
                    s.add(Record(kind=self.kind, id=self._key(obj), parent_id=self._parent(obj), data=data))
                else:
                    row.data = data
                    row.parent_id = self._parent(obj)
        except Exception as exc:  # pragma: no cover - surfaced as typed error
            raise StorageError(f"failed to save {self.kind} {self._key(obj)}") from exc
        return obj

    def get(self, key: str) -> M | None:
        with self._sessions() as s:
            row = s.get(Record, (self.kind, key))
            return self.model.model_validate(row.data) if row else None

    def require(self, key: str) -> M:
        obj = self.get(key)
        if obj is None:
            raise NotFoundError(f"{self.kind} {key} not found")
        return obj

    def list_by_parent(self, parent_id: str) -> list[M]:
        with self._sessions() as s:
            rows = s.scalars(
                select(Record)
                .where(Record.kind == self.kind, Record.parent_id == parent_id)
                .order_by(Record.created_at, Record.id)
            ).all()
            return [self.model.model_validate(r.data) for r in rows]

    def delete(self, key: str) -> bool:
        with self._sessions.begin() as s:
            row = s.get(Record, (self.kind, key))
            if row is None:
                return False
            s.delete(row)
            return True


class Repositories:
    """All repositories bound to one session factory."""

    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = Repository(sessions, "session", Session, parent=lambda m: m.owner)
        self.messages = Repository(sessions, "message", Message, parent=lambda m: m.session_id)
        self.files = Repository(sessions, "file", UploadedFile, parent=lambda m: m.session_id)
        self.tasks = Repository(sessions, "task", Task, parent=lambda m: m.session_id)
        self.jobs = Repository(sessions, "job", Job, parent=lambda m: m.task_id)
        self.interpretations = Repository(sessions, "interpretation", StoredInterpretation)
        self.artifacts = Repository(sessions, "artifact", Artifact, parent=lambda m: m.task_id)
        self.artifact_versions = Repository(
            sessions,
            "artifact_version",
            ArtifactVersion,
            key=lambda v: version_key(v.artifact_id, v.version),
            parent=lambda v: v.artifact_id,
        )
        self.dossiers = Repository(sessions, "dossier", ResearchDossier, parent=lambda d: d.task_id)
        self.templates = Repository(sessions, "template", TemplateManifest, key=lambda t: t.file_sha256)
        self.quality_reports = Repository(
            sessions, "quality_report", QualityReport, parent=lambda r: r.artifact_id
        )
        self.llm_calls = Repository(sessions, "llm_call", LLMCallRecord, parent=lambda r: r.job_id)

    def add_artifact_version(self, version: ArtifactVersion) -> ArtifactVersion:
        """Append an immutable version and advance the artifact pointer (FR-EDIT-1)."""
        artifact = self.artifacts.require(version.artifact_id)
        if self.artifact_versions.get(version.key) is not None:
            raise StorageError(f"artifact version {version.key} already exists; versions are immutable")
        if version.version != artifact.current_version + 1:
            raise StorageError(
                f"version {version.version} does not follow current version {artifact.current_version}"
            )
        self.artifact_versions.put(version)
        artifact.current_version = version.version
        self.artifacts.put(artifact)
        return version


class StoredInterpretation(BaseModel):
    """Interpretation plus the message it belongs to."""

    id: str
    message_id: str
    interpretation: Interpretation
