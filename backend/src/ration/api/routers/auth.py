"""Sign in, sign out, and report who is signed in."""

from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from ration.api.deps import CurrentUserDep, SessionDep, SettingsDep
from ration.api.errors import unauthorized
from ration.api.security import DUMMY_HASH, SessionCodec, verify_password
from ration.config import SESSION_COOKIE_NAME
from ration.repositories import models

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class CurrentUserResponse(BaseModel):
    id: str
    display_name: str
    role: str
    profile_id: str
    locale: str


@router.post("/auth/login", status_code=204, operation_id="login")
def login(
    body: LoginRequest,
    response: Response,
    session: SessionDep,
    config: SettingsDep,
) -> None:
    user = session.scalars(
        select(models.User).where(models.User.email == str(body.email))
    ).one_or_none()

    # Verify even when the account is absent, so the response time does not
    # reveal which addresses exist.
    password_hash = user.password_hash if user else DUMMY_HASH
    if not verify_password(body.password, password_hash) or user is None:
        raise unauthorized("Email or password is incorrect")

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=SessionCodec(config).issue(user.id),
        max_age=config.session_max_age_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=config.cookies_require_https,
        path="/",
    )


@router.post("/auth/logout", status_code=204, operation_id="logout")
def logout(
    response: Response,
    _user: CurrentUserDep,
    config: SettingsDep,
) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=config.cookies_require_https,
        path="/",
    )


@router.get("/auth/me", operation_id="getCurrentUser")
def get_current_user(user: CurrentUserDep) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user.id,
        display_name=user.display_name,
        role=user.role,
        profile_id=user.profile_id,
        locale=user.locale,
    )
