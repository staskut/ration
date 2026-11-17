"""Sign in, sign out, and report who is signed in."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from ration.api.deps import CurrentUserDep, SessionDep, SettingsDep
from ration.api.errors import forbidden, unauthorized
from ration.api.security import DUMMY_HASH, SessionCodec, verify_password
from ration.config import FOLLOWER_EMAIL, PLANNER_EMAIL, SESSION_COOKIE_NAME
from ration.repositories import models

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class DemoSignInRequest(BaseModel):
    role: Literal["planner", "follower"]


class DemoAccessResponse(BaseModel):
    available: bool
    roles: list[str]


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


def _demo_accounts(session: SessionDep, config: SettingsDep) -> dict[str, models.User]:
    """The seeded accounts, when signing in as one of them is allowed at all.

    Two conditions, and both matter. Production is excluded because the seed
    refuses to run there, so a demo account in a production database would
    mean something had already gone wrong — this must not be the thing that
    makes it exploitable. And the accounts have to actually exist: an
    environment that has never been seeded offers no demo, rather than
    offering a button that 403s.
    """
    if config.is_production:
        return {}
    rows = session.scalars(
        select(models.User).where(models.User.email.in_([PLANNER_EMAIL, FOLLOWER_EMAIL]))
    ).all()
    found = {row.role: row for row in rows}
    return found if len(found) == 2 else {}


@router.get("/auth/demo", operation_id="getDemoAccess")
def get_demo_access(session: SessionDep, config: SettingsDep) -> DemoAccessResponse:
    accounts = _demo_accounts(session, config)
    return DemoAccessResponse(available=bool(accounts), roles=sorted(accounts))


@router.post("/auth/demo", status_code=204, operation_id="signInAsDemo")
def sign_in_as_demo(
    body: DemoSignInRequest,
    response: Response,
    session: SessionDep,
    config: SettingsDep,
) -> None:
    """Sign in as a seeded account without a password.

    This hands out a session for the asking, which is only acceptable because
    the data behind it is fictional by construction: the seed is the only
    thing that creates these accounts and it refuses to run in production.
    The guard is that refusal restated, not a second, weaker one.
    """
    accounts = _demo_accounts(session, config)
    user = accounts.get(body.role)
    if user is None:
        raise forbidden("This deployment does not offer demo sign-in")

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
