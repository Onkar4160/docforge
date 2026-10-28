"""Message handling and deck generation — the M1 vertical slice of the orchestrator (Stage 11 grows this).

Flow: interpret → (clarify | answer what is not yet supported) → plan → validate plan → design →
render/validate/repair → persist version + report → reply. Every reply states what was and was not done.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from docforge.agents.answer import AnswerAgent
from docforge.agents.deck_planner import DeckPlannerAgent, PlannerInput
from docforge.agents.doc_writer import DocumentInput, write_document
from docforge.agents.editor import (
    SectionEditorAgent,
    SectionEditorInput,
    SectionInsertionAgent,
    SectionInsertionInput,
    SheetEditorAgent,
    SheetEditorInput,
    SlideEditorAgent,
    SlideEditorInput,
    SlideInsertionAgent,
    SlideInsertionInput,
    exact_section_replacement,
    select_section_block,
)
from docforge.agents.interpreter import InterpreterAgent, render_input
from docforge.agents.style_planner import StylePlannerAgent, StylePlannerInput
from docforge.agents.template_analyzer import PROMPT_VERSION, TemplateAnalyzerAgent
from docforge.agents.workbook_planner import WorkbookInput, WorkbookPlannerAgent
from docforge.container import Container
from docforge.core.errors import (
    DocForgeError,
    LLMModelUnavailable,
    LLMOutputInvalid,
    LLMRateLimited,
    LLMRefused,
)
from docforge.core.ids import new_id
from docforge.core.logging import get_logger, log_context
from docforge.design.system import (
    contrast_ratio,
    generated_tokens,
    tokens_from_docx_template,
    tokens_from_template,
)
from docforge.ingest.datasets import Dataset, load_dataset
from docforge.ingest.readers import extract_text
from docforge.media.images import resolve_deck_images, resolve_document_images
from docforge.models.artifact import Artifact, ArtifactVersion
from docforge.models.conversation import FileRole, Message, Role, Session, Task, TaskStatus, UploadedFile
from docforge.models.evidence import ResearchDossier
from docforge.models.intent import (
    ChangeOperation,
    ConfirmationDecision,
    Interpretation,
    OutputFormat,
    RequestKind,
    ResearchDepth,
    ScopeLevel,
    StylePlan,
)
from docforge.models.ir import (
    ArtifactIR,
    DeckPlan,
    DocumentPlan,
    ImageBlock,
    SectionDraft,
    SectionPlan,
    SlidePlan,
    WorkbookPlan,
)
from docforge.models.quality import QualityReport, Severity, Verdict
from docforge.models.template import TemplateManifest
from docforge.orchestrator.context import artifact_outline, build_interpreter_input
from docforge.orchestrator.patch import (
    ScopeViolationError,
    apply_remove_unit,
    apply_restyle,
    apply_section_block_edit,
    apply_section_edit,
    apply_section_insert,
    apply_section_move,
    apply_sheet_edit,
    apply_slide_edit,
    apply_slide_insert,
    apply_slide_move,
)
from docforge.orchestrator.targets import resolve_section_position, resolve_slide_position, resolve_targets
from docforge.render.pptx.preview import render_previews
from docforge.research.pipeline import ResearchService, UserSource, evidence_digest
from docforge.research.search import UnavailableSearchProvider
from docforge.storage.repositories import StoredInterpretation
from docforge.template.docx_analyzer import ANALYZER_VERSION as DOCX_ANALYZER_VERSION
from docforge.template.docx_analyzer import analyze_docx
from docforge.template.external import run_pptx_masters
from docforge.template.pptx_analyzer import ANALYZER_VERSION, analyze_pptx
from docforge.validate.common import CheckRun
from docforge.validate.deck import build_deck
from docforge.validate.document import build_document
from docforge.validate.plan_checks import check_deck_plan
from docforge.validate.workbook import build_workbook, extract_workbook_diagnostics

log = get_logger(__name__)

Progress = Callable[[str, str], None]  # (stage key, human-readable step)

_CHECK_NAMES = {
    "common.convert": "PDF conversion (LibreOffice not installed)",
    "pptx.visual_clipping": "visual clipping (LibreOffice not installed)",
    "docx.visual": "page rendering (LibreOffice not installed)",
    "content.review": "AI content review (coming later)",
}
_FIT_CHECKS = {"pptx.text_overflow", "pptx.font_floor", "pptx.density"}

_LABELS = {
    OutputFormat.pptx: "the presentation",
    OutputFormat.docx: "the Word document",
    OutputFormat.xlsx: "the Excel workbook",
}


def _log_failure(exc: Exception) -> None:
    if isinstance(exc, DocForgeError):
        log.warning("request failed: %s (%s)", exc.message, exc.code)
    else:
        log.error("unexpected failure: %s", "".join(traceback.format_exception(exc)))


def friendly_error(exc: Exception, doing: str) -> str:
    """Plain-language failure message: what happened, whether anything was delivered, what to do next."""
    if isinstance(exc, LLMRateLimited):
        if exc.details.get("quota") or exc.daily:
            reason = (
                "the AI model's usage limit is reached (the Gemini free tier allows only about 20 requests "
                "per model per day, and every configured model is used up)"
            )
            tip = "Please try again later, or enable billing on the Gemini API key to lift the limit."
        else:
            reason = "the AI service is busy (too many requests per minute)"
            tip = "Please try again in a minute."
    elif isinstance(exc, LLMModelUnavailable):
        reason = "the configured AI model is not available to this API key"
        tip = "Set LLM_PRIMARY_MODEL in .env to a current model (for example gemini-3.8-flash)."
    elif isinstance(exc, LLMRefused):
        reason = "the AI provider's safety filter declined this content"
        tip = "Try rephrasing the request."
    elif isinstance(exc, LLMOutputInvalid):
        reason = "the AI model returned an unusable answer"
        tip = "Say “try again”; it usually works on a second attempt."
    elif isinstance(exc, DocForgeError) and "billing" in exc.message.lower():
        reason = "the AI provider requires billing to be enabled for this project"
        tip = (
            "The Gemini API free tier is disabled for this project. Set up billing at "
            "https://aistudio.google.com/billing, use an API key from a personal project with free "
            "tier enabled, or set LLM_PROVIDER=openai_compat in .env."
        )
    elif isinstance(exc, DocForgeError) and "authentication" in exc.message:
        reason = "the AI provider rejected the API key"
        tip = "Check GEMINI_API_KEY in .env and restart the server."
    elif isinstance(exc, DocForgeError):
        reason = exc.message
        tip = "Say “try again” to retry."
    else:
        reason = f"something unexpected went wrong on my side ({exc.__class__.__name__})"
        tip = "Say “try again” to retry; if it keeps failing, the server log has the details."
    return f"I couldn't {doing}: {reason}. Nothing was delivered. {tip}"


@dataclass
class Reply:
    message: Message
    interpretation: Interpretation | None = None
    task: Task | None = None
    artifact: Artifact | None = None
    version: ArtifactVersion | None = None
    report: QualityReport | None = None
    dossier: ResearchDossier | None = None


class GenerationService:
    def __init__(self, container: Container) -> None:
        self.c = container
        self.repos = container.repos

    # ---------------------------------------------------------------- entry

    async def handle_message(
        self, session: Session, message: Message, progress: Progress | None = None
    ) -> Reply:
        """Always returns a stored assistant reply, also when something fails (FR-UX-4)."""
        self._progress = progress
        with log_context(session_id=session.id, message_id=message.id):
            self._step("understand", "Understanding your request")
            try:
                inp = build_interpreter_input(self.repos, session, message)
                interp = await InterpreterAgent(self.c.llm).run(inp)
            except Exception as exc:  # noqa: BLE001 - the user must always get an answer
                _log_failure(exc)
                return self._say(session, friendly_error(exc, "understand your message"), None)
            interp_id = new_id("interpretation")
            self.repos.interpretations.put(
                StoredInterpretation(id=interp_id, message_id=message.id, interpretation=interp)
            )
            message.interpretation_id = interp_id
            self.repos.messages.put(message)
            self._referenced = set(interp.referenced_file_ids) | set(message.file_ids)
            try:
                return await self._route(session, message, interp)
            except Exception as exc:  # noqa: BLE001
                _log_failure(exc)
                task = self.repos.tasks.get(session.active_task_id) if session.active_task_id else None
                if task is not None and task.status == TaskStatus.running:
                    task.status = TaskStatus.failed
                    self.repos.tasks.put(task)
                spec = interp.output_spec or (task.output_spec if task else None)
                label = _LABELS.get(spec.format if spec else None, "your request")
                return self._say(session, friendly_error(exc, f"finish {label}"), interp, task=task)

    def _step(self, stage: str, text: str) -> None:
        if getattr(self, "_progress", None) is not None:
            self._progress(stage, text)

    async def _route(self, session: Session, message: Message, interp: Interpretation) -> Reply:
        current = self.repos.tasks.get(session.active_task_id) if session.active_task_id else None
        if current is not None and current.pending_confirmation:
            if interp.confirmation == ConfirmationDecision.decline:
                current.pending_change = None
                current.pending_confirmation = None
                current.status = TaskStatus.delivered
                self.repos.tasks.put(current)
                return self._say(
                    session, "Understood. I did not apply the proposed style change.", interp, task=current
                )
            if interp.confirmation != ConfirmationDecision.approve or current.pending_change is None:
                return self._say(
                    session,
                    "Please confirm whether to apply the style change despite the warning, "
                    "or say no to cancel it.",
                    interp,
                    task=current,
                )
            pending_change = current.pending_change
            current.pending_change = None
            current.pending_confirmation = None
            current.status = TaskStatus.running
            self.repos.tasks.put(current)
            interp = interp.model_copy(
                update={
                    "kind": RequestKind.modify_artifact,
                    "change": pending_change,
                    "output_spec": interp.output_spec or current.output_spec,
                }
            )
        elif (
            current is not None
            and current.pending_change is not None
            and interp.kind == RequestKind.clarification_answer
        ):
            if interp.change is None:
                return self._say(
                    session,
                    "I still need a slide location to continue. Please specify whether the new slide goes "
                    "before or after an existing slide.",
                    interp,
                    task=current,
                )
            interp = interp.model_copy(
                update={
                    "kind": RequestKind.modify_artifact,
                    "output_spec": interp.output_spec or current.output_spec,
                }
            )
        if interp.kind == RequestKind.question:
            return await self._answer(session, message, interp)
        if interp.kind == RequestKind.modify_artifact and current is not None and current.artifact_id:
            return await self._edit_artifact(session, message, interp, current)
        if interp.kind == RequestKind.modify_artifact and (current is None or not current.artifact_id):
            return self._say(
                session,
                "There is no active document to edit. What would you like to create?",
                interp,
            )
        if interp.kind == RequestKind.regenerate and current is not None:
            instruction = message.content
            interp = interp.model_copy(
                update={
                    "output_spec": interp.output_spec or current.output_spec,
                    "kind": RequestKind.regenerate,
                    "objective": f"{current.objective} Requested change: {instruction}",
                }
            )
            self._change_note = instruction

        needs_clarification = interp.confidence < self.c.settings.clarify_threshold or (
            interp.clarification_questions and interp.output_spec is None
        )
        if needs_clarification or interp.output_spec is None:
            questions = [
                q.question + (f" (e.g. {', '.join(q.options)})" if q.options else "")
                for q in interp.clarification_questions
            ] or ["Which format do you need (PowerPoint, Word or Excel), and who is the audience?"]
            task = self._task_for(session, interp, status=TaskStatus.awaiting_clarification)
            return self._say(session, "Before I start: " + " ".join(questions), interp, task=task)

        if interp.output_spec.format == OutputFormat.xlsx:
            return await self._generate_workbook(session, interp)
        if interp.output_spec.format == OutputFormat.docx:
            return await self._generate_document(session, interp)
        return await self._generate_deck(session, interp)

    async def _answer(self, session: Session, message: Message, interp: Interpretation) -> Reply:
        self._step("answer", "Writing an answer")
        inp = build_interpreter_input(self.repos, session, message)
        context = render_input(inp).rsplit("<latest_user_message>", 1)[0]
        task = self.repos.tasks.get(session.active_task_id) if session.active_task_id else None
        if task is not None and task.dossier_id:
            dossier = self.repos.dossiers.get(task.dossier_id)
            if dossier is not None and dossier.claims:
                context += "\n<research_notes>\n" + evidence_digest(dossier)[:6000] + "\n</research_notes>"
        answer = await AnswerAgent(self.c.llm).run(context, message.content)
        text = answer.text.strip()
        if answer.suggestions:
            text += "\n\nYou could ask: " + " · ".join(f"“{x}”" for x in answer.suggestions[:3])
        return self._say(session, text, interp, task=task)

    # ---------------------------------------------------------------- targeted editing

    @staticmethod
    def _convert_section_draft(draft: SectionDraft, level: int = 1) -> SectionPlan:
        subsections = [
            GenerationService._convert_section_draft(sub, level=level + 1) for sub in draft.subsections
        ]
        return SectionPlan(
            id=new_id("sec"),
            heading=draft.heading,
            level=draft.level or level,
            purpose=draft.purpose,
            blocks=draft.blocks,
            subsections=subsections,
        )

    async def _edit_artifact(
        self, session: Session, message: Message, interp: Interpretation, current: Task
    ) -> Reply:
        """Edit an existing deliverable by updating only the targeted unit(s) in its IR."""
        artifact = self.repos.artifacts.get(current.artifact_id) if current.artifact_id else None
        if artifact is None or not artifact.current_version:
            return self._say(
                session,
                "There is no active deliverable in this session to edit. What would you like to create?",
                interp,
                task=current,
            )

        base_version = self.repos.artifact_versions.get(f"{artifact.id}:v{artifact.current_version}")
        if base_version is None:
            return self._say(
                session,
                "Could not find the previous version of the deliverable to edit.",
                interp,
                task=current,
            )

        base_ir = base_version.ir
        instruction = (interp.change.instruction if interp.change else None) or message.content
        outline = artifact_outline(base_ir)
        dossier = self.repos.dossiers.get(current.dossier_id) if current.dossier_id else None
        if current.pending_change is not None or current.pending_confirmation is not None:
            current.pending_change = None
            current.pending_confirmation = None
            self.repos.tasks.put(current)

        if (
            isinstance(base_ir, DeckPlan)
            and interp.change
            and interp.change.operation
            in (
                ChangeOperation.add,
                ChangeOperation.reorder,
            )
        ):
            placement = interp.change.placement
            if placement is None:
                return self._ask_slide_placement(
                    session,
                    current,
                    interp,
                    "Where should I place the slide? Specify the beginning, end, or a neighboring slide.",
                )
            position = resolve_slide_position(base_ir, placement)
            if position.clarification_needed or position.index is None:
                return self._ask_slide_placement(
                    session,
                    current,
                    interp,
                    position.clarification_question or "Which slide position do you mean?",
                    position.options,
                )

            if interp.change.operation == ChangeOperation.add:
                template = self._template_path(session, "pptx")
                manifest = await self._analyze_template(self._pptx_manifest(template)) if template else None
                guidance = (
                    template_summary(manifest, self._template_label(session, template))
                    if manifest and template
                    else None
                )
                self._step("insert", "Planning the new slide")
                insertion_plan = await SlideInsertionAgent(self.c.llm).run(
                    SlideInsertionInput(
                        deck=base_ir,
                        instruction=instruction,
                        insertion_index=position.index,
                        template_guidance=guidance,
                        evidence_digest=evidence_digest(dossier) if dossier else None,
                    )
                )
                new_ir = base_ir
                for offset, draft in enumerate(insertion_plan.slides):
                    inserted = SlidePlan(id=new_id("slide"), **draft.model_dump())
                    new_ir, _patch = apply_slide_insert(
                        new_ir,
                        inserted,
                        position.index + offset,
                        instruction=instruction,
                        base_version=base_version.version,
                    )
                target_desc = f"inserted {len(insertion_plan.slides)} slide(s)"
            else:
                target_res = resolve_targets(base_ir, interp.change, message.content)
                if target_res.clarification_needed or len(target_res.targets) != 1:
                    return self._ask_slide_placement(
                        session,
                        current,
                        interp,
                        target_res.clarification_question or "Which existing slide should I move?",
                        target_res.options,
                    )
                moving_id = target_res.targets[0].unit_id
                moving_index = next(i for i, slide in enumerate(base_ir.slides) if slide.id == moving_id)
                anchor_ids = set()
                for anchor in (placement.anchor, placement.before, placement.after):
                    if anchor is None:
                        continue
                    if anchor.resolved_unit_id:
                        anchor_ids.add(anchor.resolved_unit_id)
                    else:
                        anchor_result = resolve_targets(base_ir, None, anchor.locator)
                        anchor_ids.update(target.unit_id for target in anchor_result.targets)
                if moving_id in anchor_ids:
                    return self._ask_slide_placement(
                        session,
                        current,
                        interp,
                        "The slide being moved is one of the placement anchors. Which two other slides "
                        "should define its destination?",
                    )
                destination = position.index - int(moving_index < position.index)
                destination = max(0, min(destination, len(base_ir.slides) - 1))
                new_ir, _patch = apply_slide_move(
                    base_ir,
                    moving_id,
                    destination,
                    instruction=instruction,
                    base_version=base_version.version,
                )
                target_desc = f"moved slide “{target_res.targets[0].label}”"

            return await self._render_and_persist_edit(
                session,
                current,
                artifact,
                base_version,
                new_ir,
                interp,
                instruction,
                target_desc,
            )

        if (
            isinstance(base_ir, DocumentPlan)
            and interp.change
            and interp.change.operation
            in (
                ChangeOperation.add,
                ChangeOperation.reorder,
            )
        ):
            placement = interp.change.placement
            if placement is None:
                return self._ask_slide_placement(
                    session,
                    current,
                    interp,
                    "Where should I place the section? Specify the beginning, end, or a neighboring section.",
                )
            position = resolve_section_position(base_ir, placement)
            if position.clarification_needed or position.index is None:
                return self._ask_slide_placement(
                    session,
                    current,
                    interp,
                    position.clarification_question or "Which section position do you mean?",
                    position.options,
                )

            if interp.change.operation == ChangeOperation.add:
                template = self._template_path(session, "docx")
                manifest = await self._analyze_template(self._docx_manifest(template)) if template else None
                guidance = self._docx_template_summary(manifest) if manifest and template else None
                self._step("insert", "Planning the new section")
                insertion_plan = await SectionInsertionAgent(self.c.llm).run(
                    SectionInsertionInput(
                        document=base_ir,
                        instruction=instruction,
                        insertion_index=position.index,
                        template_guidance=guidance,
                        evidence_digest=evidence_digest(dossier) if dossier else None,
                    )
                )
                new_ir = base_ir
                for offset, draft in enumerate(insertion_plan.sections):
                    inserted = self._convert_section_draft(draft)
                    new_ir, _patch = apply_section_insert(
                        new_ir,
                        inserted,
                        position.index + offset,
                        instruction=instruction,
                        base_version=base_version.version,
                    )
                target_desc = f"inserted {len(insertion_plan.sections)} section(s)"
            else:
                target_res = resolve_targets(base_ir, interp.change, message.content)
                if target_res.clarification_needed or len(target_res.targets) != 1:
                    return self._ask_slide_placement(
                        session,
                        current,
                        interp,
                        target_res.clarification_question or "Which existing section should I move?",
                        target_res.options,
                    )
                moving_id = target_res.targets[0].unit_id
                top_level_ids = [sec.id for sec in base_ir.sections]
                if moving_id not in top_level_ids:
                    return self._say(
                        session,
                        "Only top-level sections can be reordered in the document.",
                        interp,
                        task=current,
                    )
                moving_index = top_level_ids.index(moving_id)
                anchor_ids = set()
                for anchor in (placement.anchor, placement.before, placement.after):
                    if anchor is None:
                        continue
                    if anchor.resolved_unit_id:
                        anchor_ids.add(anchor.resolved_unit_id)
                    else:
                        anchor_result = resolve_targets(base_ir, None, anchor.locator)
                        anchor_ids.update(target.unit_id for target in anchor_result.targets)
                if moving_id in anchor_ids:
                    return self._ask_slide_placement(
                        session,
                        current,
                        interp,
                        "The section being moved is one of the placement anchors. Which two other sections "
                        "should define its destination?",
                    )
                destination = position.index - int(moving_index < position.index)
                destination = max(0, min(destination, len(base_ir.sections) - 1))
                new_ir, _patch = apply_section_move(
                    base_ir,
                    moving_id,
                    destination,
                    instruction=instruction,
                    base_version=base_version.version,
                )
                target_desc = f"moved section “{target_res.targets[0].label}”"

            return await self._render_and_persist_edit(
                session,
                current,
                artifact,
                base_version,
                new_ir,
                interp,
                instruction,
                target_desc,
            )

        # 1. Interpret and apply style changes through a typed plan.
        if interp.change and (
            interp.change.operation == ChangeOperation.restyle
            or interp.change.scope.level == ScopeLevel.style
        ):
            if not isinstance(base_ir, (DeckPlan, DocumentPlan)):
                return self._say(
                    session,
                    "LLM-planned style changes are not supported for this artifact format.",
                    interp,
                    task=current,
                )
            if interp.change.scope.level == ScopeLevel.element or any(
                target.kind.value == "element" for target in interp.change.scope.targets
            ):
                return self._say(
                    session,
                    "Element-level styling is not supported because document elements do not have "
                    "stable IDs. Please target a section or the entire artifact.",
                    interp,
                    task=current,
                )
            slide_ids: list[str] = []
            section_ids: list[str] = []
            if interp.change.scope.level == ScopeLevel.unit or (
                interp.change.scope.level == ScopeLevel.style and interp.change.scope.targets
            ):
                targets = resolve_targets(base_ir, interp.change, message.content)
                if targets.clarification_needed or not targets.targets:
                    question = targets.clarification_question or (
                        "Which unit should receive this style change?"
                    )
                    return self._ask_slide_placement(session, current, interp, question, targets.options)
                target_ids = list(dict.fromkeys(target.unit_id for target in targets.targets))
                if isinstance(base_ir, DeckPlan):
                    slide_ids = target_ids
                else:
                    section_ids = target_ids

            fmt = "pptx" if isinstance(base_ir, DeckPlan) else "docx"
            template = self._template_path(session, fmt)
            manifest = None
            if template:
                parsed = self._pptx_manifest(template) if fmt == "pptx" else self._docx_manifest(template)
                manifest = await self._analyze_template(parsed)
            guidance = manifest.design_analysis if manifest is not None else None
            scope_description = (
                f"slides {', '.join(slide_ids)}"
                if slide_ids
                else f"sections {', '.join(section_ids)}"
                if section_ids
                else f"entire {fmt} artifact"
            )
            if interp.confirmation == ConfirmationDecision.approve:
                style_plan = StylePlan(changes=interp.change.style_changes)
            else:
                style_plan = await StylePlannerAgent(self.c.llm).run(
                    StylePlannerInput(
                        deck=base_ir,
                        tokens=base_version.design_tokens,
                        instruction=instruction,
                        scope_description=scope_description,
                        target_slide_ids=slide_ids,
                        target_section_ids=section_ids,
                        template_analysis=guidance,
                    )
                )
            warnings = list(style_plan.warnings)
            warnings.extend(f"Unsupported request: {item}" for item in style_plan.unsupported_requests)
            if interp.confirmation != ConfirmationDecision.approve:
                warnings.extend(_style_contrast_warnings(base_version.design_tokens, style_plan.changes))
            if not style_plan.changes:
                text = f"I couldn't map that style request to a supported {fmt} change."
                if warnings:
                    text += " " + " ".join(warnings)
                return self._say(session, text, interp, task=current)
            try:
                new_ir, _patch = apply_restyle(
                    base_ir,
                    style_plan.changes,
                    instruction=instruction,
                    base_version=base_version.version,
                    slide_ids=slide_ids,
                    section_ids=section_ids,
                )
            except ScopeViolationError as exc:
                return self._say(
                    session,
                    f"I couldn't apply that style plan safely: {exc.message}",
                    interp,
                    task=current,
                )
            if warnings:
                current.pending_change = interp.change.model_copy(
                    update={"style_changes": style_plan.changes}
                )
                current.pending_confirmation = " ".join(warnings)
                current.status = TaskStatus.awaiting_clarification
                self.repos.tasks.put(current)
                warning_text = " ".join(warnings)
                return self._say(
                    session,
                    "This style change may conflict with readability or template requirements: "
                    f"{warning_text} "
                    "Should I apply the supported changes anyway?",
                    interp,
                    task=current,
                )

            self._step("restyle", "Applying the approved style plan")
            return await self._render_and_persist_edit(
                session,
                current,
                artifact,
                base_version,
                new_ir,
                interp,
                instruction,
                (
                    "restyle"
                    if not slide_ids and not section_ids
                    else f"restyled slides {', '.join(slide_ids)}"
                    if slide_ids
                    else f"restyled sections {', '.join(section_ids)}"
                ),
            )

        # 2. Unit removal
        if interp.change and interp.change.operation == ChangeOperation.remove:
            target_res = resolve_targets(base_ir, interp.change, message.content)
            if target_res.targets:
                target = target_res.targets[0]
                self._step("remove", f"Removing {target.kind} {target.label}")
                new_ir, _patch = apply_remove_unit(
                    base_ir, target.unit_id, instruction=instruction, base_version=base_version.version
                )
                return await self._render_and_persist_edit(
                    session,
                    current,
                    artifact,
                    base_version,
                    new_ir,
                    interp,
                    instruction,
                    f"removed {target.label}",
                )

        # 3. Target resolution for edits
        target_res = resolve_targets(base_ir, interp.change, message.content)
        if target_res.clarification_needed or not target_res.targets:
            q = target_res.clarification_question or "Which slide, section, or sheet would you like to edit?"
            opts = target_res.options or [label for _, label in outline[:6]]
            task = self._task_for(session, interp, status=TaskStatus.awaiting_clarification)
            prompt = q + (" (e.g. " + ", ".join(opts[:4]) + ")" if opts else "")
            return self._say(session, prompt, interp, task=task)

        target = target_res.targets[0]
        self._step("edit", f"Editing {target.kind} “{target.label}”")

        if isinstance(base_ir, DeckPlan):
            slide = next((s for s in base_ir.slides if s.id == target.unit_id), None)
            if slide is None:
                return self._say(
                    session, f"Slide '{target.unit_id}' was not found in the deck.", interp, task=current
                )
            editor = SlideEditorAgent(self.c.llm)
            edited_slide = await editor.run(
                SlideEditorInput(
                    slide=slide,
                    instruction=instruction,
                    outline=outline,
                    evidence_digest=evidence_digest(dossier) if dossier else None,
                )
            )
            new_ir, _patch = apply_slide_edit(
                base_ir, edited_slide, instruction=instruction, base_version=base_version.version
            )
            target_desc = f"slide “{edited_slide.headline}”"

        elif isinstance(base_ir, DocumentPlan):
            sec = next((s for s in base_ir.all_sections() if s.id == target.unit_id), None)
            if sec is None:
                return self._say(
                    session,
                    f"Section '{target.unit_id}' was not found in the document.",
                    interp,
                    task=current,
                )
            edited_sec = exact_section_replacement(sec, instruction)
            if edited_sec is not None:
                new_ir, _patch = apply_section_edit(
                    base_ir, edited_sec, instruction=instruction, base_version=base_version.version
                )
                target_desc = f"section “{edited_sec.heading}”"
            else:
                selection = (
                    select_section_block(sec, instruction)
                    if (interp.change and interp.change.scope.level == ScopeLevel.element)
                    else None
                )
                if selection is not None:
                    editor = SectionEditorAgent(self.c.llm)
                    chunk = sec.model_copy(
                        update={"blocks": [selection.block], "subsections": []}
                    )
                    edited_chunk = await editor.run(
                        SectionEditorInput(
                            section=chunk,
                            instruction=instruction,
                            outline=[(sec.id, sec.heading)],
                            evidence_digest=evidence_digest(dossier) if dossier else None,
                        )
                    )
                    if len(edited_chunk.blocks) == 1:
                        new_ir, _patch = apply_section_block_edit(
                            base_ir,
                            selection.section_id,
                            selection.block_index,
                            edited_chunk.blocks[0],
                            instruction=instruction,
                            base_version=base_version.version,
                        )
                        target_desc = f"one block in section “{sec.heading}”"
                    else:
                        selection = None

                if selection is None:
                    editor = SectionEditorAgent(self.c.llm)
                    edited_sec = await editor.run(
                        SectionEditorInput(
                            section=sec,
                            instruction=instruction,
                            outline=outline,
                            evidence_digest=evidence_digest(dossier) if dossier else None,
                        )
                    )
                    new_ir, _patch = apply_section_edit(
                        base_ir, edited_sec, instruction=instruction, base_version=base_version.version
                    )
                    target_desc = f"section “{edited_sec.heading}”"

        elif isinstance(base_ir, WorkbookPlan):
            sheet = next((s for s in base_ir.sheets if s.id == target.unit_id), None)
            if sheet is None:
                return self._say(
                    session, f"Sheet '{target.unit_id}' was not found in the workbook.", interp, task=current
                )
            editor = SheetEditorAgent(self.c.llm)
            nr_summary = ", ".join(f"'{nr.name}' ({nr.ref})" for nr in base_ir.named_ranges)
            edited_sheet = await editor.run(
                SheetEditorInput(
                    sheet=sheet,
                    instruction=instruction,
                    outline=outline,
                    named_ranges_summary=nr_summary,
                )
            )
            new_ir, _patch = apply_sheet_edit(
                base_ir, edited_sheet, instruction=instruction, base_version=base_version.version
            )
            target_desc = f"sheet “{edited_sheet.name}”"

        else:
            return self._say(
                session,
                "Targeted editing is not supported for this deliverable format.",
                interp,
                task=current,
            )

        return await self._render_and_persist_edit(
            session, current, artifact, base_version, new_ir, interp, instruction, target_desc
        )

    def _ask_slide_placement(
        self,
        session: Session,
        task: Task,
        interp: Interpretation,
        question: str,
        options: list[str] | None = None,
    ) -> Reply:
        task.pending_change = interp.change
        task.pending_confirmation = None
        task.status = TaskStatus.awaiting_clarification
        self.repos.tasks.put(task)
        choices = f" Options: {'; '.join(options[:4])}." if options else ""
        return self._say(session, question + choices, interp, task=task)

    async def _render_and_persist_edit(
        self,
        session: Session,
        task: Task,
        artifact: Artifact,
        base_version: ArtifactVersion,
        new_ir: ArtifactIR,
        interp: Interpretation,
        instruction: str,
        target_desc: str,
    ) -> Reply:
        settings = self.c.settings
        version_no = artifact.current_version + 1
        spec = interp.output_spec or task.output_spec
        dossier = self.repos.dossiers.get(task.dossier_id) if task.dossier_id else None
        tokens = base_version.design_tokens

        with tempfile.TemporaryDirectory(dir=settings.storage_dir) as tmp:
            self._step("render", "Re-rendering deliverable with your changes")
            if isinstance(new_ir, DeckPlan):
                template = self._template_path(session, "pptx")
                manifest = await self._analyze_template(self._pptx_manifest(template)) if template else None
                build = await asyncio.to_thread(
                    build_deck,
                    new_ir,
                    tokens,
                    Path(tmp),
                    spec=spec,
                    dossier=dossier,
                    max_iterations=settings.max_repair_iterations,
                    libreoffice=settings.find_libreoffice(),
                    artifact_id=artifact.id,
                    version=version_no,
                    asset_resolver=self.c.blobs.resolve,
                    template=template,
                    manifest=manifest,
                )
                previews = await asyncio.to_thread(self._previews, build.path, Path(tmp) / "png")
                total_units = len(new_ir.slides)
                unit_name = "slides"
            elif isinstance(new_ir, DocumentPlan):
                template = self._template_path(session, "docx")
                manifest = await self._analyze_template(self._docx_manifest(template)) if template else None
                build = await asyncio.to_thread(
                    build_document,
                    new_ir,
                    tokens,
                    Path(tmp),
                    spec=spec,
                    dossier=dossier,
                    libreoffice=settings.find_libreoffice(),
                    template=template,
                    template_manifest=manifest,
                    audience=spec.audience if spec else "general professional audience",
                    artifact_id=artifact.id,
                    version=version_no,
                    asset_resolver=self.c.blobs.resolve,
                )
                previews = []
                total_units = len(new_ir.all_sections())
                unit_name = "sections"
            elif isinstance(new_ir, WorkbookPlan):
                datasets = {
                    f.id: load_dataset(f.id, f.filename, self.c.blobs.get(f.blob_path).read())
                    for f in self.repos.files.list_by_parent(session.id)
                    if f.role == FileRole.dataset
                }
                build = await asyncio.to_thread(
                    build_workbook,
                    new_ir,
                    tokens,
                    Path(tmp),
                    datasets=datasets,
                    dossier=dossier,
                    libreoffice=settings.find_libreoffice(),
                    artifact_id=artifact.id,
                    version=version_no,
                )
                previews = []
                total_units = len(new_ir.sheets)
                unit_name = "sheets"
            else:
                raise ValueError(f"Unknown IR format: {type(new_ir)}")

            blob = self.c.blobs.put_file(build.path)

        self.repos.quality_reports.put(build.report)
        version = self.repos.add_artifact_version(
            ArtifactVersion(
                artifact_id=artifact.id,
                version=version_no,
                parent_version=base_version.version,
                ir=new_ir,
                template_file_id=task.template_file_id or base_version.template_file_id,
                design_tokens=tokens,
                blob_path=blob.path,
                preview_paths=previews,
                change_summary=instruction,
                quality_report_id=build.report.id,
                dossier_id=dossier.id if dossier else None,
            )
        )
        task.status = TaskStatus.delivered
        self.repos.tasks.put(task)

        if target_desc == "restyle":
            reply_text = (
                f"Applied styling changes: “{instruction}”. "
                f"Content across all {total_units} {unit_name} was preserved. Delivered Version {version_no}."
            )
        elif target_desc.startswith("restyled slides "):
            scope = target_desc.removeprefix("restyled slides ")
            reply_text = (
                f"Applied styling changes to {scope}: “{instruction}”. "
                f"All other {unit_name} were preserved. Delivered Version {version_no}."
            )
        elif target_desc.startswith("inserted "):
            reply_text = (
                f"{target_desc.capitalize()} for your presentation. "
                f"All existing {unit_name} were preserved. Delivered Version {version_no}."
            )
        elif target_desc.startswith("moved "):
            reply_text = (
                f"{target_desc.capitalize()} in the presentation. Slide content and IDs were preserved. "
                f"Delivered Version {version_no}."
            )
        elif target_desc.startswith("removed"):
            reply_text = (
                f"Applied your change: {target_desc}. "
                f"All other {total_units} {unit_name} remain unchanged. Delivered Version {version_no}."
            )
        else:
            other = max(0, total_units - 1)
            reply_text = (
                f"Applied your change to {target_desc}: “{instruction}”. "
                f"All other {other} {unit_name} remain unchanged. Delivered Version {version_no}."
            )

        reply = self._say(session, reply_text, interp, task=task)
        reply.artifact = self.repos.artifacts.require(artifact.id)
        reply.version = version
        reply.report = build.report
        reply.dossier = dossier
        return reply

    # ---------------------------------------------------------------- deck generation

    async def _generate_deck(self, session: Session, interp: Interpretation) -> Reply:
        settings = self.c.settings
        spec = interp.output_spec
        assert spec is not None
        task = self._task_for(session, interp, status=TaskStatus.running)
        with log_context(task_id=task.id):
            self._step("research", "Researching the topic")
            dossier = await self._research(session, task, interp)
            usable = dossier if dossier is not None and dossier.performed and dossier.claims else None
            template = self._template_path(session, "pptx")
            task.template_file_id = self._pin_presentation_template(session, task, template)
            self.repos.tasks.put(task)
            manifest = await self._analyze_template(self._pptx_manifest(template)) if template else None
            planner = DeckPlannerAgent(self.c.llm)
            planner_input = PlannerInput(
                objective=interp.objective,
                spec=spec,
                evidence_digest=evidence_digest(usable) if usable else None,
                template_summary=template_summary(manifest, self._template_label(session, template))
                if manifest
                else None,
            )
            self._step("plan", "Planning the story and slides")
            deck = await planner.run(planner_input)
            problems = self._plan_problems(deck, interp, usable)
            if problems:
                log.info("plan has %d problems; asking planner to revise", len(problems))
                deck = await planner.revise(planner_input, deck, problems)

            if manifest is not None and manifest.pptx.design_mode == "slides":
                request_frame_photos(deck, manifest)
            self._step("images", "Finding photos")
            await resolve_deck_images(deck, self.c.images, self.c.blobs, limit=settings.max_images_per_deck)
            if manifest is not None:
                tokens = tokens_from_template(manifest, f"{interp.objective} {deck.title}")
            else:
                tokens = generated_tokens(
                    f"{interp.objective} {deck.title}", tone=spec.tone, hint=deck.design_hint
                )
            artifact = self.repos.artifacts.get(task.artifact_id) if task.artifact_id else None
            if artifact is None:
                artifact = self.repos.artifacts.put(
                    Artifact(id=new_id("artifact"), task_id=task.id, format=OutputFormat.pptx)
                )
            version_no = artifact.current_version + 1
            with tempfile.TemporaryDirectory(dir=settings.storage_dir) as tmp:
                self._step("render", "Designing, rendering and checking slides")

                def render(plan: DeckPlan, out: Path):
                    return build_deck(
                        plan,
                        tokens,
                        out,
                        spec=spec,
                        dossier=usable,
                        max_iterations=settings.max_repair_iterations,
                        libreoffice=settings.find_libreoffice(),
                        artifact_id=artifact.id,
                        version=version_no,
                        asset_resolver=self.c.blobs.resolve,
                        template=template,
                        manifest=manifest,
                    )

                build = await asyncio.to_thread(render, deck, Path(tmp))
                fit = fit_problems(build.report)
                if fit:
                    # Splitting is not allowed (fixed length) or did not help: ask for shorter text once.
                    self._step("render", "Tightening text that does not fit")
                    log.info("deck has %d fit problems; asking planner to shorten", len(fit))
                    shorter = await planner.revise(planner_input, build.deck, fit)
                    retry = await asyncio.to_thread(render, shorter, Path(tmp) / "fit")
                    if retry.report.summary.unresolved <= build.report.summary.unresolved:
                        build = retry
                blob = self.c.blobs.put_file(build.path)
                previews = await asyncio.to_thread(self._previews, build.path, Path(tmp) / "png")
            self.repos.quality_reports.put(build.report)
            version = self.repos.add_artifact_version(
                ArtifactVersion(
                    artifact_id=artifact.id,
                    version=version_no,
                    parent_version=artifact.current_version or None,
                    ir=build.deck,
                    template_file_id=task.template_file_id,
                    design_tokens=tokens,
                    blob_path=blob.path,
                    preview_paths=previews,
                    change_summary="initial generation" if version_no == 1 else "regenerated",
                    quality_report_id=build.report.id,
                    dossier_id=dossier.id if dossier else None,
                )
            )
            task.artifact_id = artifact.id
            task.status = TaskStatus.delivered
            self.repos.tasks.put(task)
            text = self._delivery_text(build.deck, build.report, interp, session, dossier)
            reply = self._say(session, text, interp, task=task)
            reply.artifact = self.repos.artifacts.require(artifact.id)
            reply.version = version
            reply.report = build.report
            reply.dossier = dossier
            return reply

    def _previews(self, path: Path, out_dir: Path, limit: int = 8) -> list[str]:
        """Thumbnails of the first slides for the chat; a preview failure never fails the deliverable."""
        try:
            pngs = render_previews(path, out_dir, width_px=640)[:limit]
            return [self.c.blobs.put_file(png).path for png in pngs]
        except Exception as exc:  # noqa: BLE001
            log.warning("preview rendering failed: %s", exc)
            return []

    async def _research(
        self, session: Session, task: Task, interp: Interpretation, *, include_datasets: bool = True
    ) -> ResearchDossier | None:
        """Run (or reuse) research for the task; returns None when research is disabled or not needed."""
        settings = self.c.settings
        if interp.kind == RequestKind.regenerate and task.dossier_id:
            previous = self.repos.dossiers.get(task.dossier_id)
            if previous is not None:
                return previous
        roles = (
            (FileRole.source, FileRole.dataset, FileRole.unknown) if include_datasets else (FileRole.source,)
        )
        files = [f for f in self.repos.files.list_by_parent(session.id) if f.role in roles]
        depth = interp.research.depth
        if not settings.research_enabled and not files:
            return None
        if depth == ResearchDepth.none and not files:
            return None
        if not settings.research_enabled:
            depth = ResearchDepth.none

        notes: list[str] = []
        user_sources = []
        for f in files:
            try:
                text = extract_text(f.filename, self.c.blobs.read_bytes(f.blob_path))
            except DocForgeError as exc:
                notes.append(f"could not read {f.filename}: {exc.message}")
                continue
            if text.strip():
                user_sources.append(UserSource(file_id=f.id, filename=f.filename, text=text))
        web = None if isinstance(self.c.search, UnavailableSearchProvider) else self.c.search
        if web is None:
            notes.append(self.c.search.reason)
        service = ResearchService(
            settings, self.c.llm, web=web, academic=self.c.academic, knowledge=self.c.knowledge
        )
        dossier = await service.run(
            task.id,
            interp.objective,
            deliverable=interp.output_spec.format.value if interp.output_spec else "pptx",
            depth=depth,
            namespace=session.id,
            user_sources=user_sources,
        )
        dossier.notes = notes + dossier.notes
        self.repos.dossiers.put(dossier)
        task.dossier_id = dossier.id
        self.repos.tasks.put(task)
        return dossier

    def _plan_problems(
        self, deck: DeckPlan, interp: Interpretation, dossier: ResearchDossier | None
    ) -> list[str]:
        run = CheckRun()
        check_deck_plan(run, deck, interp.output_spec, dossier=dossier)
        return [f.message for f in run.findings if f.severity in (Severity.critical, Severity.major)]

    def _delivery_text(
        self,
        deck: DeckPlan,
        report: QualityReport,
        interp: Interpretation,
        session: Session,
        dossier: ResearchDossier | None,
    ) -> str:
        s = report.summary
        verdict = {
            Verdict.passed: "passed all checks",
            Verdict.pass_with_warnings: "passed with warnings",
            Verdict.failed: "has unresolved problems",
        }[report.verdict]
        lines = [
            f"Created a {len(deck.slides)}-slide deck: “{deck.title}”. Quality: {verdict} "
            f"({s.corrected} fixed automatically, {s.unresolved} open)."
        ]
        critical = [f for f in report.findings if f.severity == Severity.critical and f.status != "corrected"]
        if critical:
            lines.append("Open problems: " + "; ".join(f.message for f in critical[:3]) + ".")
        skipped = [_CHECK_NAMES.get(c.check_id, c.check_id) for c in report.checks if c.status == "skipped"]
        if skipped:
            lines.append("Not checked: " + ", ".join(dict.fromkeys(skipped)) + ".")
        lines.append(research_summary(dossier, interp))
        template = self._template_path(session, "pptx")
        if template is not None:
            manifest = self._pptx_manifest(template)
            label = self._template_label(session, template)
            if manifest.pptx.design_mode == "slides":
                designs = sum(1 for b in manifest.pptx.slide_bases if b.kind == "content")
                lines.append(
                    f"Designed on your template “{label}”: its artwork, fonts and colours are kept, "
                    f"with {designs} slide designs rotated for variety and the sample slides removed."
                )
            else:
                lines.append(
                    f"Built on your template “{label}”: its layouts, theme colours, fonts and logos "
                    "are kept and the sample slides removed."
                )
            lines += [f"Template note: {w}." for w in manifest.warnings[:2]]
        return " ".join(line for line in lines if line)

    def _has_template(self, session: Session, fmt: str = "pptx") -> bool:
        return self._template_path(session, fmt) is not None

    def _template_path(self, session: Session, fmt: str) -> Path | None:
        """Most recent uploaded template of this format, else the configured default template."""
        uploads = [
            file
            for file in self.repos.files.list_by_parent(session.id)
            if file.role == FileRole.template and file.filename.lower().endswith(f".{fmt}")
        ]
        task = self.repos.tasks.get(session.active_task_id) if session.active_task_id else None
        referenced = [file for file in uploads if file.id in getattr(self, "_referenced", set())]
        if referenced:
            selected = referenced[-1]
            if task is not None and task.template_file_id != selected.id:
                task.template_file_id = selected.id
                self.repos.tasks.put(task)
            return self.c.blobs.resolve(selected.blob_path)
        if task is not None and task.template_file_id:
            pinned = self.repos.files.get(task.template_file_id)
            if pinned is None or pinned.role != FileRole.template:
                log.warning("pinned template %s is missing", task.template_file_id)
                return None
            if not pinned.filename.lower().endswith(f".{fmt}"):
                return None
            return self.c.blobs.resolve(pinned.blob_path)
        if uploads:
            return self.c.blobs.resolve(uploads[-1].blob_path)
        return self.c.settings.default_template(fmt)

    def _pin_presentation_template(self, session: Session, task: Task, template: Path | None) -> str | None:
        return self._pin_template(session, task, template, "pptx")

    def _pin_template(self, session: Session, task: Task, template: Path | None, fmt: str) -> str | None:
        """Keep the selected office template stable across immutable artifact versions and edits."""
        if template is None:
            return None
        digest = hashlib.sha256(template.read_bytes()).hexdigest()
        existing = next(
            (
                uploaded
                for uploaded in self.repos.files.list_by_parent(session.id)
                if uploaded.role == FileRole.template
                and uploaded.filename.lower().endswith(f".{fmt}")
                and uploaded.sha256 == digest
            ),
            None,
        )
        if existing is None:
            blob = self.c.blobs.put_file(template)
            media_type = {
                "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }.get(fmt, "application/octet-stream")
            existing = self.repos.files.put(
                UploadedFile(
                    id=new_id("file"),
                    session_id=session.id,
                    filename=template.name,
                    media_type=media_type,
                    size=blob.size,
                    sha256=blob.sha256,
                    role=FileRole.template,
                    blob_path=blob.path,
                )
            )
        task.template_file_id = existing.id
        return existing.id

    def _template_label(self, session: Session, path: Path) -> str:
        """Uploaded file name for a template blob (blob paths are content hashes)."""
        for f in self.repos.files.list_by_parent(session.id):
            if f.role == FileRole.template and self.c.blobs.resolve(f.blob_path) == path:
                return f.filename
        return path.name

    def _pptx_manifest(self, template: Path) -> TemplateManifest:
        """Analyse a PPTX template once per file content (cached by SHA-256, FR-TPL-8)."""
        sha = hashlib.sha256(template.read_bytes()).hexdigest()
        cached = self.repos.templates.get(sha)
        if cached is not None and cached.analyzer_version >= ANALYZER_VERSION:
            return cached
        manifest = analyze_pptx(template)
        settings = self.c.settings
        if settings.pptx_masters_enabled:
            guide = run_pptx_masters(settings, template, settings.storage_dir / "template_guides" / sha[:16])
            manifest.design_guide = guide.files
            if guide.status not in ("ok", "not_installed"):
                manifest.warnings.append(f"pptx-masters {guide.status}: {guide.detail}"[:200])
            elif guide.status == "not_installed":
                log.info("pptx-masters is enabled but not installed; skipping the design guide")
        return self.repos.templates.put(manifest)

    def _docx_manifest(self, template: Path) -> TemplateManifest:
        """Analyze and cache DOCX styles/page setup by file SHA-256."""
        sha = hashlib.sha256(template.read_bytes()).hexdigest()
        cached = self.repos.templates.get(sha)
        if (
            cached is not None
            and cached.docx is not None
            and cached.analyzer_version >= DOCX_ANALYZER_VERSION
        ):
            return cached
        return self.repos.templates.put(analyze_docx(template))

    @staticmethod
    def _docx_template_summary(manifest: TemplateManifest) -> str:
        info = manifest.docx
        if info is None:
            return ""
        lines = [
            "DOCX template guidance (observed only):",
            f"Style roles: {info.role_style_map}",
            "Styles: "
            + "; ".join(
                f"{style.name} (id={style.style_id}, base={style.based_on}, "
                f"font={style.font.model_dump(mode='json') if style.font else 'unknown'})"
                for style in info.styles
                if style.in_use or style.name in info.role_style_map.values()
            ),
            "Sections: "
            + "; ".join(
                f"{section.orientation}, {section.page_width}x{section.page_height} EMU, "
                f"margins={section.margins}, header={bool(section.header_text)}, "
                f"footer={bool(section.footer_text)}"
                for section in info.sections
            ),
            f"Existing TOC: {info.has_toc}",
        ]
        if info.image_assets:
            logos = [a for a in info.image_assets if a.is_logo]
            lines.append(
                f"Branding assets: {len(logos)} logo(s) found in {', '.join(a.location for a in logos)}"
            )
        hdr_texts = [s.header_text for s in info.sections if s.header_text]
        if hdr_texts:
            lines.append(f"Header branding text: {'; '.join(hdr_texts)}")
        ftr_texts = [s.footer_text for s in info.sections if s.footer_text]
        if ftr_texts:
            lines.append(f"Footer branding text: {'; '.join(ftr_texts)}")
        return "\n".join(lines)

    async def _analyze_template(self, manifest: TemplateManifest) -> TemplateManifest:
        """Cache LLM design guidance separately from deterministic PPTX extraction."""
        model = self.c.settings.model_for("template_analyzer")
        model_identity = model if ":" in model else f"{self.c.settings.llm_provider}:{model}"
        if (
            manifest.design_analysis is not None
            and manifest.design_analysis_version == PROMPT_VERSION
            and manifest.design_analysis_model == model_identity
        ):
            return manifest
        try:
            analysis = await TemplateAnalyzerAgent(self.c.llm).run(manifest)
        except Exception as exc:  # noqa: BLE001 - deterministic manifest remains usable
            log.warning("template design analysis failed: %s", exc.__class__.__name__)
            if manifest.design_analysis is None:
                return manifest
            fallback = manifest.model_copy(
                update={
                    "design_analysis": None,
                    "design_analysis_version": 0,
                    "design_analysis_model": None,
                }
            )
            return self.repos.templates.put(fallback)
        manifest.design_analysis = analysis
        manifest.design_analysis_version = PROMPT_VERSION
        manifest.design_analysis_model = model_identity
        return self.repos.templates.put(manifest)

    # ---------------------------------------------------------------- workbook generation

    def _datasets(self, session: Session, notes: list[str]) -> dict[str, Dataset]:
        datasets: dict[str, Dataset] = {}
        candidates = [
            f
            for f in self.repos.files.list_by_parent(session.id)
            if f.role == FileRole.dataset
            or (f.role == FileRole.unknown and f.filename.lower().endswith((".csv", ".tsv", ".xlsx")))
        ]
        for n, f in enumerate(candidates, start=1):
            try:
                ds = load_dataset(f"D{n}", f.filename, self.c.blobs.read_bytes(f.blob_path))
            except DocForgeError as exc:
                notes.append(f"could not load dataset {f.filename}: {exc.message}")
                continue
            datasets[ds.id] = ds
        return datasets

    async def _generate_workbook(self, session: Session, interp: Interpretation) -> Reply:
        settings = self.c.settings
        spec = interp.output_spec
        assert spec is not None
        task = self._task_for(session, interp, status=TaskStatus.running)
        with log_context(task_id=task.id):
            notes: list[str] = []
            datasets = self._datasets(session, notes)
            # Datasets fill tables directly; research uses only text sources and the web.
            self._step("research", "Researching the topic")
            dossier = await self._research(session, task, interp, include_datasets=False)
            usable = dossier if dossier is not None and dossier.performed and dossier.claims else None
            planner = WorkbookPlannerAgent(self.c.llm)
            wb_input = WorkbookInput(
                objective=interp.objective,
                spec=spec,
                dataset_profiles=[d.profile() for d in datasets.values()],
                evidence_digest=evidence_digest(usable) if usable else None,
            )
            self._step("plan", "Designing the workbook")
            plan = await planner.run(wb_input)
            tokens = generated_tokens(f"{interp.objective} {plan.title}", tone=spec.tone)
            artifact = self.repos.artifacts.get(task.artifact_id) if task.artifact_id else None
            if artifact is None or artifact.format != OutputFormat.xlsx:
                artifact = self.repos.artifacts.put(
                    Artifact(id=new_id("artifact"), task_id=task.id, format=OutputFormat.xlsx)
                )
            version_no = artifact.current_version + 1
            with tempfile.TemporaryDirectory(dir=settings.storage_dir) as tmp:
                self._step("render", "Building and recalculating the workbook")
                build = await asyncio.to_thread(
                    build_workbook,
                    plan,
                    tokens,
                    Path(tmp),
                    datasets=datasets,
                    dossier=usable,
                    libreoffice=settings.find_libreoffice(),
                    artifact_id=artifact.id,
                    version=version_no,
                )
                for iteration in range(min(settings.max_repair_iterations, 3)):
                    diagnostics = extract_workbook_diagnostics(plan, build)
                    if not diagnostics:
                        break
                    log.info(
                        "workbook repair iteration %d: %d problems; asking planner to revise",
                        iteration + 1,
                        len(diagnostics),
                    )
                    self._step("repair", f"Fixing formulas and recalculating (attempt {iteration + 1})")
                    revised_plan = await planner.revise(wb_input, plan, diagnostics[:12])
                    retry_build = await asyncio.to_thread(
                        build_workbook,
                        revised_plan,
                        tokens,
                        Path(tmp) / f"r{iteration + 1}",
                        datasets=datasets,
                        dossier=usable,
                        libreoffice=settings.find_libreoffice(),
                        artifact_id=artifact.id,
                        version=version_no,
                    )
                    retry_build.report.iterations = iteration + 1
                    if retry_build.report.summary.unresolved <= build.report.summary.unresolved:
                        plan = revised_plan
                        build = retry_build
                    else:
                        break
                blob = self.c.blobs.put_file(build.path)
            self.repos.quality_reports.put(build.report)
            version = self.repos.add_artifact_version(
                ArtifactVersion(
                    artifact_id=artifact.id,
                    version=version_no,
                    parent_version=artifact.current_version or None,
                    ir=build.plan,
                    design_tokens=tokens,
                    blob_path=blob.path,
                    change_summary="initial generation" if version_no == 1 else "regenerated",
                    quality_report_id=build.report.id,
                    dossier_id=dossier.id if dossier else None,
                )
            )
            task.artifact_id = artifact.id
            task.status = TaskStatus.delivered
            self.repos.tasks.put(task)
            report = build.report
            formulas = sum(1 for _ in build.result.calculated_cells) + sum(
                1 for s in build.plan.sheets for c in s.cells if c.formula
            )
            verdict = {
                Verdict.passed: "passed all checks",
                Verdict.pass_with_warnings: "passed with warnings",
                Verdict.failed: "has unresolved problems",
            }[report.verdict]
            parts = [
                f"Created an Excel workbook: “{build.plan.title}” — "
                f"{len(build.plan.sheets)} sheets plus README"
                + (" and Sources" if build.result.sources else "")
                + f", {formulas} live formulas, {sum(len(s.charts) for s in build.plan.sheets)} charts. "
                f"Every formula was recalculated independently. Quality: {verdict} "
                f"({report.summary.unresolved} open).",
            ]
            open_major = [
                f.message for f in report.findings if f.severity in (Severity.critical, Severity.major)
            ][:3]
            if open_major:
                parts.append("Open problems: " + "; ".join(open_major) + ".")
            if datasets:
                parts.append(
                    "Datasets loaded: "
                    + ", ".join(f"{d.name} ({len(d.rows)} rows)" for d in datasets.values())
                    + "."
                )
            parts += [f"Note: {n}." for n in notes[:2]]
            parts.append(research_summary(dossier, interp))
            reply = self._say(session, " ".join(p for p in parts if p), interp, task=task)
            reply.artifact = self.repos.artifacts.require(artifact.id)
            reply.version = version
            reply.report = report
            reply.dossier = dossier
            return reply

    # ---------------------------------------------------------------- document generation

    async def _generate_document(self, session: Session, interp: Interpretation) -> Reply:
        settings = self.c.settings
        spec = interp.output_spec
        assert spec is not None
        task = self._task_for(session, interp, status=TaskStatus.running)
        with log_context(task_id=task.id):
            self._step("research", "Researching the topic")
            dossier = await self._research(session, task, interp)
            usable = dossier if dossier is not None and dossier.performed and dossier.claims else None
            template = self._template_path(session, "docx")
            task.template_file_id = self._pin_template(session, task, template, "docx")
            self.repos.tasks.put(task)
            manifest = await self._analyze_template(self._docx_manifest(template)) if template else None
            doc_input = DocumentInput(
                objective=interp.objective,
                spec=spec,
                evidence_digest=evidence_digest(usable) if usable else None,
                template_summary=self._docx_template_summary(manifest) if manifest else None,
            )
            self._step("plan", "Outlining and writing sections")
            plan = await write_document(self.c.llm, doc_input)
            await resolve_document_images(
                plan, self.c.images, self.c.blobs, limit=settings.max_images_per_deck
            )
            tokens = (
                tokens_from_docx_template(manifest, f"{interp.objective} {plan.title}")
                if manifest
                else generated_tokens(f"{interp.objective} {plan.title}", tone=spec.tone)
            )
            artifact = self.repos.artifacts.get(task.artifact_id) if task.artifact_id else None
            if artifact is None or artifact.format != OutputFormat.docx:
                artifact = self.repos.artifacts.put(
                    Artifact(id=new_id("artifact"), task_id=task.id, format=OutputFormat.docx)
                )
            version_no = artifact.current_version + 1
            with tempfile.TemporaryDirectory(dir=settings.storage_dir) as tmp:
                self._step("render", "Formatting and checking the document")
                build = await asyncio.to_thread(
                    build_document,
                    plan,
                    tokens,
                    Path(tmp),
                    spec=spec,
                    dossier=usable,
                    libreoffice=settings.find_libreoffice(),
                    template=template,
                    template_manifest=manifest,
                    audience=spec.audience,
                    artifact_id=artifact.id,
                    version=version_no,
                    asset_resolver=self.c.blobs.resolve,
                )
                blob = self.c.blobs.put_file(build.path)
            self.repos.quality_reports.put(build.report)
            version = self.repos.add_artifact_version(
                ArtifactVersion(
                    artifact_id=artifact.id,
                    version=version_no,
                    parent_version=artifact.current_version or None,
                    ir=build.plan,
                    template_file_id=task.template_file_id,
                    design_tokens=tokens,
                    blob_path=blob.path,
                    change_summary="initial generation" if version_no == 1 else "regenerated",
                    quality_report_id=build.report.id,
                    dossier_id=dossier.id if dossier else None,
                )
            )
            task.artifact_id = artifact.id
            task.status = TaskStatus.delivered
            self.repos.tasks.put(task)
            r = build.result
            report = build.report
            verdict = {
                Verdict.passed: "passed all checks",
                Verdict.pass_with_warnings: "passed with warnings",
                Verdict.failed: "has unresolved problems",
            }[report.verdict]
            parts = [
                f"Created a Word document: “{plan.title}” — {len(plan.sections)} sections, about "
                f"{max(1, round(r.words / 450))} pages ({r.words} words), {r.tables} tables, "
                f"{r.figures} figures, "
                f"{r.references} references. Quality: {verdict} ({report.summary.unresolved} open).",
            ]
            open_major = [
                f.message for f in report.findings if f.severity in (Severity.critical, Severity.major)
            ][:3]
            if open_major:
                parts.append("Open problems: " + "; ".join(open_major) + ".")
            parts.append(research_summary(dossier, interp))
            if template is not None:
                parts.append(f"Styled with the template “{self._template_label(session, template)}”.")
            reply = self._say(session, " ".join(p for p in parts if p), interp, task=task)
            reply.artifact = self.repos.artifacts.require(artifact.id)
            reply.version = version
            reply.report = report
            reply.dossier = dossier
            return reply

    # ---------------------------------------------------------------- persistence helpers

    def _task_for(self, session: Session, interp: Interpretation, *, status: TaskStatus) -> Task:
        current = self.repos.tasks.get(session.active_task_id) if session.active_task_id else None
        reuse = current is not None and interp.kind in (
            RequestKind.regenerate,
            RequestKind.clarification_answer,
            RequestKind.continue_task,
        )
        if reuse:
            task = current
            task.objective = interp.objective
            task.output_spec = interp.output_spec or task.output_spec
            task.status = status
        else:
            task = Task(
                id=new_id("task"),
                session_id=session.id,
                objective=interp.objective,
                output_spec=interp.output_spec,
                status=status,
            )
            session.active_task_id = task.id
            self.repos.sessions.put(session)
        return self.repos.tasks.put(task)

    def _say(
        self, session: Session, text: str, interp: Interpretation | None, *, task: Task | None = None
    ) -> Reply:
        note = getattr(self, "_change_note", None)
        if note and text.startswith("Created"):
            text = f"Applied your change (“{note[:120]}”) by rebuilding the deliverable. {text}"
        msg = self.repos.messages.put(
            Message(id=new_id("message"), session_id=session.id, role=Role.assistant, content=text)
        )
        return Reply(message=msg, interpretation=interp, task=task)


def research_summary(dossier: ResearchDossier | None, interp: Interpretation) -> str:
    """One honest sentence (or two) about what research backs the deliverable."""
    if dossier is None:
        if interp.research.depth != ResearchDepth.none:
            return "Research is disabled, so statements come from your request and general knowledge."
        return ""
    if not dossier.performed:
        return f"No research was performed ({dossier.skipped_reason or 'not needed'})."
    scholarly = sum(1 for src in dossier.sources if src.venue)
    cov = dossier.coverage
    papers = f" ({scholarly} scholarly)" if scholarly else ""
    text = (
        f"Research: {len(dossier.sources)} sources used{papers}, "
        f"{len(dossier.claims)} evidence items; questions answered {cov.answered}, "
        f"partly {cov.partial}, unanswered {cov.unanswered}."
    )
    if dossier.notes:
        text += " Caveats: " + "; ".join(dossier.notes[:3]) + "."
    return text


def fit_problems(report: QualityReport) -> list[str]:
    """Open text-fit findings as instructions the planner can act on (one line per slide)."""
    by_slide: dict[str, str] = {}
    for f in report.findings:
        if (
            f.check_id in _FIT_CHECKS
            and f.status != "corrected"
            and f.unit_id
            and f.severity != Severity.info
        ):
            by_slide.setdefault(f.unit_id.split("-")[0], f.message)
    return [
        f"Slide {uid}: text does not fit ({msg}). Shorten it: headline <= 8 words, at most 4 bullets of "
        "<= 12 words, labels <= 3 words; keep the facts and claim IDs."
        for uid, msg in sorted(by_slide.items())
    ]


def _style_contrast_warnings(tokens, changes) -> list[str]:
    palette = tokens.palette.model_dump()
    for change in changes:
        prop = change.property.lower().strip()
        if prop.startswith(("palette.", "colors.", "palette_overrides.")):
            key = prop.split(".", 1)[1]
            color = change.value.strip().removeprefix("#").upper()
            if key in palette:
                palette[key] = color
    warnings = []
    text_roles = ("text", "text_muted", "primary")
    for text_role in text_roles:
        ratio = contrast_ratio(palette[text_role], palette["background"])
        minimum = 3.0 if text_role == "primary" else 4.5
        if ratio < minimum:
            warnings.append(
                f"The requested {text_role} and background colors have a contrast ratio of {ratio:.2f}:1; "
                f"the recommended minimum is {minimum:.1f}:1."
            )
    return warnings


def request_frame_photos(deck: DeckPlan, manifest: TemplateManifest, limit: int = 4) -> None:
    """Designed bases with photo frames look empty without a photo: ask for one on those slides."""
    from docforge.render.pptx.clone import assign_bases
    from docforge.render.pptx.composer import effective_archetype

    bases = assign_bases([effective_archetype(sl) for sl in deck.slides], manifest)
    topic = " ".join(w for w in deck.title.replace(":", " ").split()[:6])
    added = 0
    for slide, base in zip(deck.slides, bases, strict=True):
        wants = base.photo_shapes or base.frame_shapes
        if not wants or any(isinstance(b, ImageBlock) for b in slide.blocks) or added >= limit:
            continue
        slide.blocks.append(ImageBlock(description=topic, alt_text=f"Photo illustrating {slide.headline}"))
        added += 1


def template_summary(manifest: TemplateManifest, name: str) -> str:
    """What the planner should know about a template: geometry, theme, layout vocabulary, design guide."""
    info = manifest.pptx
    if info.design_mode == "slides":
        kinds = [b.kind for b in info.slide_bases]
        lines = [
            f"Template '{name}': {info.slide_width / 914400:.2f} x {info.slide_height / 914400:.2f} in, "
            f"designed slides ({kinds.count('content')} content designs, cover"
            + (", closing" if "closing" in kinds else "")
            + ").",
            f"Fonts: {info.slide_fonts.get('heading', 'template heading')} / "
            f"{info.slide_fonts.get('body', 'template body')}.",
            "Each slide is built on one of these designs; content goes into the area the sample text used, "
            "which is smaller than a full slide. Keep it tight: headlines <= 8 words, at most 4 bullets of "
            "<= 12 words, at most 3 KPIs, 4 timeline events, 4 process steps, tables <= 5 rows x 4 columns.",
        ]
        for fname, text in list(manifest.design_guide.items())[:2]:
            lines.append(f"Design guide ({fname}):\n{text[:1500]}")
        if manifest.design_analysis is not None:
            lines.append(f"Template design analysis:\n{manifest.design_analysis.model_dump_json(indent=2)}")
        return "\n".join(lines)
    layouts = ", ".join(f"{lay.name} ({lay.archetype.value})" for lay in info.layouts)
    lines = [
        f"Template '{name}': {info.slide_width / 914400:.2f} x {info.slide_height / 914400:.2f} in, "
        f"heading font {manifest.theme.major_font}, body font {manifest.theme.minor_font}.",
        f"Layouts: {layouts}.",
        "Slides are rebuilt on these layouts; sample content is removed. "
        "Keep text concise for the template's title and body areas.",
    ]
    for fname, text in list(manifest.design_guide.items())[:2]:
        lines.append(f"Design guide ({fname}):\n{text[:1500]}")
    if manifest.design_analysis is not None:
        lines.append(f"Template design analysis:\n{manifest.design_analysis.model_dump_json(indent=2)}")
    return "\n".join(lines)
