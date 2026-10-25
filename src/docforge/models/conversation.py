from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from docforge.models.base import DFModel, utcnow
from docforge.models.intent import ChangeRequest, OutputSpec


class Role(StrEnum):
    user = "user"
    assistant = "assistant"
    system = "system"


class FileRole(StrEnum):
    template = "template"
    source = "source"
    dataset = "dataset"
    unknown = "unknown"


class Session(DFModel):
    id: str
    owner: str
    title: str = "Untitled session"
    created_at: datetime = Field(default_factory=utcnow)
    active_task_id: str | None = None


class Message(DFModel):
    id: str
    session_id: str
    role: Role
    content: str
    artifact_ref: dict | None = None  # deliverable produced by this reply (shown as a download card)
    file_ids: list[str] = Field(default_factory=list)
    interpretation_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class UploadedFile(DFModel):
    id: str
    session_id: str
    filename: str
    media_type: str
    size: int
    sha256: str
    role: FileRole = FileRole.unknown
    blob_path: str
    created_at: datetime = Field(default_factory=utcnow)


class TaskStatus(StrEnum):
    pending = "pending"
    awaiting_clarification = "awaiting_clarification"
    running = "running"
    delivered = "delivered"
    failed = "failed"


class Task(DFModel):
    id: str
    session_id: str
    objective: str
    output_spec: OutputSpec | None = None
    status: TaskStatus = TaskStatus.pending
    artifact_id: str | None = None
    dossier_id: str | None = None
    template_file_id: str | None = None
    source_file_ids: list[str] = Field(default_factory=list)
    pending_change: ChangeRequest | None = None
    pending_confirmation: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class JobKind(StrEnum):
    generate = "generate"
    edit = "edit"
    regenerate = "regenerate"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class Stage(StrEnum):
    interpreted = "interpreted"
    researched = "researched"
    template_analyzed = "template_analyzed"
    planned = "planned"
    written = "written"
    rendered = "rendered"
    validated = "validated"
    delivered = "delivered"


class ProgressEvent(DFModel):
    stage: str
    message: str
    at: datetime = Field(default_factory=utcnow)
    fraction: float | None = None


class Job(DFModel):
    id: str
    task_id: str
    kind: JobKind
    status: JobStatus = JobStatus.queued
    stage: Stage | None = None
    checkpoint: dict = Field(default_factory=dict)
    progress: list[ProgressEvent] = Field(default_factory=list)
    error: dict | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
