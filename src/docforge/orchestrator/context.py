"""Build the conversation context the interpreter sees (Stage 4, FR-CONV-5)."""

from __future__ import annotations

from docforge.agents.interpreter import InterpreterInput
from docforge.models.conversation import Message, Role, Session, TaskStatus
from docforge.models.ir import DeckPlan, DocumentPlan, WorkbookPlan
from docforge.storage import Repositories

MAX_TURNS = 10
MAX_TURN_CHARS = 1500


def artifact_outline(ir) -> list[tuple[str, str]]:
    if isinstance(ir, DeckPlan):
        return [(s.id, f"slide {i} [{s.archetype.value}] {s.headline}") for i, s in enumerate(ir.slides, 1)]
    if isinstance(ir, DocumentPlan):
        return [(s.id, f"{'  ' * (s.level - 1)}section {s.heading}") for s in ir.all_sections()]
    if isinstance(ir, WorkbookPlan):
        return [(s.id, f"sheet '{s.name}' ({s.role.value})") for s in ir.sheets]
    return []


def build_interpreter_input(repos: Repositories, session: Session, message: Message) -> InterpreterInput:
    history = [m for m in repos.messages.list_by_parent(session.id) if m.id != message.id]
    turns = [
        (m.role.value, m.content[:MAX_TURN_CHARS]) for m in history[-MAX_TURNS:] if m.role != Role.system
    ]
    files = [(f.id, f.filename, f.role.value) for f in repos.files.list_by_parent(session.id)]

    active_task = None
    outline: list[tuple[str, str]] = []
    pending: list[str] = []
    task = repos.tasks.get(session.active_task_id) if session.active_task_id else None
    if task is not None:
        fmt = task.output_spec.format.value if task.output_spec else "unknown"
        active_task = f"Objective: {task.objective}\nFormat: {fmt}\nStatus: {task.status.value}"
        if task.artifact_id:
            artifact = repos.artifacts.get(task.artifact_id)
            if artifact and artifact.current_version:
                version = repos.artifact_versions.get(f"{artifact.id}:v{artifact.current_version}")
                if version:
                    outline = artifact_outline(version.ir)
        if task.status == TaskStatus.awaiting_clarification:
            last_assistant = next((m for m in reversed(history) if m.role == Role.assistant), None)
            if last_assistant:
                pending = [last_assistant.content]
    return InterpreterInput(
        message=message.content,
        recent_turns=turns,
        files=files,
        active_task=active_task,
        artifact_outline=outline,
        pending_questions=pending,
    )
