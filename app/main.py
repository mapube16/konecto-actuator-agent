"""FastAPI application entry point: lifespan, endpoints, rate limiting, and global error handler."""

import json
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastmcp.utilities.lifespan import combine_lifespans
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.agent import build_agent
from app.cache import actuator_cache
from app.config import settings
from app.db.chroma import init_chroma_collection
from app.mcp_server import mcp_app

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(None, max_length=100, pattern=r"^[a-zA-Z0-9-]+$")


class ConversationResponse(BaseModel):
    answer: str
    session_id: str


@asynccontextmanager
async def agent_lifespan(app: FastAPI):
    try:
        init_chroma_collection(settings)
    except ValueError:
        # ingest not run yet — recommend will lazy-init and surface the same error on first call
        logger.warning("ChromaDB 'actuators' collection not found at boot — run scripts/ingest.py")
    async with AsyncSqliteSaver.from_conn_string(settings.memory_db_path) as memory:
        app.state.memory = memory
        app.state.agent = build_agent(memory)
        logger.info("Agent initialized")
        yield


app = FastAPI(title="Konecto Actuator Agent", lifespan=combine_lifespans(agent_lifespan, mcp_app.lifespan))
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.mount("/mcp", mcp_app)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"error": "Rate limit exceeded. Try again in 1 minute."})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log the exception type for debugging; don't leak it to the client (info disclosure).
    logger.exception("Unhandled exception")
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/cache/stats")
async def cache_stats():
    return {"actuator_cache": {"size": len(actuator_cache), "maxsize": actuator_cache.maxsize}}


@app.post("/api/conversation", response_model=ConversationResponse)
@limiter.limit(settings.rate_limit)
async def conversation(request: Request, req: QueryRequest):
    session_id = req.session_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}
    result = await app.state.agent.ainvoke(
        {"messages": [HumanMessage(content=req.query)]},
        config=config,
    )
    answer = result["messages"][-1].content
    return {"answer": answer, "session_id": session_id}


@app.post("/api/conversation/stream")
@limiter.limit(settings.rate_limit)
async def conversation_stream(request: Request, req: QueryRequest):
    session_id = req.session_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}

    async def event_generator():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
        try:
            async for event in app.state.agent.astream_events(
                {"messages": [HumanMessage(content=req.query)]},
                config=config,
                version="v2",
            ):
                kind = event["event"]
                if kind == "on_tool_start":
                    yield f"data: {json.dumps({'type': 'tool_start', 'name': event['name']})}\n\n"
                elif kind == "on_chat_model_stream":
                    token = event["data"]["chunk"].content
                    if token:
                        yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception:
            # Mirror the global handler: don't leak exception text or type over the stream.
            logger.exception("Streaming error")
            yield f"data: {json.dumps({'error': 'Internal server error'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
