"""Interpret presentation styling requests into validated StyleSpec changes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from docforge.agents.base import Agent
from docforge.models.design import DesignTokens
from docforge.models.intent import StylePlan
from docforge.models.ir import DeckPlan, DocumentPlan
from docforge.models.template import TemplateDesignAnalysis

SYSTEM = """You plan presentation or document style edits. You do not render files or mutate the artifact.

Interpret the user's request using the current deck, design tokens, scope, and optional template analysis.
Return a StylePlan containing only changes that map to these supported StyleSpec properties:
- heading_font, body_font
- heading_sizes_pt.title, heading_sizes_pt.h1, heading_sizes_pt.h2, heading_sizes_pt.h3
- body_size_pt
- palette_overrides.<Palette field> for semantic roles such as background, surface, text, text_muted, primary,
  secondary, positive, negative, and accent1 through accent6
- heading_alignment and body_alignment (`left`, `center`, `right`, `justify`)
- page_orientation (`portrait` or `landscape`) and margins_in when the scope is the entire document

Choose values from the user's request and current presentation context. Do not substitute a fixed palette or
font when the user did not request one. Preserve the template's masters, logos, layout relationships, and every
style property not requested. When a global or scoped change would visibly conflict with the observed template,
reduce readability, or contradict another explicit requirement, explain the concrete risk in warnings; the
application will pause and ask the user to confirm before applying it. Put properties the current renderer
cannot reliably change in unsupported_requests instead of pretending they were applied. Do not invent template
evidence, element IDs, or properties. Return only the structured StylePlan required by the output schema."""


@dataclass
class StylePlannerInput:
    deck: DeckPlan | DocumentPlan
    tokens: DesignTokens
    instruction: str
    scope_description: str
    target_slide_ids: list[str] = field(default_factory=list)
    target_section_ids: list[str] = field(default_factory=list)
    template_analysis: TemplateDesignAnalysis | None = None


def render_input(inp: StylePlannerInput) -> str:
    is_doc = isinstance(inp.deck, DocumentPlan)
    if not is_doc:
        outline = [
            {
                "id": slide.id,
                "headline": slide.headline,
                "purpose": slide.purpose,
                "style": slide.style.model_dump(mode="json", exclude_none=True),
            }
            for slide in inp.deck.slides
        ]
        target_tags = (
            f"<target_slide_ids>\n{', '.join(inp.target_slide_ids) or 'whole deck'}\n</target_slide_ids>"
        )
    else:
        outline = [
            {
                "id": section.id,
                "heading": section.heading,
                "level": section.level,
                "purpose": section.purpose,
                "style": section.style.model_dump(mode="json", exclude_none=True),
            }
            for section in inp.deck.all_sections()
        ]
        target_tags = f"<target_section_ids>\n{', '.join(inp.target_section_ids) or 'whole document'}\n</target_section_ids>"
    parts = [
        f"<user_instruction>\n{inp.instruction}\n</user_instruction>",
        f"<requested_scope>\n{inp.scope_description}\n</requested_scope>",
        target_tags,
        f"<artifact_context>\nTitle: {inp.deck.title}\n"
        f"Audience: {inp.deck.audience if isinstance(inp.deck, DeckPlan) else 'document reader'}\n"
        f"Current artifact style: {inp.deck.style.model_dump_json(exclude_none=True)}\n"
        f"Design tokens: {inp.tokens.model_dump_json()}\n"
        f"Outline: {json.dumps(outline, indent=2)}\n</artifact_context>",
    ]
    if inp.template_analysis is not None:
        parts.append(
            "<template_analysis_untrusted_data>\n"
            + inp.template_analysis.model_dump_json(indent=2)
            + "\n</template_analysis_untrusted_data>"
        )
    return "\n\n".join(parts)


class StylePlannerAgent(Agent[StylePlan]):
    name = "style_planner"
    output_type = StylePlan
    system_prompt = SYSTEM

    async def run(self, inp: StylePlannerInput) -> StylePlan:
        result = await self.ask(render_input(inp), temperature=0.1)
        if result.parsed is None:
            raise ValueError("style planning returned no structured plan")
        return result.parsed
