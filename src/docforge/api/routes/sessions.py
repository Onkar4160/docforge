"""Sessions, uploads and messages (FR-CONV-1, FR-CONV-8, FR-UX-2). Every session belongs to a user.

Messages run through the generation pipeline (M1: PPTX without template).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from docforge.api.deps import current_user, get_container
from docforge.container import Container
from docforge.core.errors import FileTooLargeError, NotFoundError, UserInputError
from docforge.core.files import sniff
from docforge.core.ids import new_id
from docforge.models.conversation import FileRole, Message, Role, Session, UploadedFile
from docforge.models.intent import OutputFormat
from docforge.models.quality import QualityReport
from docforge.orchestrator.generate import GenerationService

MEDIA_TYPES = {
    OutputFormat.pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    OutputFormat.docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    OutputFormat.xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

router = APIRouter(tags=["sessions"])


class CreateSession(BaseModel):
    title: str = "Untitled session"


class RenameSession(BaseModel):
    title: str = Field(min_length=1, max_length=120)


# Message jobs live in this process; the reply message itself is persisted, so a restart loses only progress.
_JOBS: dict[str, dict] = {}
_RUNNING: set[asyncio.Task] = set()


class PostMessage(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    file_ids: list[str] = Field(default_factory=list)


def _owned_session(c: Container, session_id: str, user: str) -> Session:
    session = c.repos.sessions.get(session_id)
    # Same response for missing and foreign sessions, so IDs cannot be probed.
    if session is None or session.owner != user:
        raise NotFoundError(f"session {session_id} not found")
    return session


@router.post("/sessions", status_code=201)
def create_session(
    body: CreateSession, c: Container = Depends(get_container), user: str = Depends(current_user)
) -> Session:
    return c.repos.sessions.put(Session(id=new_id("session"), title=body.title, owner=user))


@router.get("/sessions")
def list_sessions(c: Container = Depends(get_container), user: str = Depends(current_user)) -> list[dict]:
    out = []
    for s in reversed(c.repos.sessions.list_by_parent(user)):
        messages = c.repos.messages.list_by_parent(s.id)
        out.append(
            {
                "id": s.id,
                "title": s.title,
                "created_at": s.created_at,
                "updated_at": messages[-1].created_at if messages else s.created_at,
                "messages": len(messages),
            }
        )
    return sorted(out, key=lambda x: x["updated_at"], reverse=True)


@router.patch("/sessions/{session_id}")
def rename_session(
    session_id: str,
    body: RenameSession,
    c: Container = Depends(get_container),
    user: str = Depends(current_user),
) -> Session:
    session = _owned_session(c, session_id, user)
    session.title = body.title.strip()
    return c.repos.sessions.put(session)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str, c: Container = Depends(get_container), user: str = Depends(current_user)
) -> None:
    _owned_session(c, session_id, user)
    c.repos.sessions.delete(session_id)


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str, c: Container = Depends(get_container), user: str = Depends(current_user)
) -> dict:
    session = _owned_session(c, session_id, user)
    return {
        "session": session,
        "messages": c.repos.messages.list_by_parent(session_id),
        "files": c.repos.files.list_by_parent(session_id),
        "tasks": c.repos.tasks.list_by_parent(session_id),
    }


@router.post("/sessions/{session_id}/files", status_code=201)
async def upload_file(
    session_id: str,
    file: UploadFile = File(...),
    role: FileRole = Form(FileRole.unknown),
    c: Container = Depends(get_container),
    user: str = Depends(current_user),
) -> UploadedFile:
    _owned_session(c, session_id, user)
    limit = c.settings.max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise FileTooLargeError(f"file exceeds {c.settings.upload_max_mb} MB")
    filename = file.filename or "upload"
    kind = sniff(filename, data)
    if role == FileRole.template and not kind.is_template_capable:
        raise UserInputError("templates must be PPTX/POTX, DOCX/DOTX or XLSX/XLTX files")
    ref = c.blobs.put_bytes(data, kind.extension)
    record = UploadedFile(
        id=new_id("file"),
        session_id=session_id,
        filename=filename,
        media_type=kind.media_type,
        size=ref.size,
        sha256=ref.sha256,
        role=role,
        blob_path=ref.path,
    )
    return c.repos.files.put(record)


@router.get("/sessions/{session_id}/files/{file_id}")
def download_file(
    session_id: str, file_id: str, c: Container = Depends(get_container), user: str = Depends(current_user)
) -> FileResponse:
    _owned_session(c, session_id, user)
    record = c.repos.files.get(file_id)
    if record is None or record.session_id != session_id:
        raise NotFoundError(f"file {file_id} not found")
    return FileResponse(
        c.blobs.resolve(record.blob_path), media_type=record.media_type, filename=record.filename
    )


@router.post("/sessions/{session_id}/messages")
async def post_message(
    session_id: str,
    body: PostMessage,
    c: Container = Depends(get_container),
    user: str = Depends(current_user),
) -> dict:
    """Store the message and run it through the pipeline, waiting for the reply."""
    session, message = _store_message(c, session_id, body, user)
    reply = await GenerationService(c).handle_message(session, message)
    return _reply_view(c, session_id, message, reply)


@router.post("/sessions/{session_id}/jobs", status_code=202)
async def start_message_job(
    session_id: str,
    body: PostMessage,
    c: Container = Depends(get_container),
    user: str = Depends(current_user),
) -> dict:
    """Store the message and process it in the background; poll ``GET .../jobs/{job_id}`` for progress."""
    session, message = _store_message(c, session_id, body, user)
    job = {
        "id": new_id("job"),
        "session_id": session_id,
        "owner": user,
        "status": "running",
        "steps": [],
        "result": None,
        "started_at": datetime.now(UTC).isoformat(),
    }
    _JOBS[job["id"]] = job

    def progress(stage: str, text: str) -> None:
        job["steps"].append({"stage": stage, "text": text, "at": datetime.now(UTC).isoformat()})

    async def run() -> None:
        try:
            reply = await GenerationService(c).handle_message(session, message, progress=progress)
            job["result"] = _reply_view(c, session_id, message, reply)
            job["status"] = "done"
        except Exception as exc:  # noqa: BLE001 - handle_message already replies; this is a last resort
            job["status"] = "failed"
            job["error"] = f"{exc.__class__.__name__}: {exc}"

    task = asyncio.create_task(run())
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)
    return {"job_id": job["id"], "message": message}


@router.get("/sessions/{session_id}/jobs/{job_id}")
def get_message_job(
    session_id: str, job_id: str, c: Container = Depends(get_container), user: str = Depends(current_user)
) -> dict:
    _owned_session(c, session_id, user)
    job = _JOBS.get(job_id)
    if job is None or job["session_id"] != session_id or job["owner"] != user:
        raise NotFoundError(f"job {job_id} not found")
    return {k: v for k, v in job.items() if k != "owner"}


def _store_message(c: Container, session_id: str, body: PostMessage, user: str) -> tuple[Session, Message]:
    session = _owned_session(c, session_id, user)
    for fid in body.file_ids:
        f = c.repos.files.get(fid)
        if f is None or f.session_id != session_id:
            raise UserInputError(f"unknown file id {fid}")
    if session.title in ("Untitled session", "New chat", ""):
        session.title = body.content.strip().splitlines()[0][:60]
        c.repos.sessions.put(session)
    message = c.repos.messages.put(
        Message(
            id=new_id("message"),
            session_id=session_id,
            role=Role.user,
            content=body.content,
            file_ids=body.file_ids,
        )
    )
    return session, message


def _reply_view(c: Container, session_id: str, message: Message, reply) -> dict:
    artifact = (
        _artifact_view(session_id, reply.artifact, reply.version, reply.report) if reply.artifact else None
    )
    if artifact is not None:
        reply.message.artifact_ref = artifact
        c.repos.messages.put(reply.message)
    return {
        "message": message,
        "reply": reply.message,
        "task": reply.task,
        "artifact": artifact,
        "quality_report": reply.report,
    }


def _artifact_view(session_id: str, artifact, version, report=None) -> dict:
    base = f"/api/sessions/{session_id}/artifacts/{artifact.id}/versions/{version.version}"
    ir = version.ir
    units = getattr(ir, "slides", None) or getattr(ir, "sheets", None)
    if units is None and hasattr(ir, "all_sections"):
        units = ir.all_sections()
    return {
        "id": artifact.id,
        "format": artifact.format,
        "version": version.version,
        "title": getattr(ir, "title", ""),
        "units": len(units or []),
        "download_url": f"{base}/download",
        "quality_report_url": f"{base}/report",
        "preview_urls": [f"{base}/preview/{i}" for i in range(len(version.preview_paths or []))],
        "change_summary": version.change_summary,
        "verdict": report.verdict if report else None,
        "summary": report.summary.model_dump() if report else None,
    }


def _owned_version(c: Container, session_id: str, artifact_id: str, version: int, user: str):
    _owned_session(c, session_id, user)
    artifact = c.repos.artifacts.get(artifact_id)
    task = c.repos.tasks.get(artifact.task_id) if artifact else None
    if artifact is None or task is None or task.session_id != session_id:
        raise NotFoundError(f"artifact {artifact_id} not found")
    found = c.repos.artifact_versions.get(f"{artifact_id}:v{version}")
    if found is None:
        raise NotFoundError(f"version {version} of {artifact_id} not found")
    return artifact, found


@router.get("/sessions/{session_id}/artifacts/{artifact_id}/versions/{version}/download")
def download_artifact(
    session_id: str,
    artifact_id: str,
    version: int,
    c: Container = Depends(get_container),
    user: str = Depends(current_user),
) -> FileResponse:
    artifact, found = _owned_version(c, session_id, artifact_id, version, user)
    title = getattr(found.ir, "title", "deliverable")
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in title).strip()[:80] or "deliverable"
    return FileResponse(
        c.blobs.resolve(found.blob_path),
        media_type=MEDIA_TYPES[artifact.format],
        filename=f"{safe} v{version}.{artifact.format.value}",
    )


@router.get("/sessions/{session_id}/artifacts/{artifact_id}/versions/{version}/report")
def artifact_report(
    session_id: str,
    artifact_id: str,
    version: int,
    c: Container = Depends(get_container),
    user: str = Depends(current_user),
) -> QualityReport:
    _, found = _owned_version(c, session_id, artifact_id, version, user)
    if not found.quality_report_id:
        raise NotFoundError("no quality report for this version")
    return c.repos.quality_reports.require(found.quality_report_id)


@router.get("/sessions/{session_id}/artifacts/{artifact_id}/versions/{version}/preview/{index}")
def artifact_preview(
    session_id: str,
    artifact_id: str,
    version: int,
    index: int,
    c: Container = Depends(get_container),
    user: str = Depends(current_user),
) -> FileResponse:
    _, found = _owned_version(c, session_id, artifact_id, version, user)
    paths = found.preview_paths or []
    if not 0 <= index < len(paths):
        raise NotFoundError("no such preview")
    return FileResponse(c.blobs.resolve(paths[index]), media_type="image/png")
