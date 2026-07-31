from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from yap_server.auth.identity_records import (
    Purpose,
    PurposeGrantMetadata,
    bounded_identity_text,
)
from yap_server.auth.identity_repository import (
    ControlAuthorizationDenied,
    SqliteIdentityRepository,
)
from yap_server.auth.principal import AuthenticatedPrincipal, PrincipalKey


DEFAULT_IDENTITY_ADMINISTRATOR_ROLE = "Yap.IdentityAdministrator"
VoiceOperation = Literal["enrollment", "matching", "adaptation"]
_REQUIRED_PURPOSES: dict[VoiceOperation, tuple[Purpose, ...]] = {
    "enrollment": ("enrollment",),
    "matching": ("enrollment", "matching"),
    "adaptation": ("adaptation", "enrollment", "matching"),
}


class AuthorizationDenied(PermissionError):
    """A non-disclosing, fail-closed application authorization denial."""


@dataclass(frozen=True, slots=True)
class IdentityAuthorizationPolicy:
    administrator_roles: frozenset[str] = frozenset(
        {DEFAULT_IDENTITY_ADMINISTRATOR_ROLE}
    )

    def __post_init__(self) -> None:
        if not isinstance(self.administrator_roles, frozenset):
            raise TypeError("administrator_roles must be an immutable set")
        for role in self.administrator_roles:
            bounded_identity_text(role, field="administrator_role", maximum=128)


@dataclass(frozen=True, slots=True)
class PurposeAuthorization:
    principal: PrincipalKey
    operation: VoiceOperation
    purpose_epochs: tuple[tuple[Purpose, int], ...]


@dataclass(frozen=True, slots=True)
class DeletionIntent:
    operation_id: str
    target: PrincipalKey

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", str(UUID(self.operation_id)))


class IdentityAuthorizationService:
    """Single application seam for purpose checks and privileged mutations.

    This service owns authorization decisions only. It intentionally contains
    no voice profile, embedding, matching, or deletion implementation.
    """

    def __init__(
        self,
        repository: SqliteIdentityRepository,
        *,
        policy: IdentityAuthorizationPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy or IdentityAuthorizationPolicy()

    def authorize_enrollment(
        self,
        principal: AuthenticatedPrincipal,
    ) -> PurposeAuthorization:
        return self._authorize_voice_operation(principal, "enrollment")

    def authorize_matching(
        self,
        principal: AuthenticatedPrincipal,
    ) -> PurposeAuthorization:
        return self._authorize_voice_operation(principal, "matching")

    def authorize_adaptation(
        self,
        principal: AuthenticatedPrincipal,
    ) -> PurposeAuthorization:
        return self._authorize_voice_operation(principal, "adaptation")

    def _authorize_voice_operation(
        self,
        principal: AuthenticatedPrincipal,
        operation: VoiceOperation,
    ) -> PurposeAuthorization:
        epochs = self._repository.authorize_purposes(
            principal,
            action=f"voice.{operation}",
            required_purposes=_REQUIRED_PURPOSES[operation],
        )
        if epochs is None:
            raise AuthorizationDenied(
                "The authenticated principal is not authorized for this operation."
            )
        return PurposeAuthorization(principal.key, operation, epochs)

    def grant_purpose(
        self,
        actor: AuthenticatedPrincipal,
        target: PrincipalKey,
        *,
        purpose: Purpose,
        metadata: PurposeGrantMetadata,
    ) -> int:
        try:
            return self._repository.grant_purpose(
                actor,
                target,
                purpose=purpose,
                metadata=metadata,
                administrator_roles=self._policy.administrator_roles,
            )
        except ControlAuthorizationDenied as error:
            raise AuthorizationDenied(str(error)) from error

    def revoke_purpose(
        self,
        actor: AuthenticatedPrincipal,
        target: PrincipalKey,
        *,
        purpose: Purpose,
    ) -> int:
        try:
            return self._repository.revoke_purpose(
                actor,
                target,
                purpose=purpose,
                administrator_roles=self._policy.administrator_roles,
            )
        except ControlAuthorizationDenied as error:
            raise AuthorizationDenied(str(error)) from error

    def revoke_access(
        self,
        actor: AuthenticatedPrincipal,
        target: PrincipalKey,
    ) -> int:
        try:
            return self._repository.revoke_access(
                actor,
                target,
                administrator_roles=self._policy.administrator_roles,
            )
        except ControlAuthorizationDenied as error:
            raise AuthorizationDenied(str(error)) from error

    def restore_access(
        self,
        actor: AuthenticatedPrincipal,
        target: PrincipalKey,
    ) -> int:
        try:
            return self._repository.restore_access(
                actor,
                target,
                administrator_roles=self._policy.administrator_roles,
            )
        except ControlAuthorizationDenied as error:
            raise AuthorizationDenied(str(error)) from error

    def record_deletion_intent(
        self,
        actor: AuthenticatedPrincipal,
        target: PrincipalKey,
    ) -> DeletionIntent:
        if actor.key != target:
            self._require_administrator(actor, target, "deletion_intent")
        elif not self._repository.access_is_allowed(actor):
            self._deny_control(actor, actor.key, "deletion_intent", "access_denied")
        intent = DeletionIntent(str(uuid4()), target)
        self._repository.record_deletion_event(
            actor,
            target,
            action="deletion.intent",
            operation_id=intent.operation_id,
        )
        return intent

    def record_deletion_completion(
        self,
        actor: AuthenticatedPrincipal,
        intent: DeletionIntent,
    ) -> None:
        self._require_administrator(actor, intent.target, "deletion_completion")
        self._repository.record_deletion_event(
            actor,
            intent.target,
            action="deletion.completion",
            operation_id=intent.operation_id,
        )

    def _require_administrator(
        self,
        actor: AuthenticatedPrincipal,
        target: PrincipalKey,
        action: str,
    ) -> None:
        roles = getattr(actor, "roles", frozenset())
        same_tenant = actor.tenant_id == target.tenant_id
        has_role = bool(self._policy.administrator_roles.intersection(roles))
        active = self._repository.access_is_allowed(actor)
        if same_tenant and has_role and active:
            self._repository.record_authorization_decision(
                actor,
                target,
                action=f"control.{action}",
                allowed=True,
            )
            return
        safe_target = target if same_tenant else actor.key
        if not same_tenant:
            reason = "tenant_mismatch"
        elif not has_role:
            reason = "administrator_role_required"
        else:
            reason = "access_denied"
        self._deny_control(actor, safe_target, action, reason)

    def _deny_control(
        self,
        actor: AuthenticatedPrincipal,
        target: PrincipalKey,
        action: str,
        reason: str,
    ) -> None:
        self._repository.record_authorization_decision(
            actor,
            target,
            action=f"control.{action}",
            allowed=False,
            reason=reason,
        )
        raise AuthorizationDenied(
            "The authenticated principal is not authorized for this operation."
        )


__all__ = [
    "AuthorizationDenied",
    "DEFAULT_IDENTITY_ADMINISTRATOR_ROLE",
    "DeletionIntent",
    "IdentityAuthorizationPolicy",
    "IdentityAuthorizationService",
    "PurposeAuthorization",
]
