"""Ephemeral Film Assistant endpoints (Phase 7).

The Film Assistant no longer writes a conversation per chat: the transcript
lives on the client (sessionStorage) and every turn is a stateless request.
Nothing touches `conversations`/`messages`, so "ending" the chat is just the
client discarding its transcript, and the assistant never pollutes the
reflection history or the Discover grid.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from ..deps import get_current_user
from .conversations import discovery_opening, discovery_turn

router = APIRouter()


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content cannot be blank")
        return value


class ChatBody(BaseModel):
    # Full transcript, oldest first: the client owns it and re-sends it each
    # turn (the server bounds the LLM window, but the client needs the whole
    # thread to re-render after a reload).
    messages: list[ChatMessage] = Field(min_length=1)


@router.post("/opening")
def opening(current: dict = Depends(get_current_user)) -> dict:
    return {"reply": discovery_opening(current["id"])}


@router.post("/chat")
def chat(body: ChatBody, current: dict = Depends(get_current_user)) -> dict:
    history = [{"role": m.role, "content": m.content} for m in body.messages]
    return discovery_turn(current["id"], history)