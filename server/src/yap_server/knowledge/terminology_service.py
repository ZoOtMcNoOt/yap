"""Bounded scoped vocabulary operations over the canonical append-only ledger."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
import re
from uuid import UUID, uuid4

import psycopg

from yap_server.auth import AuthenticatedPrincipal
from yap_server.private_postgres_connection import PrivatePostgresConnectionFactory
from .terminology_policy import TerminologyPolicy, TerminologyScope
from .terminology_ledger import (
    append_terminology_record,
    install_terminology_schema,
    read_scoped_terminology_page,
    read_scoped_terminology_record,
)
from .terminology_snapshot import TerminologyRecord, validate_terminology_record

_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LOCALE = re.compile(r"^(?:und|[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-[A-Z]{2}|-[0-9]{3})?)$")
_PAGE_SIZE = 10
_CONTENT_FIELDS = {"canonicalForm", "variants", "sensitivity"}


class TerminologyServiceError(Exception):
    def __init__(
        self, status: int, code: str, message: str, *, retryable: bool = False
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


def _not_found() -> TerminologyServiceError:
    return TerminologyServiceError(
        404, "TERMINOLOGY_NOT_FOUND", "This term is unavailable."
    )


def _body(value: object, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("terminology request fields are invalid")
    return value


def _version(value: object) -> int:
    if type(value) is not int or not 1 <= value < 2**63 - 1:
        raise ValueError("terminology version is invalid")
    return value


def _wire(record: TerminologyRecord, scope: TerminologyScope) -> dict[str, object]:
    return {
        "scopeId": scope.scope_id,
        "recordId": record.record_id,
        "locale": record.locale,
        "canonicalForm": record.canonical_form,
        "variants": list(record.variants),
        "sensitivity": record.sensitivity,
        "version": record.version,
        "changedAt": record.changed_at.replace("+00:00", "Z"),
    }


class TerminologyService:
    def __init__(
        self,
        *,
        connection_factory: PrivatePostgresConnectionFactory,
        policy: TerminologyPolicy | None = None,
    ):
        self._policy = policy if policy is not None else TerminologyPolicy()
        self._connect = connection_factory
        with self._connect() as connection:
            install_terminology_schema(connection)

    def list(
        self,
        *,
        principal: AuthenticatedPrincipal,
        locale: str,
        after: str = "",
        scope_id: str = "personal",
    ) -> dict[str, object]:
        scope = self._scope(principal, scope_id)
        if not isinstance(locale, str) or not _LOCALE.fullmatch(locale):
            raise ValueError("terminology locale is invalid")
        if not isinstance(after, str) or (after and not _IDENTITY.fullmatch(after)):
            raise ValueError("terminology cursor is invalid")
        try:
            with self._connect() as connection:
                records = read_scoped_terminology_page(
                    connection,
                    principal=principal.key,
                    scope=scope.kind,
                    owner_id=scope.owner_id,
                    locale=locale,
                    after=after,
                )
            page = records[:_PAGE_SIZE]
            for record in page:
                try:
                    validate_terminology_record(record, tenant_id=principal.tenant_id)
                except (TypeError, ValueError):
                    raise self._unavailable() from None
            return {
                "scopeId": scope.scope_id,
                "records": [_wire(record, scope) for record in page],
                "nextCursor": page[-1].record_id if len(records) > _PAGE_SIZE else None,
            }
        except psycopg.Error:
            raise self._unavailable() from None

    def get(
        self,
        record_id: str,
        *,
        principal: AuthenticatedPrincipal,
        scope_id: str = "personal",
    ) -> dict[str, object]:
        scope = self._scope(principal, scope_id)
        try:
            with self._connect() as connection:
                return _wire(
                    self._current(connection, record_id, principal, scope), scope
                )
        except psycopg.Error:
            raise self._unavailable() from None

    def create(
        self,
        value: object,
        *,
        principal: AuthenticatedPrincipal,
        scope_id: str = "personal",
    ) -> dict[str, object]:
        scope = self._scope(principal, scope_id, manage=True)
        body = _body(value, _CONTENT_FIELDS | {"locale", "mutationId"})
        mutation = body["mutationId"]
        if not isinstance(mutation, str) or str(UUID(mutation)) != mutation:
            raise ValueError("terminology mutation identity is invalid")
        identity_parts = [principal.tenant_id, principal.subject_id, mutation]
        if scope.kind != "personal":
            identity_parts.extend([scope.kind, scope.owner_id])
        identity = hashlib.sha256(
            json.dumps(
                identity_parts,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        record = TerminologyRecord(
            record_id=f"term-{identity}",
            tenant_id=principal.tenant_id,
            scope=scope.kind,
            owner_id=scope.owner_id,
            locale=body["locale"],
            canonical_form=body["canonicalForm"],
            variants=self._variants(body),
            sensitivity=body["sensitivity"],
            version=1,
            deleted=False,
            audit_revision=f"term-audit-{uuid4().hex}",
            changed_at=datetime.now(UTC).isoformat(),
        )
        validate_terminology_record(record, tenant_id=principal.tenant_id)
        try:
            with self._connect() as connection, connection.transaction():
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"{principal.tenant_id}:{record.record_id}",),
                )
                previous = read_scoped_terminology_record(
                    connection,
                    principal=principal.key,
                    scope=scope.kind,
                    owner_id=scope.owner_id,
                    record_id=record.record_id,
                    first_version=True,
                )
                if previous is not None:
                    if (
                        previous.locale,
                        previous.canonical_form,
                        previous.variants,
                        previous.sensitivity,
                    ) != (
                        record.locale,
                        record.canonical_form,
                        record.variants,
                        record.sensitivity,
                    ):
                        raise TerminologyServiceError(
                            409,
                            "TERMINOLOGY_CONFLICT",
                            "This creation identity was already used. Reload your terms before retrying.",
                        )
                    return _wire(previous, scope)
                append_terminology_record(
                    connection,
                    record,
                    authorization=self._policy.authorization(principal),
                )
            return _wire(record, scope)
        except psycopg.Error:
            raise self._unavailable() from None

    def update(
        self,
        record_id: str,
        value: object,
        *,
        principal: AuthenticatedPrincipal,
        scope_id: str = "personal",
    ) -> dict[str, object]:
        body = _body(value, _CONTENT_FIELDS | {"expectedVersion"})
        return self._mutate(
            record_id,
            body,
            principal,
            self._scope(principal, scope_id, manage=True),
            deleted=False,
        )

    def delete(
        self,
        record_id: str,
        value: object,
        *,
        principal: AuthenticatedPrincipal,
        scope_id: str = "personal",
    ) -> dict[str, object]:
        body = _body(value, {"expectedVersion"})
        return self._mutate(
            record_id,
            body,
            principal,
            self._scope(principal, scope_id, manage=True),
            deleted=True,
        )

    def _mutate(
        self,
        record_id: str,
        body: dict,
        principal: AuthenticatedPrincipal,
        scope: TerminologyScope,
        *,
        deleted: bool,
    ) -> dict[str, object]:
        version = _version(body["expectedVersion"])
        if not isinstance(record_id, str) or not _IDENTITY.fullmatch(record_id):
            raise _not_found()
        try:
            with self._connect() as connection, connection.transaction():
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"{principal.tenant_id}:{record_id}",),
                )
                current = self._current(connection, record_id, principal, scope)
                if current.version != version:
                    raise TerminologyServiceError(
                        409,
                        "TERMINOLOGY_CONFLICT",
                        "This term changed. Reload it before saving.",
                    )
                record = replace(
                    current,
                    version=version + 1,
                    deleted=deleted,
                    audit_revision=f"term-audit-{uuid4().hex}",
                    changed_at=datetime.now(UTC).isoformat(),
                    **(
                        {}
                        if deleted
                        else {
                            "canonical_form": body["canonicalForm"],
                            "variants": self._variants(body),
                            "sensitivity": body["sensitivity"],
                        }
                    ),
                )
                validate_terminology_record(record, tenant_id=principal.tenant_id)
                append_terminology_record(
                    connection,
                    record,
                    authorization=self._policy.authorization(principal),
                )
            return (
                {
                    "scopeId": scope.scope_id,
                    "recordId": record.record_id,
                    "version": record.version,
                    "deleted": True,
                }
                if deleted
                else _wire(record, scope)
            )
        except psycopg.Error:
            raise self._unavailable() from None

    @staticmethod
    def _current(
        connection,
        record_id: str,
        principal: AuthenticatedPrincipal,
        scope: TerminologyScope,
    ) -> TerminologyRecord:
        if not isinstance(record_id, str) or not _IDENTITY.fullmatch(record_id):
            raise _not_found()
        record = read_scoped_terminology_record(
            connection,
            principal=principal.key,
            scope=scope.kind,
            owner_id=scope.owner_id,
            record_id=record_id,
        )
        if record is None or record.deleted:
            raise _not_found()
        try:
            validate_terminology_record(record, tenant_id=principal.tenant_id)
        except (TypeError, ValueError):
            raise TerminologyService._unavailable() from None
        return record

    @staticmethod
    def _variants(body: dict) -> tuple[str, ...]:
        variants = body["variants"]
        if not isinstance(variants, list):
            raise ValueError("terminology variants are invalid")
        return tuple(variants)

    def scopes(self, *, principal: AuthenticatedPrincipal) -> dict[str, object]:
        return {"scopes": [scope.wire() for scope in self._policy.scopes(principal)]}

    def _scope(
        self, principal: AuthenticatedPrincipal, scope_id: str, *, manage: bool = False
    ) -> TerminologyScope:
        scope = next(
            (s for s in self._policy.scopes(principal) if s.scope_id == scope_id), None
        )
        if scope is None:
            raise TerminologyServiceError(
                404,
                "TERMINOLOGY_SCOPE_UNAVAILABLE",
                "This terminology scope is unavailable.",
            )
        if manage and not scope.can_manage:
            raise TerminologyServiceError(
                403,
                "TERMINOLOGY_DENIED",
                "You can view these terms but cannot change them.",
            )
        return scope

    @staticmethod
    def _unavailable() -> TerminologyServiceError:
        return TerminologyServiceError(
            503,
            "TERMINOLOGY_UNAVAILABLE",
            "Terminology is temporarily unavailable.",
            retryable=True,
        )
