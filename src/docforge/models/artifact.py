from __future__ import annotations

from datetime import datetime

from pydantic import Field

from docforge.models.base import DFModel, VersionedDocument, utcnow
from docforge.models.design import DesignTokens
from docforge.models.intent import OutputFormat
from docforge.models.ir import ArtifactIR


class Artifact(DFModel):
    id: str
    task_id: str
    format: OutputFormat
    current_version: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class ArtifactVersion(VersionedDocument):
    artifact_id: str
    version: int = Field(ge=1)
    parent_version: int | None = None
    ir: ArtifactIR
    template_file_id: str | None = None
    design_tokens: DesignTokens = Field(default_factory=DesignTokens)
    blob_path: str | None = None
    preview_paths: list[str] = Field(default_factory=list)  # PNG blobs of the first slides
    change_summary: str = ""
    quality_report_id: str | None = None
    dossier_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def key(self) -> str:
        return version_key(self.artifact_id, self.version)


def version_key(artifact_id: str, version: int) -> str:
    return f"{artifact_id}:v{version}"
