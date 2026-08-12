"""
RAG controller - retrieves relevant chunks, builds the prompt, streams the
local LLM response via Ollama, and runs a pre-publish confidence/validation
pass over the result.

Directly implements three essential HMGCC requirements:
  - "Check and validate responses before publishing" (services/confidence.py
    validate_answer, run after generation, before the answer is considered
    final).
  - "Flag a confidence score and if more source data is required"
    (services/confidence.py retrieval_confidence, computed before generation
    from retrieval evidence).
  - "Keep a memory of queries so conversations can be continued over
    several weeks" (services/conversations.py - every turn is persisted to
    SQLite and prior turns are fed back in as context).
"""

from __future__ import annotations
import json
import time
import uuid
from typing import AsyncIterator, List, Optional

import httpx

from config import OLLAMA_BASE_URL, DEFAULT_LLM_MODEL, MAX_CONTEXT_CHUNKS
from database import get_db
from services.search_engine import get_chunks_for_rag
from services.confidence import retrieval_confidence, validate_answer
from services import conversations as conv_service
from services import profile as profile_service
from services import bias as bias_service

SYSTEM_PROMPT = """You are a technical research assistant helping a security researcher
understand complex industrial control system documentation.

STRICT RULES:
1. Answer ONLY using the provided source documents below (and, if given, the recent conversation history for context only).
2. If the answer cannot be found in the sources, say exactly: "I cannot find this information in the indexed documents."
3. Always cite which source document your information comes from using [Source: filename, p.N].
4. Do not speculate. If you must synthesise/infer across multiple sources rather than quote one directly, say so explicitly (e.g. "Inferred from Source 1 and 3: ...").
5. If sources contradict each other, or more than one plausible interpretation exists, surface each hypothesis explicitly rather than silently picking one.
6. If the retrieved evidence is weak or thin, say so plainly and suggest what additional source material would help, rather than answering confidently.
7. Keep responses concise and technically precise.

SOURCE DOCUMENTS:
"""


def _build_prompt(question: str, chunks: List[dict], history: List[dict], confidence: dict) -> str:
    context_parts = []
    for i, chunk in enumerate(chunks):
        fname  = chunk.get("doc_title") or chunk.get("filename", "Unknown")
        page   = chunk.get("page_number", 0)
        # Truncate each chunk to keep total prompt small enough for CPU inference
        text   = chunk.get("text", "")[:400]
        context_parts.append(f"[Source {i+1}: {fname}, page {page}]\n{text}")

    context = "\n\n---\n\n".join(context_parts)

    history_block = ""
    if history:
        turns = []
        for h in history:
            role = "Researcher" if h["role"] == "user" else "Assistant"
            turns.append(f"{role}: {h['content'][:300]}")
        history_block = (
            "RECENT CONVERSATION HISTORY (context only - the source documents above "
            "still take priority for factual claims):\n" + "\n".join(turns) + "\n\n"
        )

    hedge = ""
    if confidence.get("level") in ("low", "medium"):
        hedge = (
            f"\nNOTE: Retrieval confidence for this query is '{confidence.get('level')}'. "
            "Be explicit about uncertainty and what additional source data would help.\n"
        )

    return f"{SYSTEM_PROMPT}{context}\n{hedge}\n{history_block}QUESTION: {question}\n\nANSWER:"


async def stream_rag_response(
    question: str,
    collection_id: Optional[str] = None,
    model: Optional[str] = None,
    max_chunks: int = MAX_CONTEXT_CHUNKS,
    conversation_id: Optional[str] = None,
) -> AsyncIterator[str]:
    """
    Async generator that yields SSE-formatted strings:
      data: {"type":"meta","data":{"conversation_id":...,"title":...}}
      data: {"type":"sources","data":[...]}
      data: {"type":"confidence","data":{...}}
      data: {"type":"coverage","data":{...}}
      data: {"type":"token","data":"..."}
      data: {"type":"validation","data":{...}}
      data: {"type":"done"}
      data: {"type":"error","data":"..."}
    """
    model = model or DEFAULT_LLM_MODEL

    # 0. Persistent conversation memory - resume if given, else start a new
    # one so every query is always recorded (essential requirement).
    conv = conv_service.get_or_create_conversation(conversation_id, collection_id, question[:80])
    history = conv_service.get_recent_history(conv["id"])
    yield f"data: {json.dumps({'type': 'meta', 'data': {'conversation_id': conv['id'], 'title': conv['title']}})}\n\n"

    try:
        profile_service.record_query_topics(question)
    except Exception:
        pass

    # 1. Retrieve chunks
    chunks = get_chunks_for_rag(question, collection_id, max_chunks)

    sources = [
        {
            "chunk_id":   c["chunk_id"],
            "doc_id":     c["doc_id"],
            "doc_title":  c.get("doc_title", c.get("filename", "")),
            "page_number": c.get("page_number", 0),
            "score":      c.get("score", 0.0),
        }
        for c in chunks
    ]
    yield f"data: {json.dumps({'type': 'sources', 'data': sources})}\n\n"

    # 2. Confidence score + "need more data" flag, computed from retrieval
    # evidence alone (essential requirement).
    confidence = retrieval_confidence(chunks)
    yield f"data: {json.dumps({'type': 'confidence', 'data': confidence})}\n\n"

    # 3. Per-answer language/cultural coverage label (desirable requirement)
    try:
        coverage = bias_service.coverage_label_for_chunks(chunks)
        if coverage:
            yield f"data: {json.dumps({'type': 'coverage', 'data': coverage})}\n\n"
    except Exception:
        pass

    if not chunks:
        fallback = (
            "I cannot find this information in the indexed documents. No relevant "
            "material was retrieved for this query - consider loading additional "
            "source data before drawing conclusions."
        )
        yield f"data: {json.dumps({'type':'token','data':fallback})}\n\n"
        try:
            conv_service.add_message(conv["id"], "user", question)
            conv_service.add_message(conv["id"], "assistant", fallback, sources=[], confidence=confidence)
        except Exception:
            pass
        yield f"data: {json.dumps({'type':'done'})}\n\n"
        return

    # 4. Build prompt (with conversation history + confidence-aware hedging)
    prompt = _build_prompt(question, chunks, history, confidence)

    # 5. Stream from Ollama, accumulating the full answer for validation
    full_answer_parts: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": True,
                    "options": {
                        "temperature": 0.1,
                        "num_ctx": 2048,
                    },
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        token = obj.get("response", "")
                        if token:
                            full_answer_parts.append(token)
                            yield f"data: {json.dumps({'type':'token','data':token})}\n\n"
                        if obj.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue

    except httpx.ConnectError:
        yield f"data: {json.dumps({'type':'error','data':'Cannot connect to Ollama. Is it running? Run: ollama serve'})}\n\n"
        yield f"data: {json.dumps({'type':'done'})}\n\n"
        return
    except Exception as exc:
        yield f"data: {json.dumps({'type':'error','data':str(exc)})}\n\n"
        yield f"data: {json.dumps({'type':'done'})}\n\n"
        return

    full_answer = "".join(full_answer_parts)

    # 6. Pre-publish validation pass - grounding check + Known/Inferred/
    # Uncertain classification (essential requirement).
    validation = validate_answer(full_answer, chunks)
    yield f"data: {json.dumps({'type': 'validation', 'data': validation})}\n\n"

    # 7. Persist this turn to the conversation (essential requirement)
    try:
        conv_service.add_message(conv["id"], "user", question)
        conv_service.add_message(
            conv["id"], "assistant", full_answer,
            sources=sources, confidence={**confidence, "validation": validation},
        )
    except Exception:
        pass

    # 8. Audit log
    try:
        db = get_db()
        db.execute(
            "INSERT INTO audit_log VALUES (?,?,?,?)",
            (str(uuid.uuid4()), "RAG_QUERY",
             json.dumps({"question": question[:200], "source_count": len(chunks),
                         "confidence": confidence.get("level")}),
             int(time.time())),
        )
        db.commit()
        db.close()
    except Exception:
        pass

    yield f"data: {json.dumps({'type':'done'})}\n\n"


async def summarise_document(doc_id: str, model: Optional[str] = None) -> str:
    """Generate a short summary of a document using the LLM."""
    model = model or DEFAULT_LLM_MODEL
    db = get_db()
    chunks = db.execute(
        "SELECT text FROM chunks WHERE doc_id=? ORDER BY chunk_index LIMIT 6", (doc_id,)
    ).fetchall()
    db.close()

    if not chunks:
        return "No text available to summarise."

    text_sample = "\n\n".join(r["text"] for r in chunks)[:6000]
    prompt = (
        "You are a technical document analyst. Summarise the following technical "
        "document in 3-5 sentences, focusing on: what the component or system is, "
        "its key specifications, and any notable security-relevant details.\n\n"
        f"DOCUMENT:\n{text_sample}\n\nSUMMARY:"
    )

    # Generous read timeout: CPU-only inference over a full document's worth
    # of context can legitimately take minutes (cold model load + longer
    # prompts for bigger documents both add up) - a short timeout here was
    # firing as a bare httpx.ReadTimeout with an *empty* message, which made
    # "Summarisation failed: " look like a mystery blank error in the UI/DB.
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.2, "num_ctx": 4096}},
            )
            r.raise_for_status()
            return r.json().get("response", "").strip()
    except httpx.HTTPStatusError as exc:
        return f"Summarisation failed: Ollama returned HTTP {exc.response.status_code}: {exc.response.text[:200]}"
    except httpx.TimeoutException:
        return ("Summarisation failed: timed out waiting for Ollama (>300s). The model may still be "
                "loading, or the machine is overloaded - try again in a moment.")
    except httpx.ConnectError:
        return "Summarisation failed: could not connect to Ollama - is it running (ollama serve)?"
    except Exception as exc:
        # Always include the exception type - some exceptions (e.g. bare
        # httpx.ReadTimeout) stringify to an empty message on their own.
        detail = str(exc) or "no further details"
        return f"Summarisation failed: {type(exc).__name__}: {detail}"
