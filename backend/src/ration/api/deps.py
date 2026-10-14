"""Request-scoped dependencies: a database session, and who is asking.

The authorisation rule worth knowing: a request for another profile's data
answers 404, not 403. A 403 would confirm the resource exists, and the API has
no reason to disclose that.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ration.api.broadcast import dispatch_pending
from ration.api.errors import forbidden, not_found, unauthorized
from ration.api.security import SessionCodec
from ration.config import SESSION_COOKIE_NAME, Settings, settings
from ration.repositories import models


def get_settings() -> Settings:
    return settings()


def get_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
        # Only now. A broadcast sent from inside the handler races this
        # commit: the other client refetches and reads the database as it was
        # before the write. See ration.api.broadcast.
        dispatch_pending(request)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: str
    display_name: str
    role: str
    profile_id: str
    locale: str

    @property
    def is_planner(self) -> bool:
        return self.role == "planner"


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def current_user(
    request: Request,
    session: SessionDep,
    config: SettingsDep,
) -> CurrentUser:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise unauthorized()

    user_id = SessionCodec(config).read(token)
    if user_id is None:
        raise unauthorized("Session is invalid or has expired")

    user = session.get(models.User, user_id)
    if user is None:
        raise unauthorized("Session refers to an account that no longer exists")

    profile = session.scalars(
        select(models.Profile).where(
            (models.Profile.planner_user_id == user.id)
            | (models.Profile.follower_user_id == user.id)
        )
    ).first()
    if profile is None:
        raise forbidden("This account is not paired with a profile")

    return CurrentUser(
        id=user.id,
        display_name=user.display_name,
        role=user.role,
        profile_id=profile.id,
        locale=profile.locale,
    )


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]


def require_planner(user: CurrentUserDep) -> CurrentUser:
    if not user.is_planner:
        raise forbidden("Only the planner may change the plan")
    return user


def owned_profile(profile_id: str, user: CurrentUserDep) -> str:
    """Resolve a profile id the caller is actually paired with."""
    if profile_id != user.profile_id:
        raise not_found("Profile")
    return profile_id


def owned_plan(
    plan_id: str,
    session: SessionDep,
    user: CurrentUserDep,
) -> models.Plan:
    plan = session.get(models.Plan, plan_id)
    if plan is None or plan.profile_id != user.profile_id:
        raise not_found("Plan")
    return plan


PlannerDep = Annotated[CurrentUser, Depends(require_planner)]
OwnedPlanDep = Annotated[models.Plan, Depends(owned_plan)]
