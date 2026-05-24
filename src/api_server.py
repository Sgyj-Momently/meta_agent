"""FastAPI entrypoint for the meta agent."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field
from prometheus_fastapi_instrumentator import Instrumentator

from .error_envelope import install_envelope_handlers
from .meta_generator import generate_meta

app = FastAPI(title="Meta Agent API", version="0.1.0")

# ADR 005 표준 에러 envelope 등록.
install_envelope_handlers(app)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


class MetaRequest(BaseModel):
    project_id: str = Field(min_length=1)
    final_markdown: str
    target_keywords: str | None = None
    photos: list[dict[str, Any]] = Field(default_factory=list)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "meta_agent"}


@app.post("/api/v1/meta")
def create_meta(request: MetaRequest) -> dict[str, Any]:
    return {"project_id": request.project_id, **generate_meta(request.model_dump())}
