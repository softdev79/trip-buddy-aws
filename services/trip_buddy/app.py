"""Trip Buddy public API + chat UI (FastAPI). The only service exposed through the load balancer."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent import GUIDE_URL, MCP_URL, run_agent
from rag import TravelNotebook
from sessions import SessionStore
from tripbuddy_shared.llm import get_embeddings, model_name, provider
from tripbuddy_shared.logs import get_logger, log_event

log = get_logger("trip_buddy.api")
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Trip Buddy", version="1.0.0")
sessions = SessionStore()
notebook = TravelNotebook(get_embeddings())


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=64)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    steps: list[dict]
    rag_hits: list[str]
    latency_ms: int


@app.get("/health")
async def health() -> dict:
    """Liveness for the ALB: the API process itself is up."""
    return {"status": "ok"}


@app.get("/health/deep")
async def deep_health() -> dict:
    """Readiness: can we reach the MCP server and the Local Guide agent?"""
    checks = {}
    async with httpx.AsyncClient(timeout=3) as client:
        for name, url in {"mcp": MCP_URL.rsplit("/mcp", 1)[0] + "/health", "guide": GUIDE_URL + "/health"}.items():
            try:
                checks[name] = (await client.get(url)).status_code == 200
            except httpx.HTTPError:
                checks[name] = False
    return {"status": "ok" if all(checks.values()) else "degraded", "checks": checks,
            "provider": provider(), "model": model_name(), "sessions": sessions.backend}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or uuid.uuid4().hex
    history = sessions.load(session_id)
    try:
        result = await run_agent(notebook, req.message, history)
    except Exception as exc:  # surfaced to the user as a 502, logged with the stack trace
        log.exception("agent_failed", extra={"fields": {"session_id": session_id}})
        raise HTTPException(status_code=502, detail="Trip Buddy could not answer right now.") from exc
    sessions.append(session_id, req.message, result.reply)
    log_event(log, "chat", session_id=session_id, latency_ms=result.latency_ms,
              tools=[s["tool"] for s in result.steps], rag_hits=result.rag_hits)
    return ChatResponse(session_id=session_id, reply=result.reply, steps=result.steps,
                        rag_hits=result.rag_hits, latency_ms=result.latency_ms)


@app.delete("/api/session/{session_id}")
async def reset(session_id: str) -> dict:
    sessions.clear(session_id)
    return {"cleared": session_id}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))
