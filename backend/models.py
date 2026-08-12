from pydantic import BaseModel, Field
from typing import Optional, List


# ── Collections ──────────────────────────────────────────────────────────────

class CollectionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    owner: str = "researcher"
    vendor_country: Optional[str] = None      # e.g. "Germany" - used for cultural/bias coverage checks
    bias_policy: str = "suggestive"            # off | suggestive | proactive


class CollectionOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    created_at: int
    owner: str
    doc_count: int = 0


# ── Documents ─────────────────────────────────────────────────────────────────

class DocumentOut(BaseModel):
    id: str
    collection_id: str
    filename: str
    title: Optional[str]
    author: Optional[str]
    doc_type: str
    manufacturer: Optional[str]
    part_number: Optional[str]
    page_count: int
    word_count: int
    ingest_status: str
    ingest_error: Optional[str]
    summary: Optional[str]
    created_at: int


# ── Search ────────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    collection_id: Optional[str] = None
    mode: str = "hybrid"          # hybrid | keyword | semantic
    limit: int = Field(default=20, le=100)
    doc_type: Optional[str] = None
    manufacturer: Optional[str] = None


class SearchHit(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: Optional[str]
    filename: str
    page_number: int
    text: str
    score: float
    source: str                   # keyword | semantic | hybrid


# ── AI / RAG ──────────────────────────────────────────────────────────────────

class RAGRequest(BaseModel):
    question: str
    collection_id: Optional[str] = None
    model: Optional[str] = None
    max_chunks: int = Field(default=8, le=20)
    conversation_id: Optional[str] = None   # resume a persistent conversation


class SummariseRequest(BaseModel):
    model: Optional[str] = None


# ── Conversations ─────────────────────────────────────────────────────────────

class ConversationCreate(BaseModel):
    collection_id: Optional[str] = None
    title: Optional[str] = None


class ConversationRename(BaseModel):
    title: str


# ── User profile ──────────────────────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    answer_style: Optional[str] = None      # concise | detailed
    proactive_suggestions: Optional[bool] = None


# ── Bias / cultural coverage ──────────────────────────────────────────────────

class BiasPolicyUpdate(BaseModel):
    collection_id: str
    bias_policy: str = "suggestive"         # off | suggestive | proactive
    vendor_country: Optional[str] = None


class TranslateRequest(BaseModel):
    text: str
    source_lang: Optional[str] = None       # auto-detected if omitted
    target_lang: str = "en"


# ── Annotations ───────────────────────────────────────────────────────────────

class AnnotationCreate(BaseModel):
    doc_id: str
    chunk_id: Optional[str] = None
    kind: str = "note"            # note | highlight | bookmark | flag
    note: Optional[str] = None
    colour: str = "yellow"
