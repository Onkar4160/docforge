"""Shared contracts. See docs/DATA_MODELS.md."""

from docforge.models.artifact import Artifact, ArtifactVersion
from docforge.models.conversation import Job, Message, Session, Task, UploadedFile
from docforge.models.design import DesignTokens
from docforge.models.edit import IRPatch, PatchOp
from docforge.models.evidence import Claim, EvidenceItem, ResearchDossier, Source
from docforge.models.intent import ChangeRequest, Interpretation, OutputFormat, OutputSpec
from docforge.models.ir import DeckPlan, DocumentPlan, StyleSpec, WorkbookPlan
from docforge.models.quality import CheckResult, Finding, QualityReport
from docforge.models.template import TemplateManifest

__all__ = [
    "Artifact",
    "ArtifactVersion",
    "ChangeRequest",
    "CheckResult",
    "Claim",
    "DeckPlan",
    "DesignTokens",
    "DocumentPlan",
    "EvidenceItem",
    "Finding",
    "IRPatch",
    "Interpretation",
    "Job",
    "Message",
    "OutputFormat",
    "OutputSpec",
    "PatchOp",
    "QualityReport",
    "ResearchDossier",
    "Session",
    "Source",
    "StyleSpec",
    "Task",
    "TemplateManifest",
    "UploadedFile",
    "WorkbookPlan",
]
