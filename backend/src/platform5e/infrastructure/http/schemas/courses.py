"""Esquemas de cursos, unidades y resultados de aprendizaje."""

from __future__ import annotations

from pydantic import Field

from platform5e.infrastructure.http.schemas.common import ApiRequest, ApiResponse


class LearningOutcomeInput(ApiRequest):
    id: str | None = Field(default=None, description="Keep it when editing; omit it for a new outcome.")
    code: str | None = Field(default=None, max_length=20, examples=["RA1"])
    text: str = Field(min_length=1, max_length=400, examples=["Distingue los protocolos TCP y UDP."])


class CourseUnitInput(ApiRequest):
    id: str | None = Field(default=None, description="Keep it when editing; omit it for a new unit.")
    title: str = Field(min_length=1, max_length=150, examples=["Capa de transporte"])
    outcomes: list[LearningOutcomeInput] | None = Field(default=None, max_length=20)


class CourseInput(ApiRequest):
    code: str = Field(min_length=1, max_length=30, description="Unique per teacher.", examples=["RED-301"])
    name: str = Field(min_length=1, max_length=150, examples=["Redes de computadoras"])
    term: str = Field(min_length=1, max_length=30, examples=["2026-II"])
    summary: str | None = Field(default=None, max_length=3000, description="Official course summary (sumilla).")
    learning_goal: str | None = Field(default=None, max_length=1000, description="Course learning goal (logro).")
    units: list[CourseUnitInput] = Field(
        min_length=1, max_length=50, description="Existing units must be sent back with their id."
    )


class LearningOutcomeResponse(ApiResponse):
    id: str
    code: str | None = None
    text: str


class UnitResponse(ApiResponse):
    id: str
    course_id: str
    number: int = Field(description="Position of the unit in the course, from 1.")
    title: str
    outcomes: list[LearningOutcomeResponse] = []


class CourseResponse(ApiResponse):
    id: str
    code: str
    name: str
    term: str
    summary: str | None = None
    learning_goal: str | None = None
    units: list[UnitResponse]
