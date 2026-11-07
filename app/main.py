import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.rag import BanglaRAG

logger = logging.getLogger("beneco")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup: load the model and database, keep them in memory."""
    app.state.rag = BanglaRAG()
    yield


app = FastAPI(
    title="Beneco Bangla Chatbot API",
    description="Bangla RAG assistant for Beneco Financial Services",
    version="0.1.0",
    lifespan=lifespan,
)

# allow a web page on another domain to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # demo only; restrict to Beneco's domain before going live
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- request / response shapes ----------
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000, examples=["remortgage ki?"])


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    used_llm: bool


# ---------- routes ----------
@app.get("/health")
def health():
    """Check the service is running and the database is loaded."""
    return {"status": "ok", "chunks": app.state.rag.collection.count()}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """Send a customer question, get a Bangla answer with sources."""
    try:
        return app.state.rag.answer(request.message.strip())
    except Exception:
        logger.exception("Chat failed")
        raise HTTPException(
            status_code=503,
            detail="The assistant is temporarily unavailable. Please call 020 8050 2478.",
        )