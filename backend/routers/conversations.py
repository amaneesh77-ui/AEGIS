"""
Conversation memory API - list, resume, and manage persistent chat
sessions (essential requirement: multi-week query memory).
"""

from typing import Optional

from fastapi import APIRouter, HTTPException

from models import ConversationCreate, ConversationRename
from services import conversations as conv_service

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("")
def list_conversations(collection_id: Optional[str] = None, limit: int = 100):
    return conv_service.list_conversations(collection_id, limit)


@router.post("", status_code=201)
def create_conversation(body: ConversationCreate):
    return conv_service.create_conversation(body.collection_id, body.title or "New conversation")


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str):
    conv = conv_service.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv["messages"] = conv_service.get_messages(conversation_id)
    return conv


@router.patch("/{conversation_id}")
def rename_conversation(conversation_id: str, body: ConversationRename):
    if not conv_service.get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv_service.rename_conversation(conversation_id, body.title)
    return {"id": conversation_id, "title": body.title}


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str):
    conv_service.delete_conversation(conversation_id)
