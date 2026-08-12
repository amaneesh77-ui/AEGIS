"""User profile / adaptation API (desirable requirement)."""

from fastapi import APIRouter

from models import ProfileUpdate
from services import profile as profile_service

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("")
def get_profile():
    profile = profile_service.get_profile()
    profile["frequent_topics"] = profile_service.frequent_topics()
    profile["suggestion"] = profile_service.proactive_suggestion()
    return profile


@router.put("")
def update_profile(body: ProfileUpdate):
    return profile_service.update_profile(body.answer_style, body.proactive_suggestions)
