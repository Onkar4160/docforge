from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from docforge.models.base import DFModel


class PatchOp(DFModel):
    op: Literal["add", "remove", "replace", "move"]
    path: str = Field(description="JSON Pointer into the IR, e.g. '/slides/3/headline'.")
    value: Any = None
    from_: str | None = Field(None, alias="from")


class IRPatch(DFModel):
    base_version: int
    ops: list[PatchOp]
    affected_unit_ids: list[str]
    rationale: str = ""
