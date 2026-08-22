"""Pydantic schemas for the support API (api/support/)."""

from typing import Optional

from pydantic import BaseModel


class OpenConversationRequest(BaseModel):
    project_id: Optional[int] = None
    category: Optional[str] = None


class SendMessageRequest(BaseModel):
    message: str


class TypingRequest(BaseModel):
    pass  # empty body — presence is the signal


class AdminReplyRequest(BaseModel):
    message: str


class AdminNoteRequest(BaseModel):
    note: str


class PriorityRequest(BaseModel):
    priority: str  # low | normal | high | urgent


class AssignRequest(BaseModel):
    admin_id: Optional[int] = None


class HandBackRequest(BaseModel):
    note: Optional[str] = None
