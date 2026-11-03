"""User-controlled memory review endpoints (F3, D12)."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from .. import memories as memory_svc
from ..deps import get_current_user

router = APIRouter()


class ReviewMemoryBody(BaseModel):
    """A proposed memory may be confirmed (optionally edited) or rejected."""

    status: Literal["confirmed", "rejected"]
    content: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Memory content cannot be blank")
        return value

    @model_validator(mode="after")
    def reject_cannot_edit(self):
        if self.status == "rejected" and self.content is not None:
            raise ValueError("Rejected memories cannot be edited")
        return self


@router.get("")
def list_memories(
    status: Literal["proposed", "confirmed", "rejected"] | None = None,
    current: dict = Depends(get_current_user),
) -> dict:
    return {"memories": memory_svc.list_for_user(current["id"], status)}


@router.patch("/{memory_id}")
def review_memory(
    memory_id: UUID,
    body: ReviewMemoryBody,
    current: dict = Depends(get_current_user),
) -> dict:
    memory_id_text = str(memory_id)
    memory = memory_svc.get_owned(memory_id_text, current["id"])
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    if memory["status"] != "proposed":
        raise HTTPException(
            status_code=409, detail="Only proposed memories can be reviewed"
        )
    updated = memory_svc.review(memory_id_text, body.status, body.content)
    return {"memory": memory_svc.serialise_rows([updated], current["id"])[0]}
