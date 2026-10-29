from __future__ import annotations

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=80)


class LoginIn(BaseModel):
    email: str
    password: str


class SessionCreate(BaseModel):
    document_ids: list[str] = Field(default_factory=list)
    collection_id: str | None = None
    title: str | None = None


class SessionPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    document_ids: list[str] | None = None
    collection_id: str | None = None


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class FeedbackIn(BaseModel):
    rating: int = Field(ge=-1, le=1)
    comment: str | None = Field(default=None, max_length=2000)


class CollectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class CollectionDocsIn(BaseModel):
    document_ids: list[str]


class DocumentPatch(BaseModel):
    category: str | None = None
    title: str | None = Field(default=None, max_length=300)


class StudyRequest(BaseModel):
    focus: str | None = Field(default=None, max_length=500)
    count: int = Field(default=12, ge=4, le=30)
    difficulty: str = Field(default="intermediate")


class QuizSubmit(BaseModel):
    answers: list[str]
    student_name: str | None = None


