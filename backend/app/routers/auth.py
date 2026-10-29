from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from .. import db
from ..models import LoginIn, RegisterIn
from ..security import (
    CurrentUser,
    audit,
    check_rate_limit,
    clear_session_cookie,
    get_current_user,
    hash_password,
    set_session_cookie,
    verify_password,
)
from ..security import EMAIL_RE
from .. import security

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _user_out(user: dict) -> dict:
    return {
        "id": str(user["_id"]),
        "email": user["email"],
        "name": user.get("name") or user["email"].split("@")[0],
        "role": user.get("role", "student"),
        "created_at": user.get("created_at").isoformat() if user.get("created_at") else None,
    }


@router.post("/register")
def register(payload: RegisterIn, request: Request, response: Response):
    check_rate_limit("register", _client_ip(request), limit=20)
    email = payload.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if db.users().find_one({"email": email}):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    is_first = db.users().count_documents({"is_eval": {"$ne": True}}) == 0
    user = {
        "email": email,
        "name": payload.name.strip(),
        "password_hash": hash_password(payload.password),
        "role": "admin" if is_first else "student",
        "disabled": False,
        "created_at": db.utcnow(),
    }
    user_id = db.users().insert_one(user).inserted_id
    user["_id"] = user_id
    set_session_cookie(response, security.create_token(str(user_id)))
    audit("auth.register", str(user_id), email=email, role=user["role"])
    return _user_out(user)


@router.post("/login")
def login(payload: LoginIn, request: Request, response: Response):
    email = payload.email.strip().lower()
    check_rate_limit("login", f"{_client_ip(request)}:{email}", limit=30)
    user = db.users().find_one({"email": email})
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        time.sleep(0.25)
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if user.get("disabled"):
        raise HTTPException(status_code=403, detail="This account has been disabled")
    set_session_cookie(response, security.create_token(str(user["_id"])))
    audit("auth.login", str(user["_id"]), email=email)
    return _user_out(user)


@router.post("/logout")
def logout(response: Response, user: CurrentUser = Depends(get_current_user)):
    clear_session_cookie(response)
    audit("auth.logout", user.id)
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    record = db.users().find_one({"_id": db.oid(user.id)})
    if not record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    return _user_out(record)
