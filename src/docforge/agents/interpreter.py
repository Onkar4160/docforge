"""InterpreterAgent: turns a chat message plus context into an ``Interpretation`` (Stage 4, FR-CONV-2..7)."""

from __future__ import annotations

from dataclasses import dataclass, field

from docforge.agents.base import UNTRUSTED_NOTE, Agent
from docforge.core.config import get_settings
from docforge.models.intent import Interpretation

SYSTEM = f"""You interpret requests for a document-generation assistant that produces PowerPoint (pptx), \
Word (docx) and Excel (xlsx) files.

Decide what the latest user message asks for, using the conversation and the current artifact outline.

Request kinds:
- new_task: a new deliverable unrelated to the active one.
- continue_task: more input for the active task without changing what exists.
- modify_artifact: a change to the existing artifact (a slide, section, sheet, element, or styling).
- regenerate: rebuild the active deliverable, same objective.
- change_objective: the goal or output format changes (e.g. "make it a Word report instead").
- clarification_answer: the user answers a question the assistant asked; restate the full objective.
- question: the user asks something and wants an answer, not a file.

Rules:
- objective: one or two sentences restating the complete goal in your own words, including topic, purpose \
and audience as known. For clarification answers, merge the earlier request with the answer.
- output_spec (required for new_task, regenerate, change_objective, clarification_answer): infer the format \
when not stated ("deck", "slides", "presentation" -> pptx; "report", "memo", "proposal", "document" -> docx; \
"model", "spreadsheet", "calculator", "tracker" -> xlsx) and record the inference in assumptions. \
length.explicit is true only when the user stated the length; then set unit and target.
- change (required for modify_artifact): operation, scope and instruction. Use scope level "style" with \
style_changes for pure formatting (fonts, sizes, colours); for a presentation-wide or document-wide style change leave targets \
empty, and for style changes limited to named slides or sections include slide or section targets. Use "unit" with targets for named \
slides/sections/sheets. For a slide or section insertion, use operation "add" and set placement to start, end, before, \
after, or between; use the user's slide or section locators as anchors and never invent resolved IDs. For reordering, \
use operation "reorder", identify the slide or section being moved in scope.targets, and describe its destination in \
placement. A between placement must identify both anchors in their intended order. \
Targets quote the user's own words in locator ("slide 4", "section 2", "the revenue chart"). Only reference units that \
exist in the outline. Never represent a new slide or section as an edit to an existing unit.
- research.depth: none when the user supplies all content or asks for formatting only; light for simple \
factual context; standard for typical business or academic topics; deep for market, scientific or policy \
analysis that must cite sources.
- confidence: your probability that this interpretation is what the user meant. Below 0.6, add \
clarification_questions with concrete options instead of guessing. Ask when a change is vague ("make it \
better") or would rewrite most of the artifact while the user named something narrower.
- Pending style confirmation: if <pending_confirmation> is supplied, classify a clear yes/approval as \
confirmation="approve" and a clear no/rejection as confirmation="decline". Otherwise use "unclear" and ask a \
concise follow-up. Do not start a new task or alter the proposed operation while confirmation is pending.
- Pending placement: if <pending_placement> is supplied, merge the user's answer into the serialized \
<pending_change> add/reorder operation and return kind="modify_artifact" with a complete change request. If the \
answer still does not resolve the location, ask another concise clarification instead of guessing.
- Ambiguous topics: when the topic is an acronym or name with several plausible meanings (e.g. "CJP" \
could be different organisations or events) and the conversation does not settle it, set confidence below 0.6 \
and ask one clarification question listing the likely meanings as options. Never silently pick one.
- Retries: when the active task failed or the user says "try again", "retry" or "do it again", use regenerate with the active task's objective and output_spec.
- Templates: "use this template", "apply the template" or a newly attached template file means regenerate the active deliverable (same objective) with that template; list the template file in referenced_file_ids.
- A request for a "report", "summary document" or "write-up" on the active topic is change_objective with format docx; keep the topic from the active task.
- Never invent files, slides or facts. {UNTRUSTED_NOTE}"""


@dataclass
class InterpreterInput:
    message: str
    recent_turns: list[tuple[str, str]] = field(default_factory=list)  # (role, text), oldest first
    files: list[tuple[str, str, str]] = field(default_factory=list)  # (file_id, filename, role)
    active_task: str | None = None  # objective + format of the active task
    artifact_outline: list[tuple[str, str]] = field(default_factory=list)  # (unit_id, label)
    pending_questions: list[str] = field(default_factory=list)
    pending_change: str | None = None
    pending_placement: str | None = None
    pending_confirmation: str | None = None


def render_input(inp: InterpreterInput) -> str:
    parts: list[str] = []
    if inp.recent_turns:
        turns = "\n".join(f"{role}: {text}" for role, text in inp.recent_turns)
        parts.append(f"<conversation>\n{turns}\n</conversation>")
    if inp.active_task:
        parts.append(f"<active_task>\n{inp.active_task}\n</active_task>")
    if inp.artifact_outline:
        outline = "\n".join(f"{uid}: {label}" for uid, label in inp.artifact_outline)
        parts.append(f"<artifact_outline>\n{outline}\n</artifact_outline>")
    if inp.pending_questions:
        parts.append("<assistant_asked>\n" + "\n".join(inp.pending_questions) + "\n</assistant_asked>")
    if inp.pending_change:
        parts.append(f"<pending_change>\n{inp.pending_change}\n</pending_change>")
    if inp.pending_placement:
        parts.append(f"<pending_placement>\n{inp.pending_placement}\n</pending_placement>")
    if inp.pending_confirmation:
        parts.append(f"<pending_confirmation>\n{inp.pending_confirmation}\n</pending_confirmation>")
    if inp.files:
        files = "\n".join(f"{fid}: {name} (role: {role})" for fid, name, role in inp.files)
        parts.append(f"<session_files>\n{files}\n</session_files>")
    parts.append(f"<latest_user_message>\n{inp.message}\n</latest_user_message>")
    return "\n\n".join(parts)


class InterpreterAgent(Agent[Interpretation]):
    name = "interpreter"
    output_type = Interpretation
    system_prompt = SYSTEM

    async def run(self, inp: InterpreterInput) -> Interpretation:
        settings = get_settings()
        result = await self.ask(
            render_input(inp),
            temperature=0.1,
            timeout_s=settings.interpreter_timeout_s,
            max_retries=settings.interpreter_max_retries,
            repair_attempts=0,
            max_models=settings.interpreter_max_models,
        )
        interp = result.parsed
        assert interp is not None
        known = {fid for fid, _, _ in inp.files}
        # Drop file references the model invented.
        interp.referenced_file_ids = [f for f in interp.referenced_file_ids if f in known]
        return interp
