"""Provider-agnostic structured output: schema-in-prompt, tolerant JSON extraction, repair prompts."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def schema_instructions(model: type[BaseModel]) -> str:
    schema = json.dumps(model.model_json_schema(), separators=(",", ":"), ensure_ascii=False)
    return (
        "Respond with one JSON object that validates against the JSON Schema below. "
        "Output only the JSON: no prose, no markdown, no code fences. "
        "Use exactly the property names in the schema; omit optional fields you have no value for.\n"
        f"<json_schema>{schema}</json_schema>"
    )


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply that may wrap it in fences or surrounding prose."""
    candidate = text.strip()
    fenced = _FENCE.match(candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    start = min((i for i in (candidate.find("{"), candidate.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError("no JSON object found in reply")
    decoder = json.JSONDecoder()
    value, _ = decoder.raw_decode(candidate[start:])
    return value


def parse_structured(text: str, model: type[BaseModel]) -> BaseModel:
    """Raise ``ValueError`` with a model-readable message when the reply is not valid output."""
    try:
        data = extract_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"reply is not valid JSON: {exc}") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()[:8]
        )
        raise ValueError(f"JSON does not match the schema: {problems}") from exc


def repair_prompt(error: str) -> str:
    return (
        f"Your previous reply could not be used: {error}\n"
        "Return the complete corrected JSON object only, following the schema exactly."
    )
