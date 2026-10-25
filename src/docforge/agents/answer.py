"""AnswerAgent: replies in chat when the user asks a question instead of requesting a file (FR-CONV-2)."""

from __future__ import annotations

from pydantic import Field

from docforge.agents.base import UNTRUSTED_NOTE, Agent
from docforge.models.base import DFModel

SYSTEM = f"""You are DocForge, an assistant that creates PowerPoint decks, Word documents and Excel workbooks \
and can research topics. Answer the user's latest question briefly and helpfully (2-6 sentences, plain text, \
no markdown headings). Use the conversation, the active deliverable outline and the research notes. If the \
question is about what you can do, explain and suggest a concrete request they could send. If you do not know, \
say so; never invent facts or sources. {UNTRUSTED_NOTE}"""


class Answer(DFModel):
    text: str = Field(description="The reply shown to the user")
    suggestions: list[str] = Field(
        default_factory=list, description="Up to 3 short follow-up requests the user could send"
    )


class AnswerAgent(Agent[Answer]):
    name = "answer"
    output_type = Answer
    system_prompt = SYSTEM

    async def run(self, context: str, question: str) -> Answer:
        result = await self.ask(
            f"{context}\n\n<latest_user_message>\n{question}\n</latest_user_message>", temperature=0.3
        )
        assert result.parsed is not None
        return result.parsed
