import time
import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import httpx

from config import OLLAMA_BASE_URL, DEFAULT_LLM_MODEL
from database import get_db
from models import RAGRequest, SummariseRequest
from services.rag import stream_rag_response, summarise_document

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/query")
async def rag_query(body: RAGRequest):
    """Stream RAG response as Server-Sent Events."""
    return StreamingResponse(
        stream_rag_response(
            question=body.question,
            collection_id=body.collection_id,
            model=body.model,
            max_chunks=body.max_chunks,
            conversation_id=body.conversation_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/summarise/{doc_id}")
async def summarise(doc_id: str, body: SummariseRequest = SummariseRequest()):
    summary = await summarise_document(doc_id, body.model)
    # Persist summary
    db = get_db()
    db.execute("UPDATE documents SET summary=? WHERE id=?", (summary, doc_id))
    db.commit()
    db.close()
    return {"doc_id": doc_id, "summary": summary}


@router.get("/models")
async def list_models():
    """List available Ollama models."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            return {"models": models, "default": DEFAULT_LLM_MODEL}
    except Exception as e:
        return {"models": [], "default": DEFAULT_LLM_MODEL,
                "error": f"Ollama not reachable: {e}"}


@router.get("/status")
async def ai_status():
    """Check Ollama health."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            return {
                "ollama_online": True,
                "models": models,
                "embedding_ready": any("nomic" in m for m in models),
                "llm_ready": any(DEFAULT_LLM_MODEL.split(":")[0] in m for m in models),
            }
    except Exception:
        return {"ollama_online": False, "models": [], "embedding_ready": False, "llm_ready": False}
