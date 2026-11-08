import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.leads import update_lead
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
    version="0.3.0",
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
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=4000)


class Lead(BaseModel):
    """What we know about the customer so far (kept in their browser)."""
    name: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=30)
    email: str | None = Field(None, max_length=200)
    declined: list[Literal["name", "phone", "email"]] = Field(default_factory=list, max_length=3)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000, examples=["remortgage ki?"])
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    lead: Lead = Field(default_factory=Lead)


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    used_llm: bool
    lead: Lead


# ---------- routes ----------
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", response_class=FileResponse)
def home():
    """The chat page."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    """Check the service is running and the database is loaded."""
    return {"status": "ok", "chunks": app.state.rag.collection.count()}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """Send a customer question plus recent history and customer record;
    get a Bangla answer, sources and the updated customer record."""
    try:
        message = request.message.strip()
        history = [m.model_dump() for m in request.history]

        # update the customer record from this message (name, phone, email, "no")
        lead, is_new_contact = update_lead(request.lead.model_dump(), message, history)
        # is_new_contact will trigger the lead email in the next step

        result = app.state.rag.answer(message, history, lead)
        return {**result, "lead": lead}
    except Exception:
        logger.exception("Chat failed")
        raise HTTPException(
            status_code=503,
            detail="The assistant is temporarily unavailable. Please call 020 8050 2478.",
        )