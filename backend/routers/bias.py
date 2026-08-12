"""Cultural/language bias detection + offline translation API (desirable requirement)."""

from fastapi import APIRouter, HTTPException

from database import get_db
from models import BiasPolicyUpdate, TranslateRequest
from services import bias as bias_service
from services import translate as translate_service

router = APIRouter(prefix="/api/bias", tags=["bias"])


@router.get("/audit/{collection_id}")
def audit(collection_id: str):
    db = get_db()
    exists = db.execute("SELECT 1 FROM collections WHERE id=?", (collection_id,)).fetchone()
    db.close()
    if not exists:
        raise HTTPException(status_code=404, detail="Collection not found")
    return bias_service.corpus_language_audit(collection_id)


@router.put("/policy")
def set_policy(body: BiasPolicyUpdate):
    return bias_service.set_collection_settings(body.collection_id, body.bias_policy, body.vendor_country)


@router.get("/policy/{collection_id}")
def get_policy(collection_id: str):
    return bias_service.get_collection_settings(collection_id)


@router.post("/translate")
def translate(body: TranslateRequest):
    return translate_service.translate_text(body.text, body.target_lang, body.source_lang)


@router.get("/translate/languages")
def translate_languages():
    return {"languages": translate_service.available_languages()}
