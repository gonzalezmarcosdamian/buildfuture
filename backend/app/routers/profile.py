from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.auth import get_current_user
from app.models import UserProfile

router = APIRouter(prefix="/profile", tags=["profile"])


class ProfileUpdate(BaseModel):
    risk_profile: Optional[str] = None  # conservative | moderate | aggressive


@router.get("/")
def get_profile(user_id: str = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if not profile:
        return {"risk_profile": None}
    return {"risk_profile": profile.risk_profile}


@router.put("/")
def update_profile(
    data: ProfileUpdate,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if not profile:
        profile = UserProfile(user_id=user_id)
        db.add(profile)
    if data.risk_profile is not None:
        profile.risk_profile = data.risk_profile
    db.commit()
    db.refresh(profile)
    return {"risk_profile": profile.risk_profile}
