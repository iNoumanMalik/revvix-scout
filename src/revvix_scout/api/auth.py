"""API-mediated Supabase authentication and workspace authorization."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol, cast
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from revvix_scout.config import Settings, get_settings
from revvix_scout.db.models import UserProfile, Workspace, WorkspaceMember
from revvix_scout.db.session import get_db_session

WorkspaceRole = Literal["owner", "admin", "operator", "reviewer", "viewer", "automation"]
WorkspaceCapability = Literal[
    "read",
    "export",
    "ingest",
    "run_pipeline",
    "review",
    "privacy",
]

_ROLE_CAPABILITIES: dict[WorkspaceRole, frozenset[WorkspaceCapability]] = {
    "owner": frozenset({"read", "export", "ingest", "run_pipeline", "review", "privacy"}),
    "admin": frozenset({"read", "export", "ingest", "run_pipeline", "review", "privacy"}),
    "operator": frozenset({"read", "export", "ingest", "run_pipeline", "review", "privacy"}),
    "reviewer": frozenset({"read", "review"}),
    "viewer": frozenset({"read"}),
    "automation": frozenset({"read", "run_pipeline"}),
}


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    """Identity established by a trusted authentication provider."""

    user_id: UUID
    is_anonymous: bool


@dataclass(frozen=True, slots=True)
class CurrentActor:
    """Authenticated identity plus server-authorized workspace membership."""

    user_id: UUID
    workspace_id: UUID
    role: WorkspaceRole
    display_name: str
    auth_mode: Literal["development", "supabase"]

    @property
    def capabilities(self) -> frozenset[WorkspaceCapability]:
        """Return immutable, server-owned capabilities for this workspace role."""

        return _ROLE_CAPABILITIES[self.role]


class AuthVerifier(Protocol):
    """Port for validating an opaque browser access token."""

    def verify(self, access_token: str) -> AuthenticatedIdentity:
        """Return the verified identity or raise an authentication error."""


class SupabaseAuthVerifier:
    """Validate a token through Supabase Auth's authenticated user endpoint."""

    def __init__(self, *, url: str, publishable_key: str) -> None:
        self._user_url = f"{url.rstrip('/')}/auth/v1/user"
        self._publishable_key = publishable_key

    def verify(self, access_token: str) -> AuthenticatedIdentity:
        try:
            response = httpx.get(
                self._user_url,
                headers={
                    "apikey": self._publishable_key,
                    "authorization": f"Bearer {access_token}",
                },
                timeout=5.0,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=503, detail="Authentication service unavailable"
            ) from exc
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid or expired access token")
        payload = response.json()
        try:
            return AuthenticatedIdentity(
                user_id=UUID(payload["id"]),
                is_anonymous=bool(payload.get("is_anonymous", False)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="Invalid authentication response") from exc


class UnconfiguredAuthVerifier:
    """Fail closed if Supabase mode is selected without complete settings."""

    def verify(self, access_token: str) -> AuthenticatedIdentity:
        del access_token
        raise HTTPException(status_code=503, detail="Supabase authentication is not configured")


_bearer = HTTPBearer(auto_error=False)


def get_auth_verifier(settings: Annotated[Settings, Depends(get_settings)]) -> AuthVerifier:
    """Build the configured external verifier without exposing server credentials."""

    if settings.supabase_url is None or settings.supabase_publishable_key is None:
        return UnconfiguredAuthVerifier()
    return SupabaseAuthVerifier(
        url=settings.supabase_url,
        publishable_key=settings.supabase_publishable_key,
    )


def require_current_actor(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    verifier: Annotated[AuthVerifier, Depends(get_auth_verifier)],
) -> CurrentActor:
    """Authenticate a request and authorize active membership in the configured workspace."""

    if settings.auth_mode == "development":
        identity = AuthenticatedIdentity(
            user_id=settings.development_user_id,
            is_anonymous=False,
        )
    else:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Bearer access token required")
        identity = verifier.verify(credentials.credentials)

    if identity.is_anonymous:
        raise HTTPException(status_code=403, detail="Anonymous sessions are not permitted")

    membership = session.execute(
        select(WorkspaceMember, UserProfile)
        .join(UserProfile, UserProfile.user_id == WorkspaceMember.user_id)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(
            WorkspaceMember.workspace_id == settings.default_workspace_id,
            WorkspaceMember.user_id == identity.user_id,
            WorkspaceMember.status == "active",
            Workspace.status == "active",
        )
    ).one_or_none()
    if membership is None:
        raise HTTPException(status_code=403, detail="Active workspace membership required")

    member, profile = membership
    role = cast(WorkspaceRole, member.role)
    return CurrentActor(
        user_id=identity.user_id,
        workspace_id=member.workspace_id,
        role=role,
        display_name=profile.display_name,
        auth_mode=settings.auth_mode,
    )


CurrentActorDependency = Annotated[CurrentActor, Depends(require_current_actor)]


def require_capability(
    capability: WorkspaceCapability,
) -> Callable[[CurrentActorDependency], CurrentActor]:
    """Build a FastAPI dependency that enforces one explicit workspace capability."""

    def dependency(actor: CurrentActorDependency) -> CurrentActor:
        if capability not in actor.capabilities:
            raise HTTPException(
                status_code=403,
                detail=f"Workspace role '{actor.role}' lacks '{capability}' capability",
            )
        return actor

    return dependency
