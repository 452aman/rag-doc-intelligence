"""Accounts: registration, login, refresh, and the current-user dependency."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import Conversation, Document, User, get_db

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
ALGO = "HS256"


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    model_config = {"from_attributes": True}


def _token(uid: int, kind: str, delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(uid), "type": kind, "iat": now, "exp": now + delta}, get_settings().secret_key, algorithm=ALGO)


def _pair(u: User) -> dict:
    s = get_settings()
    return {"access_token": _token(u.id, "access", timedelta(minutes=s.access_token_minutes)),
            "refresh_token": _token(u.id, "refresh", timedelta(days=s.refresh_token_days)), "token_type": "bearer"}


def _decode(token: str, kind: str) -> int:
    payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGO])
    if payload.get("type") != kind:
        raise jwt.InvalidTokenError("wrong token type")
    return int(payload["sub"])


def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    try:
        uid = _decode(token, "access")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


@router.post("/register", response_model=UserOut, status_code=201)
@limiter.limit("10/minute")
def register(request: Request, body: RegisterIn, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "Email already registered")
    first_user = db.scalar(select(User.id).limit(1)) is None
    u = User(name=body.name, email=body.email.lower(), hashed_password=bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode())
    db.add(u)
    db.flush()
    if first_user:  # data created before accounts existed is adopted by the first account, so nothing is orphaned
        db.execute(update(Document).where(Document.owner_id.is_(None)).values(owner_id=u.id))
        db.execute(update(Conversation).where(Conversation.owner_id.is_(None)).values(owner_id=u.id))
    db.commit()
    return u


@router.post("/login")
@limiter.limit("20/minute")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == form.username.lower()))
    if not u or not bcrypt.checkpw(form.password.encode(), u.hashed_password.encode()):
        raise HTTPException(401, "Incorrect email or password")
    return _pair(u)


@router.post("/refresh")
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    try:
        uid = _decode(body.refresh_token, "refresh")
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid refresh token")
    u = db.get(User, uid)
    if not u:
        raise HTTPException(401, "User not found")
    return _pair(u)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
