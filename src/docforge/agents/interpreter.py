"""InterpreterAgent: turns a chat message plus context into an ``Interpretation`` (Stage 4, FR-CONV-2..7)."""

from __future__ import annotations

from dataclasses import dataclass, field

from docforge.agents.base import UNTRUSTED_NOTE, Agent
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
style_changes for pure formatting (fonts, sizes, colours); "unit" with targets for named \
slides/sections/sheets. \
Targets quote the user's own words in locator ("slide 4", "the revenue chart"). Only reference units that \
exist in the outline.
- research.depth: none when the user supplies all content or asks for formatting only; light for simple \
factual context; standard for typical business or academic topics; deep for market, scientific or policy \
analysis that must cite sources.
- confidence: your probability that this interpretation is what the user meant. Below 0.6, add \
clarification_questions with concrete options instead of guessing. Ask when a change is vague ("make it \
better") or would rewrite most of the artifact while the user named something narrower.
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
        result = await self.ask(render_input(inp), temperature=0.1)
        interp = result.parsed
        assert interp is not None
        known = {fid for fid, _, _ in inp.files}
        # Drop file references the model invented.
        interp.referenced_file_ids = [f for f in interp.referenced_file_ids if f in known]
        return interp
